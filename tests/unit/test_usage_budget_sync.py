"""`usage()` / `iter_usage_turns()` / `budget()` — sync client.

CS2-01-02..04, SPEC-CS2-USE-001/002, SPEC-CS2-BUD-001/002. Mirrored in
``test_usage_budget_async.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from prismal_sdk.exceptions import InvalidRequestError, PrismalTimeoutError
from prismal_sdk.models import (
    BudgetAmounts,
    BudgetReport,
    QuotaWindow,
    Usage,
    UsageReport,
    UsageTurn,
)
from tests.wire_v02 import (
    BUDGET_REPORT,
    TOTALS,
    USAGE_EXAMPLE,
    usage_report,
    usage_turn,
)

UTC = timezone.utc


def _json_handler(body, seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return handler


# ── usage() ────────────────────────────────────────────────────────────────


def test_usage_gets_v1_usage_with_only_non_none_params(make_client):
    seen: list[httpx.Request] = []
    with make_client(_json_handler(usage_report(), seen)) as client:
        client.usage()
    (request,) = seen
    assert request.method == "GET"
    assert request.url.path == "/v1/usage"
    assert dict(request.url.params) == {"limit": "100"}


def test_usage_serializes_aware_datetimes_as_rfc3339_utc(make_client):
    seen: list[httpx.Request] = []
    plus2 = timezone(timedelta(hours=2))
    with make_client(_json_handler(usage_report(), seen)) as client:
        client.usage(
            thread_id="t-42",
            since=datetime(2026, 10, 3, 14, 0, tzinfo=plus2),
            until=datetime(2026, 10, 4, 12, 0, 0, 500000, tzinfo=UTC),
            limit=50,
            cursor="c-1",
        )
    assert dict(seen[0].url.params) == {
        "thread_id": "t-42",
        "since": "2026-10-03T12:00:00Z",
        "until": "2026-10-04T12:00:00.500000Z",
        "limit": "50",
        "cursor": "c-1",
    }


@pytest.mark.parametrize("field", ["since", "until"])
def test_usage_rejects_naive_datetimes_before_io(make_client, field):
    seen: list[httpx.Request] = []
    with make_client(_json_handler(usage_report(), seen)) as client:
        with pytest.raises(ValueError, match=field):
            client.usage(**{field: datetime(2026, 10, 4, 12, 0)})
    assert seen == []


def test_usage_org_id_goes_in_the_header_not_the_query(make_client):
    seen: list[httpx.Request] = []
    with make_client(_json_handler(usage_report(), seen), org_id="default") as client:
        client.usage(org_id="acme")
    assert seen[0].headers["X-Org-Id"] == "acme"
    assert "org_id" not in seen[0].url.params


def test_usage_parses_the_report(make_client):
    with make_client(_json_handler(usage_report(), [])) as client:
        report = client.usage()
    assert isinstance(report, UsageReport)
    assert report.org_id == "acme"
    assert report.thread_id is None
    assert report.since == datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    assert report.totals == Usage.model_validate(TOTALS)
    assert report.cache_hit_ratio == 0.75
    assert report.by_model == [Usage.model_validate(USAGE_EXAMPLE)]
    (turn,) = report.turns
    assert isinstance(turn, UsageTurn)
    assert turn.turn_id == "01J-a"
    assert turn.finished_at == datetime(2026, 10, 4, 11, 59, 58, tzinfo=UTC)
    assert turn.usage == Usage.model_validate(USAGE_EXAMPLE)
    assert report.next_cursor is None


def test_usage_cache_hit_ratio_is_the_hosts_not_recomputed(make_client):
    # USG-003: the window ratio is taken verbatim, even if it disagrees with
    # totals.cache_hit_ratio.
    body = {**usage_report(), "cache_hit_ratio": 0.1234}
    with make_client(_json_handler(body, [])) as client:
        assert client.usage().cache_hit_ratio == 0.1234


def test_usage_invalid_window_raises_invalid_request(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": "invalid_window", "message": "> 31 d"}}
        )

    with make_client(handler) as client, pytest.raises(InvalidRequestError):
        client.usage()


def test_usage_is_retried_on_timeout_like_any_get(make_client):
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json=usage_report())

    with make_client(handler, max_retries=1) as client:
        client.usage()
    assert len(calls) == 2

    calls.clear()
    with make_client(handler, max_retries=0) as client:
        with pytest.raises(PrismalTimeoutError):
            client.usage()


# ── iter_usage_turns() ─────────────────────────────────────────────────────


def _paged_handler(seen: list[httpx.Request]):
    pages = {
        None: usage_report([usage_turn("a"), usage_turn("b")], next_cursor="c1"),
        "c1": usage_report([usage_turn("c")], next_cursor="c2"),
        "c2": usage_report([], next_cursor=None),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params.get("cursor")])

    return handler


def test_iter_usage_turns_follows_next_cursor_until_none(make_client):
    seen: list[httpx.Request] = []
    since = datetime(2026, 10, 1, tzinfo=UTC)
    with make_client(_paged_handler(seen)) as client:
        turns = list(
            client.iter_usage_turns(thread_id="t-42", since=since, page_size=2)
        )
    assert [t.turn_id for t in turns] == ["a", "b", "c"]
    assert [r.url.params.get("cursor") for r in seen] == [None, "c1", "c2"]
    for request in seen:
        assert request.url.params["limit"] == "2"
        assert request.url.params["thread_id"] == "t-42"
        assert request.url.params["since"] == "2026-10-01T00:00:00Z"


def test_iter_usage_turns_sends_org_id_and_until_on_every_page(make_client):
    seen: list[httpx.Request] = []
    until = datetime(2026, 10, 4, tzinfo=UTC)
    with make_client(_paged_handler(seen), org_id="default") as client:
        list(client.iter_usage_turns(until=until, org_id="acme", page_size=2))
    assert len(seen) == 3
    for request in seen:
        assert request.headers["X-Org-Id"] == "acme"
        assert request.url.params["until"] == "2026-10-04T00:00:00Z"


def test_iter_usage_turns_is_lazy(make_client):
    seen: list[httpx.Request] = []
    with make_client(_paged_handler(seen)) as client:
        first = next(iter(client.iter_usage_turns(page_size=2)))
    assert first.turn_id == "a"
    assert len(seen) == 1


def test_iter_usage_turns_rejects_naive_datetimes_before_io(make_client):
    seen: list[httpx.Request] = []
    with make_client(_paged_handler(seen)) as client:
        with pytest.raises(ValueError):
            list(client.iter_usage_turns(until=datetime(2026, 10, 4)))
    assert seen == []


# ── budget() ───────────────────────────────────────────────────────────────


def test_budget_gets_v1_budget(make_client):
    seen: list[httpx.Request] = []
    with make_client(_json_handler(BUDGET_REPORT, seen)) as client:
        client.budget()
        client.budget(thread_id="t-42", org_id="acme")
    assert [r.url.path for r in seen] == ["/v1/budget", "/v1/budget"]
    assert dict(seen[0].url.params) == {}
    assert dict(seen[1].url.params) == {"thread_id": "t-42"}
    assert seen[1].headers["X-Org-Id"] == "acme"


def test_budget_parses_the_report(make_client):
    with make_client(_json_handler(BUDGET_REPORT, [])) as client:
        report = client.budget()
    assert isinstance(report, BudgetReport)
    assert (report.enabled, report.scope, report.status) == (True, "tenant", "within")
    assert report.limits == BudgetAmounts(
        tokens=2000000, cost_usd=50.0, calls=0, wall_clock_s=0.0
    )
    # `0` means unlimited on the host; the SDK keeps it verbatim (USG-003).
    assert report.limits is not None and report.limits.calls == 0
    assert report.remaining is not None and report.remaining.calls is None
    first, second = report.gateways
    assert isinstance(first, QuotaWindow)
    assert first.resets_at is None
    assert second.resets_at == datetime(2026, 10, 4, 15, 10, tzinfo=UTC)
    assert second.source == "ledger"


def test_budget_status_unknown_is_a_value_not_an_error(make_client):
    body = {**BUDGET_REPORT, "status": "unknown", "enabled": False}
    with make_client(_json_handler(body, [])) as client:
        assert client.budget().status == "unknown"


def test_budget_unknown_enum_values_parse_as_strings(make_client):
    gateway = {**BUDGET_REPORT["gateways"][0], "window": "hourly", "unit": "credits"}
    body = {
        **BUDGET_REPORT,
        "status": "throttled",
        "scope": "project",
        "gateways": [gateway],
    }
    with make_client(_json_handler(body, [])) as client:
        report = client.budget()
    assert report.status == "throttled"
    assert report.scope == "project"
    assert (report.gateways[0].window, report.gateways[0].unit) == ("hourly", "credits")


def test_budget_minimal_report_defaults(make_client):
    body = {
        "org_id": None,
        "enabled": False,
        "scope": "tenant",
        "status": "disabled",
        "as_of": "2026-10-04T12:00:00Z",
    }
    with make_client(_json_handler(body, [])) as client:
        report = client.budget()
    assert report.gateways == []
    assert report.limits is None
    assert report.breached_dimension is None


def test_budget_keeps_unknown_extra_fields(make_client):
    body = {**BUDGET_REPORT, "forecast": {"eta_s": 30}}
    with make_client(_json_handler(body, [])) as client:
        assert client.budget().model_dump()["forecast"] == {"eta_s": 30}

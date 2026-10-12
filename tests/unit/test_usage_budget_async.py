"""`usage()` / `iter_usage_turns()` / `budget()` — async client.

Mirror of ``test_usage_budget_sync.py`` (SPEC-CS2-NFR-002).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from prismal_sdk.exceptions import InvalidRequestError
from prismal_sdk.models import BudgetReport, Usage, UsageReport
from tests.wire_v02 import BUDGET_REPORT, TOTALS, usage_report, usage_turn

UTC = timezone.utc


def _json_handler(body, seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return handler


async def test_usage_request_shape(make_async_client):
    seen: list[httpx.Request] = []
    plus2 = timezone(timedelta(hours=2))
    async with make_async_client(_json_handler(usage_report(), seen)) as client:
        await client.usage()
        await client.usage(
            thread_id="t-42",
            since=datetime(2026, 10, 3, 14, 0, tzinfo=plus2),
            limit=5,
            cursor="c-1",
            org_id="acme",
        )
    assert seen[0].url.path == "/v1/usage"
    assert dict(seen[0].url.params) == {"limit": "100"}
    assert dict(seen[1].url.params) == {
        "thread_id": "t-42",
        "since": "2026-10-03T12:00:00Z",
        "limit": "5",
        "cursor": "c-1",
    }
    assert seen[1].headers["X-Org-Id"] == "acme"


async def test_usage_rejects_naive_datetimes_before_io(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_json_handler(usage_report(), seen)) as client:
        with pytest.raises(ValueError, match="since"):
            await client.usage(since=datetime(2026, 10, 4))
    assert seen == []


async def test_usage_parses_the_report(make_async_client):
    async with make_async_client(_json_handler(usage_report(), [])) as client:
        report = await client.usage()
    assert isinstance(report, UsageReport)
    assert report.totals == Usage.model_validate(TOTALS)
    assert report.turns[0].turn_id == "01J-a"


async def test_usage_invalid_window_raises_invalid_request(make_async_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": "invalid_window", "message": "> 31 d"}}
        )

    async with make_async_client(handler) as client:
        with pytest.raises(InvalidRequestError):
            await client.usage()


async def test_iter_usage_turns_follows_next_cursor_until_none(make_async_client):
    seen: list[httpx.Request] = []
    pages = {
        None: usage_report([usage_turn("a"), usage_turn("b")], next_cursor="c1"),
        "c1": usage_report([usage_turn("c")], next_cursor=None),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params.get("cursor")])

    since = datetime(2026, 10, 1, tzinfo=UTC)
    until = datetime(2026, 10, 4, tzinfo=UTC)
    async with make_async_client(handler, org_id="default") as client:
        turns = [
            t
            async for t in client.iter_usage_turns(
                thread_id="t", since=since, until=until, page_size=2, org_id="acme"
            )
        ]
    assert [t.turn_id for t in turns] == ["a", "b", "c"]
    assert [r.url.params.get("cursor") for r in seen] == [None, "c1"]
    for request in seen:
        assert request.url.params["limit"] == "2"
        assert request.url.params["thread_id"] == "t"
        assert request.url.params["since"] == "2026-10-01T00:00:00Z"
        assert request.url.params["until"] == "2026-10-04T00:00:00Z"
        assert request.headers["X-Org-Id"] == "acme"


async def test_iter_usage_turns_rejects_naive_datetimes_before_io(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_json_handler(usage_report(), seen)) as client:
        with pytest.raises(ValueError):
            _ = [t async for t in client.iter_usage_turns(until=datetime(2026, 1, 1))]
    assert seen == []


async def test_budget(make_async_client):
    seen: list[httpx.Request] = []
    body = {**BUDGET_REPORT, "status": "unknown"}
    async with make_async_client(_json_handler(body, seen)) as client:
        report = await client.budget(thread_id="t-42", org_id="acme")
    assert isinstance(report, BudgetReport)
    assert report.status == "unknown"
    assert seen[0].url.path == "/v1/budget"
    assert dict(seen[0].url.params) == {"thread_id": "t-42"}
    assert seen[0].headers["X-Org-Id"] == "acme"

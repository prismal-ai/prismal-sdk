"""Admin reads — sync client (CS2-01-06/07, SPEC-CS2-ADM-001..004).

Mirrored in ``test_admin_reports_async.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from prismal_sdk.admin import (
    AuditChain,
    AuditEntry,
    AuditPage,
    DecisionIntegrationReport,
    DecisionShadowReport,
    ReportWindow,
    RoutingPolicyReport,
    RoutingSavingsReport,
    TenantSummary,
)
from prismal_sdk.exceptions import AdminDisabledError, ForbiddenError
from tests.wire_v02 import AUDIT_PAGE, DECISIONS_REPORT, ROUTING_REPORT, TENANTS

UTC = timezone.utc
SINCE = datetime(2026, 9, 27, 14, 0, tzinfo=timezone(timedelta(hours=2)))
UNTIL = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def _json_handler(body: Any, seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return handler


# Every admin call, as (method name, kwargs, path, wire body).
_CALLS = [
    ("decisions_report", {}, "/v1/admin/decisions", DECISIONS_REPORT),
    ("routing_report", {}, "/v1/admin/routing", ROUTING_REPORT),
    ("audit", {}, "/v1/admin/audit", AUDIT_PAGE),
    ("tenants", {}, "/v1/admin/tenants", TENANTS),
]
_IDS = [c[0] for c in _CALLS]


@pytest.mark.parametrize(("method", "kwargs", "path", "body"), _CALLS, ids=_IDS)
def test_admin_calls_get_their_route(make_client, method, kwargs, path, body):
    seen: list[httpx.Request] = []
    with make_client(_json_handler(body, seen)) as client:
        getattr(client, method)(**kwargs)
    (request,) = seen
    assert (request.method, request.url.path) == ("GET", path)


# ── decisions_report / routing_report ──────────────────────────────────────


@pytest.mark.parametrize("method", ["decisions_report", "routing_report"])
def test_report_query_params(make_client, method):
    seen: list[httpx.Request] = []
    body = DECISIONS_REPORT if method == "decisions_report" else ROUTING_REPORT
    with make_client(_json_handler(body, seen), org_id="home") as client:
        getattr(client, method)()
        getattr(client, method)(since=SINCE, until=UNTIL, org_id="acme")
    assert dict(seen[0].url.params) == {}
    assert dict(seen[1].url.params) == {
        "org_id": "acme",
        "since": "2026-09-27T12:00:00Z",
        "until": "2026-10-04T12:00:00Z",
    }
    # On admin routes org_id is a query filter (`*` = all tenants); the
    # X-Org-Id header keeps the client's own tenant.
    assert seen[1].headers["X-Org-Id"] == "home"


@pytest.mark.parametrize("method", ["decisions_report", "routing_report", "audit"])
def test_naive_datetimes_rejected_before_io(make_client, method):
    seen: list[httpx.Request] = []
    with make_client(_json_handler({}, seen)) as client:
        with pytest.raises(ValueError, match="since"):
            getattr(client, method)(since=datetime(2026, 10, 1))
    assert seen == []


def test_decisions_report_parses(make_client):
    with make_client(_json_handler(DECISIONS_REPORT, [])) as client:
        report = client.decisions_report()
    assert isinstance(report, DecisionShadowReport)
    assert (report.org_id, report.enabled) == ("acme", True)
    assert report.window == ReportWindow(
        since=datetime(2026, 9, 27, 12, tzinfo=UTC), until=UNTIL
    )
    (row,) = report.integrations
    assert isinstance(row, DecisionIntegrationReport)
    assert (row.integration, row.mode, row.samples) == ("routing", "shadow", 2412)
    assert row.agreement_ratio == 0.974
    assert (row.accepted, row.escalated, row.abstained) == (1830, 402, 180)
    assert row.llm_calls_avoided == 1830
    # The engine clamps a row's window to retained stats: kept, not "fixed".
    assert row.window.since == datetime(2026, 9, 30, 8, 15, tzinfo=UTC)
    assert report.as_of == UNTIL


def test_agreement_ratio_null_is_none(make_client):
    row = {**DECISIONS_REPORT["integrations"][0], "samples": 0, "agreement_ratio": None}
    body = {**DECISIONS_REPORT, "integrations": [row]}
    with make_client(_json_handler(body, [])) as client:
        assert client.decisions_report().integrations[0].agreement_ratio is None


def test_agreement_ratio_is_never_recomputed(make_client):
    # 1830 / 2412 != 0.5: the host's figure wins (ADM-003).
    row = {**DECISIONS_REPORT["integrations"][0], "agreement_ratio": 0.5}
    body = {**DECISIONS_REPORT, "integrations": [row]}
    with make_client(_json_handler(body, [])) as client:
        assert client.decisions_report().integrations[0].agreement_ratio == 0.5


@pytest.mark.parametrize(
    ("method", "body", "rows"),
    [
        ("decisions_report", DECISIONS_REPORT, "integrations"),
        ("routing_report", ROUTING_REPORT, "policies"),
    ],
)
def test_disabled_feature_is_a_result_not_an_error(make_client, method, body, rows):
    disabled = {**body, "enabled": False, rows: []}
    with make_client(_json_handler(disabled, [])) as client:
        report = getattr(client, method)()
    assert report.enabled is False
    assert getattr(report, rows) == []


def test_routing_report_parses(make_client):
    with make_client(_json_handler(ROUTING_REPORT, [])) as client:
        report = client.routing_report()
    assert isinstance(report, RoutingSavingsReport)
    assert report.mode == "shadow"
    (policy,) = report.policies
    assert isinstance(policy, RoutingPolicyReport)
    assert policy.decisions_by_tier == {"small": 3900, "medium": 1000, "frontier": 220}
    assert policy.escalations_by_reason["structured_invalid"] == 40
    assert (policy.plan_cache_hits, policy.estimated_savings_usd) == (610, 12.43)


def test_report_rows_keep_unknown_fields_and_modes(make_client):
    row = {**ROUTING_REPORT["policies"][0], "carbon_saved_g": 3.2}
    body = {**ROUTING_REPORT, "mode": "canary", "policies": [row]}
    with make_client(_json_handler(body, [])) as client:
        report = client.routing_report()
    assert report.mode == "canary"
    assert report.policies[0].model_dump()["carbon_saved_g"] == 3.2


# ── audit ──────────────────────────────────────────────────────────────────


def test_audit_query_params(make_client):
    seen: list[httpx.Request] = []
    with make_client(_json_handler(AUDIT_PAGE, seen)) as client:
        client.audit()
        client.audit(3, 200, since=UNTIL, org_id="*")
    assert dict(seen[0].url.params) == {"page": "1", "page_size": "50"}
    assert dict(seen[1].url.params) == {
        "page": "3",
        "page_size": "200",
        "since": "2026-10-04T12:00:00Z",
        "org_id": "*",
    }
    assert "X-Org-Id" not in seen[1].headers


def test_audit_parses_entries_and_chain(make_client):
    with make_client(_json_handler(AUDIT_PAGE, [])) as client:
        page = client.audit()
    assert isinstance(page, AuditPage)
    assert (page.page, page.page_size, page.total) == (1, 50, 2)
    first, second = page.entries
    assert isinstance(first, AuditEntry)
    assert first.ts == datetime(2026, 10, 4, 11, tzinfo=UTC)
    assert (first.hash, first.prev_hash) == ("h1", None)
    assert first.fields == {"method": "ListTasks"}
    assert second.actor is None
    assert page.chain == AuditChain(status="valid", checked=2, first_broken_seq=None)


def test_audit_chain_status_is_the_hosts(make_client):
    # h2.prev_hash == h1 looks valid, but the host says broken: SDK never
    # re-verifies the chain (ADM-003). Unknown statuses parse as strings.
    for status in ["broken", "pending_rehash"]:
        chain = {"status": status, "checked": 2, "first_broken_seq": 2}
        body = {**AUDIT_PAGE, "chain": chain}
        with make_client(_json_handler(body, [])) as client:
            page = client.audit()
        assert page.chain.status == status
        assert page.chain.first_broken_seq == 2


def test_audit_total_may_be_null(make_client):
    with make_client(_json_handler({**AUDIT_PAGE, "total": None}, [])) as client:
        assert client.audit().total is None


# ── tenants ────────────────────────────────────────────────────────────────


def test_tenants_unwraps_the_list(make_client):
    with make_client(_json_handler(TENANTS, [])) as client:
        tenants = client.tenants()
    assert [t.org_id for t in tenants] == ["acme", "globex"]
    acme, globex = tenants
    assert isinstance(acme, TenantSummary)
    assert acme.gateways == ["openrouter", "opencode_go"]
    assert acme.created_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert (acme.a2a_protocol_version, acme.config_source) == ("1.0", "vault")
    assert (globex.live, globex.created_at, globex.a2a_protocol_version) == (
        False,
        None,
        None,
    )


def test_tenants_sends_no_query(make_client):
    seen: list[httpx.Request] = []
    with make_client(_json_handler(TENANTS, seen)) as client:
        client.tenants()
    assert dict(seen[0].url.params) == {}


# ── errors (ADM-003) ───────────────────────────────────────────────────────


def _status_handler(status: int, body: Any):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


_ERROR_BODIES = [
    pytest.param(
        {"error": {"code": "admin_disabled", "message": "off"}}, id="envelope"
    ),
    pytest.param({"detail": "Not Found"}, id="fastapi-detail"),
    pytest.param({"error": {"code": "not_found", "message": "x"}}, id="other-code"),
]


@pytest.mark.parametrize(("method", "kwargs", "path", "body"), _CALLS, ids=_IDS)
@pytest.mark.parametrize("error_body", _ERROR_BODIES)
def test_404_is_admin_disabled_whatever_the_body(
    make_client, method, kwargs, path, body, error_body
):
    with make_client(_status_handler(404, error_body)) as client:
        with pytest.raises(AdminDisabledError) as info:
            getattr(client, method)(**kwargs)
    assert info.value.status_code == 404


@pytest.mark.parametrize(("method", "kwargs", "path", "body"), _CALLS, ids=_IDS)
@pytest.mark.parametrize(
    "error_body",
    [
        {"error": {"code": "forbidden", "message": "missing prismal:admin"}},
        {"error": {"code": "permission_denied", "message": "scope"}},
        {"detail": "Forbidden"},
    ],
)
def test_403_is_forbidden_whatever_the_body(
    make_client, method, kwargs, path, body, error_body
):
    with make_client(_status_handler(403, error_body)) as client:
        with pytest.raises(ForbiddenError) as info:
            getattr(client, method)(**kwargs)
    assert info.value.status_code == 403


def test_403_keeps_the_hosts_code_and_message(make_client):
    body = {"error": {"code": "forbidden_tenant", "message": "org_id=* needs global"}}
    with make_client(_status_handler(403, body)) as client:
        with pytest.raises(ForbiddenError) as info:
            client.audit(org_id="*")
    assert info.value.code == "forbidden_tenant"
    assert info.value.message == "org_id=* needs global"


def test_other_admin_errors_use_the_normal_code_table(make_client):
    from prismal_sdk.exceptions import InvalidRequestError

    body = {"error": {"code": "invalid_window", "message": "since > until"}}
    with make_client(_status_handler(400, body)) as client:
        with pytest.raises(InvalidRequestError):
            client.decisions_report(since=UNTIL, until=SINCE)


@pytest.mark.parametrize("body", [{"max_tenants": 64}, [{"org_id": "acme"}]])
def test_tenants_contract_break_fails_loudly_not_as_an_empty_list(make_client, body):
    import pydantic

    with make_client(_json_handler(body, [])) as client:
        with pytest.raises(pydantic.ValidationError):
            client.tenants()


def test_admin_reports_are_exported_from_the_package():
    import prismal_sdk

    for name in ["AuditPage", "DecisionShadowReport", "RoutingSavingsReport"]:
        assert name in prismal_sdk.__all__
    assert prismal_sdk.TenantSummary is TenantSummary

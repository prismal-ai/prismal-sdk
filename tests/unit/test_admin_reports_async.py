"""Admin reads — async client. Mirror of ``test_admin_reports_sync.py``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from prismal_sdk.admin import (
    AuditPage,
    DecisionShadowReport,
    RoutingSavingsReport,
    TenantSummary,
)
from prismal_sdk.exceptions import AdminDisabledError, ForbiddenError
from tests.wire_v02 import AUDIT_PAGE, DECISIONS_REPORT, ROUTING_REPORT, TENANTS

UTC = timezone.utc
SINCE = datetime(2026, 9, 27, 12, tzinfo=UTC)
UNTIL = datetime(2026, 10, 4, 12, tzinfo=UTC)


def _json_handler(body: Any, seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return handler


async def test_decisions_report(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_json_handler(DECISIONS_REPORT, seen)) as client:
        report = await client.decisions_report(since=SINCE, until=UNTIL, org_id="*")
    assert isinstance(report, DecisionShadowReport)
    assert report.integrations[0].agreement_ratio == 0.974
    assert seen[0].url.path == "/v1/admin/decisions"
    assert dict(seen[0].url.params) == {
        "org_id": "*",
        "since": "2026-09-27T12:00:00Z",
        "until": "2026-10-04T12:00:00Z",
    }


async def test_routing_report(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_json_handler(ROUTING_REPORT, seen)) as client:
        report = await client.routing_report(since=SINCE, until=UNTIL, org_id="acme")
    assert isinstance(report, RoutingSavingsReport)
    assert report.policies[0].estimated_savings_usd == 12.43
    assert seen[0].url.path == "/v1/admin/routing"
    assert dict(seen[0].url.params) == {
        "org_id": "acme",
        "since": "2026-09-27T12:00:00Z",
        "until": "2026-10-04T12:00:00Z",
    }


async def test_audit(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_json_handler(AUDIT_PAGE, seen)) as client:
        page = await client.audit(2, 10, since=SINCE, org_id="acme")
    assert isinstance(page, AuditPage)
    assert page.chain.status == "valid"
    assert seen[0].url.path == "/v1/admin/audit"
    assert dict(seen[0].url.params) == {
        "page": "2",
        "page_size": "10",
        "since": "2026-09-27T12:00:00Z",
        "org_id": "acme",
    }


async def test_tenants(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_json_handler(TENANTS, seen)) as client:
        tenants = await client.tenants()
    assert all(isinstance(t, TenantSummary) for t in tenants)
    assert [t.org_id for t in tenants] == ["acme", "globex"]
    assert seen[0].url.path == "/v1/admin/tenants"


@pytest.mark.parametrize(
    "method", ["decisions_report", "routing_report", "audit", "tenants"]
)
async def test_admin_404_and_403(make_async_client, method):
    def handler_for(status: int):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"detail": "x"})

        return handler

    async with make_async_client(handler_for(404)) as client:
        with pytest.raises(AdminDisabledError):
            await getattr(client, method)()
    async with make_async_client(handler_for(403)) as client:
        with pytest.raises(ForbiddenError):
            await getattr(client, method)()


async def test_naive_datetime_rejected_before_io(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_json_handler(DECISIONS_REPORT, seen)) as client:
        with pytest.raises(ValueError, match="until"):
            await client.routing_report(until=datetime(2026, 10, 4))
    assert seen == []

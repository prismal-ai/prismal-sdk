"""Admin read models (CS2-01-06/07, SPEC-CS2-ADM-001..004).

Typed views of the host's admin-scoped reads (``/v1/admin/*``, host
``SPEC-RH2-ADM-002..005``), for dashboards. Every figure — agreement ratios,
savings estimates, audit-chain status — is the engine's, serialized by the
host field for field; the SDK never recomputes one (SPEC-CS2-ADM-003).

Unknown fields are kept and unknown enum values (``mode``, chain ``status``,
``config_source``) parse as plain strings (DD-CS2-002).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from prismal_sdk._transport import (
    extract_detail,
    parse_error_object,
    raise_for_response,
)
from prismal_sdk.exceptions import AdminDisabledError, ForbiddenError


class _AdminModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ReportWindow(_AdminModel):
    since: datetime
    until: datetime


# ── GET /v1/admin/decisions (SPEC-RH2-ADM-004) ──────────────────────────────


class DecisionIntegrationReport(_AdminModel):
    """One decision integration's shadow/enforce statistics."""

    integration: str
    mode: str  # off | shadow | enforce
    samples: int
    #: ``None`` when ``samples`` is 0.
    agreement_ratio: float | None
    accepted: int
    escalated: int
    abstained: int
    llm_calls_avoided: int
    #: May start later than requested: the engine clamps to retained stats.
    window: ReportWindow


class DecisionShadowReport(_AdminModel):
    """``enabled=False`` with no ``integrations`` is a valid answer."""

    org_id: str | None
    enabled: bool
    window: ReportWindow
    integrations: list[DecisionIntegrationReport] = Field(default_factory=list)
    as_of: datetime


# ── GET /v1/admin/routing (SPEC-RH2-ADM-005) ────────────────────────────────


class RoutingPolicyReport(_AdminModel):
    policy: str
    decisions: int
    decisions_by_tier: dict[str, int]
    escalations: int
    escalations_by_reason: dict[str, int]
    plan_cache_hits: int
    #: The engine's frontier-counterfactual estimate, never recomputed.
    estimated_savings_usd: float
    window: ReportWindow


class RoutingSavingsReport(_AdminModel):
    """``enabled=False`` with no ``policies`` is a valid answer."""

    org_id: str | None
    enabled: bool
    mode: str  # shadow | enforce
    window: ReportWindow
    policies: list[RoutingPolicyReport] = Field(default_factory=list)
    as_of: datetime


# ── GET /v1/admin/audit (SPEC-RH2-ADM-003) ──────────────────────────────────


class AuditEntry(_AdminModel):
    seq: int
    ts: datetime
    event: str
    actor: str | None
    org_id: str | None
    hash: str
    prev_hash: str | None
    fields: dict[str, Any]


AuditChainStatus = Literal["valid", "broken", "unverified"]


class AuditChain(_AdminModel):
    """The engine's verification of the hash chain — not re-verified here."""

    status: AuditChainStatus | str
    checked: int
    first_broken_seq: int | None


class AuditPage(_AdminModel):
    page: int
    page_size: int
    total: int | None
    entries: list[AuditEntry]
    chain: AuditChain


# ── GET /v1/admin/tenants (SPEC-RH2-ADM-002) ────────────────────────────────


class TenantSummary(_AdminModel):
    """One tenant as the host sees it; never carries secret values."""

    org_id: str
    live: bool
    created_at: datetime | None
    last_used_at: datetime | None
    gateways: list[str]
    a2a_protocol_version: str | None
    config_source: str  # vault | process


class TenantsEnvelope(_AdminModel):
    """``GET /v1/admin/tenants`` body; the clients return just ``tenants``."""

    tenants: list[TenantSummary]
    max_tenants: int | None = None


def raise_for_admin_response(response: httpx.Response) -> None:
    """Raise for a non-2xx admin response (SPEC-CS2-ADM-003).

    ``404`` always means the admin surface is off and ``403`` always means a
    missing scope, whatever the body says — FastAPI's plain
    ``{"detail": ...}`` included — so they are mapped by status. The host's
    ``code``/``message`` are kept when present. Anything else goes through
    the normal code table.
    """
    if response.status_code == 404:
        klass: type[AdminDisabledError | ForbiddenError] = AdminDisabledError
        default_code = "admin_disabled"
    elif response.status_code == 403:
        klass, default_code = ForbiddenError, "forbidden"
    else:
        raise_for_response(response)
        return
    error = parse_error_object(response) or {}
    code = error.get("code")
    message = error.get("message")
    raise klass(
        response.status_code,
        code if isinstance(code, str) else default_code,
        message if isinstance(message, str) else extract_detail(response),
    )


__all__ = [
    "AuditChain",
    "AuditEntry",
    "AuditPage",
    "DecisionIntegrationReport",
    "DecisionShadowReport",
    "ReportWindow",
    "RoutingPolicyReport",
    "RoutingSavingsReport",
    "TenantSummary",
    "TenantsEnvelope",
    "raise_for_admin_response",
]

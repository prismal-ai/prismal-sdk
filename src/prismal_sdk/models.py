"""Typed wire models (CSB-02-01, CSB-03-01, SPEC-CSB-CHT-*, SPEC-CSB-A2A-001).

These models mirror the shapes fixed by ``prismal-server``'s
``SPEC.md`` — they are not reinterpretations of them. Field names and
optionality follow the server's response bodies exactly (see that repo's
``routes/threads.py``, ``routes/a2a.py``, ``streaming.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Health (SPEC-CSB-HLT-*) ─────────────────────────────────────────────────


class HealthStatus(BaseModel):
    """``GET /healthz`` response."""

    status: Literal["ok"]


class ReadyStatus(BaseModel):
    """``GET /readyz`` response on ``200``."""

    status: Literal["ready"]


# ── Threads & chat (SPEC-CSB-THR-*, SPEC-CSB-CHT-*) ─────────────────────────


class MessageIn(BaseModel):
    """Request body for ``POST /threads/{thread_id}/messages``."""

    content: str = Field(min_length=1)
    role: str = "user"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadCreated(BaseModel):
    """``POST /threads`` response."""

    thread_id: str


class TokenEvent(BaseModel):
    """SSE ``event: token`` — incremental assistant text."""

    delta: str


class ToolCallEvent(BaseModel):
    """SSE ``event: tool_call`` — a tool invocation surfaced by the graph."""

    name: str
    args: Any = None


class StateEvent(BaseModel):
    """SSE ``event: state`` — an optional node/state transition."""

    data: dict[str, Any] = Field(default_factory=dict)


# ── Usage (SPEC-CS2-USG-*) ───────────────────────────────────────────────────

#: Known ``cost_source`` values; unknown future values still parse as ``str``.
CostSource = Literal["gateway", "litellm", "table", "subscription", "none", "mixed"]


class Usage(BaseModel):
    """Per-turn (or aggregated) LLM usage — the 12-key prismal usage wire.

    Field names, types and order are fixed by the engine/host/SDK shared
    fixture (``tests/fixtures/usage_wire.json``, SPEC-CS2-USG-001); a change
    needs a coordinated minor in all three repos. Values are the host's: the
    SDK never computes, re-prices or adjusts them (SPEC-CS2-USG-003).
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    cost_source: CostSource | str = "none"
    estimated: bool = True
    served_model: str | None = None
    gateway: str | None = None

    @property
    def cache_hit_ratio(self) -> float:
        """``cache_read_tokens / prompt_tokens`` (``0.0`` with no prompt tokens).

        The only derived value the SDK offers (SPEC-CS2-USG-003); a property,
        so it never reaches ``model_dump()``.
        """
        if self.prompt_tokens == 0:
            return 0.0
        return self.cache_read_tokens / self.prompt_tokens


class DoneEvent(BaseModel):
    """SSE ``event: done`` — terminal, ends the stream normally."""

    thread_id: str
    finish_reason: str
    #: ``None`` when the host sent ``null`` or omitted it (v0.1 host).
    usage: Usage | None = None


class ErrorEvent(BaseModel):
    """SSE ``event: error`` — terminal failure payload (raised, not yielded)."""

    code: str
    message: str


# Union of everything a chat stream can yield to the caller.
ChatEvent = TokenEvent | ToolCallEvent | StateEvent | DoneEvent


# ── Usage & budget reports (SPEC-CS2-USE-*, SPEC-CS2-BUD-*) ─────────────────


class _WireModel(BaseModel):
    """Report models keep unknown host fields (forward compatibility, DD-CS2-002)."""

    model_config = ConfigDict(extra="allow")


class UsageTurn(_WireModel):
    """One completed turn in a ``GET /v1/usage`` report."""

    thread_id: str
    turn_id: str
    finished_at: datetime
    finish_reason: str
    usage: Usage


class UsageReport(_WireModel):
    """``GET /v1/usage`` — totals over the whole window, turns paged by cursor.

    ``totals``, ``by_model`` and ``cache_hit_ratio`` are computed host-side
    over the whole window (SPEC-RH2-USE-003) and taken verbatim.
    """

    org_id: str | None
    thread_id: str | None
    since: datetime
    until: datetime
    totals: Usage
    cache_hit_ratio: float
    by_model: list[Usage]
    turns: list[UsageTurn]
    next_cursor: str | None = None


class BudgetAmounts(_WireModel):
    """Per-dimension budget amounts. On ``limits``, ``0`` means unlimited."""

    tokens: int | None = None
    cost_usd: float | None = None
    calls: int | None = None
    wall_clock_s: float | None = None


class QuotaWindow(_WireModel):
    """One gateway quota window (``credit|5h|daily|weekly|monthly``)."""

    gateway: str
    window: str
    unit: str
    limit: float | None = None
    used: float | None = None
    remaining: float | None = None
    resets_at: datetime | None = None
    source: str
    as_of: datetime


BudgetStatus = Literal[
    "within", "soft_exceeded", "hard_exceeded", "disabled", "unknown"
]


class BudgetReport(_WireModel):
    """``GET /v1/budget`` — the engine's budget status, field for field.

    ``status`` ``"unknown"`` is a valid answer, not an error
    (SPEC-CS2-BUD-001); unknown enum values parse as plain strings
    (SPEC-CS2-BUD-002).
    """

    org_id: str | None
    enabled: bool
    scope: str
    status: BudgetStatus | str
    breached_dimension: str | None = None
    soft_ratio: float | None = None
    hard_cap: bool | None = None
    limits: BudgetAmounts | None = None
    consumed: BudgetAmounts | None = None
    remaining: BudgetAmounts | None = None
    gateways: list[QuotaWindow] = Field(default_factory=list)
    as_of: datetime


# ── A2A (SPEC-CSB-A2A-*) ─────────────────────────────────────────────────────


class AgentCard(BaseModel):
    """The A2A Agent Card (``GET /.well-known/agent-card.json``).

    Only the fields the SDK actively uses are declared; ``extra="allow"``
    lets the model tolerate additional server-side fields without breaking
    (SPEC-CSB-A2A-001) — the card is a forward-compatible, camelCase wire
    document owned by the A2A spec, not by this SDK.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = None
    protocol_version: str | None = Field(default=None, alias="protocolVersion")


class JsonRpcRequest(BaseModel):
    """A JSON-RPC 2.0 request envelope sent to ``POST /a2a``."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcError(BaseModel):
    """The ``error`` member of a JSON-RPC 2.0 response."""

    code: int
    message: str
    data: Any = None


class JsonRpcResponse(BaseModel):
    """A JSON-RPC 2.0 response envelope received from ``POST /a2a``."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any = None
    error: JsonRpcError | None = None

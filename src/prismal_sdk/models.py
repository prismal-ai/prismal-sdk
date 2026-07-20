"""Typed wire models (CSB-02-01, CSB-03-01, SPEC-CSB-CHT-*, SPEC-CSB-A2A-001).

These models mirror the shapes fixed by ``prismal-server``'s
``SPEC.md`` — they are not reinterpretations of them. Field names and
optionality follow the server's response bodies exactly (see that repo's
``routes/threads.py``, ``routes/a2a.py``, ``streaming.py``).
"""

from __future__ import annotations

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


class DoneEvent(BaseModel):
    """SSE ``event: done`` — terminal, ends the stream normally."""

    thread_id: str
    finish_reason: str


class ErrorEvent(BaseModel):
    """SSE ``event: error`` — terminal failure payload (raised, not yielded)."""

    code: str
    message: str


# Union of everything a chat stream can yield to the caller.
ChatEvent = TokenEvent | ToolCallEvent | StateEvent | DoneEvent


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

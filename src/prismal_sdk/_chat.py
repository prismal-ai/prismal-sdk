"""Chat SSE frame -> typed event translation (CSB-02-04, CS2-02-03).

Shared by ``PrismalClient.send_message`` and
``AsyncPrismalClient.send_message`` so the "raise on terminal error frame"
rule — and the per-protocol request/response handling of
SPEC-CS2-AGU-001..007 — can never diverge between the sync and async paths.

Internal module (leading underscore) — not part of the public API.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import httpx

from prismal_sdk._sse import DEFAULT_EVENT
from prismal_sdk.agui import (
    AgUiEvent,
    PrismalUsageEvent,
    RunError,
    RunFinished,
    parse_agui_event,
)
from prismal_sdk.exceptions import ProtocolNotEnabledError, error_for_code
from prismal_sdk.models import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    StateEvent,
    TokenEvent,
    ToolCallEvent,
    Usage,
)

# The HTTP status a mid-stream error frame maps to: the response already
# committed to 200 before the server-side failure occurred
# (SPEC-RHB-CHT-006), so the exception's status_code reflects that reality
# rather than a guessed 5xx.
_MID_STREAM_ERROR_STATUS = 200

_EVENT_MODELS: dict[str, type[TokenEvent | ToolCallEvent | StateEvent | DoneEvent]] = {
    "token": TokenEvent,
    "tool_call": ToolCallEvent,
    "state": StateEvent,
    "done": DoneEvent,
}


def translate_chat_frame(event: str, data: str) -> ChatEvent | None:
    """Translate one parsed SSE frame into a typed chat event, or ``None`` to skip.

    Raises the mapped exception for a terminal ``error`` frame
    (SPEC-CSB-CHT-004) instead of returning it. Unknown event names are
    skipped rather than raised, so a forward-compatible server addition never
    breaks an installed SDK version.
    """
    if event not in _EVENT_MODELS and event != "error":
        # Includes data-only frames: never part of the native protocol.
        return None
    return translate_chat_event(event, json.loads(data) if data else {})


def translate_chat_event(event: str, payload: Any) -> ChatEvent | None:
    """Translate an already-decoded native event (SSE frame or WS ``data``).

    Same rules as :func:`translate_chat_frame`: ``error`` raises the mapped
    exception, unknown names give ``None``.
    """
    model = _EVENT_MODELS.get(event)
    if model is not None:
        return model.model_validate(payload)
    if event == "error":
        err = ErrorEvent.model_validate(payload)
        # The whole payload rides along: budget_exceeded carries the partial
        # `usage` here (SPEC-CS2-ERR-002).
        raise error_for_code(_MID_STREAM_ERROR_STATUS, err.code, err.message, payload)
    return None


class AgUiTranslator:
    """Data-only frame -> AG-UI event, for one run (SPEC-CS2-AGU-002/003).

    Stateful only to remember the run's last ``prismal.usage``: a
    ``RUN_ERROR`` carries native ``TokenUsage[]`` instead, so the raised
    :class:`~prismal_sdk.exceptions.BudgetExceededError` gets its 12-key
    ``usage`` from that earlier event (SPEC-CS2-ERR-002) — the host's value,
    not a conversion.
    """

    def __init__(self) -> None:
        self._last_usage: Usage | None = None

    def __call__(self, event: str, data: str) -> AgUiEvent | None:
        if event != DEFAULT_EVENT or not data:
            # Named frames are not AG-UI; ignore them like unknown native ones.
            return None
        return self.translate(json.loads(data))

    def translate(self, payload: Mapping[str, Any]) -> AgUiEvent:
        """Translate an already-decoded AG-UI event (SSE frame or WS ``data``)."""
        parsed = parse_agui_event(payload)
        if isinstance(parsed, PrismalUsageEvent):
            self._last_usage = parsed.usage
        if isinstance(parsed, RunError):
            details: dict[str, Any] = dict(payload)
            details["usage"] = (
                self._last_usage.model_dump() if self._last_usage else None
            )
            raise error_for_code(
                _MID_STREAM_ERROR_STATUS,
                parsed.code or "internal_error",
                parsed.message,
                details,
            )
        return parsed


#: ``Accept`` that selects AG-UI on ``POST /threads/{id}/messages``.
AGUI_ACCEPT = "text/event-stream; profile=ag-ui"

#: Response header naming the protocol the host actually streams.
STREAM_PROTOCOL_HEADER = "X-Prismal-Stream-Protocol"


class StreamProfile(NamedTuple):
    """Everything that differs between a native and an AG-UI turn."""

    request_headers: dict[str, str]
    translate: Callable[[str, str], ChatEvent | AgUiEvent | None]
    terminal: type[DoneEvent] | type[RunFinished]
    #: Required value of :data:`STREAM_PROTOCOL_HEADER`, if any.
    negotiated: str | None


def stream_profile(protocol: str) -> StreamProfile:
    """The profile for ``send_message(protocol=...)``; ``ValueError`` if unknown."""
    if protocol == "prismal":
        return StreamProfile({}, translate_chat_frame, DoneEvent, None)
    if protocol == "ag-ui":
        return StreamProfile(
            {"Accept": AGUI_ACCEPT}, AgUiTranslator(), RunFinished, "ag-ui"
        )
    raise ValueError(f"protocol must be 'prismal' or 'ag-ui', got {protocol!r}")


def check_negotiated(profile: StreamProfile, response: httpx.Response) -> None:
    """Raise if the host streams another protocol than requested (AGU-007).

    A host without AG-UI support (v0.1) ignores the ``Accept`` profile and
    streams native frames, which the AG-UI translator would drop one by one:
    the caller would see an empty, successful turn.
    """
    if profile.negotiated is None:
        return
    got = response.headers.get(STREAM_PROTOCOL_HEADER, "").strip().lower()
    if got != profile.negotiated:
        raise ProtocolNotEnabledError(
            response.status_code,
            "protocol_not_enabled",
            f"Host did not negotiate {profile.negotiated!r} "
            f"({STREAM_PROTOCOL_HEADER}: {got or 'absent'})",
        )

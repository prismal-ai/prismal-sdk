"""Chat SSE frame -> typed event translation (CSB-02-04, SPEC-CSB-CHT-002/004).

Shared by ``PrismalClient.send_message`` and
``AsyncPrismalClient.send_message`` so the "raise on terminal error frame"
rule can never diverge between the sync and async code paths.

Internal module (leading underscore) — not part of the public API.
"""

from __future__ import annotations

import json

from prismal_sdk.exceptions import error_for_code
from prismal_sdk.models import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    StateEvent,
    TokenEvent,
    ToolCallEvent,
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
    payload = json.loads(data) if data else {}
    model = _EVENT_MODELS.get(event)
    if model is not None:
        return model.model_validate(payload)
    if event == "error":
        err = ErrorEvent.model_validate(payload)
        # The whole payload rides along: budget_exceeded carries the partial
        # `usage` here (SPEC-CS2-ERR-002).
        raise error_for_code(_MID_STREAM_ERROR_STATUS, err.code, err.message, payload)
    return None

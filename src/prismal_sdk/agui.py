"""AG-UI 1.0 event models (CS2-02-01, SPEC-CS2-AGU-002/004).

Hand-written Pydantic models for the 31 event types pinned by the engine's
``ADR-PRT-001`` §2.3 (``ag-ui-protocol`` 1.0.0). The wire is camelCase; the
models expose snake_case attributes through an alias generator and accept
either spelling on input.

Every model keeps unknown fields (``extra="allow"``) and an unknown ``type``
parses as the base :class:`AgUiEvent`, so a newer host never breaks an
installed SDK (DD-CS2-002). Payload values are kept verbatim: the native
``RUN_FINISHED.usage`` (``TokenUsage[]``) stays a raw list, and the
prismal 12-key usage arrives separately as ``CUSTOM`` ``prismal.usage``
(:class:`PrismalUsageEvent`).

AG-UI 1.0 has no ``INTERRUPT`` event: an interrupted run ends with
``RUN_FINISHED`` whose ``outcome`` is ``{"type": "interrupt", ...}``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from prismal_sdk.models import Usage

#: ``send_message(protocol=...)`` values (SPEC-CS2-AGU-001/006).
StreamProtocol = Literal["prismal", "ag-ui"]

#: ``CUSTOM`` event name the host uses for the 12-key usage (SPEC-RH2-AGU-004).
PRISMAL_USAGE_EVENT = "prismal.usage"


class AgUiEvent(BaseModel):
    """Base of every AG-UI event; also the model for unknown ``type`` values."""

    model_config = ConfigDict(
        extra="allow", alias_generator=to_camel, populate_by_name=True
    )

    type: str
    timestamp: int | None = None
    run_id: str | None = None
    thread_id: str | None = None


# ── Lifecycle ───────────────────────────────────────────────────────────────


class RunStarted(AgUiEvent):
    protocol_version: str | None = None


class RunFinished(AgUiEvent):
    """Terminal: always the last event a successful run yields."""

    result: Any | None = None
    #: ``{"type": "interrupt", "interrupts": [...]}`` for an interrupted run.
    outcome: dict[str, Any] | None = None
    #: Native AG-UI ``TokenUsage[]``, raw (camelCase keys).
    usage: list[dict[str, Any]] | None = None


class RunError(AgUiEvent):
    """Terminal failure — raised as the mapped exception, never yielded."""

    message: str
    code: str | None = None
    usage: list[dict[str, Any]] | None = None


class StepStarted(AgUiEvent): ...


class StepFinished(AgUiEvent): ...


# ── Text messages ───────────────────────────────────────────────────────────


class TextMessageStart(AgUiEvent):
    message_id: str
    role: str | None = None


class TextMessageContent(AgUiEvent):
    message_id: str
    delta: str


class TextMessageEnd(AgUiEvent):
    message_id: str


class TextMessageChunk(AgUiEvent): ...


# ── Tool calls ──────────────────────────────────────────────────────────────


class ToolCallStart(AgUiEvent):
    tool_call_id: str
    tool_call_name: str
    parent_message_id: str | None = None


class ToolCallArgs(AgUiEvent):
    tool_call_id: str
    delta: str


class ToolCallEnd(AgUiEvent):
    tool_call_id: str


class ToolCallChunk(AgUiEvent): ...


class ToolCallResult(AgUiEvent):
    tool_call_id: str
    content: Any
    message_id: str | None = None


# ── State, messages, activity ───────────────────────────────────────────────


class StateSnapshot(AgUiEvent):
    snapshot: dict[str, Any]


class StateDelta(AgUiEvent):
    #: RFC 6902 JSON Patch operations.
    delta: list[dict[str, Any]]


class MessagesSnapshot(AgUiEvent): ...


class ActivitySnapshot(AgUiEvent): ...


class ActivityDelta(AgUiEvent): ...


# ── Reasoning ───────────────────────────────────────────────────────────────


class ReasoningStart(AgUiEvent): ...


class ReasoningMessageStart(AgUiEvent): ...


class ReasoningMessageContent(AgUiEvent): ...


class ReasoningMessageEnd(AgUiEvent): ...


class ReasoningMessageChunk(AgUiEvent): ...


class ReasoningEnd(AgUiEvent): ...


class ReasoningEncryptedValue(AgUiEvent): ...


# ── Sub-agents ──────────────────────────────────────────────────────────────


class SubagentStarted(AgUiEvent):
    subagent_run_id: str
    name: str
    description: str | None = None
    parent_subagent_run_id: str | None = None
    parent_tool_call_id: str | None = None
    parent_message_id: str | None = None


class SubagentFinished(AgUiEvent):
    subagent_run_id: str
    result: Any | None = None
    outcome: Any | None = None


class SubagentError(AgUiEvent):
    subagent_run_id: str


# ── Escape hatches ──────────────────────────────────────────────────────────


class Raw(AgUiEvent): ...


class CustomEvent(AgUiEvent):
    name: str
    value: Any = None


class PrismalUsageEvent(CustomEvent):
    """``CUSTOM`` ``prismal.usage`` — the turn's 12-key usage (SPEC-CS2-AGU-004).

    The host sends it just before ``RUN_FINISHED`` (or ``RUN_ERROR``).
    """

    value: Usage

    @property
    def usage(self) -> Usage:
        return self.value


#: AG-UI 1.0 ``type`` string → model (the 31 types of ADR-PRT-001 §2.3).
AGUI_EVENT_TYPES: Mapping[str, type[AgUiEvent]] = {
    "RUN_STARTED": RunStarted,
    "RUN_FINISHED": RunFinished,
    "RUN_ERROR": RunError,
    "STEP_STARTED": StepStarted,
    "STEP_FINISHED": StepFinished,
    "TEXT_MESSAGE_START": TextMessageStart,
    "TEXT_MESSAGE_CONTENT": TextMessageContent,
    "TEXT_MESSAGE_END": TextMessageEnd,
    "TEXT_MESSAGE_CHUNK": TextMessageChunk,
    "TOOL_CALL_START": ToolCallStart,
    "TOOL_CALL_ARGS": ToolCallArgs,
    "TOOL_CALL_END": ToolCallEnd,
    "TOOL_CALL_CHUNK": ToolCallChunk,
    "TOOL_CALL_RESULT": ToolCallResult,
    "STATE_SNAPSHOT": StateSnapshot,
    "STATE_DELTA": StateDelta,
    "MESSAGES_SNAPSHOT": MessagesSnapshot,
    "ACTIVITY_SNAPSHOT": ActivitySnapshot,
    "ACTIVITY_DELTA": ActivityDelta,
    "REASONING_START": ReasoningStart,
    "REASONING_MESSAGE_START": ReasoningMessageStart,
    "REASONING_MESSAGE_CONTENT": ReasoningMessageContent,
    "REASONING_MESSAGE_END": ReasoningMessageEnd,
    "REASONING_MESSAGE_CHUNK": ReasoningMessageChunk,
    "REASONING_END": ReasoningEnd,
    "REASONING_ENCRYPTED_VALUE": ReasoningEncryptedValue,
    "SUBAGENT_STARTED": SubagentStarted,
    "SUBAGENT_FINISHED": SubagentFinished,
    "SUBAGENT_ERROR": SubagentError,
    "RAW": Raw,
    "CUSTOM": CustomEvent,
}


def parse_agui_event(data: Mapping[str, Any]) -> AgUiEvent:
    """Parse one decoded AG-UI event, dispatching on ``type``.

    An unknown ``type`` parses as the base :class:`AgUiEvent` with every
    field kept (SPEC-CS2-AGU-002).
    """
    model = AGUI_EVENT_TYPES.get(str(data.get("type")), AgUiEvent)
    if model is CustomEvent and data.get("name") == PRISMAL_USAGE_EVENT:
        model = PrismalUsageEvent
    return model.model_validate(data)


__all__ = [
    "AGUI_EVENT_TYPES",
    "PRISMAL_USAGE_EVENT",
    "ActivityDelta",
    "ActivitySnapshot",
    "AgUiEvent",
    "CustomEvent",
    "MessagesSnapshot",
    "PrismalUsageEvent",
    "Raw",
    "ReasoningEncryptedValue",
    "ReasoningEnd",
    "ReasoningMessageChunk",
    "ReasoningMessageContent",
    "ReasoningMessageEnd",
    "ReasoningMessageStart",
    "ReasoningStart",
    "RunError",
    "RunFinished",
    "RunStarted",
    "StateDelta",
    "StateSnapshot",
    "StepFinished",
    "StepStarted",
    "StreamProtocol",
    "SubagentError",
    "SubagentFinished",
    "SubagentStarted",
    "TextMessageChunk",
    "TextMessageContent",
    "TextMessageEnd",
    "TextMessageStart",
    "ToolCallArgs",
    "ToolCallChunk",
    "ToolCallEnd",
    "ToolCallResult",
    "ToolCallStart",
    "parse_agui_event",
]

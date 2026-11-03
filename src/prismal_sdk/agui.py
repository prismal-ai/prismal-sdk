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
:attr:`RunFinished.interrupts` reads them, and :class:`ResumeEntry` answers
them through ``run_agui(..., resume=[...])`` (SPEC-CS3-INT-*). Interrupt ids
and resume payloads are opaque: the SDK passes both through unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from prismal_sdk.models import Usage

#: ``send_message(protocol=...)`` values (SPEC-CS2-AGU-001/006).
StreamProtocol = Literal["prismal", "ag-ui"]

#: ``ResumeEntry.status`` values of AG-UI 1.0. The host 0.3 refuses
#: ``"cancelled"`` (``422 unsupported_resume``) until the engine defines it.
ResumeStatus = Literal["resolved", "cancelled"]

#: ``RUN_FINISHED.outcome.type`` of an interrupted run.
INTERRUPT_OUTCOME = "interrupt"

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


# ── Interrupts and resume (SPEC-CS3-INT-*) ──────────────────────────────────


class ResumeEntry(BaseModel):
    """One answer to an open interrupt — AG-UI 1.0 ``ResumeEntry``.

    ``payload`` goes to the engine unchanged as the interrupt's resume value;
    the SDK never reads it (SPEC-CS3-INT-004).
    """

    model_config = ConfigDict(
        extra="allow", alias_generator=to_camel, populate_by_name=True
    )

    interrupt_id: str = Field(min_length=1)
    status: ResumeStatus | str = "resolved"
    payload: Any = None
    metadata: dict[str, Any] | None = None

    def to_wire(self) -> dict[str, Any]:
        """The camelCase wire object; ``metadata`` only when set (INT-003)."""
        wire: dict[str, Any] = {
            "interruptId": self.interrupt_id,
            "status": self.status,
            "payload": self.payload,
        }
        if self.metadata is not None:
            wire["metadata"] = self.metadata
        return wire


class AgUiInterrupt(BaseModel):
    """One open interrupt from ``RUN_FINISHED.outcome.interrupts[]``.

    ``id`` is opaque (the host 0.3 sends ``"<engine id>.<checkpoint id>"``):
    send it back exactly as received (SPEC-CS3-INT-002).
    """

    model_config = ConfigDict(
        extra="allow", alias_generator=to_camel, populate_by_name=True
    )

    id: str
    reason: str | None = None
    message: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] | None = None

    def resolve(self, payload: Any = None) -> ResumeEntry:
        """A ``resolved`` :class:`ResumeEntry` answering this interrupt."""
        return ResumeEntry(interrupt_id=self.id, status="resolved", payload=payload)


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

    @property
    def is_interrupted(self) -> bool:
        """Whether the run paused on interrupts (``outcome.type == "interrupt"``)."""
        return (self.outcome or {}).get("type") == INTERRUPT_OUTCOME

    @property
    def interrupts(self) -> list[AgUiInterrupt]:
        """The open interrupts, in host order; ``[]`` unless interrupted.

        Entries that are not objects with an ``id`` are skipped rather than
        raised, so a malformed outcome never breaks the stream (INT-001).
        """
        if not self.is_interrupted:
            return []
        raw = (self.outcome or {}).get("interrupts")
        if not isinstance(raw, list):
            return []
        return [
            AgUiInterrupt.model_validate(item)
            for item in raw
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]


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
    "AgUiInterrupt",
    "CustomEvent",
    "INTERRUPT_OUTCOME",
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
    "ResumeEntry",
    "ResumeStatus",
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

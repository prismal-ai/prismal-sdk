"""AG-UI 1.0 event models (CS2-02-01, SPEC-CS2-AGU-002/004)."""

from __future__ import annotations

import pytest

from prismal_sdk.agui import (
    AGUI_EVENT_TYPES,
    AgUiEvent,
    CustomEvent,
    PrismalUsageEvent,
    RunError,
    RunFinished,
    RunStarted,
    SubagentError,
    SubagentFinished,
    SubagentStarted,
    TextMessageContent,
    ToolCallResult,
    ToolCallStart,
    parse_agui_event,
)
from prismal_sdk.models import Usage
from tests.wire_v02 import AGUI_1_0_TYPES, AGUI_GOLDEN, USAGE_EXAMPLE

_GOLDEN_EVENTS = [
    pytest.param(event, id=f"{name}-{i}-{event['type']}")
    for name, golden in AGUI_GOLDEN.items()
    for i, event in enumerate(golden["expected"])
]


def test_registry_covers_exactly_the_31_pinned_types():
    assert set(AGUI_EVENT_TYPES) == AGUI_1_0_TYPES


def test_every_registered_model_is_an_agui_event():
    for model in AGUI_EVENT_TYPES.values():
        assert issubclass(model, AgUiEvent)
    # One model per type: no two type strings share a class.
    assert len(set(AGUI_EVENT_TYPES.values())) == len(AGUI_EVENT_TYPES)


def test_there_is_no_interrupt_event():
    # ADR-PRT-001 §2.3: interrupts arrive in RUN_FINISHED.outcome.
    assert "INTERRUPT" not in AGUI_EVENT_TYPES


@pytest.mark.parametrize("raw", _GOLDEN_EVENTS)
def test_golden_events_parse_to_their_model_and_round_trip(raw):
    event = parse_agui_event(raw)
    expected = AGUI_EVENT_TYPES[raw["type"]]
    if raw["type"] == "CUSTOM" and raw["name"] == "prismal.usage":
        expected = PrismalUsageEvent
    assert type(event) is expected
    assert event.model_dump(by_alias=True, exclude_unset=True) == raw


def test_fields_are_snake_case_on_the_model():
    event = parse_agui_event(
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m-1", "delta": "hi"}
    )
    assert isinstance(event, TextMessageContent)
    assert (event.message_id, event.delta) == ("m-1", "hi")


def test_run_started_carries_the_protocol_version():
    event = AGUI_GOLDEN["react_text"]["expected"][0]
    parsed = parse_agui_event(event)
    assert isinstance(parsed, RunStarted)
    assert parsed.protocol_version == "1.0"
    assert (parsed.run_id, parsed.thread_id) == ("run-1", "thread-1")


def test_interrupt_is_read_from_run_finished_outcome():
    parsed = parse_agui_event(AGUI_GOLDEN["hitl_interrupt"]["expected"][-1])
    assert isinstance(parsed, RunFinished)
    assert parsed.outcome is not None
    assert parsed.outcome["type"] == "interrupt"
    assert parsed.outcome["interrupts"][0]["id"] == "intr-1"
    # Native AG-UI TokenUsage[] stays raw (camelCase); the SDK does not map it.
    assert parsed.usage is not None and parsed.usage[0]["inputTokens"] == 30


def test_subagent_events_use_subagent_run_id():
    golden = AGUI_GOLDEN["skynet_subagents"]["expected"]
    by_type = {e["type"]: parse_agui_event(e) for e in golden}
    started = by_type["SUBAGENT_STARTED"]
    finished = by_type["SUBAGENT_FINISHED"]
    error = by_type["SUBAGENT_ERROR"]
    assert isinstance(started, SubagentStarted)
    assert isinstance(finished, SubagentFinished)
    assert isinstance(error, SubagentError)
    assert started.subagent_run_id.startswith("worker-")
    assert error.subagent_run_id == "worker-o2"
    assert error.model_dump(by_alias=True)["code"] == "timeout"


def test_tool_call_models():
    start = parse_agui_event(
        {
            "type": "TOOL_CALL_START",
            "toolCallId": "c-1",
            "toolCallName": "search",
            "parentMessageId": "m-1",
        }
    )
    assert isinstance(start, ToolCallStart)
    assert (start.tool_call_id, start.tool_call_name) == ("c-1", "search")
    result = parse_agui_event(
        {"type": "TOOL_CALL_RESULT", "toolCallId": "c-1", "content": "ok"}
    )
    assert isinstance(result, ToolCallResult)
    assert result.message_id is None


def test_run_error_model():
    raw = AGUI_GOLDEN["run_error"]["expected"][-1]
    parsed = parse_agui_event(raw)
    assert isinstance(parsed, RunError)
    assert (parsed.code, parsed.message) == ("budget_exceeded", raw["message"])


def test_prismal_usage_custom_event_exposes_typed_usage():
    parsed = parse_agui_event(
        {"type": "CUSTOM", "name": "prismal.usage", "value": USAGE_EXAMPLE}
    )
    assert isinstance(parsed, PrismalUsageEvent)
    assert isinstance(parsed, CustomEvent)
    assert parsed.usage == Usage.model_validate(USAGE_EXAMPLE)


def test_other_custom_events_stay_generic():
    parsed = parse_agui_event(
        {"type": "CUSTOM", "name": "prismal.routing", "value": {"tier": "small"}}
    )
    assert type(parsed) is CustomEvent
    assert parsed.value == {"tier": "small"}


def test_unknown_type_parses_as_base_event_keeping_its_fields():
    raw = {"type": "TELEPATHY_STARTED", "timestamp": 1, "mindId": "x", "depth": 3}
    parsed = parse_agui_event(raw)
    assert type(parsed) is AgUiEvent
    assert parsed.type == "TELEPATHY_STARTED"
    assert parsed.model_dump(by_alias=True, exclude_unset=True) == raw


def test_known_type_with_extra_fields_keeps_them():
    raw = {"type": "TEXT_MESSAGE_END", "messageId": "m-1", "futureField": [1]}
    parsed = parse_agui_event(raw)
    assert parsed.model_dump(by_alias=True, exclude_unset=True) == raw


def test_agui_entry_points_are_exported_from_the_package():
    import prismal_sdk

    for name in ["AgUiEvent", "PrismalUsageEvent", "RunFinished", "parse_agui_event"]:
        assert name in prismal_sdk.__all__
    assert prismal_sdk.parse_agui_event is parse_agui_event

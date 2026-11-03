"""AG-UI interrupts and resume entries (CS3-01-01/02, SPEC-CS3-INT-*, ERR-001)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from prismal_sdk import ResumeConflictError, ValidationError
from prismal_sdk.agui import (
    AgUiInterrupt,
    ResumeEntry,
    RunFinished,
    parse_agui_event,
)
from prismal_sdk.exceptions import PrismalAPIError, error_for_code

FIXTURE = json.loads(
    (
        Path(__file__).parent.parent / "fixtures/agui_resume/interrupt_resume.json"
    ).read_text()
)


def _interrupted_finish() -> dict[str, Any]:
    return FIXTURE["runs"][0]["events"][-1]


# ── SPEC-CS3-INT-001 / 002 ──────────────────────────────────────────────────


def test_interrupted_run_exposes_its_interrupts():
    finished = parse_agui_event(_interrupted_finish())
    assert isinstance(finished, RunFinished)
    assert finished.is_interrupted is True
    [interrupt] = finished.interrupts
    assert isinstance(interrupt, AgUiInterrupt)
    # The checkpoint suffix is kept verbatim (INT-002).
    assert interrupt.id == "fake-int-1.fake-ckpt-1"
    assert interrupt.reason == "input_required"
    assert interrupt.message == "Approve the plan?"
    assert interrupt.tool_call_id is None
    assert interrupt.metadata == {
        "value": {"reason": "input_required", "message": "Approve the plan?"}
    }


def test_successful_run_has_no_interrupts():
    finished = parse_agui_event(FIXTURE["runs"][1]["events"][-1])
    assert isinstance(finished, RunFinished)
    assert finished.is_interrupted is False
    assert finished.interrupts == []


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        {"type": "success"},
        {"type": "interrupt"},
        {"type": "interrupt", "interrupts": "not-a-list"},
        {"type": "interrupt", "interrupts": ["not-an-object", {"no": "id"}]},
    ],
)
def test_missing_or_malformed_interrupts_give_an_empty_list(outcome):
    finished = RunFinished.model_validate({"type": "RUN_FINISHED", "outcome": outcome})
    assert finished.interrupts == []
    assert finished.is_interrupted is (
        outcome is not None and outcome.get("type") == "interrupt"
    )


def test_interrupt_accepts_camel_case_tool_call_id_and_keeps_extras():
    interrupt = AgUiInterrupt.model_validate(
        {"id": "i.c", "reason": "tool", "toolCallId": "tc-1", "future": 1}
    )
    assert interrupt.tool_call_id == "tc-1"
    assert interrupt.model_extra == {"future": 1}


def test_several_interrupts_keep_host_order():
    finished = RunFinished.model_validate(
        {
            "type": "RUN_FINISHED",
            "outcome": {
                "type": "interrupt",
                "interrupts": [{"id": "b.c"}, {"id": "a.c"}],
            },
        }
    )
    assert [i.id for i in finished.interrupts] == ["b.c", "a.c"]


# ── SPEC-CS3-INT-003 / 004 / 005 ────────────────────────────────────────────


def test_resolve_builds_a_resolved_entry_with_the_verbatim_id():
    interrupt = AgUiInterrupt(id="fake-int-1.fake-ckpt-1")
    entry = interrupt.resolve({"action": "approve"})
    assert entry == ResumeEntry(
        interrupt_id="fake-int-1.fake-ckpt-1",
        status="resolved",
        payload={"action": "approve"},
    )


def test_resume_entry_wire_matches_the_host_fixture():
    recorded = FIXTURE["runs"][1]["input"]["resume"]
    entry = ResumeEntry(
        interrupt_id="fake-int-1.fake-ckpt-1", payload={"action": "approve"}
    )
    assert [entry.to_wire()] == recorded


def test_resume_entry_defaults_payload_to_null_and_omits_unset_metadata():
    assert ResumeEntry(interrupt_id="i.c").to_wire() == {
        "interruptId": "i.c",
        "status": "resolved",
        "payload": None,
    }
    assert AgUiInterrupt(id="i.c").resolve().payload is None


def test_resume_entry_sends_metadata_when_set():
    wire = ResumeEntry(interrupt_id="i.c", metadata={"by": "ui"}).to_wire()
    assert wire["metadata"] == {"by": "ui"}


def test_cancelled_status_is_sent_as_given():
    # The host refuses it with 422 unsupported_resume; the SDK does not decide.
    wire = ResumeEntry(interrupt_id="i.c", status="cancelled").to_wire()
    assert wire["status"] == "cancelled"


def test_resume_entry_rejects_an_empty_interrupt_id():
    with pytest.raises(PydanticValidationError):
        ResumeEntry(interrupt_id="")


def test_resume_entry_accepts_the_camel_case_wire():
    entry = ResumeEntry.model_validate(FIXTURE["runs"][1]["input"]["resume"][0])
    assert entry.interrupt_id == "fake-int-1.fake-ckpt-1"
    assert entry.payload == {"action": "approve"}


# ── SPEC-CS3-ERR-001 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "status", "klass"),
    [
        ("no_pending_interrupt", 409, ResumeConflictError),
        ("resume_in_progress", 409, ResumeConflictError),
        ("invalid_resume", 422, ValidationError),
        ("unsupported_resume", 422, ValidationError),
    ],
)
def test_resume_codes_map_by_code(code, status, klass):
    err = error_for_code(status, code, "msg")
    assert type(err) is klass
    assert err.code == code
    assert err.status_code == status
    # Mapped by code, never by status (SPEC-CS2-ERR-001).
    assert type(error_for_code(200, code, "msg")) is klass


def test_resume_conflict_is_an_api_error():
    assert issubclass(ResumeConflictError, PrismalAPIError)

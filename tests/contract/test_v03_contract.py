"""v0.3 contract suite (CS3-03-01, SPEC-CS3-CTR-002) — AG-UI interrupt resume.

Runs against a **fake-LLM** ``prismal-server`` 0.3, whose fake script turns
``/interrupt <message>`` into a LangGraph interrupt and echoes a resume as
``resumed: <json>`` (host RH3-02 DESIGN §4.4). Same opt-in and skip rules as
``test_v02_contract.py``::

    PRISMAL_BASE_URL=http://localhost:8000 uv run pytest -m contract

The host 0.2 has no resume, so against it these cases fail by design.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest

from prismal_sdk import (
    AsyncPrismalClient,
    PrismalClient,
    ResumeConflictError,
    ValidationError,
)
from prismal_sdk.agui import (
    AgUiInterrupt,
    PrismalUsageEvent,
    ResumeEntry,
    RunFinished,
    RunStarted,
    TextMessageContent,
)
from tests.contract.test_v02_contract import (
    BASE_URL,
    FAKE_USAGE,
    ORG_ID,
    TOKEN,
    fake_host,  # noqa: F401 — pytest fixture, re-used
)

pytestmark = pytest.mark.contract

APPROVE = {"action": "approve"}


@pytest.fixture
def client(fake_host: httpx.Response) -> Iterator[PrismalClient]:  # noqa: F811
    with PrismalClient(BASE_URL, token=TOKEN, org_id=ORG_ID) as c:
        yield c


@pytest.fixture
async def async_client(
    fake_host: httpx.Response,  # noqa: F811
) -> AsyncIterator[AsyncPrismalClient]:
    async with AsyncPrismalClient(BASE_URL, token=TOKEN, org_id=ORG_ID) as c:
        yield c


def _text(events: list[Any]) -> str:
    return "".join(e.delta for e in events if isinstance(e, TextMessageContent))


def _interrupted(client: PrismalClient, question: str) -> tuple[str, AgUiInterrupt]:
    thread_id = client.create_thread().thread_id
    events = list(client.run_agui(thread_id, f"/interrupt {question}"))
    assert isinstance(events[0], RunStarted)
    assert [e.usage for e in events if isinstance(e, PrismalUsageEvent)] == [FAKE_USAGE]
    finished = events[-1]
    assert isinstance(finished, RunFinished) and finished.is_interrupted
    [interrupt] = finished.interrupts
    assert interrupt.reason == "input_required"
    assert interrupt.message == question
    return thread_id, interrupt


def test_interrupt_then_resume_round_trip(client: PrismalClient) -> None:
    thread_id, interrupt = _interrupted(client, "Approve the plan?")
    run_id = uuid.uuid4().hex
    events = list(
        client.run_agui(thread_id, resume=[interrupt.resolve(APPROVE)], run_id=run_id)
    )
    assert isinstance(events[0], RunStarted) and events[0].run_id == run_id
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.is_interrupted is False
    assert finished.outcome == {"type": "success"}
    text = _text(events)
    assert text.startswith("resumed: ") and '{"action": "approve"}' in text


def test_retried_resume_is_a_conflict(client: PrismalClient) -> None:
    thread_id, interrupt = _interrupted(client, "Once only?")
    answer = [interrupt.resolve(APPROVE)]
    list(client.run_agui(thread_id, resume=answer))
    with pytest.raises(ResumeConflictError) as info:
        list(client.run_agui(thread_id, resume=answer))
    assert info.value.code == "no_pending_interrupt"
    assert info.value.status_code == 409


def test_unfenced_interrupt_id_is_invalid_resume(client: PrismalClient) -> None:
    # An id without the host's checkpoint suffix (docs/agui.md).
    thread_id, _ = _interrupted(client, "Which one?")
    with pytest.raises(ValidationError) as info:
        list(client.run_agui(thread_id, resume=[ResumeEntry(interrupt_id="nope")]))
    assert info.value.code == "invalid_resume"
    assert info.value.status_code == 422


def test_stale_checkpoint_suffix_is_a_conflict(client: PrismalClient) -> None:
    # A suffix from another checkpoint means the run has moved on.
    thread_id, _ = _interrupted(client, "Still there?")
    with pytest.raises(ResumeConflictError) as info:
        list(client.run_agui(thread_id, resume=[ResumeEntry(interrupt_id="a.b")]))
    assert info.value.code == "no_pending_interrupt"


def test_cancelled_entry_is_unsupported(client: PrismalClient) -> None:
    thread_id, interrupt = _interrupted(client, "Cancel me?")
    entry = ResumeEntry(interrupt_id=interrupt.id, status="cancelled")
    with pytest.raises(ValidationError) as info:
        list(client.run_agui(thread_id, resume=[entry]))
    assert info.value.code == "unsupported_resume"
    # The refusal consumed nothing: the interrupt is still open.
    events = list(client.run_agui(thread_id, resume=[interrupt.resolve(APPROVE)]))
    assert isinstance(events[-1], RunFinished) and not events[-1].is_interrupted


def test_resume_with_nothing_pending_is_a_conflict(client: PrismalClient) -> None:
    thread_id = client.create_thread().thread_id
    with pytest.raises(ResumeConflictError) as info:
        list(client.run_agui(thread_id, resume=[ResumeEntry(interrupt_id="i.c")]))
    assert info.value.code == "no_pending_interrupt"


def test_plain_run_agui_turn_succeeds(client: PrismalClient) -> None:
    thread_id = client.create_thread().thread_id
    content = f"contract {uuid.uuid4().hex}"
    events = list(client.run_agui(thread_id, content))
    finished = events[-1]
    assert isinstance(finished, RunFinished) and not finished.is_interrupted
    assert content in _text(events)


async def test_async_interrupt_then_resume(async_client: AsyncPrismalClient) -> None:
    thread_id = (await async_client.create_thread()).thread_id
    first = [e async for e in async_client.run_agui(thread_id, "/interrupt Go?")]
    finished = first[-1]
    assert isinstance(finished, RunFinished) and finished.is_interrupted
    answers = [i.resolve(APPROVE) for i in finished.interrupts]
    second = [e async for e in async_client.run_agui(thread_id, resume=answers)]
    assert isinstance(second[-1], RunFinished) and not second[-1].is_interrupted
    assert _text(second).startswith("resumed: ")

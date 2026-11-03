"""`run_agui` — `POST /v1/agui` with a `RunAgentInput` (CS3-02-01/02).

SPEC-CS3-RUN-001..006 and FIX-001, sync and async, against the host's
recorded interrupt → resume fixture.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from prismal_sdk import (
    PrismalConnectionError,
    ProtocolNotEnabledError,
    ResumeConflictError,
    ValidationError,
)
from prismal_sdk.agui import (
    AgUiEvent,
    ResumeEntry,
    RunFinished,
    TextMessageContent,
)
from prismal_sdk.exceptions import BudgetExceededError
from tests.wire_v02 import agui_body

FIXTURE = json.loads(
    (
        Path(__file__).parent.parent / "fixtures/agui_resume/interrupt_resume.json"
    ).read_text()
)
RUN_1, RUN_2 = FIXTURE["runs"]
HEX32 = re.compile(r"^[0-9a-f]{32}$")
SSE = {"content-type": "text/event-stream", "x-prismal-stream-protocol": "ag-ui"}
_EMPTY_INPUT = {"tools": [], "context": [], "state": {}, "forwardedProps": {}}
_START = {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"}
_END = {"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"}


def _handler(body: bytes, seen: list[httpx.Request], status: int = 200, headers=SSE):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body, headers=headers)

    return handler


def _error(status: int, code: str) -> bytes:
    return json.dumps({"error": {"code": code, "message": code}}).encode()


def _without_generated_ids(body: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in body.items() if k != "runId"}
    out["messages"] = [
        {k: v for k, v in m.items() if k != "id"} for m in body["messages"]
    ]
    return out


# ── request shape (RUN-001, RUN-003, RUN-006) ───────────────────────────────


def test_content_run_posts_a_full_run_agent_input(make_client):
    seen: list[httpx.Request] = []
    handler = _handler(agui_body([_START, _END]), seen)
    with make_client(handler, token="tok", org_id="default-org") as client:
        list(client.run_agui("t-1", "hello", run_id="r-1", org_id="acme"))
    [request] = seen
    assert request.method == "POST"
    assert request.url.path == "/v1/agui"
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["x-org-id"] == "acme"
    assert request.headers["accept"] == "text/event-stream"
    body = json.loads(request.content)
    [message] = body["messages"]
    assert HEX32.match(message["id"])
    assert body == {
        "threadId": "t-1",
        "runId": "r-1",
        "messages": [{"id": message["id"], "role": "user", "content": "hello"}],
        **_EMPTY_INPUT,
    }


def test_run_id_defaults_to_a_fresh_uuid4_hex(make_client):
    seen: list[httpx.Request] = []
    with make_client(_handler(agui_body([_START, _END]), seen)) as client:
        list(client.run_agui("t-1", "a"))
        list(client.run_agui("t-1", "b"))
    run_ids = [json.loads(r.content)["runId"] for r in seen]
    message_ids = [json.loads(r.content)["messages"][0]["id"] for r in seen]
    assert all(HEX32.match(i) for i in run_ids + message_ids)
    assert len(set(run_ids)) == 2 and len(set(message_ids)) == 2


def test_client_org_id_is_used_without_an_override(make_client):
    seen: list[httpx.Request] = []
    with make_client(_handler(agui_body([_START, _END]), seen), org_id="o") as c:
        list(c.run_agui("t-1", "hi"))
    assert seen[0].headers["x-org-id"] == "o"


def test_resume_run_sends_entries_in_order_and_no_messages(make_client):
    seen: list[httpx.Request] = []
    entries = [
        ResumeEntry(interrupt_id="b.c", payload=1),
        ResumeEntry(interrupt_id="a.c", status="cancelled", metadata={"m": 1}),
    ]
    with make_client(_handler(agui_body([_START, _END]), seen)) as client:
        list(client.run_agui("t-1", resume=entries, run_id="r-2"))
    body = json.loads(seen[0].content)
    assert body == {
        "threadId": "t-1",
        "runId": "r-2",
        "messages": [],
        "resume": [
            {"interruptId": "b.c", "status": "resolved", "payload": 1},
            {
                "interruptId": "a.c",
                "status": "cancelled",
                "payload": None,
                "metadata": {"m": 1},
            },
        ],
        **_EMPTY_INPUT,
    }


def test_thread_id_travels_verbatim_in_the_body(make_client):
    seen: list[httpx.Request] = []
    with make_client(_handler(agui_body([_START, _END]), seen)) as client:
        list(client.run_agui("a/../b?x", "hi"))
    assert seen[0].url.path == "/v1/agui"
    assert json.loads(seen[0].content)["threadId"] == "a/../b?x"


# ── argument checks before I/O (RUN-002) ────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"content": "hi", "resume": [ResumeEntry(interrupt_id="i.c")]},
        {"resume": []},
        {"content": None, "resume": None},
    ],
)
def test_exactly_one_of_content_and_resume(make_client, kwargs):
    seen: list[httpx.Request] = []
    with make_client(_handler(b"", seen)) as client:
        with pytest.raises(ValueError, match="exactly one of"):
            list(client.run_agui("t-1", **kwargs))
    assert seen == []


async def test_async_exactly_one_of_content_and_resume(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_handler(b"", seen)) as client:
        with pytest.raises(ValueError, match="exactly one of"):
            async for _ in client.run_agui("t-1"):
                pass
    assert seen == []


# ── response handling (RUN-004) ─────────────────────────────────────────────


def test_iteration_ends_at_run_finished(make_client):
    trailing = {"type": "RAW", "event": "after"}
    with make_client(_handler(agui_body([_START, _END, trailing]), [])) as client:
        events = list(client.run_agui("t-1", "hi"))
    assert [e.type for e in events] == ["RUN_STARTED", "RUN_FINISHED"]
    assert isinstance(events[-1], RunFinished)


@pytest.mark.parametrize(
    ("status", "code", "klass"),
    [
        (409, "no_pending_interrupt", ResumeConflictError),
        (409, "resume_in_progress", ResumeConflictError),
        (422, "invalid_resume", ValidationError),
        (422, "unsupported_resume", ValidationError),
        (406, "protocol_not_enabled", ProtocolNotEnabledError),
    ],
)
def test_refusals_raise_before_any_event(make_client, status, code, klass):
    handler = _handler(
        _error(status, code), [], status, {"content-type": "application/json"}
    )
    events: list[AgUiEvent] = []
    with make_client(handler) as client:
        with pytest.raises(klass) as info:
            for event in client.run_agui("t-1", resume=[ResumeEntry(interrupt_id="x")]):
                events.append(event)
    assert events == []
    assert info.value.code == code and info.value.status_code == status


def test_run_error_raises_the_mapped_error_with_the_last_usage(make_client):
    usage = RUN_1["events"][2]
    run_error = {"type": "RUN_ERROR", "message": "out", "code": "budget_exceeded"}
    with make_client(_handler(agui_body([_START, usage, run_error]), [])) as client:
        with pytest.raises(BudgetExceededError) as info:
            list(client.run_agui("t-1", "hi"))
    assert info.value.usage is not None
    assert info.value.usage.total_tokens == 15


# ── never retried (RUN-005) ─────────────────────────────────────────────────


def test_connect_failure_is_not_retried(make_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    with make_client(handler, max_retries=3) as client:
        with pytest.raises(PrismalConnectionError):
            list(client.run_agui("t-1", resume=[ResumeEntry(interrupt_id="i.c")]))
    assert len(calls) == 1


async def test_async_connect_failure_is_not_retried(make_async_client):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectTimeout("slow", request=request)

    async with make_async_client(handler, max_retries=3) as client:
        with pytest.raises(Exception) as info:
            async for _ in client.run_agui("t-1", "hi"):
                pass
    assert type(info.value).__name__ == "PrismalTimeoutError"
    assert len(calls) == 1


# ── the host fixture, replayed (FIX-001) ────────────────────────────────────


def _replay_handler(seen: list[httpx.Request]):
    runs = iter(FIXTURE["runs"])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=agui_body(next(runs)["events"]), headers=SSE)

    return handler


def _assert_replayed(seen: list[httpx.Request], first, second) -> None:
    for request, run in zip(seen, FIXTURE["runs"], strict=True):
        body = json.loads(request.content)
        assert _without_generated_ids(body) == _without_generated_ids(run["input"])
    for events, run in ((first, RUN_1), (second, RUN_2)):
        assert [e.model_dump(by_alias=True, exclude_unset=True) for e in events] == (
            run["events"]
        )
    finished = first[-1]
    assert isinstance(finished, RunFinished) and finished.is_interrupted
    assert second[-1].is_interrupted is False
    text = "".join(e.delta for e in second if isinstance(e, TextMessageContent))
    assert text == 'resumed: {"fake-int-1": {"action": "approve"}}'


def test_fixture_interrupt_then_resume_round_trip(make_client):
    seen: list[httpx.Request] = []
    with make_client(_replay_handler(seen)) as client:
        content = RUN_1["input"]["messages"][0]["content"]
        first = list(client.run_agui("thread-1", content, run_id="run-1"))
        resume = [i.resolve({"action": "approve"}) for i in first[-1].interrupts]
        second = list(client.run_agui("thread-1", resume=resume, run_id="run-2"))
    _assert_replayed(seen, first, second)


async def test_async_fixture_interrupt_then_resume_round_trip(make_async_client):
    seen: list[httpx.Request] = []
    async with make_async_client(_replay_handler(seen)) as client:
        content = RUN_1["input"]["messages"][0]["content"]
        first = [e async for e in client.run_agui("thread-1", content, run_id="run-1")]
        resume = [i.resolve({"action": "approve"}) for i in first[-1].interrupts]
        second = [
            e async for e in client.run_agui("thread-1", resume=resume, run_id="run-2")
        ]
    _assert_replayed(seen, first, second)


async def test_async_refusal_raises_before_any_event(make_async_client):
    handler = _handler(
        _error(409, "no_pending_interrupt"),
        [],
        409,
        {"content-type": "application/json"},
    )
    async with make_async_client(handler, org_id="o") as client:
        with pytest.raises(ResumeConflictError):
            async for _ in client.run_agui(
                "t-1", resume=[ResumeEntry(interrupt_id="x")], org_id="acme"
            ):
                pass


# ── stream edges: named frames are skipped; a cut stream just ends ──────────


def _edge_body() -> bytes:
    named = b'event: token\ndata: {"delta": "native"}\n\n'
    return named + agui_body([_START], heartbeats=False)


def test_named_frames_are_skipped_and_a_cut_stream_ends(make_client):
    with make_client(_handler(_edge_body(), [])) as client:
        events = list(client.run_agui("t-1", "hi"))
    assert [e.type for e in events] == ["RUN_STARTED"]


async def test_async_named_frames_are_skipped_and_a_cut_stream_ends(
    make_async_client,
):
    async with make_async_client(_handler(_edge_body(), [])) as client:
        events = [e async for e in client.run_agui("t-1", "hi")]
    assert [e.type for e in events] == ["RUN_STARTED"]

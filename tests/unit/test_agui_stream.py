"""AG-UI over SSE — `send_message(protocol="ag-ui")` (CS2-02-02..04).

SPEC-CS2-AGU-001..007, against the engine/host golden streams. Sync and
async are exercised through the same cases.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from prismal_sdk._sse import iter_sse_events
from prismal_sdk.agui import (
    AgUiEvent,
    PrismalUsageEvent,
    RunFinished,
    TextMessageContent,
)
from prismal_sdk.exceptions import (
    BudgetExceededError,
    PrismalAPIError,
    ProtocolNotEnabledError,
)
from prismal_sdk.models import DoneEvent, Usage
from tests.conftest import sse_body, sse_frame
from tests.wire_v02 import AGUI_GOLDEN, agui_body

AGUI_HEADERS = {
    "content-type": "text/event-stream",
    "x-prismal-stream-protocol": "ag-ui",
}

_FINISHING = sorted(n for n, g in AGUI_GOLDEN.items() if g["end"]["kind"] == "finish")
_RUN_START = {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r-1"}
_RUN_END = {"type": "RUN_FINISHED", "threadId": "t-1", "runId": "r-1"}


def _agui_handler(
    body: bytes, seen: list[httpx.Request] | None = None, headers=AGUI_HEADERS
):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, content=body, headers=headers)

    return handler


def _collect_until_error(iterator) -> tuple[list[Any], Exception | None]:
    events: list[Any] = []
    try:
        for event in iterator:
            events.append(event)
    except Exception as exc:  # noqa: BLE001 — returned for assertions
        return events, exc
    return events, None


async def _acollect_until_error(iterator) -> tuple[list[Any], Exception | None]:
    events: list[Any] = []
    try:
        async for event in iterator:
            events.append(event)
    except Exception as exc:  # noqa: BLE001 — returned for assertions
        return events, exc
    return events, None


def _dumped(events: list[Any]) -> list[dict[str, Any]]:
    return [e.model_dump(by_alias=True, exclude_unset=True) for e in events]


# ── SSE parser: data-only frames (AGU-002) ─────────────────────────────────


def test_sse_parser_yields_data_only_frames_as_message_events():
    lines = ": heartbeat", "", 'data: {"type":"RAW"}', "", "event: done", "data: {}", ""
    assert list(iter_sse_events(lines)) == [
        ("message", '{"type":"RAW"}'),
        ("done", "{}"),
    ]


def test_native_stream_ignores_data_only_frames(make_client):
    body = sse_body(
        'data: {"not": "native"}\n\n',
        sse_frame("token", json.dumps({"delta": "hi"})),
        sse_frame("done", json.dumps({"thread_id": "t-1", "finish_reason": "stop"})),
    )
    handler = _agui_handler(body, headers={"content-type": "text/event-stream"})
    with make_client(handler) as client:
        events = list(client.send_message("t-1", "hello"))
    assert len(events) == 2 and isinstance(events[-1], DoneEvent)


def test_native_stream_ignores_non_json_data_only_and_unknown_frames(make_client):
    # v0.1 dropped data-only frames in the parser; now that the parser yields
    # them (for AG-UI), the native path must still never try to decode them.
    body = sse_body(
        "data: not json\n\n",
        sse_frame("future_event", "not json either"),
        sse_frame("done", json.dumps({"thread_id": "t-1", "finish_reason": "stop"})),
    )
    handler = _agui_handler(body, headers={"content-type": "text/event-stream"})
    with make_client(handler) as client:
        events = list(client.send_message("t-1", "hello"))
    assert len(events) == 1 and isinstance(events[0], DoneEvent)


# ── request shape (AGU-001, AGU-006) ───────────────────────────────────────


def test_agui_request_sets_the_profile_accept_header_and_same_body(make_client):
    seen: list[httpx.Request] = []
    agui = agui_body([_RUN_START, _RUN_END])
    native = sse_body(sse_frame("done", '{"thread_id":"t-1","finish_reason":"s"}'))

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "profile=ag-ui" in request.headers.get("accept", ""):
            return httpx.Response(200, content=agui, headers=AGUI_HEADERS)
        return httpx.Response(200, content=native)

    with make_client(handler) as client:
        kwargs: dict[str, Any] = {"metadata": {"k": 1}, "org_id": "acme"}
        list(client.send_message("t-1", "hello", protocol="ag-ui", **kwargs))
        list(client.send_message("t-1", "hello", **kwargs))
    agui_req, native_req = seen
    assert agui_req.url.path == native_req.url.path == "/threads/t-1/messages"
    assert agui_req.headers["accept"] == "text/event-stream; profile=ag-ui"
    assert agui_req.headers["x-org-id"] == "acme"
    assert "profile=ag-ui" not in native_req.headers.get("accept", "")
    assert json.loads(agui_req.content) == json.loads(native_req.content)


async def test_async_agui_request_sets_the_profile_accept_header(make_async_client):
    seen: list[httpx.Request] = []
    body = agui_body([_RUN_START, _RUN_END])
    async with make_async_client(_agui_handler(body, seen)) as client:
        _ = [e async for e in client.send_message("t-1", "hi", protocol="ag-ui")]
    assert seen[0].headers["accept"] == "text/event-stream; profile=ag-ui"


def test_unknown_protocol_raises_value_error_before_io(make_client):
    seen: list[httpx.Request] = []
    with make_client(_agui_handler(b"", seen)) as client:
        with pytest.raises(ValueError, match="protocol"):
            list(client.send_message("t-1", "hi", protocol="carrier-pigeon"))  # type: ignore[call-overload]
    assert seen == []


# ── golden streams (AGU-002/003/004, CS2-02-04) ────────────────────────────


@pytest.mark.parametrize("name", _FINISHING)
def test_golden_stream_yields_every_event_in_order(make_client, name):
    expected = AGUI_GOLDEN[name]["expected"]
    with make_client(_agui_handler(agui_body(expected))) as client:
        events = list(client.send_message("t-1", "hi", protocol="ag-ui"))
    assert _dumped(events) == expected
    assert isinstance(events[-1], RunFinished)


@pytest.mark.parametrize("name", _FINISHING)
async def test_async_golden_stream_yields_every_event_in_order(make_async_client, name):
    expected = AGUI_GOLDEN[name]["expected"]
    async with make_async_client(_agui_handler(agui_body(expected))) as client:
        events = [e async for e in client.send_message("t-1", "hi", protocol="ag-ui")]
    assert _dumped(events) == expected
    assert isinstance(events[-1], RunFinished)


def test_usage_event_arrives_typed_before_run_finished(make_client):
    golden = AGUI_GOLDEN["react_text"]
    with make_client(_agui_handler(agui_body(golden["expected"]))) as client:
        events = list(client.send_message("t-1", "hi", protocol="ag-ui"))
    usage_events = [e for e in events if isinstance(e, PrismalUsageEvent)]
    assert [e.usage for e in usage_events] == [
        Usage.model_validate(golden["summary_usage_wire"])
    ]
    assert events.index(usage_events[0]) == len(events) - 2


def test_run_finished_ends_iteration(make_client):
    late = {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "late"}
    body = agui_body([_RUN_START, _RUN_END, late])
    with make_client(_agui_handler(body)) as client:
        events = list(client.send_message("t-1", "hi", protocol="ag-ui"))
    assert isinstance(events[-1], RunFinished)
    assert not any(isinstance(e, TextMessageContent) for e in events)


def test_golden_run_error_raises_mapped_error_after_prior_events(make_client):
    golden = AGUI_GOLDEN["run_error"]
    expected = golden["expected"]
    with make_client(_agui_handler(agui_body(expected))) as client:
        events, exc = _collect_until_error(
            client.send_message("t-1", "hi", protocol="ag-ui")
        )
    assert _dumped(events) == expected[:-1]  # everything but RUN_ERROR
    assert isinstance(exc, BudgetExceededError)
    assert exc.status_code == 200
    assert exc.message == golden["end"]["message"]
    # ERR-002 on AG-UI: the partial usage is the run's last prismal.usage.
    assert exc.usage == Usage.model_validate(golden["summary_usage_wire"])


async def test_async_golden_run_error_raises_mapped_error(make_async_client):
    golden = AGUI_GOLDEN["run_error"]
    async with make_async_client(_agui_handler(agui_body(golden["expected"]))) as c:
        events, exc = await _acollect_until_error(
            c.send_message("t-1", "hi", protocol="ag-ui")
        )
    assert len(events) == len(golden["expected"]) - 1
    assert isinstance(exc, BudgetExceededError)
    assert exc.usage == Usage.model_validate(golden["summary_usage_wire"])


def test_run_error_without_a_prior_usage_event_has_no_usage(make_client):
    error = {"type": "RUN_ERROR", "code": "budget_exceeded", "message": "cap"}
    with make_client(_agui_handler(agui_body([_RUN_START, error]))) as client:
        with pytest.raises(BudgetExceededError) as info:
            list(client.send_message("t-1", "hi", protocol="ag-ui"))
    assert info.value.usage is None


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ({"type": "RUN_ERROR", "code": "mystery", "message": "m"}, "mystery"),
        ({"type": "RUN_ERROR", "message": "m"}, "internal_error"),
    ],
)
def test_run_error_with_unmapped_or_missing_code(make_client, error, code):
    with make_client(_agui_handler(agui_body([_RUN_START, error]))) as client:
        with pytest.raises(PrismalAPIError) as info:
            list(client.send_message("t-1", "hi", protocol="ag-ui"))
    assert type(info.value) is PrismalAPIError
    assert info.value.code == code


def test_unknown_event_types_are_yielded_as_base_events(make_client):
    future = {"type": "TELEPATHY_STARTED", "mindId": "x"}
    body = agui_body([_RUN_START, future, _RUN_END])
    with make_client(_agui_handler(body)) as client:
        events = list(client.send_message("t-1", "hi", protocol="ag-ui"))
    assert type(events[1]) is AgUiEvent
    assert events[1].model_dump(by_alias=True, exclude_unset=True) == future


def test_named_frames_on_an_agui_stream_are_ignored(make_client):
    body = agui_body([_RUN_START]) + sse_body(sse_frame("token", '{"delta":"x"}'))
    body += agui_body([_RUN_END])
    with make_client(_agui_handler(body)) as client:
        events = list(client.send_message("t-1", "hi", protocol="ag-ui"))
    assert [e.type for e in events] == ["RUN_STARTED", "RUN_FINISHED"]


# ── negotiation failures (AGU-005, AGU-007) ────────────────────────────────


def test_406_raises_protocol_not_enabled_before_any_event(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            406, json={"error": {"code": "protocol_not_enabled", "message": "off"}}
        )

    with make_client(handler) as client:
        events, exc = _collect_until_error(
            client.send_message("t-1", "hi", protocol="ag-ui")
        )
    assert events == []
    assert isinstance(exc, ProtocolNotEnabledError)
    assert exc.status_code == 406


async def test_async_406_raises_protocol_not_enabled(make_async_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            406, json={"error": {"code": "protocol_not_enabled", "message": "off"}}
        )

    async with make_async_client(handler) as client:
        with pytest.raises(ProtocolNotEnabledError):
            _ = [e async for e in client.send_message("t-1", "hi", protocol="ag-ui")]


def test_host_that_did_not_negotiate_agui_raises_instead_of_yielding_nothing(
    make_client,
):
    # A v0.1 host ignores the Accept profile and streams native frames. Without
    # the response header those would be silently dropped (AGU-007).
    native = sse_body(
        sse_frame("token", '{"delta":"hi"}'),
        sse_frame("done", '{"thread_id":"t-1","finish_reason":"stop"}'),
    )
    handler = _agui_handler(native, headers={"content-type": "text/event-stream"})
    with make_client(handler) as client:
        events, exc = _collect_until_error(
            client.send_message("t-1", "hi", protocol="ag-ui")
        )
    assert events == []
    assert isinstance(exc, ProtocolNotEnabledError)
    assert exc.code == "protocol_not_enabled"


async def test_async_host_that_did_not_negotiate_agui_raises(make_async_client):
    handler = _agui_handler(b"", headers={"content-type": "text/event-stream"})
    async with make_async_client(handler) as client:
        with pytest.raises(ProtocolNotEnabledError):
            _ = [e async for e in client.send_message("t-1", "hi", protocol="ag-ui")]

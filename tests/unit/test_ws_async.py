"""WebSocket client — async. Mirror of ``test_ws_sync.py`` (SPEC-CS2-NFR-002)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from prismal_sdk import AsyncPrismalClient
from prismal_sdk.agui import RunFinished
from prismal_sdk.exceptions import (
    BudgetExceededError,
    ForbiddenError,
    PrismalConnectionError,
    PrismalTimeoutError,
    PrismalWebSocketError,
    TurnCancelledError,
    TurnInProgressError,
    WebSocketAuthenticationError,
    WebSocketProtocolError,
    WebSocketUnavailableError,
)
from prismal_sdk.models import DoneEvent, TokenEvent, Usage
from tests.unit.test_ws_sync import (
    _agui_turn,
    _reject,
    cancellable_turns,
    native_turns,
)
from tests.wire_v02 import AGUI_GOLDEN, USAGE_EXAMPLE
from tests.ws_fake import fake_ws_server, send


def _client(base: str, **kwargs: Any) -> AsyncPrismalClient:
    kwargs.setdefault("timeout_s", 5.0)
    return AsyncPrismalClient(base, **kwargs)


async def _collect(iterator) -> list[Any]:
    return [event async for event in iterator]


async def test_handshake_and_native_turns():
    with fake_ws_server(native_turns) as (base, rec):
        async with _client(base, token="s3cr3t", org_id="home") as client:
            async with client.ws("t-1", org_id="acme") as session:
                first = await _collect(session.send_message("a"))
                second = await _collect(session.send_message("b", role="system"))
    assert rec.paths == ["/ws/threads/t-1"]
    assert rec.headers[0]["authorization"] == "Bearer s3cr3t"
    assert rec.headers[0]["x-org-id"] == "acme"
    assert first[0] == TokenEvent(delta="echo: a")
    assert isinstance(first[-1], DoneEvent)
    assert first[-1].usage == Usage.model_validate(USAGE_EXAMPLE)
    assert second[0] == TokenEvent(delta="echo: b")
    assert rec.frames[1]["role"] == "system"
    assert len(first) == 4  # heartbeat/pong never yielded


async def test_lazy_connect_and_idempotent_close():
    with fake_ws_server(native_turns) as (base, rec):
        async with _client(base) as client:
            session = client.ws("t-1")
            assert rec.connections == 0
            events = await _collect(session.send_message("hi"))
            await session.close()
            await session.close()
    assert isinstance(events[-1], DoneEvent)


async def test_missing_websockets_raises_unavailable(monkeypatch):
    import sys

    for name in [m for m in sys.modules if m.startswith("websockets")]:
        monkeypatch.setitem(sys.modules, name, None)
    async with AsyncPrismalClient("http://h") as client:
        with pytest.raises(WebSocketUnavailableError):
            client.ws("t-1")


async def test_rejected_handshake_maps_the_error_body():
    body = json.dumps({"error": {"code": "forbidden_tenant", "message": "no"}}).encode()
    reject = _reject(403, body, "application/json")
    with fake_ws_server(native_turns, process_request=reject) as (base, _):
        async with _client(base) as client:
            with pytest.raises(ForbiddenError):
                await client.ws("t-1").connect()


async def test_unreachable_host_is_a_connection_error():
    with fake_ws_server(native_turns) as (base, _):
        pass
    async with _client(base) as client:
        with pytest.raises(PrismalConnectionError):
            await client.ws("t-1").connect()


async def test_agui_turn_over_ws():
    golden = AGUI_GOLDEN["react_text"]
    with fake_ws_server(_agui_turn("react_text")) as (base, rec):
        async with _client(base) as client, client.ws("t-1") as session:
            events = await _collect(session.send_message("hi", protocol="ag-ui"))
    dumped = [e.model_dump(by_alias=True, exclude_unset=True) for e in events]
    assert dumped == golden["expected"]
    assert isinstance(events[-1], RunFinished)
    assert rec.frames[0]["protocol"] == "ag-ui"


async def test_agui_run_error_over_ws():
    with fake_ws_server(_agui_turn("run_error")) as (base, _):
        async with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(BudgetExceededError) as info:
                await _collect(session.send_message("hi", protocol="ag-ui"))
    assert info.value.usage is not None


async def test_cancel_ends_the_turn():
    with fake_ws_server(cancellable_turns) as (base, rec):
        async with _client(base) as client, client.ws("t-1") as session:
            seen: list[Any] = []
            with pytest.raises(TurnCancelledError):
                async for event in session.send_message("hi"):
                    seen.append(event)
                    if len(seen) == 1:
                        await session.cancel()
    assert [e.delta for e in seen] == ["start hi", "in flight"]
    assert [f["type"] for f in rec.frames] == ["message", "cancel"]


async def test_abandoned_turn_is_cancelled_and_drained():
    with fake_ws_server(cancellable_turns) as (base, rec):
        async with _client(base) as client, client.ws("t-1") as session:
            first = session.send_message("first")
            async for _ in first:
                break
            await first.aclose()
            second = session.send_message("second")
            assert (await second.__anext__()).delta == "start second"
            await second.aclose()
    assert [f["type"] for f in rec.frames] == ["message", "cancel", "message", "cancel"]


async def test_breaking_on_the_terminal_event_sends_no_cancel():
    with fake_ws_server(native_turns) as (base, rec):
        async with _client(base) as client, client.ws("t-1") as session:
            turn = session.send_message("hi")
            async for event in turn:
                if isinstance(event, DoneEvent):
                    break
            await turn.aclose()
            await _collect(session.send_message("again"))
    assert [f["type"] for f in rec.frames] == ["message", "message"]


@pytest.mark.parametrize(
    ("code", "klass"),
    [
        (1008, WebSocketAuthenticationError),
        (4409, TurnInProgressError),
        (4400, WebSocketProtocolError),
        (4999, PrismalWebSocketError),
    ],
)
async def test_close_codes(code, klass):
    def handler(conn, rec):
        rec.recv(conn)
        conn.close(code=code, reason="scripted")

    with fake_ws_server(handler) as (base, rec):
        async with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(PrismalWebSocketError) as info:
                await _collect(session.send_message("hi"))
    assert type(info.value) is klass
    assert info.value.close_code == code
    assert rec.connections == 1


async def test_malformed_server_frame_is_a_protocol_error():
    def handler(conn, rec):
        rec.recv(conn)
        conn.send("[1, 2]")

    with fake_ws_server(handler) as (base, _):
        async with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(WebSocketProtocolError):
                await _collect(session.send_message("hi"))


async def test_silent_server_hits_the_read_timeout():
    def handler(conn, rec):
        rec.recv(conn)
        send(conn, "heartbeat")
        conn.recv()

    with fake_ws_server(handler) as (base, _):
        async with _client(base, timeout_s=0.2) as client, client.ws("t-1") as session:
            with pytest.raises(PrismalTimeoutError):
                await _collect(session.send_message("hi"))


async def test_unknown_protocol_raises_before_sending():
    with fake_ws_server(native_turns) as (base, rec):
        async with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(ValueError, match="protocol"):
                await _collect(session.send_message("hi", protocol="x"))  # type: ignore[call-overload]
    assert rec.frames == []


async def test_handshake_timeout_is_a_timeout_error():
    from tests.unit.test_ws_sync import _silent_tcp_listener

    sock, base = _silent_tcp_listener()
    try:
        async with _client(base, timeout_s=0.2) as client:
            with pytest.raises(PrismalTimeoutError):
                await client.ws("t-1").connect()
    finally:
        sock.close()


async def test_cancel_without_a_connection_raises():
    async with AsyncPrismalClient("http://h") as client:
        with pytest.raises(PrismalWebSocketError, match="not connected"):
            await client.ws("t-1").cancel()


async def test_sending_on_a_connection_the_host_closed_maps_the_close_code():
    import asyncio
    import time

    from prismal_sdk.exceptions import WebSocketServerError
    from tests.unit.test_ws_sync import _closes_immediately

    with fake_ws_server(_closes_immediately) as (base, _):
        async with _client(base) as client, client.ws("t-1") as session:
            deadline = time.monotonic() + 5
            with pytest.raises(WebSocketServerError):
                while time.monotonic() < deadline:
                    await session.cancel()
                    await asyncio.sleep(0.01)

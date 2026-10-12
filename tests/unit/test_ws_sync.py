"""WebSocket client — sync (CS2-03-01..03, SPEC-CS2-WSK-001..004).

Runs against the in-process fake server in ``tests/ws_fake.py``. The async
session is covered by ``test_ws_async.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Any

import pytest
from websockets.sync.server import ServerConnection

from prismal_sdk import PrismalClient
from prismal_sdk._ws import ws_url
from prismal_sdk.agui import PrismalUsageEvent, RunFinished
from prismal_sdk.exceptions import (
    BudgetExceededError,
    ForbiddenError,
    MessageTooLargeError,
    PrismalAPIError,
    PrismalConnectionError,
    PrismalSDKError,
    PrismalTimeoutError,
    PrismalTransportError,
    PrismalWebSocketError,
    TurnCancelledError,
    TurnInProgressError,
    WebSocketAuthenticationError,
    WebSocketProtocolError,
    WebSocketServerError,
    WebSocketUnavailableError,
)
from prismal_sdk.models import DoneEvent, StateEvent, TokenEvent, ToolCallEvent, Usage
from tests.wire_v02 import AGUI_GOLDEN, USAGE_EXAMPLE
from tests.ws_fake import Recorder, fake_ws_server, send

DONE = {"thread_id": "t-1", "finish_reason": "stop", "usage": USAGE_EXAMPLE}


def _client(base: str, **kwargs: Any) -> PrismalClient:
    kwargs.setdefault("timeout_s", 5.0)
    return PrismalClient(base, **kwargs)


def native_turns(conn: ServerConnection, rec: Recorder) -> None:
    """Answer every `message` with a full native turn; heartbeats interleaved."""
    while True:
        frame = rec.recv(conn)
        if frame["type"] != "message":
            continue
        send(conn, "heartbeat")
        send(conn, "token", {"delta": f"echo: {frame['content']}"})
        send(conn, "tool_call", {"name": "fake_tool", "args": {"q": "x"}})
        send(conn, "state", {"data": {"node": "agent"}})
        send(conn, "pong")
        send(conn, "done", DONE)


# ── URL, availability, packaging (WSK-001, NFR-003) ────────────────────────


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("http://h:8000", "ws://h:8000/ws/threads/t-1"),
        ("https://h", "wss://h/ws/threads/t-1"),
        ("https://h/api/", "wss://h/api/ws/threads/t-1"),
    ],
)
def test_ws_url(base, expected):
    assert ws_url(base, "t-1") == expected


def test_missing_websockets_raises_unavailable_with_install_hint(monkeypatch):
    for name in [
        m for m in sys.modules if m == "websockets" or m.startswith("websockets.")
    ]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "websockets", None)
    with PrismalClient("http://h") as client:
        with pytest.raises(WebSocketUnavailableError) as info:
            client.ws("t-1")
    assert isinstance(info.value, ImportError)
    assert isinstance(info.value, PrismalSDKError)
    assert "prismal-sdk[ws]" in str(info.value)


def test_importing_the_sdk_does_not_import_websockets():
    code = "import sys, prismal_sdk; sys.exit('websockets' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# ── handshake (WSK-001) ────────────────────────────────────────────────────


def test_handshake_path_and_auth_headers():
    with fake_ws_server(native_turns) as (base, rec):
        with _client(base, token="s3cr3t", org_id="home") as client:
            with client.ws("t-1", org_id="acme") as session:
                list(session.send_message("hi"))
            with client.ws("t-2") as session:
                list(session.send_message("hi"))
    assert rec.paths == ["/ws/threads/t-1", "/ws/threads/t-2"]
    assert rec.headers[0]["authorization"] == "Bearer s3cr3t"
    assert rec.headers[0]["x-org-id"] == "acme"
    assert rec.headers[1]["x-org-id"] == "home"


def _reject(
    status: int, body: bytes, content_type: str, calls: list[int] | None = None
):
    """``process_request`` hook answering the upgrade with a plain HTTP error."""
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    def process_request(connection, request):
        if calls is not None:
            calls.append(1)
        headers = Headers(
            [("Content-Type", content_type), ("Content-Length", str(len(body)))]
        )
        return Response(status, "Rejected", headers, body)

    return process_request


def test_rejected_handshake_maps_the_error_body():
    body = json.dumps({"error": {"code": "forbidden_tenant", "message": "no"}}).encode()
    calls: list[int] = []
    reject = _reject(403, body, "application/json", calls)
    with fake_ws_server(native_turns, process_request=reject) as (base, _):
        with _client(base, token="s3cr3t", max_retries=5) as client:
            with pytest.raises(ForbiddenError) as info:
                client.ws("t-1").connect()
    assert info.value.status_code == 403
    assert "s3cr3t" not in str(info.value)
    assert calls == [1]  # one handshake, never retried (WSK-004)


def test_rejected_handshake_without_json_is_a_plain_api_error():
    reject = _reject(404, b"Not Found", "text/plain")
    with fake_ws_server(native_turns, process_request=reject) as (base, _):
        with _client(base) as client:
            with pytest.raises(PrismalAPIError) as info:
                client.ws("t-1").connect()
    assert type(info.value) is PrismalAPIError
    assert info.value.status_code == 404


def test_unreachable_host_is_a_connection_error_and_not_retried():
    with fake_ws_server(native_turns) as (base, _):
        pass  # server gone: the port now refuses connections
    with _client(base, max_retries=5) as client:
        with pytest.raises(PrismalConnectionError):
            client.ws("t-1").connect()


# ── native turns (WSK-002) ─────────────────────────────────────────────────


def test_native_turn_yields_v01_models_and_skips_heartbeat_pong():
    with fake_ws_server(native_turns) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            events = list(session.send_message("hi", metadata={"k": 1}))
    assert events == [
        TokenEvent(delta="echo: hi"),
        ToolCallEvent(name="fake_tool", args={"q": "x"}),
        StateEvent(data={"node": "agent"}),
        DoneEvent(
            thread_id="t-1",
            finish_reason="stop",
            usage=Usage.model_validate(USAGE_EXAMPLE),
        ),
    ]
    assert rec.frames == [
        {
            "type": "message",
            "content": "hi",
            "role": "user",
            "metadata": {"k": 1},
            "protocol": "prismal",
        }
    ]


def test_one_session_runs_several_turns():
    with fake_ws_server(native_turns) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            first = list(session.send_message("a"))
            second = list(session.send_message("b"))
    assert first[0] == TokenEvent(delta="echo: a")
    assert second[0] == TokenEvent(delta="echo: b")
    assert rec.connections == 1


def test_send_message_connects_lazily_without_a_with_block():
    with fake_ws_server(native_turns) as (base, rec):
        with _client(base) as client:
            session = client.ws("t-1")
            assert rec.connections == 0
            assert list(session.send_message("hi"))[-1].finish_reason == "stop"
            session.close()
            session.close()  # idempotent


def test_native_error_frame_raises_mapped_error_with_usage():
    def handler(conn, rec):
        rec.recv(conn)
        send(conn, "token", {"delta": "par"})
        send(
            conn,
            "error",
            {"code": "budget_exceeded", "message": "cap", "usage": USAGE_EXAMPLE},
        )

    with fake_ws_server(handler) as (base, _):
        with _client(base) as client, client.ws("t-1") as session:
            events: list[Any] = []
            with pytest.raises(BudgetExceededError) as info:
                for event in session.send_message("hi"):
                    events.append(event)
    assert events == [TokenEvent(delta="par")]
    assert info.value.usage == Usage.model_validate(USAGE_EXAMPLE)


def test_unknown_protocol_raises_before_sending():
    with fake_ws_server(native_turns) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(ValueError, match="protocol"):
                list(session.send_message("hi", protocol="smoke"))  # type: ignore[call-overload]
    assert rec.frames == []


def test_malformed_server_frame_is_a_protocol_error():
    def handler(conn, rec):
        rec.recv(conn)
        conn.send("not json")

    with fake_ws_server(handler) as (base, _):
        with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(WebSocketProtocolError) as info:
                list(session.send_message("hi"))
    assert info.value.close_code is None


# ── AG-UI over WS (WSK-002) ────────────────────────────────────────────────


def _agui_turn(golden: str):
    def handler(conn, rec):
        while True:
            frame = rec.recv(conn)
            if frame["type"] == "message":
                for event in AGUI_GOLDEN[golden]["expected"]:
                    send(conn, "heartbeat")
                    send(conn, "agui", event)

    return handler


def test_agui_turn_over_ws():
    golden = AGUI_GOLDEN["react_text"]
    with fake_ws_server(_agui_turn("react_text")) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            events = list(session.send_message("hi", protocol="ag-ui"))
    dumped = [e.model_dump(by_alias=True, exclude_unset=True) for e in events]
    assert dumped == golden["expected"]
    assert isinstance(events[-1], RunFinished)
    assert any(isinstance(e, PrismalUsageEvent) for e in events)
    assert rec.frames[0]["protocol"] == "ag-ui"


def test_agui_run_error_over_ws_raises_with_last_usage():
    golden = AGUI_GOLDEN["run_error"]
    with fake_ws_server(_agui_turn("run_error")) as (base, _):
        with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(BudgetExceededError) as info:
                list(session.send_message("hi", protocol="ag-ui"))
    assert info.value.usage == Usage.model_validate(golden["summary_usage_wire"])


def test_native_error_frame_raises_during_an_agui_turn():
    # The host reports `cancel` as a native `error` frame in both protocols.
    def handler(conn, rec):
        rec.recv(conn)
        send(conn, "agui", {"type": "RUN_STARTED", "threadId": "t-1", "runId": "r"})
        send(conn, "error", {"code": "cancelled", "message": "cancelled"})

    with fake_ws_server(handler) as (base, _):
        with _client(base) as client, client.ws("t-1") as session:
            with pytest.raises(TurnCancelledError):
                list(session.send_message("hi", protocol="ag-ui"))


# ── cancel & abandoned turns ───────────────────────────────────────────────


def cancellable_turns(conn: ServerConnection, rec: Recorder) -> None:
    """Stream tokens until the client cancels; then `error cancelled`."""
    while True:
        frame = rec.recv(conn)
        if frame["type"] != "message":
            continue
        send(conn, "token", {"delta": f"start {frame['content']}"})
        while rec.recv(conn)["type"] != "cancel":
            pass
        send(conn, "token", {"delta": "in flight"})
        send(conn, "error", {"code": "cancelled", "message": "cancelled by client"})


def test_cancel_ends_the_turn_with_turn_cancelled_error():
    with fake_ws_server(cancellable_turns) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            seen: list[Any] = []
            with pytest.raises(TurnCancelledError):
                for event in session.send_message("hi"):
                    seen.append(event)
                    if len(seen) == 1:
                        session.cancel()
    assert [e.delta for e in seen] == ["start hi", "in flight"]
    assert [f["type"] for f in rec.frames] == ["message", "cancel"]


def test_cancel_from_another_thread():
    with fake_ws_server(cancellable_turns) as (base, _):
        with _client(base) as client, client.ws("t-1") as session:
            turn = session.send_message("hi")
            assert next(turn).delta == "start hi"
            threading.Thread(target=session.cancel).start()
            with pytest.raises(TurnCancelledError):
                list(turn)


def test_abandoning_a_turn_cancels_it_and_the_next_turn_is_clean():
    with fake_ws_server(cancellable_turns) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            for _ in session.send_message("first"):
                break  # abandon mid-turn
            second = session.send_message("second")
            # Leftovers of turn 1 ("in flight", error cancelled) are drained,
            # never yielded as turn 2's events.
            assert next(second).delta == "start second"
            second.close()
    assert [f["type"] for f in rec.frames] == ["message", "cancel", "message", "cancel"]


def cancellable_agui_turns(conn: ServerConnection, rec: Recorder) -> None:
    """AG-UI turns that end in RUN_ERROR once the client cancels."""
    while True:
        frame = rec.recv(conn)
        if frame["type"] != "message":
            continue
        send(conn, "agui", {"type": "RUN_STARTED", "runId": frame["content"]})
        while rec.recv(conn)["type"] != "cancel":
            pass
        send(conn, "agui", {"type": "TEXT_MESSAGE_END", "messageId": "late"})
        send(conn, "agui", {"type": "RUN_ERROR", "code": "cancelled", "message": "x"})


def test_abandoned_agui_turn_is_drained_up_to_run_error():
    with fake_ws_server(cancellable_agui_turns) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            for _ in session.send_message("first", protocol="ag-ui"):
                break
            second = session.send_message("second", protocol="ag-ui")
            assert next(second).model_dump(by_alias=True)["runId"] == "second"
            second.close()
    assert [f["type"] for f in rec.frames] == ["message", "cancel", "message", "cancel"]


def test_breaking_on_the_terminal_event_sends_no_cancel():
    with fake_ws_server(native_turns) as (base, rec):
        with _client(base) as client, client.ws("t-1") as session:
            for event in session.send_message("hi"):
                if isinstance(event, DoneEvent):
                    break
            list(session.send_message("again"))
    assert [f["type"] for f in rec.frames] == ["message", "message"]


# ── close codes (WSK-003) and no retry (WSK-004) ───────────────────────────


@pytest.mark.parametrize(
    ("code", "klass"),
    [
        (1008, WebSocketAuthenticationError),
        (4409, TurnInProgressError),
        (4400, WebSocketProtocolError),
        (1009, MessageTooLargeError),
        (1011, WebSocketServerError),
        (4999, PrismalWebSocketError),
        (1000, PrismalWebSocketError),
    ],
)
def test_close_codes_map_to_websocket_errors(code, klass):
    def handler(conn, rec):
        rec.recv(conn)
        send(conn, "token", {"delta": "x"})
        conn.close(code=code, reason="scripted")

    with fake_ws_server(handler) as (base, rec):
        with _client(base, max_retries=5) as client, client.ws("t-1") as session:
            with pytest.raises(PrismalWebSocketError) as info:
                list(session.send_message("hi"))
    assert type(info.value) is klass
    assert isinstance(info.value, PrismalTransportError)
    assert (info.value.close_code, info.value.reason) == (code, "scripted")
    assert rec.connections == 1  # never reconnected (WSK-004)
    assert len(rec.frames) == 1  # never re-sent


def test_silent_server_hits_the_read_timeout():
    def handler(conn, rec):
        rec.recv(conn)
        conn.recv()  # never answers

    with fake_ws_server(handler) as (base, _):
        with _client(base, timeout_s=0.2) as client, client.ws("t-1") as session:
            with pytest.raises(PrismalTimeoutError):
                list(session.send_message("hi"))


def test_ws_is_on_both_clients_with_the_same_parameters():
    import inspect

    from prismal_sdk import AsyncPrismalClient
    from prismal_sdk._ws import AsyncWsSession, WsSession

    assert list(inspect.signature(PrismalClient.ws).parameters) == list(
        inspect.signature(AsyncPrismalClient.ws).parameters
    )
    public = {n for n in dir(WsSession) if not n.startswith("_")}
    assert public == {n for n in dir(AsyncWsSession) if not n.startswith("_")}
    assert public == {"connect", "send_message", "cancel", "close"}


# ── connection-state edges ─────────────────────────────────────────────────


def _silent_tcp_listener():
    """A TCP port that accepts but never answers the HTTP upgrade."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, f"http://127.0.0.1:{sock.getsockname()[1]}"


def test_handshake_timeout_is_a_timeout_error():
    sock, base = _silent_tcp_listener()
    try:
        with _client(base, timeout_s=0.2) as client:
            with pytest.raises(PrismalTimeoutError):
                client.ws("t-1").connect()
    finally:
        sock.close()


def test_cancel_without_a_connection_raises():
    with PrismalClient("http://h") as client:
        with pytest.raises(PrismalWebSocketError, match="not connected"):
            client.ws("t-1").cancel()


def _closes_immediately(conn, rec):
    conn.close(code=1011, reason="boom")


def test_sending_on_a_connection_the_host_closed_maps_the_close_code():
    import time

    with fake_ws_server(_closes_immediately) as (base, _):
        with _client(base) as client, client.ws("t-1") as session:
            deadline = time.monotonic() + 5
            with pytest.raises(WebSocketServerError) as info:
                while time.monotonic() < deadline:  # until the close lands
                    session.cancel()
                    time.sleep(0.01)
    assert info.value.close_code == 1011

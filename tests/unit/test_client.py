"""Sync client tests (CSB-01/02/03) — fully offline (SPEC-CSB-NFR-003)."""

from __future__ import annotations

import json

import httpx
import pytest

from prismal_sdk.exceptions import (
    A2ANotEnabledError,
    PermissionDeniedError,
    RuntimeCompositionError,
)
from prismal_sdk.models import DoneEvent, ThreadCreated, TokenEvent, ToolCallEvent
from tests.conftest import sse_body, sse_frame


def test_healthz_ok(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(200, json={"status": "ok"})

    with make_client(handler) as client:
        assert client.healthz().status == "ok"


def test_readyz_not_ready_maps_reason(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503, json={"status": "not_ready", "reason": "runtime_composition_error"}
        )

    with make_client(handler) as client:
        with pytest.raises(RuntimeCompositionError) as exc_info:
            client.readyz()
        assert exc_info.value.status_code == 503
        assert exc_info.value.code == "runtime_composition_error"


def test_create_thread(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/threads"
        return httpx.Response(200, json={"thread_id": "abc123"})

    with make_client(handler) as client:
        result = client.create_thread()
        assert result == ThreadCreated(thread_id="abc123")


def test_send_message_streams_typed_events(make_client):
    body = sse_body(
        sse_frame("token", json.dumps({"delta": "Hola"})),
        sse_frame("tool_call", json.dumps({"name": "web_search", "args": {"q": "x"}})),
        sse_frame("done", json.dumps({"thread_id": "t-1", "finish_reason": "stop"})),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/threads/t-1/messages"
        payload = json.loads(request.content)
        assert payload == {"content": "hi", "role": "user", "metadata": {}}
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    with make_client(handler) as client:
        events = list(client.send_message("t-1", "hi"))

    assert events == [
        TokenEvent(delta="Hola"),
        ToolCallEvent(name="web_search", args={"q": "x"}),
        DoneEvent(thread_id="t-1", finish_reason="stop"),
    ]


def test_send_message_heartbeat_is_swallowed(make_client):
    body = sse_body(
        ": heartbeat\n\n",
        sse_frame("token", json.dumps({"delta": "hi"})),
        sse_frame("done", json.dumps({"thread_id": "t-1", "finish_reason": "stop"})),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    with make_client(handler) as client:
        events = list(client.send_message("t-1", "hi"))

    assert events == [
        TokenEvent(delta="hi"),
        DoneEvent(thread_id="t-1", finish_reason="stop"),
    ]


def test_send_message_terminal_error_frame_raises(make_client):
    error_payload = {"code": "permission_denied", "message": "nope"}
    body = sse_body(
        sse_frame("token", json.dumps({"delta": "partial"})),
        sse_frame("error", json.dumps(error_payload)),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    with make_client(handler) as client:
        seen = []
        with pytest.raises(PermissionDeniedError) as exc_info:
            for event in client.send_message("t-1", "hi"):
                seen.append(event)
        assert seen == [TokenEvent(delta="partial")]
        assert exc_info.value.code == "permission_denied"


def test_agent_card_not_enabled_maps_404(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "A2A is not enabled"})

    with make_client(handler) as client:
        with pytest.raises(A2ANotEnabledError) as exc_info:
            client.agent_card()
        assert exc_info.value.status_code == 404
        assert "not enabled" in exc_info.value.message


def test_agent_card_parses_camel_case(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"name": "prismal", "protocolVersion": "0.3.0", "extra": "field"}
        )

    with make_client(handler) as client:
        card = client.agent_card()
        assert card.name == "prismal"
        assert card.protocol_version == "0.3.0"


def test_auth_headers_sent(make_client):
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"status": "ok"})

    with make_client(handler, token="s3cr3t", org_id="acme") as client:
        client.healthz()

    assert seen_headers["authorization"] == "Bearer s3cr3t"
    assert seen_headers["x-org-id"] == "acme"


def test_no_token_no_authorization_header(make_client):
    seen_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"status": "ok"})

    with make_client(handler) as client:
        client.healthz()

    assert "authorization" not in seen_headers

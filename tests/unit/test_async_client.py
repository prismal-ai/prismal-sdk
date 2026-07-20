"""Async client tests — mirrors test_client.py (SPEC-CSB-NFR-001 parity)."""

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


async def test_healthz_ok(make_async_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    async with make_async_client(handler) as client:
        assert (await client.healthz()).status == "ok"


async def test_readyz_not_ready_maps_reason(make_async_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503, json={"status": "not_ready", "reason": "runtime_composition_error"}
        )

    async with make_async_client(handler) as client:
        with pytest.raises(RuntimeCompositionError):
            await client.readyz()


async def test_create_thread(make_async_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"thread_id": "abc123"})

    async with make_async_client(handler) as client:
        result = await client.create_thread()
        assert result == ThreadCreated(thread_id="abc123")


async def test_send_message_streams_typed_events(make_async_client):
    body = sse_body(
        sse_frame("token", json.dumps({"delta": "Hola"})),
        sse_frame("tool_call", json.dumps({"name": "web_search", "args": {"q": "x"}})),
        sse_frame("done", json.dumps({"thread_id": "t-1", "finish_reason": "stop"})),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    async with make_async_client(handler) as client:
        events = [event async for event in client.send_message("t-1", "hi")]

    assert events == [
        TokenEvent(delta="Hola"),
        ToolCallEvent(name="web_search", args={"q": "x"}),
        DoneEvent(thread_id="t-1", finish_reason="stop"),
    ]


async def test_send_message_terminal_error_frame_raises(make_async_client):
    error_payload = {"code": "permission_denied", "message": "nope"}
    body = sse_body(
        sse_frame("token", json.dumps({"delta": "partial"})),
        sse_frame("error", json.dumps(error_payload)),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    async with make_async_client(handler) as client:
        seen = []
        with pytest.raises(PermissionDeniedError):
            async for event in client.send_message("t-1", "hi"):
                seen.append(event)
        assert seen == [TokenEvent(delta="partial")]


async def test_agent_card_not_enabled_maps_404(make_async_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "A2A is not enabled"})

    async with make_async_client(handler) as client:
        with pytest.raises(A2ANotEnabledError):
            await client.agent_card()


async def test_a2a_send_round_trip(make_async_client):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["method"] == "message/send"
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {"ok": True}}
        )

    async with make_async_client(handler) as client:
        result = await client.a2a.message_send({"foo": "bar"})
        assert result == {"ok": True}

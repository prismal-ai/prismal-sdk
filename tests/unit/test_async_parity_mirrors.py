"""Async mirrors of sync-only tests (SPEC-CSB-NFR-001).

The parity test proves both clients expose the same *signatures*; it cannot
prove they *behave* the same. These are the async counterparts of assertions
that previously existed only for `PrismalClient`, so a behavioural drift
between the two halves fails a test instead of shipping.
"""

from __future__ import annotations

import httpx
import pytest

from prismal_sdk.a2a import MESSAGE_STREAM
from prismal_sdk.async_client import AsyncPrismalClient
from prismal_sdk.config import ClientConfig
from prismal_sdk.exceptions import (
    A2AJsonRpcError,
    A2ANotEnabledError,
    PrismalAPIError,
)
from prismal_sdk.models import DoneEvent, TokenEvent


def _static(response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return handler


async def test_from_config_sends_the_token_as_bearer():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"status": "ok"})

    config = ClientConfig(base_url="http://testserver", token="hunter2", org_id="acme")
    client = AsyncPrismalClient.from_config(config)
    client._client = httpx.AsyncClient(
        base_url="http://testserver", transport=httpx.MockTransport(handler)
    )
    async with client:
        await client.healthz()

    assert seen["authorization"] == "Bearer hunter2"
    assert seen["x-org-id"] == "acme"


async def test_readyz_ok(make_async_client):
    async with make_async_client(
        _static(httpx.Response(200, json={"status": "ready"}))
    ) as client:
        assert (await client.readyz()).status == "ready"


async def test_heartbeat_is_swallowed(make_async_client):
    body = (
        b": heartbeat\n\n"
        b'event: token\ndata: {"delta": "hi"}\n\n'
        b": heartbeat\n\n"
        b'event: done\ndata: {"thread_id": "t1", "finish_reason": "stop"}\n\n'
    )

    async def abody():
        yield body

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=abody())

    async with make_async_client(handler) as client:
        events = [e async for e in client.send_message("t1", "hola")]

    assert isinstance(events[0], TokenEvent)
    assert isinstance(events[-1], DoneEvent)
    assert len(events) == 2


async def test_send_message_non_2xx_raises_before_streaming(make_async_client):
    response = httpx.Response(
        400, json={"error": {"code": "invalid_request", "message": "bad"}}
    )
    async with make_async_client(_static(response)) as client:
        with pytest.raises(PrismalAPIError):
            [e async for e in client.send_message("t1", "hola")]


async def test_agent_card_parses_camel_case(make_async_client):
    card = {
        "name": "prismal",
        "protocolVersion": "0.3.0",
        "somethingBrandNew": {"the SDK": "has never seen"},
    }
    async with make_async_client(_static(httpx.Response(200, json=card))) as client:
        parsed = await client.agent_card()
    assert parsed.name == "prismal"


async def test_a2a_send_raises_on_error_member(make_async_client):
    response = httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"code": -32601, "message": "Method not found"},
        },
    )
    async with make_async_client(_static(response)) as client:
        with pytest.raises(A2AJsonRpcError) as excinfo:
            await client.a2a.send("nope/nope", {})
    assert excinfo.value.code == -32601


async def test_a2a_stream_404_raises_not_enabled(make_async_client):
    response = httpx.Response(404, json={"detail": "A2A is not enabled"})
    async with make_async_client(_static(response)) as client:
        with pytest.raises(A2ANotEnabledError):
            [f async for f in client.a2a.stream(MESSAGE_STREAM, {})]


async def test_a2a_stream_non_2xx_raises(make_async_client):
    response = httpx.Response(
        500, json={"error": {"code": "internal_error", "message": "boom"}}
    )
    async with make_async_client(_static(response)) as client:
        with pytest.raises(PrismalAPIError):
            [f async for f in client.a2a.stream(MESSAGE_STREAM, {})]


async def test_agent_card_404_raises_not_enabled(make_async_client):
    response = httpx.Response(404, json={"detail": "A2A is not enabled"})
    async with make_async_client(_static(response)) as client:
        with pytest.raises(A2ANotEnabledError):
            await client.agent_card()

"""Lifecycle, thread-id ownership and stream teardown.

CSB-01-04 (SPEC-CSB-TRN-003), CSB-02-03 (SPEC-CSB-THR-002) and CSB-02-05
(SPEC-CSB-CHT-006) — three tasks TASKS.md marked DONE without a test.
"""

from __future__ import annotations

import httpx
import pytest

from prismal_sdk.models import TokenEvent

_DONE = b'event: done\ndata: {"thread_id": "t1", "finish_reason": "stop"}\n\n'


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"status": "ok"})


# --- SPEC-CSB-TRN-003: context manager & explicit close ---------------------


def test_context_manager_closes_transport(make_client):
    with make_client(_ok) as client:
        client.healthz()
        assert client._client.is_closed is False
    assert client._client.is_closed is True


def test_explicit_close(make_client):
    client = make_client(_ok)
    client.healthz()
    client.close()
    assert client._client.is_closed is True


def test_context_manager_closes_on_exception(make_client):
    class Boom(Exception):
        pass

    client = make_client(_ok)
    with pytest.raises(Boom), client:
        raise Boom
    assert client._client.is_closed is True


def test_context_manager_yields_the_client(make_client):
    client = make_client(_ok)
    with client as entered:
        assert entered is client


async def test_async_context_manager_closes_transport(make_async_client):
    async with make_async_client(_ok) as client:
        await client.healthz()
        assert client._client.is_closed is False
    assert client._client.is_closed is True


async def test_async_explicit_aclose(make_async_client):
    client = make_async_client(_ok)
    await client.healthz()
    await client.aclose()
    assert client._client.is_closed is True


# --- SPEC-CSB-THR-002: the caller may choose the thread id ------------------


def test_send_message_accepts_a_caller_chosen_thread_id(make_client):
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, content=_DONE)

    with make_client(handler) as client:
        list(client.send_message("my-own-thread-id", "hola"))

    # No POST /threads round trip was required to start the turn.
    assert paths == ["/threads/my-own-thread-id/messages"]


def test_content_is_passed_through_unmodified(make_client):
    # SPEC-CSB-CHT-007: the SDK must not inspect, template or mutate content.
    raw = '  {"not": "json"} <script>\n\ttrailing  '
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(200, content=_DONE)

    with make_client(handler) as client:
        list(client.send_message("t1", raw, role="system", metadata={"k": 1}))

    import json

    sent = json.loads(bodies[0])
    assert sent["content"] == raw
    assert sent["role"] == "system"
    assert sent["metadata"] == {"k": 1}


# --- SPEC-CSB-CHT-006: breaking out early closes the response ---------------


def _endless_sse():
    """A stream far longer than the caller intends to consume."""
    for i in range(1000):
        yield f'event: token\ndata: {{"delta": "{i}"}}\n\n'.encode()


def test_early_break_closes_the_response(make_client):
    """A caller that stops consuming must release the connection promptly.

    The server relies on that disconnect to cancel its own ``astream`` task
    (SPEC-RHB-CHT-004), so a leaked response leaks server-side work too.

    ``response.is_closed`` is the probe that matters: it is what releases the
    connection back to the pool. (The underlying body generator's ``finally``
    is *not* a valid probe — httpx's ``IteratorByteStream`` does not propagate
    close to it, so it stays unrun even on a correct teardown.)
    """
    captured: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, content=_endless_sse())
        captured.append(response)
        return response

    with make_client(handler) as client:
        stream = client.send_message("t1", "hola")
        first = next(stream)
        assert isinstance(first, TokenEvent)
        assert captured[0].is_closed is False, "still streaming"
        # The documented deterministic teardown for an early break.
        stream.close()
        assert captured[0].is_closed is True


async def test_async_early_break_closes_the_response(make_async_client):
    captured: list[httpx.Response] = []

    async def _aendless_sse():
        for chunk in _endless_sse():
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        # An AsyncClient requires an async byte stream for the body.
        response = httpx.Response(200, content=_aendless_sse())
        captured.append(response)
        return response

    async with make_async_client(handler) as client:
        stream = client.send_message("t1", "hola")
        first = await stream.__anext__()
        assert isinstance(first, TokenEvent)
        assert captured[0].is_closed is False, "still streaming"
        await stream.aclose()
        assert captured[0].is_closed is True

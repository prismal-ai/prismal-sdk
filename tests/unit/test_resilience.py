"""Retry-policy tests (SPEC-CSB-RSL-001..004).

`POST /threads` is safe to re-mint and MUST be retried alongside `GET`;
`POST /threads/{id}/messages` MUST NOT be, because re-sending a chat turn is
not idempotent.
"""

from __future__ import annotations

import httpx
import pytest

from prismal_sdk._transport import is_retryable
from prismal_sdk.exceptions import PrismalTimeoutError


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/healthz", True),
        ("GET", "/.well-known/agent-card.json", True),
        # Minting a thread id again is harmless (SPEC-CSB-RSL-001).
        ("POST", "/threads", True),
        # Re-sending a chat turn is not idempotent (SPEC-CSB-RSL-002).
        ("POST", "/threads/t1/messages", False),
        ("POST", "/a2a", False),
    ],
)
def test_is_retryable_respects_path_idempotency(method, path, expected):
    exc = httpx.ConnectTimeout("timed out")
    assert is_retryable(method, path, exc) is expected


def test_create_thread_retries_transient_failure(make_client):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("boom", request=request)
        return httpx.Response(200, json={"thread_id": "t-42"})

    with make_client(handler, max_retries=2) as client:
        assert client.create_thread().thread_id == "t-42"
    assert attempts == 2


def test_send_message_never_retries(make_client):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("boom", request=request)

    with make_client(handler, max_retries=3) as client:
        with pytest.raises(PrismalTimeoutError):
            list(client.send_message("t-1", "hola"))
    assert attempts == 1


def test_max_retries_zero_disables_retry(make_client):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("boom", request=request)

    with make_client(handler, max_retries=0) as client:
        with pytest.raises(PrismalTimeoutError):
            client.healthz()
    assert attempts == 1


async def test_async_create_thread_retries_transient_failure(make_async_client):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("boom", request=request)
        return httpx.Response(200, json={"thread_id": "t-42"})

    async with make_async_client(handler, max_retries=2) as client:
        thread = await client.create_thread()
    assert thread.thread_id == "t-42"
    assert attempts == 2


async def test_async_send_message_never_retries(make_async_client):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("boom", request=request)

    async with make_async_client(handler, max_retries=3) as client:
        with pytest.raises(PrismalTimeoutError):
            [event async for event in client.send_message("t-1", "hola")]
    assert attempts == 1

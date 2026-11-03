"""``thread_id`` is one path segment, never path or query syntax.

A caller-supplied ``thread_id`` is interpolated into ``/threads/{id}/messages``
and ``/ws/threads/{id}``. Unencoded, ``?``/``#``/``/``/``..`` would retarget the
request — bearer token included — at another route. It is percent-encoded as
a single segment; ``""``, ``.`` and ``..`` (which no encoding can neutralise)
raise ``ValueError`` before any I/O.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from prismal_sdk import AsyncPrismalClient, PrismalClient
from prismal_sdk._ws import ws_url
from tests.conftest import sse_body, sse_frame

DONE = sse_frame("done", '{"thread_id":"t","finish_reason":"stop"}')

HOSTILE = [
    ("a/b", "/threads/a%2Fb/messages"),
    ("x?admin=1", "/threads/x%3Fadmin%3D1/messages"),
    ("x#frag", "/threads/x%23frag/messages"),
    ("../v1/admin/tenants", "/threads/..%2Fv1%2Fadmin%2Ftenants/messages"),
    ("a b", "/threads/a%20b/messages"),
]


def _recorder(seen: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, content=sse_body(DONE), headers={"content-type": "text/event-stream"}
        )

    return handler


@pytest.mark.parametrize(("thread_id", "raw_path"), HOSTILE)
def test_sync_send_message_encodes_thread_id(
    make_client: Callable[..., PrismalClient], thread_id: str, raw_path: str
) -> None:
    seen: list[httpx.Request] = []
    with make_client(_recorder(seen)) as client:
        list(client.send_message(thread_id, "hi"))
    assert seen[0].url.raw_path.decode() == raw_path
    assert seen[0].url.query == b""


@pytest.mark.parametrize(("thread_id", "raw_path"), HOSTILE)
async def test_async_send_message_encodes_thread_id(
    make_async_client: Callable[..., AsyncPrismalClient], thread_id: str, raw_path: str
) -> None:
    seen: list[httpx.Request] = []
    async with make_async_client(_recorder(seen)) as client:
        _ = [e async for e in client.send_message(thread_id, "hi")]
    assert seen[0].url.raw_path.decode() == raw_path
    assert seen[0].url.query == b""


def test_plain_thread_ids_are_unchanged(
    make_client: Callable[..., PrismalClient],
) -> None:
    seen: list[httpx.Request] = []
    with make_client(_recorder(seen)) as client:
        list(client.send_message("t-1_A.b~9", "hi"))
    assert seen[0].url.raw_path.decode() == "/threads/t-1_A.b~9/messages"


@pytest.mark.parametrize("thread_id", ["", ".", ".."])
def test_sync_send_message_rejects_dot_segments(
    make_client: Callable[..., PrismalClient], thread_id: str
) -> None:
    seen: list[httpx.Request] = []
    with make_client(_recorder(seen)) as client, pytest.raises(ValueError):
        list(client.send_message(thread_id, "hi"))
    assert seen == []


@pytest.mark.parametrize("thread_id", ["", ".", ".."])
async def test_async_send_message_rejects_dot_segments(
    make_async_client: Callable[..., AsyncPrismalClient], thread_id: str
) -> None:
    seen: list[httpx.Request] = []
    async with make_async_client(_recorder(seen)) as client:
        with pytest.raises(ValueError):
            _ = [e async for e in client.send_message(thread_id, "hi")]
    assert seen == []


@pytest.mark.parametrize(
    ("thread_id", "expected"),
    [
        ("t-1", "ws://h/p/ws/threads/t-1"),
        ("a/b", "ws://h/p/ws/threads/a%2Fb"),
        ("x?y=1#z", "ws://h/p/ws/threads/x%3Fy%3D1%23z"),
        ("../admin", "ws://h/p/ws/threads/..%2Fadmin"),
    ],
)
def test_ws_url_encodes_thread_id(thread_id: str, expected: str) -> None:
    assert ws_url("http://h/p/", thread_id) == expected


@pytest.mark.parametrize("thread_id", ["", ".", ".."])
def test_ws_url_rejects_dot_segments(thread_id: str) -> None:
    with pytest.raises(ValueError):
        ws_url("http://h", thread_id)

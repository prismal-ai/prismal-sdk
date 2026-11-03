"""`DoneEvent.usage` on native streams (CS2-01-01, SPEC-CS2-USG-002)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from prismal_sdk.models import DoneEvent, TokenEvent, Usage
from tests.conftest import sse_body, sse_frame
from tests.wire_v02 import USAGE_EXAMPLE

_ABSENT = object()


def _stream_handler(done_usage: Any):
    done: dict[str, Any] = {"thread_id": "t-1", "finish_reason": "stop"}
    if done_usage is not _ABSENT:
        done["usage"] = done_usage
    body = sse_body(
        sse_frame("token", json.dumps({"delta": "hi"})),
        sse_frame("done", json.dumps(done)),
        # Anything after `done` must never be read (DoneEvent ends iteration).
        sse_frame("token", json.dumps({"delta": "late"})),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    return handler


_CASES = [
    pytest.param(USAGE_EXAMPLE, Usage.model_validate(USAGE_EXAMPLE), id="usage"),
    pytest.param(None, None, id="null"),
    pytest.param(_ABSENT, None, id="v0.1-host-omits-usage"),
]


@pytest.mark.parametrize(("wire", "expected"), _CASES)
def test_done_carries_usage_and_is_last(make_client, wire, expected):
    with make_client(_stream_handler(wire)) as client:
        events = list(client.send_message("t-1", "hello"))
    assert events[0] == TokenEvent(delta="hi")
    assert isinstance(events[-1], DoneEvent)
    assert len(events) == 2
    assert events[-1].usage == expected


@pytest.mark.parametrize(("wire", "expected"), _CASES)
async def test_async_done_carries_usage_and_is_last(make_async_client, wire, expected):
    async with make_async_client(_stream_handler(wire)) as client:
        events = [e async for e in client.send_message("t-1", "hello")]
    assert isinstance(events[-1], DoneEvent)
    assert len(events) == 2
    assert events[-1].usage == expected

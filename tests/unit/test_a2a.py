"""A2A client tests (CSB-03-02/03 — SPEC-CSB-A2A-002/003/004/005).

Closes the coverage gap for the JSON-RPC streaming route and the typed method
wrappers, which TASKS.md marked DONE with only `a2a.send` under test.
"""

from __future__ import annotations

import json

import httpx
import pytest

from prismal_sdk.a2a import MESSAGE_SEND, MESSAGE_STREAM, TASKS_CANCEL, TASKS_GET
from prismal_sdk.exceptions import A2AJsonRpcError, A2ANotEnabledError

_STREAM_BODY = (
    b'data: {"result": {"kind": "status-update", "n": 1}}\n\n'
    b'data: {"result": {"kind": "status-update", "n": 2}}\n\n'
    b'data: {"result": {"kind": "status-update", "n": 3}}\n\n'
)


def _rpc_ok(result=None):
    """Handler returning a JSON-RPC success envelope and recording the request."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": "1", "result": result or {}}
        )

    return handler, seen


# --- SPEC-CSB-A2A-002: the JSON-RPC envelope --------------------------------


def test_send_builds_a_jsonrpc_2_0_envelope(make_client):
    handler, seen = _rpc_ok()
    with make_client(handler) as client:
        client.a2a.send("message/send", {"foo": "bar"}, request_id="req-1")

    assert seen[0] == {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {"foo": "bar"},
    }


def test_send_mints_a_request_id_when_omitted(make_client):
    handler, seen = _rpc_ok()
    with make_client(handler) as client:
        client.a2a.send("message/send", {})
    assert isinstance(seen[0]["id"], str) and seen[0]["id"]


def test_send_returns_the_result_member(make_client):
    handler, _ = _rpc_ok(result={"taskId": "t-9"})
    with make_client(handler) as client:
        assert client.a2a.send("tasks/get", {}) == {"taskId": "t-9"}


def test_send_raises_on_a_jsonrpc_error_member(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "error": {"code": -32601, "message": "Method not found"},
            },
        )

    with make_client(handler) as client:
        with pytest.raises(A2AJsonRpcError) as excinfo:
            client.a2a.send("nope/nope", {})

    assert excinfo.value.code == -32601
    assert "Method not found" in str(excinfo.value)


# --- SPEC-CSB-A2A-004: typed wrappers pick the right method -----------------


@pytest.mark.parametrize(
    ("call", "expected_method"),
    [
        (lambda a: a.message_send({}), MESSAGE_SEND),
        (lambda a: a.tasks_get({}), TASKS_GET),
        (lambda a: a.tasks_cancel({}), TASKS_CANCEL),
    ],
    ids=["message_send", "tasks_get", "tasks_cancel"],
)
def test_typed_wrappers_use_the_standard_method_name(
    make_client, call, expected_method
):
    handler, seen = _rpc_ok()
    with make_client(handler) as client:
        call(client.a2a)
    assert seen[0]["method"] == expected_method


def test_message_stream_uses_the_standard_method_name(make_client):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=_STREAM_BODY)

    with make_client(handler) as client:
        list(client.a2a.message_stream({}))
    assert seen[0]["method"] == MESSAGE_STREAM


# --- SPEC-CSB-A2A-003: the streaming route ----------------------------------


def test_stream_yields_json_decoded_data_frames(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_STREAM_BODY)

    with make_client(handler) as client:
        frames = list(client.a2a.stream(MESSAGE_STREAM, {}))

    assert [f["result"]["n"] for f in frames] == [1, 2, 3]


async def test_async_stream_yields_json_decoded_data_frames(make_async_client):
    async def body():
        yield _STREAM_BODY

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body())

    async with make_async_client(handler) as client:
        frames = [f async for f in client.a2a.stream(MESSAGE_STREAM, {})]

    assert [f["result"]["n"] for f in frames] == [1, 2, 3]


# --- SPEC-CSB-A2A-005: 404 on either route ----------------------------------


def test_send_404_raises_not_enabled(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "A2A is not enabled"})

    with make_client(handler) as client:
        with pytest.raises(A2ANotEnabledError):
            client.a2a.send(MESSAGE_SEND, {})


def test_stream_404_raises_not_enabled(make_client):
    # The streaming route must map 404 the same way the unary one does —
    # a generic PrismalAPIError here would hide "the host disabled A2A".
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "A2A is not enabled"})

    with make_client(handler) as client:
        with pytest.raises(A2ANotEnabledError):
            list(client.a2a.stream(MESSAGE_STREAM, {}))


def test_agent_card_404_raises_not_enabled(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "A2A is not enabled"})

    with make_client(handler) as client:
        with pytest.raises(A2ANotEnabledError):
            client.agent_card()

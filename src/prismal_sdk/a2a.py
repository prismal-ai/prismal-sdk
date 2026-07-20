"""A2A JSON-RPC helpers (CSB-03-01/02/03, SPEC-CSB-A2A-*).

Pure, transport-agnostic helpers shared by the ``a2a`` resource on both
:class:`~prismal_sdk.client.PrismalClient` and
:class:`~prismal_sdk.async_client.AsyncPrismalClient` — building the JSON-RPC
envelope, parsing the response, and framing the ``message/stream`` SSE body
(``data:`` lines only, per ``prismal-server/docs/a2a.md``: "emitting the
handler's ``data:`` lines"). No prismal-specific extension over standard A2A
v0.3.x, per SPEC-RHB-SDK-002.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any
from uuid import uuid4

from prismal_sdk.exceptions import A2AJsonRpcError
from prismal_sdk.models import JsonRpcResponse

# Standard A2A v0.3.x JSON-RPC methods the SDK wraps (SPEC-CSB-A2A-004).
MESSAGE_SEND = "message/send"
MESSAGE_STREAM = "message/stream"
TASKS_GET = "tasks/get"
TASKS_CANCEL = "tasks/cancel"


def build_jsonrpc_request(
    method: str, params: dict[str, Any], *, request_id: str | int | None = None
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request body for ``POST /a2a``."""
    return {
        "jsonrpc": "2.0",
        "id": request_id if request_id is not None else uuid4().hex,
        "method": method,
        "params": params,
    }


def parse_jsonrpc_response(body: dict[str, Any]) -> Any:
    """Parse a non-streaming ``POST /a2a`` JSON body, raising on a JSON-RPC error.

    Returns ``result`` on success. Raises :class:`A2AJsonRpcError` for an
    ``error`` member — this is a distinct surface from the REST
    ``{"error": {"code": str, ...}}`` envelope (ARCHITECTURE.md §4.2/§6).
    """
    rpc = JsonRpcResponse.model_validate(body)
    if rpc.error is not None:
        raise A2AJsonRpcError(rpc.error.code, rpc.error.message)
    return rpc.result


def _feed_data_line(line: str, buf: list[str]) -> str | None:
    """Feed one line into a data-only SSE buffer; return a completed frame, if any."""
    if line == "":
        if buf:
            frame = "\n".join(buf)
            buf.clear()
            return frame
        return None
    if line.startswith("data:"):
        buf.append(line[len("data:") :].strip())
    # Any other line shape (comments, an "event:" line the handler may add in
    # the future, ids) is ignored — the SDK only needs the `data:` payload.
    return None


def iter_a2a_data_frames(lines: Iterable[str]) -> Iterator[Any]:
    """Parse ``message/stream``'s SSE body into JSON-decoded frames (sync)."""
    buf: list[str] = []
    for line in lines:
        frame = _feed_data_line(line, buf)
        if frame:
            yield json.loads(frame)


async def aiter_a2a_data_frames(lines: AsyncIterable[str]) -> AsyncIterator[Any]:
    """Async counterpart of :func:`iter_a2a_data_frames`."""
    buf: list[str] = []
    async for line in lines:
        frame = _feed_data_line(line, buf)
        if frame:
            yield json.loads(frame)

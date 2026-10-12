"""WebSocket chat sessions (CS2-03-*, SPEC-CS2-WSK-001..004).

``client.ws(thread_id)`` returns a :class:`WsSession` (sync) or
:class:`AsyncWsSession` (async) bound to ``GET /ws/threads/{id}``. A session
is one connection that runs one turn at a time (host ``SPEC-RH2-WSK-003``);
server frames are translated by the same code as the SSE path, so a native
event or an AG-UI event is the same model whichever transport carried it
(DD-CS2-006).

``websockets`` is an optional dependency (extra ``[ws]``). Nothing here
imports it at module load — only a session's methods do — so the base
install never needs it (DD-CS2-005).

Turns are never retried (SPEC-CS2-WSK-004). Abandoning a turn mid-way (a
``break`` out of ``send_message``) sends ``cancel`` — the WebSocket
equivalent of SSE's prompt disconnect (SPEC-CSB-CHT-006) — and the next
``send_message`` first drains the abandoned turn's remaining frames, so
they are never mistaken for the new turn's.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, overload

import httpx

from prismal_sdk._chat import AgUiTranslator, translate_chat_event
from prismal_sdk._transport import parse_error_object
from prismal_sdk.agui import AgUiEvent, RunFinished, StreamProtocol
from prismal_sdk.exceptions import (
    MessageTooLargeError,
    PrismalAPIError,
    PrismalConnectionError,
    PrismalSDKError,
    PrismalTimeoutError,
    PrismalWebSocketError,
    TurnInProgressError,
    WebSocketAuthenticationError,
    WebSocketProtocolError,
    WebSocketServerError,
    WebSocketUnavailableError,
    error_for_code,
)
from prismal_sdk.models import ChatEvent, DoneEvent

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection as AsyncConnection
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import ClientConnection as SyncConnection

INSTALL_HINT = (
    "WebSocket support needs the optional dependency: pip install 'prismal-sdk[ws]'"
)

_CANCEL_FRAME = json.dumps({"type": "cancel"})

_CLOSE_CODE_ERRORS: dict[int, type[PrismalWebSocketError]] = {
    1008: WebSocketAuthenticationError,
    1009: MessageTooLargeError,
    1011: WebSocketServerError,
    4400: WebSocketProtocolError,
    4409: TurnInProgressError,
}


def require_websockets() -> None:
    """Raise :class:`WebSocketUnavailableError` unless ``websockets`` imports."""
    try:
        import websockets.asyncio.client  # noqa: F401
        import websockets.sync.client  # noqa: F401
    except ImportError as exc:
        raise WebSocketUnavailableError(INSTALL_HINT) from exc


def ws_url(base_url: str, thread_id: str) -> str:
    """``http(s)://host/prefix`` -> ``ws(s)://host/prefix/ws/threads/{id}``."""
    url = httpx.URL(base_url)
    scheme = {"http": "ws", "https": "wss"}.get(url.scheme, url.scheme)
    path = url.path.rstrip("/") + f"/ws/threads/{thread_id}"
    return str(url.copy_with(scheme=scheme, path=path))


# ── frame codec (SPEC-RH2-WSK-002) ──────────────────────────────────────────


def encode_message(
    content: str, role: str, metadata: dict[str, Any] | None, protocol: str
) -> str:
    return json.dumps(
        {
            "type": "message",
            "content": content,
            "role": role,
            "metadata": metadata or {},
            "protocol": protocol,
        }
    )


def decode_frame(raw: str | bytes) -> dict[str, Any]:
    """Parse one server frame; anything but ``{"event": str, ...}`` is an error."""
    try:
        frame = json.loads(raw)
    except ValueError as exc:
        raise WebSocketProtocolError("Malformed server frame: not JSON") from exc
    if not isinstance(frame, dict) or not isinstance(frame.get("event"), str):
        raise WebSocketProtocolError("Malformed server frame: no 'event'")
    return frame


def ends_turn(frame: dict[str, Any]) -> bool:
    """Whether ``frame`` is the last one of a turn, in either protocol."""
    event = frame["event"]
    if event in ("done", "error"):
        return True
    data = frame.get("data")
    return (
        event == "agui"
        and isinstance(data, dict)
        and data.get("type") in ("RUN_FINISHED", "RUN_ERROR")
    )


class TurnDecoder:
    """Server frame -> typed event for one turn (SPEC-CS2-WSK-002).

    A native ``error`` frame raises in both protocols (``cancelled`` included);
    ``heartbeat``/``pong`` and frames of the other protocol are ignored, like
    unknown SSE events.
    """

    def __init__(self, protocol: str) -> None:
        if protocol not in ("prismal", "ag-ui"):
            raise ValueError(f"protocol must be 'prismal' or 'ag-ui', got {protocol!r}")
        self._agui = AgUiTranslator() if protocol == "ag-ui" else None

    def feed(self, frame: dict[str, Any]) -> tuple[ChatEvent | AgUiEvent | None, bool]:
        """Return ``(event or None, is_last)``; raises the mapped error frame."""
        event = frame["event"]
        data = frame.get("data") or {}
        if event == "error" or self._agui is None:
            parsed = translate_chat_event(event, data)
            return parsed, isinstance(parsed, DoneEvent)
        if event != "agui":
            return None, False
        agui = self._agui.translate(data)
        return agui, isinstance(agui, RunFinished)


# ── error mapping ───────────────────────────────────────────────────────────


def closed_error(exc: ConnectionClosed) -> PrismalWebSocketError:
    """Map a closed connection to its exception by close code (WSK-003)."""
    frame = exc.rcvd or exc.sent
    code = frame.code if frame is not None else 1006
    reason = frame.reason if frame is not None else ""
    klass = _CLOSE_CODE_ERRORS.get(code, PrismalWebSocketError)
    detail = f": {reason}" if reason else ""
    return klass(f"WebSocket closed [{code}]{detail}", close_code=code, reason=reason)


def connect_error(exc: Exception) -> PrismalSDKError:
    """Map a failed connect/handshake to an SDK error.

    A rejected upgrade is an ordinary HTTP response: its error body goes
    through the normal code table (e.g. ``403 forbidden_tenant``).
    """
    from websockets.exceptions import InvalidStatus

    if isinstance(exc, InvalidStatus):
        status = exc.response.status_code
        body = httpx.Response(status, content=bytes(exc.response.body or b""))
        error = parse_error_object(body)
        code = error.get("code") if error else None
        message = error.get("message") if error else None
        if isinstance(code, str):
            return error_for_code(
                status,
                code,
                message if isinstance(message, str) else f"HTTP {status}",
                error,
            )
        return PrismalAPIError(
            status,
            "websocket_rejected",
            f"WebSocket handshake rejected (HTTP {status})",
        )
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return PrismalTimeoutError(f"WebSocket connect timed out: {exc}")
    # Refused/unreachable host, bad URI, failed upgrade (InvalidHandshake).
    return PrismalConnectionError(f"WebSocket connect failed: {exc}")


def _read_timeout(timeout_s: float) -> PrismalTimeoutError:
    return PrismalTimeoutError(f"No WebSocket frame within {timeout_s}s")


# ── sync session ────────────────────────────────────────────────────────────


class WsSession:
    """One sync WebSocket connection to a thread (SPEC-CS2-WSK-001).

    Connects on ``with`` or lazily on the first :meth:`send_message`.
    ``cancel`` may be called from another thread while a turn is iterated.
    """

    def __init__(self, url: str, headers: dict[str, str], timeout_s: float) -> None:
        self._url = url
        self._headers = headers
        self._timeout_s = timeout_s
        self._conn: SyncConnection | None = None
        self._turn_open = False

    def __enter__(self) -> WsSession:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def connect(self) -> None:
        """Open the connection (a no-op when already open)."""
        if self._conn is not None:
            return
        from websockets.sync.client import connect

        try:
            # Entered as a context manager: websockets >= 17.1 deprecates
            # using connect()'s return value directly, and its future
            # default returns a reconnecting factory whose __enter__ yields
            # the connection. Both shapes work from 13.0 on.
            self._conn = connect(
                self._url,
                additional_headers=self._headers,
                open_timeout=self._timeout_s,
            ).__enter__()
        except Exception as exc:
            raise connect_error(exc) from exc

    def close(self) -> None:
        """Close the connection; idempotent."""
        conn, self._conn = self._conn, None
        self._turn_open = False
        if conn is not None:
            conn.__exit__(None, None, None)

    def cancel(self) -> None:
        """Ask the host to stop the running turn; it then ends with
        :class:`~prismal_sdk.exceptions.TurnCancelledError`."""
        self._send(_CANCEL_FRAME)

    @overload
    def send_message(
        self,
        content: str,
        *,
        role: str = ...,
        metadata: dict[str, Any] | None = ...,
        protocol: Literal["prismal"] = ...,
    ) -> Iterator[ChatEvent]: ...

    @overload
    def send_message(
        self,
        content: str,
        *,
        role: str = ...,
        metadata: dict[str, Any] | None = ...,
        protocol: Literal["ag-ui"],
    ) -> Iterator[AgUiEvent]: ...

    def send_message(
        self,
        content: str,
        *,
        role: str = "user",
        metadata: dict[str, Any] | None = None,
        protocol: StreamProtocol = "prismal",
    ) -> Iterator[ChatEvent | AgUiEvent]:
        """Run one turn, yielding its events (SPEC-CS2-WSK-002).

        Ends after ``DoneEvent`` (native) or ``RunFinished`` (AG-UI); an
        ``error`` frame raises the mapped exception, a close frame the
        :class:`~prismal_sdk.exceptions.PrismalWebSocketError` for its code.
        """
        decoder = TurnDecoder(protocol)
        self.connect()
        if self._turn_open:
            self._drain()
        self._send(encode_message(content, role, metadata, protocol))
        self._turn_open = True
        try:
            while True:
                event, last = decoder.feed(self._recv())
                if last:
                    # Before yielding: a `break` on the last event is not an
                    # abandoned turn and must not send `cancel`.
                    self._turn_open = False
                if event is not None:
                    yield event
                if last:
                    return
        except PrismalAPIError:
            self._turn_open = False  # the host ended the turn with an error
            raise
        finally:
            if self._turn_open and self._conn is not None:
                self._cancel_quietly()

    def _connection(self) -> SyncConnection:
        if self._conn is None:
            raise PrismalWebSocketError("WebSocket session is not connected")
        return self._conn

    def _send(self, text: str) -> None:
        from websockets.exceptions import ConnectionClosed

        conn = self._connection()
        try:
            conn.send(text)
        except ConnectionClosed as exc:
            raise self._lost(exc) from exc

    def _recv(self) -> dict[str, Any]:
        from websockets.exceptions import ConnectionClosed

        conn = self._connection()
        try:
            raw = conn.recv(timeout=self._timeout_s)
        except TimeoutError as exc:
            self.close()  # the turn's state is unknown: start afresh
            raise _read_timeout(self._timeout_s) from exc
        except ConnectionClosed as exc:
            raise self._lost(exc) from exc
        return decode_frame(raw)

    def _lost(self, exc: ConnectionClosed) -> PrismalWebSocketError:
        self._conn = None
        self._turn_open = False
        return closed_error(exc)

    def _drain(self) -> None:
        while not ends_turn(self._recv()):
            pass
        self._turn_open = False

    def _cancel_quietly(self) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            self._connection().send(_CANCEL_FRAME)
        except ConnectionClosed:
            pass  # already gone: nothing left to cancel


# ── async session ───────────────────────────────────────────────────────────


class AsyncWsSession:
    """Async mirror of :class:`WsSession` (``async with`` / ``async for``)."""

    def __init__(self, url: str, headers: dict[str, str], timeout_s: float) -> None:
        self._url = url
        self._headers = headers
        self._timeout_s = timeout_s
        self._conn: AsyncConnection | None = None
        self._turn_open = False

    async def __aenter__(self) -> AsyncWsSession:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the connection (a no-op when already open)."""
        if self._conn is not None:
            return
        from websockets.asyncio.client import connect

        try:
            self._conn = await connect(
                self._url,
                additional_headers=self._headers,
                open_timeout=self._timeout_s,
            )
        except Exception as exc:
            raise connect_error(exc) from exc

    async def close(self) -> None:
        """Close the connection; idempotent."""
        conn, self._conn = self._conn, None
        self._turn_open = False
        if conn is not None:
            await conn.close()

    async def cancel(self) -> None:
        """Ask the host to stop the running turn (see :meth:`WsSession.cancel`)."""
        await self._send(_CANCEL_FRAME)

    @overload
    def send_message(
        self,
        content: str,
        *,
        role: str = ...,
        metadata: dict[str, Any] | None = ...,
        protocol: Literal["prismal"] = ...,
    ) -> AsyncIterator[ChatEvent]: ...

    @overload
    def send_message(
        self,
        content: str,
        *,
        role: str = ...,
        metadata: dict[str, Any] | None = ...,
        protocol: Literal["ag-ui"],
    ) -> AsyncIterator[AgUiEvent]: ...

    async def send_message(
        self,
        content: str,
        *,
        role: str = "user",
        metadata: dict[str, Any] | None = None,
        protocol: StreamProtocol = "prismal",
    ) -> AsyncIterator[ChatEvent | AgUiEvent]:
        """Run one turn, yielding its events (see :meth:`WsSession.send_message`)."""
        decoder = TurnDecoder(protocol)
        await self.connect()
        if self._turn_open:
            await self._drain()
        await self._send(encode_message(content, role, metadata, protocol))
        self._turn_open = True
        try:
            while True:
                event, last = decoder.feed(await self._recv())
                if last:
                    self._turn_open = False
                if event is not None:
                    yield event
                if last:
                    return
        except PrismalAPIError:
            self._turn_open = False
            raise
        finally:
            if self._turn_open and self._conn is not None:
                await self._cancel_quietly()

    def _connection(self) -> AsyncConnection:
        if self._conn is None:
            raise PrismalWebSocketError("WebSocket session is not connected")
        return self._conn

    async def _send(self, text: str) -> None:
        from websockets.exceptions import ConnectionClosed

        conn = self._connection()
        try:
            await conn.send(text)
        except ConnectionClosed as exc:
            raise self._lost(exc) from exc

    async def _recv(self) -> dict[str, Any]:
        from websockets.exceptions import ConnectionClosed

        conn = self._connection()
        try:
            raw = await asyncio.wait_for(conn.recv(), self._timeout_s)
        except asyncio.TimeoutError as exc:
            await self.close()
            raise _read_timeout(self._timeout_s) from exc
        except ConnectionClosed as exc:
            raise self._lost(exc) from exc
        return decode_frame(raw)

    def _lost(self, exc: ConnectionClosed) -> PrismalWebSocketError:
        self._conn = None
        self._turn_open = False
        return closed_error(exc)

    async def _drain(self) -> None:
        while not ends_turn(await self._recv()):
            pass
        self._turn_open = False

    async def _cancel_quietly(self) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            await self._connection().send(_CANCEL_FRAME)
        except ConnectionClosed:
            pass

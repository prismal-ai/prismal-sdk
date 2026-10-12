# WebSocket sessions

`client.ws(thread_id)` opens a WebSocket on `GET /ws/threads/{thread_id}`: one
connection that runs many turns of the same thread, one at a time, and can
**cancel** a running turn — something an SSE request cannot do.

## Install

`websockets` is an optional dependency, so the base install stays
`httpx` + `pydantic`:

```bash
pip install 'prismal-sdk[ws]'
```

Without it, `client.ws()` raises `WebSocketUnavailableError` (also an
`ImportError`) with that hint. Nothing else in the SDK imports `websockets`.

## Usage

```python
from prismal_sdk import PrismalClient, DoneEvent, TokenEvent

with PrismalClient("http://localhost:8000", token="...") as client:
    thread = client.create_thread()
    with client.ws(thread.thread_id) as session:
        for event in session.send_message("Hola"):
            if isinstance(event, TokenEvent):
                print(event.delta, end="")
        for event in session.send_message("¿Y ahora?", protocol="ag-ui"):
            ...
```

Async — the same with `async with` / `async for` / `await`:

```python
async with AsyncPrismalClient(url) as client:
    async with client.ws(thread_id) as session:
        async for event in session.send_message("Hola"):
            ...
```

- **Same events as SSE.** Native turns yield `TokenEvent` … `DoneEvent`
  (with `usage`); `protocol="ag-ui"` yields AG-UI models ending in
  `RunFinished`. One translator serves both transports, so a model never
  depends on how it arrived.
- **Same auth.** The handshake sends `Authorization: Bearer` and `X-Org-Id`
  as headers (`org_id=` on `client.ws()` overrides the client's tenant). The
  URL is the base URL with `http`→`ws` / `https`→`wss`; the token never goes
  in the query string.
- **Lazy connect.** `client.ws()` does no I/O; the session connects on
  `with` / `connect()` or on the first `send_message`. `close()` is
  idempotent.
- **Timeouts.** The client's `timeout_s` bounds the handshake and each wait
  for a frame; heartbeats reset it. Exceeding it raises `PrismalTimeoutError`.
- **No retries.** A turn is never re-sent (`SPEC-CS2-WSK-004`).

## Cancelling

```python
for event in session.send_message("Una tarea larga"):
    if should_stop():
        session.cancel()          # the turn then ends with TurnCancelledError
```

Breaking out of the loop instead **abandons** the turn: the SDK sends
`cancel` for you, and the next `send_message` first drains the old turn's
remaining frames, so they are never mixed into the new one. Breaking on the
terminal event (`DoneEvent` / `RunFinished`) is not an abandonment and sends
nothing. The sync `cancel()` may be called from another thread.

## Errors

An `error` frame raises the mapped `PrismalAPIError` (same table as SSE). A
close frame, a failed handshake or an undecodable frame raises a
`PrismalWebSocketError` (a `PrismalTransportError`) with `close_code` and
`reason`:

| Close code | Exception | Meaning |
|---|---|---|
| `1008` | `WebSocketAuthenticationError` | credential rejected on the handshake |
| `1009` | `MessageTooLargeError` | frame larger than the host's limit |
| `1011` | `WebSocketServerError` | the host failed internally |
| `4400` | `WebSocketProtocolError` | malformed frame (also raised for a server frame the SDK cannot decode) |
| `4409` | `TurnInProgressError` | a message arrived while a turn was running |
| other | `PrismalWebSocketError` | |

A handshake the host rejects with an HTTP error body raises the mapped
`PrismalAPIError` (e.g. `ForbiddenError`); a host that cannot be reached
raises `PrismalConnectionError`.

# Streaming chat

`send_message()` (sync, `Iterator[ChatEvent]`) and its async counterpart
(`AsyncIterator[ChatEvent]`) stream a chat turn exactly as
`prismal-server` frames it — no buffering, no re-batching.

## Event types

| Event | When | Fields |
|---|---|---|
| `TokenEvent` | Incremental assistant text | `delta: str` |
| `ToolCallEvent` | A tool invocation surfaced by the graph | `name: str`, `args: Any` |
| `StateEvent` | An optional node/state transition | `data: dict` |
| `DoneEvent` | Terminal — ends iteration normally | `thread_id: str`, `finish_reason: str` |

A terminal **`error`** frame is not a value you receive — it is **raised**
from inside the iterator as the mapped exception (see
[`errors.md`](./errors.md)), because the HTTP status is already `200` by the
time a mid-stream failure happens (the host committed to the stream before
it could know). Wrap consumption in a `try`/`except PrismalAPIError`:

```python
from prismal_sdk import PrismalClient, DoneEvent, TokenEvent
from prismal_sdk.exceptions import PrismalAPIError

with PrismalClient("http://localhost:8000") as client:
    thread = client.create_thread()
    try:
        for event in client.send_message(thread.thread_id, "Hola"):
            if isinstance(event, TokenEvent):
                print(event.delta, end="")
            elif isinstance(event, DoneEvent):
                print(f"\n({event.finish_reason})")
    except PrismalAPIError as exc:
        print(f"stream failed: {exc.code}")
```

## Heartbeats

The server emits a `: heartbeat` comment line (default every 15s) to keep
intermediaries from closing an idle connection. The SDK's parser consumes
these silently — they never reach your code as an event.

## Disconnecting early

Breaking out of the `for` / `async for` loop (or calling `.close()` on the
generator) drops the underlying HTTP response. On CPython this happens
promptly via reference counting, which the server observes as a client
disconnect and cancels its `astream` work accordingly. If you need a
disconnect to happen at a precise moment rather than "whenever the generator
is garbage collected," call `.close()`/`.aclose()` on the iterator explicitly
instead of relying on `break` alone.

## A2A streaming

`client.a2a.stream(...)` / `client.a2a.message_stream(...)` follow the same
shape but yield raw JSON-decoded JSON-RPC frames (the A2A wire format is
`data:`-only, no named `event:` lines) rather than the chat event types
above — see [`prismal-server/docs/a2a.md`](https://github.com/prismal-ai/prismal-server/blob/main/docs/a2a.md).

# AG-UI streaming

`send_message(..., protocol="ag-ui")` streams a turn as
[AG-UI 1.0](https://docs.ag-ui.com) events instead of prismal's native
`token`/`tool_call`/`state`/`done` frames — the format UI toolkits such as
CopilotKit consume directly. Same endpoint, same auth; only the `Accept`
header changes.

```python
from prismal_sdk import PrismalClient, RunFinished
from prismal_sdk.agui import PrismalUsageEvent, TextMessageContent, ToolCallStart

with PrismalClient("http://localhost:8000") as client:
    thread = client.create_thread()
    for event in client.send_message(thread.thread_id, "Hola", protocol="ag-ui"):
        if isinstance(event, TextMessageContent):
            print(event.delta, end="")
        elif isinstance(event, ToolCallStart):
            print(f"\n[tool] {event.tool_call_name}")
        elif isinstance(event, PrismalUsageEvent):
            print(f"\n[usage] {event.value.total_tokens} tokens")
        elif isinstance(event, RunFinished):
            print("\n[done]")
```

The return type follows the argument (`typing.overload`): `protocol="ag-ui"`
is typed `Iterator[AgUiEvent]`, the default `"prismal"` stays
`Iterator[ChatEvent]`. An unknown `protocol` raises `ValueError` before any
I/O. The async client is identical with `async for`.

## Events

Every event is a pydantic model in `prismal_sdk.agui`, subclassing
`AgUiEvent`. Fields use Python names (`message_id`) and accept the wire's
camelCase (`messageId`); `model_dump(by_alias=True)` gives the wire shape
back.

| Group | Models |
|---|---|
| Run lifecycle | `RunStarted`, `RunFinished`, `RunError`, `StepStarted`, `StepFinished` |
| Text | `TextMessageStart`, `TextMessageContent`, `TextMessageEnd`, `TextMessageChunk` |
| Tools | `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallChunk`, `ToolCallResult` |
| State | `StateSnapshot`, `StateDelta`, `MessagesSnapshot`, `ActivitySnapshot`, `ActivityDelta` |
| Reasoning | `ReasoningStart`, `ReasoningMessageStart` / `Content` / `End` / `Chunk`, `ReasoningEnd`, `ReasoningEncryptedValue` |
| Sub-agents | `SubagentStarted`, `SubagentFinished`, `SubagentError` |
| Extension | `Raw`, `CustomEvent`, `PrismalUsageEvent` |

An event type the SDK does not know yet parses as the base `AgUiEvent` with
its fields kept — a newer host never breaks the stream. `parse_agui_event()`
is public for callers that read AG-UI frames from elsewhere.

## How a run ends

- **Success** — the last event is always `RunFinished`; iteration stops
  there. Just before it the host sends a `CUSTOM` event named
  `prismal.usage`, surfaced as `PrismalUsageEvent` whose `value` is the same
  `Usage` model as `DoneEvent.usage` (see [`usage.md`](./usage.md)).
- **Failure** — `RUN_ERROR` is **raised**, not yielded, as the mapped
  exception (same table as native `error` frames, see
  [`errors.md`](./errors.md)). A `BudgetExceededError` raised this way
  carries the usage the host reported before the error.

## When the host cannot stream AG-UI

A host or tenant with AG-UI disabled answers `406` and the SDK raises
`ProtocolNotEnabledError` before any event. A v0.1 host ignores the request
and streams native frames; the SDK detects that from the missing
`X-Prismal-Stream-Protocol: ag-ui` response header and raises the same
`ProtocolNotEnabledError` instead of handing you an empty, "successful" run.

## Over WebSocket

`session.send_message(content, protocol="ag-ui")` on a `client.ws()` session
yields the same models — see [`websocket.md`](./websocket.md).

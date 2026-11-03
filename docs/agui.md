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

## Running from a `RunAgentInput` — and resuming interrupts

`client.run_agui(thread_id, content)` posts an AG-UI 1.0 `RunAgentInput` to
`POST /v1/agui` (host ≥ 0.3 for resume) and yields the same event models.
Pass **either** `content` (a new user message) **or** `resume` (answers to
open interrupts) — both or neither raise `ValueError` before any I/O.
`run_id=` sets `RunAgentInput.runId`; it defaults to a fresh uuid4 hex.

When the agent pauses (an engine approval gate, a LangGraph `interrupt()`),
the run ends with `RunFinished.is_interrupted == True` and
`RunFinished.interrupts` lists the open `AgUiInterrupt`s (`id`, `reason`,
`message`, `tool_call_id`, `metadata`). Answer every one of them:

```python
from prismal_sdk import PrismalClient, ResumeConflictError
from prismal_sdk.agui import RunFinished, TextMessageContent

with PrismalClient("http://localhost:8000") as client:
    thread_id = client.create_thread().thread_id
    events = list(client.run_agui(thread_id, "Deploy the release"))
    finished = events[-1]
    while isinstance(finished, RunFinished) and finished.is_interrupted:
        for interrupt in finished.interrupts:
            print(f"[{interrupt.reason}] {interrupt.message}")
        answers = [i.resolve({"action": "approve"}) for i in finished.interrupts]
        events = list(client.run_agui(thread_id, resume=answers))
        finished = events[-1]
    print("".join(e.delta for e in events if isinstance(e, TextMessageContent)))
```

- **Ids are opaque.** The host 0.3 sends `"<engine id>.<checkpoint id>"`;
  send them back exactly as received (`interrupt.resolve()` does).
- **Payloads are yours.** `resolve(payload)` / `ResumeEntry(payload=...)`
  go to the engine unchanged; the SDK never interprets them. Build a
  `ResumeEntry(interrupt_id=..., status=..., payload=..., metadata=...)`
  directly for full control. `status="cancelled"` is sent as given, and the
  host 0.3 refuses it (`422 unsupported_resume`).
- **Never retried.** `run_agui` is not retried, not even on a connect
  failure: a resume may already have run. The host also keeps running a
  resume whose client disconnected. If you are unsure whether a resume
  landed, re-sending is safe — the host answers `409` instead of resuming
  twice.
- **Refusals** raise before any event:

  | Code | Exception | When |
  |---|---|---|
  | `no_pending_interrupt` (409) | `ResumeConflictError` | Nothing to resume, already answered (a retry), or a stale checkpoint suffix |
  | `resume_in_progress` (409) | `ResumeConflictError` | Another resume of the thread is still running |
  | `invalid_resume` (422) | `ValidationError` | The ids are not exactly the open interrupts, or lack the checkpoint suffix |
  | `unsupported_resume` (422) | `ValidationError` | A `cancelled` entry |

Resume is AG-UI only: it is not available over WebSocket or the native
`send_message` route. Client-declared frontend tools are not forwarded yet
(the engine does not support them).

## When the host cannot stream AG-UI

A host or tenant with AG-UI disabled answers `406` and the SDK raises
`ProtocolNotEnabledError` before any event. A v0.1 host ignores the request
and streams native frames; the SDK detects that from the missing
`X-Prismal-Stream-Protocol: ag-ui` response header and raises the same
`ProtocolNotEnabledError` instead of handing you an empty, "successful" run.

## Over WebSocket

`session.send_message(content, protocol="ag-ui")` on a `client.ws()` session
yields the same models — see [`websocket.md`](./websocket.md).

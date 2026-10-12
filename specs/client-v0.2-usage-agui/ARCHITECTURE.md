# prismal-sdk — Architecture (Client v0.2: Usage, AG-UI, WebSocket, A2A v1)

| Field | Value |
|---|---|
| **Status** | `READY` |
| **Version** | 1.0 |
| **Date** | 2026-10-04 |
| **Author** | Ernesto Crespo |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`SPEC.md`](./SPEC.md) · [`TASKS.md`](./TASKS.md) |

---

## 1. Context

v0.1 modules: `config.py` (`ClientConfig`), `exceptions.py`, `_transport.py` (headers, retry,
dispatch), `client.py` / `async_client.py`, `models.py`, `_sse.py` (frame parser mirroring
`prismal-server/streaming.py`), `a2a.py`. Tests run offline with `respx`/`httpx.MockTransport`; a
`contract` marker targets a live host. v0.2 extends these seams additively; v0.1 call sites keep working.

## 2. Feasibility

- **Usage:** a new optional field on `DoneEvent` plus new models; Pydantic tolerates missing keys
  from a v0.1 host (`usage=None`).
- **AG-UI:** the server reuses SSE; only the `Accept` header and a data-only frame path differ. The
  v0.1 parser already separates `event:` and `data:` lines; a frame without `event:` is routed to
  `parse_agui_event`.
- **WebSocket:** `websockets` offers async and sync clients **[verify sync API at the pinned floor]**;
  wrapping both behind one adapter keeps parity. Deferred import keeps the base install unchanged.
- **A2A v1:** the existing JSON-RPC envelope code is version-agnostic; method names become a lookup.
- **Contract suite:** the server's fake-LLM mode (RH2-06) removes the credential dependency that
  blocked CSB-05-01.

## 3. Modules

| Module | New/ext | Purpose |
|---|---|---|
| `models.py` | ext | `Usage`, `DoneEvent.usage`, `UsageTurn`, `UsageReport`, `BudgetAmounts`, `QuotaWindow`, `BudgetReport`, `TaskListPage` |
| `agui.py` | new | AG-UI models, `AGUI_EVENT_TYPES`, `parse_agui_event`, `PrismalUsageEvent` |
| `_sse.py` | ext | data-only frame routing to `parse_agui_event` |
| `client.py` / `async_client.py` | ext | `usage`, `iter_usage_turns`, `budget`, `send_message(protocol=)`, `ws`, `a2a_protocol` kwarg |
| `_ws.py` | new | `WsSession` / `AsyncWsSession`, frame codec, close-code mapping (deferred `websockets` import) |
| `a2a.py` | ext | `negotiated_version`, `tasks_list`, version-aware wrappers |
| `_a2a_methods.py` | new | single constants table `{"0.3": {...}, "1.0": {...}}` |
| `admin.py` | new | admin report models + `decisions_report`, `routing_report`, `audit`, `tenants` mixins |
| `exceptions.py` | ext | new subclasses (SPEC §4, §5, §7) |
| `tests/fixtures/usage_wire.json` | new | vendored copy of the engine/host shared fixture |

## 4. Data flows

### 4.1 Native turn

```
send_message(tid, content) ─► POST /threads/{tid}/messages (Accept: text/event-stream)
   _sse frames:  event: token     → TokenEvent
                 event: tool_call → ToolCallEvent
                 event: state     → StateEvent
                 event: done      → DoneEvent(usage=Usage | None)  → yield, stop
                 event: error     → raise mapped PrismalAPIError
```

### 4.2 AG-UI turn

```
send_message(tid, content, protocol="ag-ui")
   ─► POST … (Accept: text/event-stream; profile=ag-ui)
   406 protocol_not_enabled ─► ProtocolNotEnabledError
   data: {"type":"RUN_STARTED",…}             → RunStarted
   data: {"type":"TEXT_MESSAGE_CONTENT",…}    → TextMessageContent
   data: {"type":"CUSTOM","name":"prismal.usage","value":{12 keys}} → PrismalUsageEvent(.usage)
   data: {"type":"RUN_FINISHED",…}            → RunFinished → yield, stop
   data: {"type":"RUN_ERROR","code":…}        → raise mapped PrismalAPIError
   data: {"type":"<unknown>",…}               → AgUiEvent (extra fields kept)
```

### 4.3 WebSocket

```
with client.ws(tid) as s:            # handshake: Authorization, X-Org-Id
    for ev in s.send_message("hi"):  # → {"type":"message",…}
        ...                          # ← {"event":"token","data":…} → TokenEvent
                                     # ← {"event":"agui","data":…}  → AgUiEvent
                                     # ← heartbeat/pong swallowed
    s.cancel()                       # → {"type":"cancel"} ; ← error{code:"cancelled"} → TurnCancelledError
close 4409/4400/1009/1008/1011 ─► mapped PrismalWebSocketError subclass
```

### 4.4 A2A negotiation

```
a2a.tasks_list() ─► negotiated_version()   (GET agent-card.json once, cache)
   "0.3" ─► A2AVersionError (no request)
   "1.0" ─► POST /a2a {jsonrpc, method=_a2a_methods["1.0"]["tasks_list"], params}
```

## 5. Design decisions

| ID | Decision | Rationale |
|---|---|---|
| DD-CS2-001 | Field names copied verbatim from the host; no aliases | One vocabulary across engine, host, SDK, dashboard |
| DD-CS2-002 | `extra="allow"` on every wire model; unknown enum values kept as strings | Forward compatibility with host 0.x and AG-UI evolution |
| DD-CS2-003 | `DoneEvent` / `RunFinished` yielded as last item | Callers need usage without a side channel |
| DD-CS2-004 | `protocol=` is a `send_message` kwarg with overloads, not a new method | Parity and discoverability; precise return types |
| DD-CS2-005 | WS behind `[ws]`, deferred import | Base install stays `httpx` + `pydantic` only |
| DD-CS2-006 | WS frames parsed by the same models as SSE | One event model per protocol |
| DD-CS2-007 | Version-specific A2A method names in one table | PRT0 verification changes one file |
| DD-CS2-008 | Contract suite is the release gate | Avoid repeating v0.1 (tag without a green live run) |

## 6. Error hierarchy additions

```
PrismalSDKError
├── PrismalAPIError
│   ├── ProtocolNotEnabledError · InvalidRequestError · ForbiddenError
│   ├── ServerConfigurationError · TurnCancelledError · AdminDisabledError
├── PrismalTransportError
│   └── PrismalWebSocketError (close_code)
│       ├── TurnInProgressError · WebSocketProtocolError · MessageTooLargeError
├── A2AJsonRpcError            (v0.1)
├── A2AVersionError            (new)
└── WebSocketUnavailableError  (new; also subclasses ImportError)
```
`1008` maps to the existing `AuthenticationError`; `1011` to `PrismalAPIError` with `code="internal_error"`.

## 7. Testing

Offline unit tests: fixture round-trip for `Usage`; native `done` with/without `usage`; AG-UI frame
parsing from a golden stream (copied from the host test assets); `RunError` mapping; `406`; usage
paging with cursors; budget enum tolerance; WS against an in-process fake server (`websockets.serve`)
for frames and close codes; A2A negotiation + `tasks_list` against `respx`. Contract: CI starts the
GHCR `prismal-server:0.2.0` image with `PRISMAL_SERVER_HOST_FAKE_LLM_MODE=true` and runs
`pytest -m contract`.

## 8. Open questions

1. Should `iter_usage_turns` stream across multiple windows (> 31 d) by splitting requests? Default: no.

# prismal-sdk — Architecture (Client SDK Bootstrap)

| Field | Value |
|---|---|
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-10 |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`SPEC.md`](./SPEC.md) · [`TASKS.md`](./TASKS.md) |

---

## 1. Guiding principle — a thin, typed wire client

> **contract → `prismal-server` (`SPEC-RHB-SDK-*`); transport, typing,
> ergonomics → this SDK. No agent, RAG, tool, or business logic lives here.**

The SDK talks to exactly **one** surface: the HTTP/SSE API `prismal-server`
already fixed. It has **zero** import-time dependency on `prismal` (the
engine) or `prismal_server` (the host) — it never links against them, is
installable without them, and is verified only against their **wire
contract**, not their internals.

| Seam | What crosses it | Owned by |
|---|---|---|
| Chat | `POST /threads`, `POST /threads/{id}/messages` (SSE) | `prismal-server` `SPEC.md` §3 |
| A2A | `GET /.well-known/agent-card.json`, `POST /a2a` (JSON-RPC/SSE) | `prismal-server` `SPEC.md` §4, standard A2A v0.3.x |
| Auth | `Authorization: Bearer`, `X-Org-Id` | `prismal-server` `SPEC.md` §5/§6 |
| Discovery | `GET /openapi.json` | `prismal-server` `SPEC.md` §9 |

Any pull toward importing `prismal.*` or `prismal_server.*`, embedding a
local copy of the engine's security/RAG/agent logic, or adding
caching/business rules beyond transport plumbing is a design smell — see the
`CLAUDE.md` review checklist.

---

## 2. C4 — Context

```
   dashboard / TUI / webchat / chatbot / your app
                        │
                        │ import prismal_sdk
                        ▼
              ┌───────────────────────┐
              │   prismal-sdk (thin)  │   this repo — pip dep `prismal-sdk`
              │  PrismalClient        │   import module `prismal_sdk`
              │  AsyncPrismalClient   │
              └───────────┬───────────┘
                           │ HTTP + SSE (REST today; WS deferred)
                           ▼
              ┌───────────────────────┐
              │     prismal-server    │   sibling repo, pip dep of the *host*,
              │  (FastAPI ASGI host)  │   NOT of this SDK
              └───────────┬───────────┘
                           │ 4 entry points (host's own boundary)
                           ▼
              ┌───────────────────────┐
              │     prismal (engine)  │
              └───────────────────────┘
```

The SDK sits **outside** the `prismal`/`prismal-server` dependency graph
entirely — it is a peer HTTP client, the same relationship any external A2A
peer or `curl` caller has to the host.

---

## 3. C4 — Container / module layout

`src/` layout, single distributable package `prismal_sdk`:

```
prismal-sdk/
├── pyproject.toml                 # deps: httpx, pydantic; NO prismal/prismal-server dep
├── CLAUDE.md                      # boundary rule + review checklist
├── src/prismal_sdk/
│   ├── __init__.py                # __version__, public re-exports
│   ├── py.typed                   # PEP 561 marker
│   ├── config.py                  # ClientConfig (pydantic-settings, PRISMAL_SDK_ prefix)
│   ├── models.py                  # typed wire models: MessageIn, ThreadCreated, SSE events, AgentCard, JSON-RPC envelopes
│   ├── exceptions.py              # PrismalAPIError hierarchy + transport errors
│   ├── _sse.py                    # SSE frame parser (event:/data:/heartbeat), internal
│   ├── _transport.py              # shared request building: headers, retry/backoff, error mapping
│   ├── client.py                  # PrismalClient (sync, httpx.Client)
│   ├── async_client.py            # AsyncPrismalClient (async, httpx.AsyncClient)
│   └── a2a.py                     # typed A2A JSON-RPC helpers used by both clients
├── examples/
│   ├── quickstart.py              # create_thread + send_message, sync
│   ├── streaming_chat.py          # async streaming with typed events
│   └── a2a_agent_card.py          # fetch card + one JSON-RPC call
├── docs/
│   ├── streaming.md               # SSE event types, heartbeat/cancellation semantics
│   ├── auth.md                    # bearer + X-Org-Id
│   └── errors.md                  # exception hierarchy ↔ server error codes
└── tests/
    ├── conftest.py                 # respx/MockTransport fixtures, no network
    ├── unit/                       # client, async_client, sse, errors, config (offline)
    └── contract/                   # opt-in: real prismal-server round-trip
```

**Why one package with two clients, not two packages:** the sync and async
clients share request construction, model parsing, and error mapping
(`_transport.py`); splitting them into separate distributions would either
duplicate that logic or force a dependency between packages for no benefit.
A single `prismal_sdk` package with `PrismalClient` / `AsyncPrismalClient` as
its two top-level entry points mirrors how `httpx` itself ships both.

---

## 4. Data flow

### 4.1 Streaming chat turn (RF-CSB-002)

```
client.send_message(thread_id, "Hola")
  │
  ├─ POST /threads/{thread_id}/messages   {content, role, metadata}
  │     headers: Authorization? , X-Org-Id?
  ├─ response: text/event-stream
  └─ _sse.iter_events(response) parses frames:
        ": heartbeat\n\n"                      → swallowed (keeps the read alive)
        "event: token\ndata: {...}\n\n"        → TokenEvent
        "event: tool_call\ndata: {...}\n\n"    → ToolCallEvent
        "event: state\ndata: {...}\n\n"        → StateEvent
        "event: done\ndata: {...}\n\n"         → DoneEvent, generator stops
        "event: error\ndata: {...}\n\n"        → raise the mapped PrismalAPIError, generator stops
     (caller breaks the `for`/`async for` early → underlying httpx response is
      closed → server observes a disconnect and cancels its `astream` task,
      SPEC-RHB-CHT-004 on the host side)
```

The SDK's parser is a mirror image of the host's `streaming.py::sse_stream`
— it does not reinterpret the payloads (`delta`, tool `name`/`args`,
`finish_reason`, `{code, message}`), it only gives them a type.

### 4.2 A2A JSON-RPC call (RF-CSB-003)

```
client.agent_card(org_id=None)
  └─ GET /.well-known/agent-card.json  [X-Org-Id?]  → AgentCard (camelCase parsed to snake_case fields)

client.a2a.send(method="message/send", params={...})
  └─ POST /a2a  {"jsonrpc":"2.0","id":...,"method":...,"params":...}
        200 + {"result": ...}      → parsed result (typed where the SPEC fixes a shape, else raw dict)
        200 + {"error": {code,msg}}→ raise A2AJsonRpcError(code, message)

client.a2a.stream(method="message/stream", params={...})
  └─ POST /a2a  → text/event-stream, `data:` lines → yields raw JSON-RPC stream chunks
```

The host never wraps A2A errors in the REST `{"error":{"code","message"}}`
envelope (§4.3 below) — A2A stays JSON-RPC end to end, per
`SPEC-RHB-SDK-002` ("no prismal-specific extension"). The SDK therefore has
two independent error surfaces: `PrismalAPIError` (REST) and
`A2AJsonRpcError` (JSON-RPC), never conflated.

### 4.3 Error mapping (RF-CSB-005)

```
HTTP response, non-2xx, body {"error": {"code": "...", "message": "..."}}
  └─ _transport.raise_for_error_body(response) looks up `code` in a table
     mirroring prismal-server/errors.py::_NAME_MAP:
        runtime_composition_error → RuntimeCompositionError   (503)
        policy_denied             → PolicyDeniedError         (403)
        permission_denied         → PermissionDeniedError     (403)
        budget_exceeded           → BudgetExceededError       (429)
        a2a_agent_unavailable     → A2AAgentUnavailableError  (502)
        validation_error          → ValidationError           (422)
        (unmapped / internal_error) → PrismalAPIError         (>=500, opaque)
  └─ network-level (no response): httpx.TransportError → PrismalConnectionError
                                    httpx.TimeoutException → PrismalTimeoutError
```

Every mapped exception carries `status_code`, `code`, and `message` so a
caller can branch on the stable `code` string without depending on the HTTP
status alone (the same contract the host itself guarantees in
`SPEC-RHB-ERR-001`).

---

## 5. Architecture Decision Records

### ADR-001 — `httpx` for both sync and async transport
**Decision:** Build `PrismalClient` on `httpx.Client` and `AsyncPrismalClient`
on `httpx.AsyncClient`, sharing request/error-mapping logic in
`_transport.py`. **Rationale:** one HTTP stack covers both call styles with
first-class streaming support (`iter_lines`/`aiter_lines`) and typed
timeouts/retries; it's already the de facto standard used server-side by
FastAPI/Starlette, so behavior (timeouts, connection pooling) is familiar to
maintainers of both repos. **Alternatives:** `requests` (no async, no native
SSE ergonomics), `aiohttp` (async-only, would force a second library for the
sync client). **Status:** Accepted.

### ADR-002 — Hand-written SSE parser, no extra dependency
**Decision:** Implement `_sse.py` directly against the exact frame format
`prismal-server/streaming.py` emits (`event: NAME\ndata: JSON\n\n`,
`: heartbeat\n\n`) rather than pulling in a generic SSE client library.
**Rationale:** the wire format is small, fixed, and owned by a sibling repo
in the same organization — a ~40-line parser with its own unit tests is
easier to keep in lockstep with `streaming.py` than a general-purpose
dependency that would parse a superset of the SSE spec we don't need.
**Status:** Accepted. Revisit if the host's framing grows materially more
complex.

### ADR-003 — No dependency on `prismal` or `prismal-server`
**Decision:** The SDK imports nothing from either sibling repo; it is
verified against their **documented wire contract** (`SPEC-RHB-SDK-*`,
`/openapi.json`) via the opt-in `contract` test suite, never against their
source. **Rationale:** this is the same hexagonal-boundary discipline the
engine (`ToolProviderPort`, `VectorStorePort`, …) and host (`CLAUDE.md`
"exactly four seams") already apply; a client that imports its server is not
a client. It also lets the SDK support a Python range wider than the
engine's `>=3.13` pin (ADR-004) and be installed in processes that will
never run the engine at all. **Status:** Accepted.

### ADR-004 — Python `>=3.10`, wider than the engine's `>=3.13`
**Decision:** `requires-python = ">=3.10"`, not pinned to the engine's floor.
**Rationale:** because of ADR-003 the SDK has no code-level coupling to the
engine's runtime requirements; consumers (TUI, dashboard, CI containers,
third-party integrators) should not have to adopt Python 3.13 just to make an
HTTP call. The dev environment still targets 3.13 for consistency with the
rest of the org (`.python-version`), but the package itself is written and
tested to not require newer-than-3.10 syntax. **Status:** Accepted.

### ADR-005 — Sync and async as two classes in one package, not two packages
**Decision:** Ship `PrismalClient` and `AsyncPrismalClient` from the single
`prismal_sdk` distribution, both built over `_transport.py`.
**Rationale:** see §3 above; splitting would duplicate the error-mapping and
model-parsing logic that must stay identical between the two call styles, and
every consumer repo in the ecosystem is expected to need only one of the two
at a time (dashboard/webchat likely async under an ASGI/browser event loop,
TUI/CLI scripts likely sync) without wanting a second install. **Status:**
Accepted.

### ADR-006 — WebSocket support deferred, tracked not built
**Decision:** No WS client in v0.1. **Rationale:** `prismal-server` itself
has not shipped a WS endpoint (its own ADR-002: "SSE first, WS deferred");
building a client against a transport the host doesn't expose yet would be
speculative and untestable end-to-end. **Status:** Accepted; revisit when
`prismal-server` publishes a WS contract (tracked as `CSB-FUTURE-01`).

---

## 6. Error handling

- `_transport.py` centralizes response handling for both clients: a 2xx body
  is parsed into the matching pydantic model; a non-2xx body is passed to
  `raise_for_error_body` (see §4.3); a transport-level failure (DNS, refused
  connection, timeout) is wrapped before it reaches the caller so nothing
  raw from `httpx` leaks into the public API surface.
- Mid-stream failures (`SPEC-RHB-CHT-006`: the host emits a terminal SSE
  `error` event because the HTTP status is already `200`) are raised as the
  same mapped exception type from inside the event generator — a caller
  iterating `for event in client.send_message(...)` sees a normal Python
  exception at the point of failure, not a silently truncated stream.
- A2A JSON-RPC errors never reuse the REST exception hierarchy; they raise
  `A2AJsonRpcError(code, message)` so callers who already speak JSON-RPC
  (e.g. a generic A2A client swapped in later) see the codes they expect
  (`-32001` unauthenticated, `-32000` inbound A2A not composed, per the
  host's `routes/a2a.py`).
- No credential is ever logged or included in an exception message; only the
  stable `code`/`message` from the server response body is surfaced.

---

## 7. Observability

The SDK does not stand up its own telemetry stack (no OTel dependency) — it
is a library, not a service. It exposes hooks a caller can wire into their
own observability: an optional `on_request`/`on_response` callback pair on
`ClientConfig` for logging/tracing, and every raised exception carries enough
structured data (`status_code`, `code`, `message`, `thread_id` where
applicable) to be logged meaningfully by the caller without the SDK
prescribing a logging framework.

---

## 8. Packaging & release (sketch)

`uv`-based, `src` layout, `hatchling` build backend (mirrors `prismal-server`
exactly). Published to PyPI as `prismal-sdk`; import module `prismal_sdk`.
Versioning follows the same `MAJOR.MINOR.PATCH` scheme as the rest of the
org; v0.1.0 targets parity with `prismal-server` v0.1's shipped contract.
Tagging and release workflow are a v0.1 hardening task (`TASKS.md` phase 5),
not built in the M0 seed.

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-10 | Ernesto Crespo | Initial architecture for the client SDK |

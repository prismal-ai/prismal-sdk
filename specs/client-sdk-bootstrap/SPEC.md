# prismal-sdk — Technical Specification (Client SDK Bootstrap)

| Field | Value |
|---|---|
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-10 |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`TASKS.md`](./TASKS.md) |

Requirement IDs are `SPEC-CSB-<AREA>-NNN`. Priority follows RFC 2119
(`MUST`/`SHOULD`/`MAY`). Each maps back to an `RF-CSB-*` in `PLAN.md`. Where a
requirement mirrors a clause fixed by the host, the host's ID is cited
(`SPEC-RHB-*`, from `prismal-server/specs/reference-host-bootstrap/SPEC.md`).

---

## 1. Transport & construction

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-TRN-001 | `PrismalClient(base_url, *, token=None, org_id=None, timeout_s=30, max_retries=2)` and `AsyncPrismalClient(...)` MUST expose an identical constructor signature and public method set. | `MUST` |
| SPEC-CSB-TRN-002 | Both clients MUST also be constructible from a `ClientConfig` (`PrismalClient.from_config(config)`), and `ClientConfig` MUST be loadable from environment variables prefixed `PRISMAL_SDK_` (`BASE_URL`, `TOKEN`, `ORG_ID`, `TIMEOUT_S`, `MAX_RETRIES`). | `MUST` |
| SPEC-CSB-TRN-003 | Both clients MUST be usable as a context manager (`with` / `async with`) that closes the underlying `httpx` transport on exit; they MUST also expose an explicit `close()` / `aclose()`. | `MUST` |
| SPEC-CSB-TRN-004 | The SDK MUST NOT import `prismal` or `prismal_server` at any point (enforced by an AST import-guard test, mirroring the host's `SPEC-RHB-NFR-001`). | `MUST` |
| SPEC-CSB-TRN-005 | `base_url` MUST default to `http://localhost:8000` when unset, matching `prismal-server`'s default bind (`HostSettings.port=8000`). | `SHOULD` |

## 2. Health

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-HLT-001 | `healthz()` MUST `GET /healthz` and return a typed `HealthStatus(status="ok")`, raising the mapped exception on any non-2xx. | `MUST` |
| SPEC-CSB-HLT-002 | `readyz()` MUST `GET /readyz`, returning `ReadyStatus(status="ready")` on `200` or raising `RuntimeCompositionError` (mapped from the body's `reason` code) on `503`, per `SPEC-RHB-HLT-002`. | `MUST` |

## 3. Threads & chat streaming

### 3.1 `create_thread()`

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-THR-001 | `create_thread()` MUST `POST /threads` and return `ThreadCreated(thread_id: str)` (`SPEC-RHB-THR-002`). | `MUST` |
| SPEC-CSB-THR-002 | Callers MUST also be able to skip `create_thread()` and pass a self-chosen `thread_id` directly to `send_message()` — the SDK MUST NOT require minting server-side (`SPEC-RHB-THR-002`, "clients MAY also choose their own"). | `MUST` |

### 3.2 `send_message()` (SSE)

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-CHT-001 | `send_message(thread_id, content, *, role="user", metadata=None)` MUST `POST /threads/{thread_id}/messages` with body `{"content","role","metadata"}` and return an iterator (sync) / async iterator (async) of typed SSE events — never a single blocking response. | `MUST` |
| SPEC-CSB-CHT-002 | The iterator MUST yield `TokenEvent(delta: str)`, `ToolCallEvent(name: str, args: Any)`, `StateEvent(data: dict)`, in the order the server emits them, matching `SPEC-RHB-CHT-002`. | `MUST` |
| SPEC-CSB-CHT-003 | A terminal `DoneEvent(thread_id: str, finish_reason: str)` MUST end iteration normally (`StopIteration`/`StopAsyncIteration`), mirroring `SPEC-RHB-CHT-002`'s `done` event. | `MUST` |
| SPEC-CSB-CHT-004 | A terminal `error` SSE frame MUST be raised as the mapped `PrismalAPIError` subclass **from within** the iterator (not returned as a value), matching `SPEC-RHB-CHT-006` (HTTP status is already `200`). | `MUST` |
| SPEC-CSB-CHT-005 | Heartbeat comment frames (`: heartbeat`) MUST be silently consumed by the parser and never surfaced to the caller. | `MUST` |
| SPEC-CSB-CHT-006 | Breaking out of the iterator early (caller stops consuming) MUST close the underlying HTTP response promptly, so the server observes a disconnect and cancels its `astream` task (`SPEC-RHB-CHT-004` on the host side). | `MUST` |
| SPEC-CSB-CHT-007 | `content` MUST be passed through unmodified as the request body — the SDK MUST NOT inspect, template, or mutate it (it is the caller's trust boundary to manage; the engine's own security layers apply server-side per `SPEC-RHB-CHT-005`). | `MUST` |

## 4. A2A client

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-A2A-001 | `agent_card(*, org_id=None)` MUST `GET /.well-known/agent-card.json` (with `X-Org-Id` if `org_id` given) and return a typed `AgentCard`, tolerating additional server-side fields (`model_config = {"extra": "allow"}`) so the SDK does not break on a forward-compatible card. | `MUST` |
| SPEC-CSB-A2A-002 | `a2a.send(method, params, *, request_id=None)` MUST `POST /a2a` with a JSON-RPC 2.0 envelope and return the parsed `result` on success or raise `A2AJsonRpcError(code, message)` on a JSON-RPC `error` member. | `MUST` |
| SPEC-CSB-A2A-003 | `a2a.stream(method, params, *, request_id=None)` MUST `POST /a2a` with `method="message/stream"` and return an iterator/async iterator over the `data:` lines of the resulting `text/event-stream`, JSON-decoded, matching `SPEC-RHB-A2A-002`. | `MUST` |
| SPEC-CSB-A2A-004 | The SDK MUST implement the standard A2A v0.3.x JSON-RPC methods (`message/send`, `message/stream`, `tasks/get`, `tasks/cancel`) as thin typed wrappers over `a2a.send`/`a2a.stream` — no prismal-specific extension, per `SPEC-RHB-SDK-002`. | `SHOULD` |
| SPEC-CSB-A2A-005 | A `404` response from either A2A route (host's `a2a_enabled=false`, `SPEC-RHB-A2A-005`) MUST raise a distinct `A2ANotEnabledError`, not a generic `PrismalAPIError`. | `MUST` |

## 5. Authentication & tenancy

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-AUT-001 | When `token` is set, every request MUST carry `Authorization: Bearer <token>`; when unset, no `Authorization` header is sent (dev/no-auth mode), per `SPEC-RHB-SDK-003`. | `MUST` |
| SPEC-CSB-AUT-002 | When `org_id` is set, every request MUST carry `X-Org-Id: <org_id>`; the SDK MUST NOT send any other prismal-specific header. | `MUST` |
| SPEC-CSB-AUT-003 | `token` and any static credential in `ClientConfig` MUST be stored as `pydantic.SecretStr` and MUST NOT appear in `repr()`, logs, or exception messages. | `MUST` |
| SPEC-CSB-AUT-004 | A per-call override of `org_id` (e.g. `send_message(..., org_id="acme")`) MUST be supported for callers managing multiple tenants from one client instance. | `SHOULD` |

## 6. Error model

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-ERR-001 | Every REST non-2xx response with body `{"error":{"code","message"}}` MUST raise the exception mapped from `code` (table in `ARCHITECTURE.md` §4.3), mirroring the host's `SPEC-RHB-ERR-001` shape. | `MUST` |
| SPEC-CSB-ERR-002 | An unmapped `code` or a non-JSON error body MUST raise the base `PrismalAPIError` with `status_code` set and `code="internal_error"` if absent, never crash on unexpected shapes. | `MUST` |
| SPEC-CSB-ERR-003 | A network-level failure (no response) MUST raise `PrismalConnectionError`; a timeout MUST raise `PrismalTimeoutError`; both MUST subclass a common `PrismalTransportError`, distinct from `PrismalAPIError`. | `MUST` |
| SPEC-CSB-ERR-004 | All SDK exceptions MUST subclass a single `PrismalSDKError` root so callers can catch broadly with one `except`. | `MUST` |
| SPEC-CSB-ERR-005 | A2A errors (JSON-RPC `error` member) MUST raise `A2AJsonRpcError`, which MUST NOT subclass `PrismalAPIError` (distinct error surface per `ARCHITECTURE.md` §4.2/§6), but MUST subclass `PrismalSDKError`. | `MUST` |

## 7. Resilience

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-RSL-001 | The SDK MUST retry a request up to `max_retries` times, with exponential backoff, **only** for connection errors and `httpx.TimeoutException` on idempotent, non-streaming requests (`GET`, and `POST /threads` which is safe to re-mint). | `SHOULD` |
| SPEC-CSB-RSL-002 | The SDK MUST NOT retry `POST /threads/{id}/messages` or any established SSE stream automatically (re-sending a chat turn is not idempotent); a retry there is the caller's decision. | `MUST` |
| SPEC-CSB-RSL-003 | The SDK MUST NOT retry on any 4xx response (client error, not transient). | `MUST` |
| SPEC-CSB-RSL-004 | `max_retries=0` MUST fully disable retry behavior. | `MUST` |

## 8. Configuration

`ClientConfig` (pydantic-settings, prefix `PRISMAL_SDK_`) governs client
construction only — it has no relationship to `HostSettings` on the server
side beyond sharing naming conventions.

| Key | Env var | Default | Meaning |
|---|---|---|---|
| `base_url` | `PRISMAL_SDK_BASE_URL` | `http://localhost:8000` | Target `prismal-server` |
| `token` | `PRISMAL_SDK_TOKEN` | `None` | Bearer credential (`SecretStr`) |
| `org_id` | `PRISMAL_SDK_ORG_ID` | `None` | Default `X-Org-Id` |
| `timeout_s` | `PRISMAL_SDK_TIMEOUT_S` | `30` | Per-request timeout (connect+read) |
| `max_retries` | `PRISMAL_SDK_MAX_RETRIES` | `2` | Bounded retry count (§7) |

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-CFG-001 | `ClientConfig` MUST validate `base_url` is an absolute `http(s)://` URL at construction time, failing fast. | `MUST` |
| SPEC-CSB-CFG-002 | `token` MUST be `SecretStr`, per `SPEC-CSB-AUT-003`. | `MUST` |

## 9. Non-functional

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CSB-NFR-001 | `PrismalClient` and `AsyncPrismalClient` MUST expose the same method names and parameter shapes (a parity test enumerates both and diffs). | `MUST` |
| SPEC-CSB-NFR-002 | The package MUST declare `requires-python = ">=3.10"` and MUST NOT use syntax unavailable below that floor (ADR-004). | `MUST` |
| SPEC-CSB-NFR-003 | The unit test suite MUST run with no network access (mocked transport); a separate `contract` suite (opt-in marker, deselected by default) exercises a live `prismal-server`. | `MUST` |
| SPEC-CSB-NFR-004 | The package MUST ship a `py.typed` marker and pass `mypy --strict`. | `MUST` |
| SPEC-CSB-NFR-005 | No secret (`token`) may appear in any log line, exception message, or `repr()` produced by the SDK. | `MUST` |

---

## 10. Traceability (RF → SPEC)

| RF | Covered by |
|---|---|
| RF-CSB-001 | SPEC-CSB-TRN-* |
| RF-CSB-002 | SPEC-CSB-THR-*, SPEC-CSB-CHT-* |
| RF-CSB-003 | SPEC-CSB-A2A-* |
| RF-CSB-004 | SPEC-CSB-AUT-* |
| RF-CSB-005 | SPEC-CSB-ERR-* |
| RF-CSB-006 | SPEC-CSB-RSL-* |
| RF-CSB-007 | SPEC-CSB-TRN-004 (import guard), `CLAUDE.md` review checklist |
| RF-CSB-008 | SPEC-CSB-NFR-003 |

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-10 | Ernesto Crespo | Initial technical spec for the client SDK |

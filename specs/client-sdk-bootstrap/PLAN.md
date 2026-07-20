# prismal-sdk — Client SDK (Client SDK Bootstrap)

## Strategic Plan / Product Requirements Document (PLAN)

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo |
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-10 |
| **Phase** | CSB (Client SDK Bootstrap) |
| **Repository** | `prismal-ai/prismal-sdk` (this repo) |
| **Upstream contract** | `prismal-server >= 0.1, < 1` (wire contract fixed by `prismal-server/specs/reference-host-bootstrap/SPEC.md` §9, `SPEC-RHB-SDK-*`) |
| **Reviewers** | Tech Lead, AI Architect |
| **Priority** | P0 (unblocks every front-end repo in the ecosystem) |
| **Related** | `prismal-ai/prismal` (engine, v3.10.1, 21/21 specs); `prismal-ai/prismal-server` (host, v0.1 — reference host bootstrap complete); consumers `prismal-tui`, `prismal-dashboard`, `prismal-webchat`, `prismal-chatbot` (all `PENDING`) |

---

## 1. Executive Summary

`prismal` (the engine) is a pure LangGraph library with no server. `prismal-server`
is the reference host that puts it on the network: it fixed a wire contract —
`POST /threads` + `POST /threads/{id}/messages` (SSE: `token`/`tool_call`/
`state`/`done`/`error`), the standard A2A v0.3.x surface (`GET
/.well-known/agent-card.json`, `POST /a2a`), a single `Authorization: Bearer`
credential plus an optional `X-Org-Id` header, and an `/openapi.json` document —
specifically so that a **thin, business-logic-free client** could be built
against it without waiting for the host's internals to stabilize further.

`prismal-sdk` is that client. It is the last piece blocking every front-end
repo in the `prismal-ai` organization (`prismal-tui`, `prismal-dashboard`,
`prismal-webchat`, `prismal-chatbot`) — none of them can start until there is a
typed, tested way to create a thread, stream a chat turn, and talk A2A over
HTTP. This PLAN scopes the **v0.1** SDK: a Python package (sync + async
clients) that implements exactly the contract `prismal-server` already fixed,
nothing more.

`ARCHITECTURE.md`, `SPEC.md`, and `TASKS.md` in this same folder refine this
PLAN into a buildable, test-first plan.

---

## 2. Context and Problem

- Per the `prismal-ai` ecosystem presentation (2026-07-07, v3.10.1): 8
  repositories total. `prismal` (engine) and `prisma-notebooks` are `LISTO`
  (done). `prismal-server` is `EN DISEÑO` (v0.1 reference-host-bootstrap
  complete: streaming chat, inbound A2A, auth/tenancy, health/readiness,
  release plumbing). `prismal-sdk`, `prismal-tui`, `prismal-dashboard`,
  `prismal-webchat`, and `prismal-chatbot` are all `PENDIENTE`.
- `prismal-server`'s own SDD explicitly carved out the SDK as **not its
  responsibility** (`SPEC.md` §9 "SDK wire contract (for prismal-sdk)" — "This
  repo does not implement the SDK … it fixes the contract the SDK must
  satisfy so the SDK stays business-logic-free"). That contract is now stable
  and version-controlled in a sibling repo; this repo's job is to consume it,
  not to renegotiate it.
- Without an SDK, every consumer (dashboard, TUI, webchat, chatbot, or any
  third-party integrator) has to hand-roll SSE parsing, error-code mapping,
  and A2A JSON-RPC framing from scratch — exactly the duplicated-effort
  problem an SDK exists to prevent.
- The SDK has **zero dependency on the engine**. It never imports `prismal`
  or `prismal_server`; it speaks HTTP/SSE to whatever `prismal-server`
  instance it's pointed at. This is a deliberate architectural boundary (see
  `ARCHITECTURE.md` §1) that keeps the SDK installable in environments that
  never run the engine (browsers via future JS port, thin CLI tools, other
  services) and lets it support a wider Python range than the engine's
  `>=3.13` pin.

---

## 3. Target Users

- **Front-end repo maintainers** — `prismal-tui`, `prismal-dashboard`,
  `prismal-webchat`, `prismal-chatbot` — who need a typed client instead of
  reimplementing SSE parsing and error mapping four times.
- **Application developers** integrating prismal chat/A2A into their own
  Python service or script.
- **A2A ecosystem peers** who want a Python-native way to call a running
  `prismal-server` agent (as an alternative to a generic A2A client).
- **QA / contract testing** — the SDK's own `contract` suite doubles as a
  living smoke test of `prismal-server`'s wire contract.

---

## 4. Goals and Success Metrics

| Goal | Metric | Target |
|---|---|---|
| Typed chat client | `create_thread()` + `send_message()` round-trip a full SSE turn | Works against a local `prismal-server --reload` with zero hand-written SSE parsing in caller code |
| Typed A2A client | Fetch the Agent Card and complete one `message/send` JSON-RPC call | Works against a `prismal-server` with `a2a_enabled=true` |
| Sync + async parity | Every capability exists on both `PrismalClient` and `AsyncPrismalClient` | Mirrored public API, same models/exceptions |
| Zero engine coupling | The SDK never imports `prismal` or `prismal_server` | Enforced by an AST import-guard test (mirrors the host's own) |
| Business-logic-free | The SDK adds no retries beyond transient network errors, no prompt logic, no agent logic | Code review checklist in `CLAUDE.md` |
| Offline-testable | Unit suite runs with no live server | `respx`/`httpx.MockTransport` fakes; a separate opt-in `contract` suite hits a real host |
| Installable via uv | `uv pip install -e ".[dev]"` from a fresh clone | Boots, lints, type-checks, tests green |

---

## 5. Scope

### In scope (v0.1 — the minimal viable client)
- `PrismalClient` (sync, `httpx.Client`) and `AsyncPrismalClient` (async,
  `httpx.AsyncClient`) with a mirrored public surface.
- Health: `healthz()` / `readyz()`.
- Threads/chat: `create_thread()`, `send_message(thread_id, content, ...)`
  streaming typed SSE events (`TokenEvent`, `ToolCallEvent`, `StateEvent`,
  `DoneEvent`, `ErrorEvent`).
- A2A: `agent_card(org_id=None)`, JSON-RPC `message/send` / `tasks/get` /
  `tasks/cancel`, and `message/stream` (SSE) — the standard A2A v0.3.x
  surface, no prismal-specific extension (mirrors `SPEC-RHB-SDK-002`).
- Auth: single `Authorization: Bearer` header (optional in dev) + optional
  `X-Org-Id` header for tenancy — nothing else (mirrors `SPEC-RHB-SDK-003`).
- A typed exception hierarchy mapping the host's stable error codes
  (`runtime_composition_error`, `policy_denied`, `permission_denied`,
  `budget_exceeded`, `a2a_agent_unavailable`, `validation_error`,
  `internal_error`) plus transport-level errors (connection, timeout).
- Configurable timeout and bounded retry/backoff on transient network
  failures only (never on 4xx, never mid-SSE-stream).
- `ClientConfig` / `SDKSettings` (pydantic-settings, `PRISMAL_SDK_` prefix)
  for `base_url`, `token`, `org_id`, `timeout_s`, `max_retries`.
- Unit test suite offline (mocked transport); opt-in `contract` suite against
  a running `prismal-server`.
- `uv`-based dev foundation: `pyproject.toml` (`src` layout), `ruff`, `mypy`
  strict, `pytest` + `pytest-asyncio`, CI workflow.

### Out of scope (deferred)
- **WebSocket transport** — `prismal-server` itself specs WS as `SHOULD` and
  has not shipped it (ADR-002 in that repo: "SSE first, WS deferred"). The
  SDK will not build a WS client against an endpoint that does not exist yet;
  this is a fast-follow once the host ships one (tracked as CSB-FUTURE-01).
- **Code generation from `/openapi.json`** — v0.1 hand-writes typed models
  against the fixed contract (small surface, stable, documented in the
  host's `SPEC.md` §9). Generating a client from the OpenAPI document is a
  possible v0.2 hardening step (`SPEC-RHB-SDK-004` only requires the document
  to exist and be verifiable against, not that the SDK is generated).
  `contract` tests already assert the SDK's hand-written models stay
  consistent with `/openapi.json`.
- **Non-Python language bindings** — a JS/TS SDK for `prismal-webchat` is a
  separate, later effort; this repo is the Python client only.
  distinct from the current 8-repo scope.
- **Any business/agent logic** — retries, caching, prompt construction,
  multi-turn orchestration, or anything beyond typed transport belongs in the
  caller (dashboard/TUI/chatbot) or the engine, never in this SDK.
- **Auth token acquisition** (OAuth/OIDC login flows) — the SDK accepts a
  bearer token; how a caller obtains one (browser OIDC flow, static config,
  secret manager) is out of scope.

---

## 6. Functional Requirements (summary; refined in `SPEC.md`)

| ID | Requirement | Priority |
|---|---|---|
| RF-CSB-001 | Typed sync + async transport layer speaking only HTTP/SSE to `prismal-server`; zero import of `prismal`/`prismal_server` | `MUST` |
| RF-CSB-002 | Thread lifecycle: `create_thread()` + `send_message()` streaming typed SSE events | `MUST` |
| RF-CSB-003 | A2A client: Agent Card fetch + JSON-RPC `message/send`/`tasks/get`/`tasks/cancel`/`message/stream` | `MUST` |
| RF-CSB-004 | Auth: single bearer credential + optional `X-Org-Id`, pluggable credential source | `MUST` |
| RF-CSB-005 | Central error mapping: HTTP/JSON-RPC errors → typed exception hierarchy | `MUST` |
| RF-CSB-006 | Bounded retry/backoff on transient network errors only | `SHOULD` |
| RF-CSB-007 | No business logic — the SDK stays a thin wire-contract client | `MUST` |
| RF-CSB-008 | Offline-testable unit suite + opt-in `contract` suite against a live host | `MUST` |

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| SDK drifts from the host's actual wire contract | Opt-in `contract` suite runs the SDK against a real `prismal-server` in CI; pin a compatible version range and bump deliberately |
| Scope creep — SDK grows business/agent logic | `CLAUDE.md` hard rule + review checklist: transport and typed models only |
| SSE parsing bugs (partial frames, heartbeats, disconnects) | Dedicated `_sse.py` parser with its own unit tests mirroring the host's `streaming.py` framing exactly |
| Sync/async surfaces diverge over time | Both clients generated from the same request-building/error-mapping core (`_transport.py`); a parity test asserts identical public method sets |
| Consumers block on WS that doesn't exist server-side | Explicitly out of scope until `prismal-server` ships it; documented in README and PLAN §5 |
| Breaking the "business-logic-free" principle under feature pressure from a consumer repo | Every new capability must trace to a `SPEC-RHB-SDK-*` clause or a new one negotiated in `prismal-server` first — never added unilaterally here |

---

## 8. Dependencies

- `prismal-server` — the wire contract owner. No build dependency (HTTP
  only), but `contract` tests run against a live instance (local `uvicorn` or
  `docker compose up`, see that repo's `docs/running.md`).
- `httpx` — sync + async HTTP transport (already a transitive dependency in
  the ecosystem via FastAPI/Starlette on the server side; chosen here for
  the same reason ADR-001 in `prismal-server` chose FastAPI: one HTTP
  stack, well-typed, first-class async).
- `pydantic` — typed request/response/event models (mirrors the engine and
  host's own use of pydantic v2).
- Dev-only: `pytest`, `pytest-asyncio`, `respx` (offline httpx mocking),
  `ruff`, `mypy`.
- **Not** a dependency: `prismal-ai` (the engine) or `prismal-server` —
  enforced by the import-guard test (`ARCHITECTURE.md` §1).

---

## 9. Milestones

| Milestone | Content | Exit criterion |
|---|---|---|
| M0 — Seed | This SDD set (`PLAN`/`ARCHITECTURE`/`SPEC`/`TASKS`) + repo `CLAUDE.md` + `uv` scaffold | Reviewed & merged |
| M1 — Transport skeleton | `config.py`, `exceptions.py`, `models.py`, `_transport.py`; `healthz`/`readyz` on both clients | Both clients construct and hit `/healthz` against a local host |
| M2 — Chat client | `create_thread()` + `send_message()` SSE streaming, typed events, `_sse.py` | A full chat turn round-trips end-to-end (unit, mocked) |
| M3 — A2A client | Agent Card fetch + JSON-RPC send/stream | Agent Card parses; `message/send` round-trips against a fake handler |
| M4 — Auth, tenancy, resilience | Bearer + `X-Org-Id` injection, retry/backoff, error mapping complete | Two `org_id`s route correctly; transient failures retry, 4xx don't |
| M5 — Hardening & release | `contract` suite vs a real `prismal-server`, docs, packaging, CI, `v0.1.0` tag | CI green; `uv pip install -e ".[dev]"` from a fresh clone works end to end |

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-10 | Ernesto Crespo | Initial PLAN for the client SDK, derived from `prismal-server`'s `SPEC-RHB-SDK-*` contract and the ecosystem presentation |

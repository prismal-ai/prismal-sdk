# prismal-sdk — Task Breakdown (Client SDK Bootstrap)

| Field | Value |
|---|---|
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-10 |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`SPEC.md`](./SPEC.md) |

Status legend: `TODO` · `WIP` · `DONE` · `BLOCKED`. Every task is **test-first
(TDD)** — write the failing test, watch it fail, minimal code to green. Tasks
map to `SPEC-CSB-*` IDs and the `M0…M5` milestones in `PLAN.md`.

---

## Phase 0 — Repo scaffold (M0/M1 prep)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CSB-00-01 | `pyproject.toml`: `src` layout, `httpx`, `pydantic`, `pydantic-settings`; dev extras `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy` | 0.3 d | — | NFR-002/004 | `DONE` |
| CSB-00-02 | Package skeleton `src/prismal_sdk/__init__.py` (`__version__`), `py.typed`, empty modules per `ARCHITECTURE.md` §3 | 0.2 d | 00-01 | — | `DONE` |
| CSB-00-03 | `tests/conftest.py`: `respx`/`httpx.MockTransport` fixtures for both clients, no network | 0.3 d | 00-02 | NFR-003 | `DONE` |
| CSB-00-04 | Import-guard test: AST scan asserting no `prismal`/`prismal_server` import anywhere in `src/` | 0.2 d | 00-02 | TRN-004 | `DONE` |
| CSB-00-05 | CI (`.github/workflows/ci.yml`): ruff + mypy + pytest (unit); a separate opt-in `contract` job | 0.3 d | 00-01 | NFR-003 | `DONE` |

## Phase 1 — Transport skeleton (M1)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CSB-01-01 | `config.py`: `ClientConfig` (pydantic-settings, `PRISMAL_SDK_` prefix, `SecretStr` token, URL validation) | 0.3 d | 00-02 | CFG-001/002 | `DONE` |
| CSB-01-02 | `exceptions.py`: `PrismalSDKError` root, `PrismalAPIError`/`PrismalTransportError` hierarchies, error-code map | 0.4 d | 00-02 | ERR-001..005 | `DONE` |
| CSB-01-03 | `_transport.py`: shared header injection (bearer + `X-Org-Id`), retry/backoff, response → model/exception dispatch | 0.6 d | 01-01, 01-02 | TRN-001, AUT-001/002, RSL-* | `DONE` |
| CSB-01-04 | `client.py` + `async_client.py`: constructors (`from_config`, context manager, `close`/`aclose`) | 0.4 d | 01-03 | TRN-001/002/003 | `DONE` |
| CSB-01-05 | `healthz()` / `readyz()` on both clients | 0.3 d | 01-04 | HLT-001/002 | `DONE` |

## Phase 2 — Chat client (M2)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CSB-02-01 | `models.py`: `MessageIn`, `ThreadCreated`, `TokenEvent`/`ToolCallEvent`/`StateEvent`/`DoneEvent`/`ErrorEvent` | 0.4 d | 00-02 | CHT-002/003 | `DONE` |
| CSB-02-02 | `_sse.py`: frame parser (`event:`/`data:`/heartbeat) mirroring `prismal-server/streaming.py` exactly, sync + async iterator variants | 0.6 d | 02-01 | CHT-002/005 | `DONE` |
| CSB-02-03 | `create_thread()` on both clients | 0.2 d | 01-04 | THR-001/002 | `DONE` |
| CSB-02-04 | `send_message()` streaming on both clients, raising on terminal `error` frame | 0.7 d | 02-02, 02-03 | CHT-001/004/006/007 | `DONE` |
| CSB-02-05 | Early-break-closes-response test (simulated slow/hanging stream) | 0.3 d | 02-04 | CHT-006 | `DONE` |

## Phase 3 — A2A client (M3)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CSB-03-01 | `models.py`: `AgentCard` (extra="allow"), JSON-RPC request/response envelopes | 0.3 d | 02-01 | A2A-001 | `DONE` |
| CSB-03-02 | `a2a.py`: `agent_card()`, `send()`, `stream()` core + `A2AJsonRpcError` | 0.5 d | 03-01, 01-03 | A2A-001/002/003 | `DONE` |
| CSB-03-03 | Typed method wrappers: `message_send`, `message_stream`, `tasks_get`, `tasks_cancel` | 0.4 d | 03-02 | A2A-004 | `DONE` |
| CSB-03-04 | `404` → `A2ANotEnabledError` on both A2A routes | 0.2 d | 03-02 | A2A-005 | `DONE` |

## Phase 4 — Auth, tenancy, resilience (M4)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CSB-04-01 | Bearer header injection wired end-to-end (all routes); `repr()`/log redaction test | 0.3 d | 01-03 | AUT-001/003 | `DONE` |
| CSB-04-02 | `X-Org-Id` injection + per-call `org_id` override | 0.3 d | 01-03 | AUT-002/004 | `DONE` |
| CSB-04-03 | Retry/backoff for connect/timeout on idempotent requests; no retry on 4xx or established streams | 0.5 d | 01-03 | RSL-001..004 | `DONE` |
| CSB-04-04 | Sync/async parity test: enumerate public methods on both clients, assert identical signatures | 0.3 d | 02-04, 03-03 | NFR-001 | `DONE` |

## Phase 5 — Hardening & release (M5)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CSB-05-01 | `tests/contract/`: opt-in suite against a running `prismal-server` — health, one chat turn, agent card fetch | 0.5 d | all | NFR-003 | `DONE` — closed by CS2-05-01 (2026-11-02, host v0.2.0 fake mode) |
| CSB-05-02 | `examples/`: `quickstart.py`, `streaming_chat.py`, `a2a_agent_card.py`, runnable against local host | 0.3 d | 02-04, 03-03 | — | `DONE` |
| CSB-05-03 | `docs/`: `streaming.md`, `auth.md`, `errors.md` | 0.3 d | all | — | `DONE` |
| CSB-05-04 | `README.md` quickstart + status table; link engine/host repos | 0.3 d | all | — | `DONE` |
| CSB-05-05 | `mypy --strict` clean, `ruff` clean, coverage baseline recorded | 0.3 d | all | NFR-004 | `DONE` |
| CSB-05-06 | Tag `v0.1.0`; release workflow (PyPI optional) | 0.2 d | 05-01, 05-05 | — | `WIP` |

### Phase 5 notes

**CSB-05-01 — closed 2026-11-02 by CS2-05-01.** The v0.2 fake-LLM host needs no provider credentials, and the smoke suite below passes against it. Original note, kept for history: **CSB-05-01 is `BLOCKED`, not deferred.** The suite is written and gates
correctly — with no host on `localhost:8000` it skips all three tests and
exits `0`, so it never fails a build for the wrong reason. It has never run
green because the available `prismal-server` answers `internal_error` on the
chat turn, most likely missing engine/LLM credentials. Unblocking it needs a
properly configured host, which lives outside this repo; nothing in the SDK
can fix it. This is the **only** Definition-of-Done item still open.

**CSB-05-05 baseline: 93.44%** statement+branch coverage (105 unit tests).
`fail_under = 93` in `pyproject.toml` is a ratchet — raise it as coverage
rises, never lower it to turn a red build green. CI enforces it.

**CSB-05-06 update (2026-11-02):** the `v0.1.0` tag *was* pushed on 2026-07-20; the Release run passed every step and failed at `Publish` with `invalid-publisher` (no PyPI pending publisher registered for `prismal-ai/prismal-sdk`, workflow `release.yml`, environment `pypi`). Nothing is on PyPI. Superseded by CS2-05-05 unless 0.1.0 is published on its own. Original note: **CSB-05-06 is `WIP` by design.** `.github/workflows/release.yml` publishes
via `uv build` + `uv publish` on any `v*` tag, using PyPI trusted publishing
(OIDC), and re-runs lint, types, tests and a packaging smoke test before it
will publish. The version is bumped to `0.1.0` and tagged **locally only** —
the tag has not been pushed, so nothing has been published yet. Note the DoD
makes this task depend on `CSB-05-01`: releasing before the contract suite
has ever run green means shipping a client never verified against a live
host. Pushing the tag is a deliberate human decision.

## Future (out of scope for v0.1, tracked only)

| ID | Task | Trigger |
|---|---|---|
| CSB-FUTURE-01 | WebSocket client | Once `prismal-server` ships a WS endpoint (its own ADR-002 fast-follow) |
| CSB-FUTURE-02 | OpenAPI-generated client verification step | If the hand-written surface drifts from `/openapi.json` in practice |
| CSB-FUTURE-03 | JS/TS SDK for `prismal-webchat` | Separate repo, not this one |

---

## Definition of Done (v0.1)

- `uv pip install -e ".[dev]"` works from a fresh clone; `ruff check .` and
  `mypy src` are clean.
- Both `PrismalClient` and `AsyncPrismalClient` create a thread, stream a
  full chat turn (`token`/`tool_call`/`state`/`done`), and surface a
  mid-stream `error` frame as a typed exception — verified offline
  (`respx`/`MockTransport`).
- The A2A client fetches an Agent Card and completes one JSON-RPC
  `message/send` round trip against a fake handler.
- The import-guard test proves zero coupling to `prismal`/`prismal_server`.
- The `contract` suite passes against a locally running `prismal-server`
  (`uvicorn prismal_server.app:app`).
- README + `docs/` explain install, quickstart (sync + async), streaming
  semantics, auth, and the error hierarchy.

## Estimate roll-up

~**7.5 person-days** across M1–M5 (excludes the M0 seed). M1→M2→M3 is the
critical path (transport before chat before A2A); M4 can parallelize after
M1; M5 closes. Phases 0–4 are scaffolded in this bootstrap pass; Phase 5's
contract suite and release tag are left `TODO` for the first real run against
a live `prismal-server`.

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-10 | Ernesto Crespo | Initial task breakdown for the client SDK |
| 1.1 | 2026-11-02 | Ernesto Crespo | CSB-05-01 `DONE` via CS2-05-01; CSB-05-06 note corrected (tag pushed, PyPI publish failed on the missing trusted publisher) |

# prismal-sdk — Plan (Client v0.2: Usage, AG-UI, WebSocket, A2A v1)

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo |
| **Status** | `READY` |
| **Version** | 1.1 |
| **Date** | 2026-10-12 |
| **Target version** | `0.2.0` |
| **Prefix** | `CS2` (requirements `SPEC-CS2-<AREA>-NNN`, tasks `CS2-0x-yy`) |
| **Companion** | [`SPEC.md`](./SPEC.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`TASKS.md`](./TASKS.md) |
| **Depends on** | `prismal-server` 0.2.0 (`specs/host-v0.2-usage-gateways-agui/`) — wire contract only; no code dependency |

---

## 1. Executive summary

`prismal-sdk` v0.1 gives Python callers a sync + async client for health, threads, SSE chat and the
A2A v0.3 surface of `prismal-server`. Its only open Definition-of-Done item is **CSB-05-01** — the
contract suite is `BLOCKED` because the available server answers `internal_error` on chat (missing
LLM credentials) — which also holds back the `v0.1.0` tag (CSB-05-06).

v0.2 follows host v0.2: a typed `Usage` on `DoneEvent`, `usage()` / `budget()` reports, AG-UI 1.0
event models and iterators, an optional WebSocket client (`[ws]` extra), A2A v1.0 methods with
version negotiation from the Agent Card, and a contract suite that runs green against the host's
`host_fake_llm_mode` — closing CSB-05-01 without any provider credentials.

The boundary does not move: the SDK is a wire client. It never imports `prismal` or
`prismal_server` (AST import guard stays), never computes cost or budget status, and mirrors the
server's field names exactly.

## 2. Requirements (RF)

| ID | Requirement | Prio |
|---|---|---|
| RF-CS2-001 | `Usage` model (12 keys of `SPEC-RH2-USG-002`) and `DoneEvent.usage` | `MUST` |
| RF-CS2-002 | `usage()` and `budget()` on both clients, typed reports matching `SPEC-RH2-USE/BUD` | `MUST` |
| RF-CS2-003 | AG-UI event models (`extra="allow"`) + `send_message(..., protocol="ag-ui")` iterators | `MUST` |
| RF-CS2-004 | WebSocket client behind optional extra `[ws]` | `SHOULD` |
| RF-CS2-005 | A2A v1.0: `tasks_list`, version negotiation by card, version-aware wrappers | `MUST` |
| RF-CS2-006 | Contract suite green against server fake-LLM mode (closes CSB-05-01) | `MUST` |
| RF-CS2-007 | Sync/async parity test covers every new method | `MUST` |
| RF-CS2-008 | No engine/host import; Python ≥ 3.10; `mypy --strict` | `MUST` |
| RF-CS2-009 | Admin reads for the dashboard: `decisions_report`, `routing_report`, `audit`, `tenants` | `MUST` |

## 3. Goals & success metrics

| Goal | Metric | Target |
|---|---|---|
| Wire agreement | Shared `usage_wire.json` fixture parses to `Usage` and re-dumps identically | 100 % |
| Backward compatibility | v0.1 unit tests unchanged and green | 100 % |
| Contract coverage | Contract tests against fake-mode host (native, AG-UI, WS, usage, budget, A2A) | ≥ 10 tests, all green |
| Parity | Public method/signature diff between sync and async clients | 0 |
| Footprint | Base install adds no new runtime dependency (`websockets` only in `[ws]`) | 0 new base deps |
| Coverage ratchet | `fail_under` | ≥ 93 % (v0.1 baseline), never lowered |

## 4. Scope

**In:** RF-CS2-001…009, docs (`usage.md`, `agui.md`, `websocket.md`, `a2a-v1.md`), examples, release.
**Out:** JS/TS SDK (CSB-FUTURE-03); OAuth PKCE/device-code flows in the SDK (bearer only); HITL
resume (server has no endpoint in 0.2); AG-UI `RunAgentInput` endpoint (`POST /v1/agui`) — aimed at off-the-shelf AG-UI clients.

## 5. Phases

| Phase | Focus | Est. |
|---|---|---|
| CS2-0 | Verify server 0.2 wire, vendor fixture, `[ws]` extra, CI contract job | 0.9 d |
| CS2-1 | Usage models, `usage()` / `budget()`, admin reports (decisions, routing, audit, tenants) | 2.5 d |
| CS2-2 | AG-UI models + iterators | 1.8 d |
| CS2-3 | WebSocket client | 1.7 d |
| CS2-4 | A2A v1.0 | 1.4 d |
| CS2-5 | Contract suite (closes CSB-05-01), parity, docs, release 0.2.0 | 1.6 d |
| **Total** | | **~9.9 d** |

Critical path: server RH2-06 (fake mode) → CS2-0 → CS2-5-01. CS2-1…4 parallelise after CS2-0.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Server wire changes after SDK release | Contract suite pinned to server image tag; fixture vendored from engine |
| ~~AG-UI 1.0 event names differ from current knowledge~~ — **materialised and closed** at CS2-00-02 (no `INTERRUPT`, `subagentRunId`, `SUBAGENT_ERROR`); SPEC 1.1 amended | Models keyed by `type` string with `extra="allow"`; unknown types parsed as base `AgUiEvent` |
| ~~`websockets` sync API~~ — **closed** at CS2-00-03: floor `websockets>=13.0` | Deferred import behind `[ws]`; one adapter module |
| A2A v1 card has no top-level `protocolVersion` (ADR-PRT-001) — **materialised**, SPEC-CS2-A2A-001 amended | Negotiate from `supportedInterfaces[]`; fall back to the v0.3 card shape |
| Host v0.2 not built yet: on 2026-10-12 only RH2-0/RH2-1 are `DONE` (no `/v1/usage`, AG-UI, WS, A2A v1, fake mode or image) | Phases 1–5 build against the documented wire offline; CS2-00-04 run + CS2-05-01 + tag stay `BLOCKED` until host RH2-06/07-04 |
| Releasing without a green contract run (v0.1 lesson) | `v0.2.0` tag depends on CS2-05-01 green in CI |

## 7. References

Server: `prismal-server/specs/host-v0.2-usage-gateways-agui/`. Engine wire source:
`prismal/specs/protocol-upgrades-2026/` (`SPEC-PRT-USG-001`). SDK v0.1: `specs/client-sdk-bootstrap/`.
AG-UI 1.0 — https://www.copilotkit.ai/blog/ag-ui-1.0 · A2A — https://github.com/a2aproject/A2A/releases

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-10-04 | Ernesto Crespo | Initial plan for client v0.2 |
| 1.1 | 2026-10-12 | Ernesto Crespo | Risks updated after CS2-00 verification; host-readiness risk added |

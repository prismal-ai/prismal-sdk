# prismal-sdk — Task Breakdown (Client v0.2: Usage, AG-UI, WebSocket, A2A v1)

| Field | Value |
|---|---|
| **Status** | `READY` |
| **Version** | 1.5 |
| **Date** | 2026-10-12 |
| **Author** | Ernesto Crespo |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`SPEC.md`](./SPEC.md) |

Status legend: `TODO` · `WIP` · `DONE` · `BLOCKED`. Every task is test-first (TDD). SPEC column
omits the `SPEC-CS2-` prefix.

## Prerequisites — verify before build

`prismal-server` 0.2 SPEC frozen (`SPEC-RH2-*`); server RH2-06 (fake-LLM mode) merged and an image
published for the contract job. Every **[verify]** item (AG-UI 1.0 names, A2A v1 method names,
`websockets` sync API) is closed by a CS2-00 task — all closed on 2026-10-12, see
[`VERIFY-CS2-00.md`](./VERIFY-CS2-00.md).

## Phase 0 — Verify & scaffold

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CS2-00-01 | Confirm host wire (usage keys, `/v1/usage`, `/v1/budget`, AG-UI framing, WS frames); vendor `usage_wire.json` | 0.2 d | server SPEC | USG-001, USE-*, BUD-* | `DONE` |
| CS2-00-02 | Pin AG-UI 1.0 event names and A2A v1 method names from engine `ADR-PRT-001`; amend SPEC 1.1 | 0.2 d | engine PRT0 | AGU-*, A2A-* | `DONE` |
| CS2-00-03 | Choose `websockets` floor with a sync client (`>=13.0`); add `[ws]` extra | 0.2 d | — | WSK-001, NFR-003 | `DONE` |
| CS2-00-04 | CI `contract` job: start `prismal-server:0.2.x` with fake-LLM mode; version `0.2.0.dev0` | 0.3 d | server RH2-06 | CTR-001 | `BLOCKED` (job wired; first run needs host image) |

## Phase 1 — Usage & budget

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CS2-01-01 | `Usage` + `DoneEvent.usage`; fixture round-trip; v0.1-host compatibility | 0.3 d | 00-01 | USG-001/002/003 | `DONE` |
| CS2-01-02 | `UsageTurn`, `UsageReport`, `BudgetAmounts`, `QuotaWindow`, `BudgetReport` | 0.4 d | 01-01 | USE-*, BUD-002 | `DONE` |
| CS2-01-03 | `usage()` + `iter_usage_turns()` on both clients (RFC 3339, naive-datetime guard, cursor) | 0.5 d | 01-02 | USE-001/002 | `DONE` |
| CS2-01-04 | `budget()` on both clients | 0.3 d | 01-02 | BUD-001 | `DONE` |
| CS2-01-05 | Error-map additions (`protocol_not_enabled`, `invalid_window`, `forbidden_tenant`, `tenant_config_invalid`, `cancelled`, `admin_disabled`); `BudgetExceededError` fields (`scope`, `limit`, `consumed`, `usage`) | 0.3 d | 01-01 | ERR-001/002 | `DONE` |
| CS2-01-06 | Admin models: `DecisionShadowReport`, `RoutingSavingsReport`, `AuditPage`, `TenantSummary` (+ rows, `ReportWindow`) | 0.4 d | 00-01 | ADM-001/002 | `DONE` |
| CS2-01-07 | `decisions_report()`, `routing_report()`, `audit()`, `tenants()` on both clients; 404/403 mapping | 0.4 d | 01-06, 01-05 | ADM-001..004 | `DONE` |

## Phase 2 — AG-UI

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CS2-02-01 | `agui.py`: models, `AGUI_EVENT_TYPES`, `parse_agui_event`, `PrismalUsageEvent` | 0.6 d | 00-02 | AGU-002/004 | `DONE` |
| CS2-02-02 | `_sse.py`: data-only frame routing (sync + async) | 0.3 d | 02-01 | AGU-002 | `DONE` |
| CS2-02-03 | `send_message(protocol=)` overloads on both clients; `RunFinished` ends; `RunError` raises; `406`; negotiation header | 0.6 d | 02-02, 01-05 | AGU-001/003/005/006/007 | `DONE` |
| CS2-02-04 | Golden-stream test (12 engine/host streams vendored in `tests/fixtures/agui/`) incl. usage event and unknown types | 0.3 d | 02-03 | AGU-* | `DONE` |

## Phase 3 — WebSocket

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CS2-03-01 | `_ws.py`: `WsSession` / `AsyncWsSession`, deferred import, `WebSocketUnavailableError` | 0.8 d | 00-03 | WSK-001 | `DONE` |
| CS2-03-02 | Frame codec, cancel, close-code → exception mapping, no auto-retry | 0.5 d | 03-01, 02-01 | WSK-002/003/004/005 | `DONE` |
| CS2-03-03 | Tests against an in-process fake WS server | 0.4 d | 03-02 | WSK-* | `DONE` |

## Phase 4 — A2A v1.0

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CS2-04-01 | `_a2a_methods.py` table; `a2a_protocol` kwarg; `negotiated_version()` from `supportedInterfaces[]` | 0.4 d | 00-02 | A2A-001 | `TODO` |
| CS2-04-02 | `tasks_list()` + `TaskListPage` (`""` last page, `page_size` 1..100); `A2AVersionError` on v0.3 | 0.4 d | 04-01 | A2A-003 | `TODO` |
| CS2-04-03 | Version-aware typed wrappers + `A2A-Version: 1.0` header; `agent_card(protocol_version=)` | 0.3 d | 04-01 | A2A-002/004/005 | `TODO` |
| CS2-04-04 | Tests (`respx`): v0.3 and v1 cards, wrappers, `tasks_list` paging | 0.3 d | 04-03 | A2A-* | `TODO` |

## Phase 5 — Contract, parity, release

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| CS2-05-01 | Contract suite vs fake-mode host (all CTR-002 cases) — **closes CSB-05-01** | 0.6 d | 00-04, phases 1–4 | CTR-001/002 | `TODO` |
| CS2-05-02 | Parity test extended to every new method/kwarg | 0.2 d | phases 1–4 | NFR-002 | `TODO` |
| CS2-05-03 | Import guard unchanged; assert `websockets` absent from base deps | 0.1 d | 03-01 | NFR-001/003 | `TODO` |
| CS2-05-04 | Docs `usage.md`, `agui.md`, `websocket.md`, `a2a-v1.md`; examples | 0.5 d | phases 1–4 | — | `TODO` |
| CS2-05-05 | CHANGELOG; tag `v0.2.0` only after 05-01 green in CI (supersedes CSB-05-06) | 0.2 d | 05-01 | — | `TODO` |

## Test inventory & traceability

| SPEC area | Tasks | Tests |
|---|---|---|
| USG-001..003 | 01-01 | `tests/unit/test_usage_model.py`, `tests/unit/test_sse_done_usage.py` |
| USE-001/002, BUD-001/002 | 01-02..04 | `tests/unit/test_usage_budget_{sync,async}.py` |
| ERR-001/002 | 01-05 | `tests/unit/test_error_map_v02.py` |
| ADM-001..003 | 01-06, 01-07 | `tests/unit/test_admin_reports_{sync,async}.py` |
| AGU-001..006 | 02-01..04 | `tests/unit/test_agui_{models,stream}.py` |
| WSK-001..004 | 03-01..03 | `tests/unit/test_ws_{sync,async}.py` |
| A2A-001..004 | 04-01..04 | `tests/unit/test_a2a_v1.py` |
| CTR-001/002 | 00-04, 05-01 | `tests/contract/test_v02_contract.py` (`contract` marker) |
| NFR-001..003 | 05-02, 05-03 | `tests/unit/test_parity.py`, `tests/unit/test_import_guard.py`, `tests/unit/test_packaging.py` |

## Risk register

| Risk | Mitigation |
|---|---|
| Host image not yet published when SDK work starts — **materialised** (2026-10-12: host RH2-02..07 `TODO`) | Phases 1–4 run offline; 00-04 run, 05-01 and 05-05 wait on the image |
| AG-UI / A2A names change after PRT0 | Single tables (`AGUI_EVENT_TYPES`, `_a2a_methods.py`); base-model fallback |
| ~~WS sync client unavailable in chosen library~~ — closed at 00-03 (`websockets.sync.client` since 13.0) | — |

## Definition of Done (v0.2)

- Every MUST in SPEC has ≥ 1 task and ≥ 1 test; coverage ≥ 93 % (ratchet), `mypy --strict`, ruff clean.
- `Usage` parses the shared fixture identically to engine and host.
- Contract suite green against a fake-mode host with zero provider credentials (CSB-05-01 closed).
- Import guard and parity test green; base install has no new dependency.

## Estimate roll-up

CS2-0 0.9 d · CS2-1 2.5 d · CS2-2 1.8 d · CS2-3 1.7 d · CS2-4 1.4 d · CS2-5 1.6 d → **~9.9 person-days**.

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-10-04 | Ernesto Crespo | Initial task breakdown for client v0.2 |
| 1.1 | 2026-10-12 | Ernesto Crespo | Phase 0: 00-01..03 `DONE`, 00-04 `BLOCKED` on host image (see `VERIFY-CS2-00.md`); 01-05/04-0x amended per SPEC 1.1 |
| 1.2 | 2026-10-12 | Ernesto Crespo | 01-01..05 `DONE` (usage, budget, v0.2 error map); coverage ratchet 93 → 95 |
| 1.3 | 2026-10-12 | Ernesto Crespo | 02-01..04 `DONE` (AG-UI); run out of order, before 01-06/07, by the author's approval |
| 1.4 | 2026-10-12 | Ernesto Crespo | 01-06/07 `DONE` (admin reads); phase 1 of TASKS complete |
| 1.5 | 2026-10-12 | Ernesto Crespo | 03-01..03 `DONE` (WebSocket); suite verified on websockets 13.0/py3.10 and 17.2/py3.13 |

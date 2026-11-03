# prismal-sdk — Phase CS2-0 verification record

| Field | Value |
|---|---|
| **Date** | 2026-10-12 |
| **Author** | Ernesto Crespo |
| **Tasks** | CS2-00-01 · CS2-00-02 · CS2-00-03 · CS2-00-04 |
| **Sources** | `prismal-server/specs/host-v0.2-usage-gateways-agui/SPEC.md` (v1.2) · `prismal/docs/adr/ADR-PRT-001-protocol-pins.md` (2026-10-06) · `websockets` docs + install of 13.0 |

Read-only verification against the **documented** wire (CLAUDE.md: never against host/engine
source). Outcome: SPEC/ARCHITECTURE/PLAN bumped to 1.1; no requirement dropped, five amended, three
added (ERR-001, ERR-002, A2A-005).

## CS2-00-01 — Host wire

| Item | Host clause | Matches SDK SPEC 1.0? |
|---|---|---|
| `done.data = {thread_id, finish_reason, usage}`, `usage` may be `null` | RH2-USG-001 | yes |
| 12 usage keys, fixed order | RH2-USG-002 | yes |
| `GET /v1/usage?thread_id=&since=&until=&limit=&cursor=`; `limit` 1–500 | RH2-USE-002 | yes |
| Window totals / `cache_hit_ratio` computed host-side | RH2-USE-003 | yes (SDK never recomputes, USG-003) |
| `GET /v1/budget?thread_id=` field-for-field | RH2-BUD-001/002 | yes |
| AG-UI: `Accept: text/event-stream; profile=ag-ui` or `?protocol=ag-ui`; data-only frames; header `X-Prismal-Stream-Protocol: ag-ui`; `406 protocol_not_enabled` | RH2-AGU-001..003 | yes |
| AG-UI usage as `CUSTOM prismal.usage` before `RUN_FINISHED`; `RUN_ERROR` code = native code | RH2-AGU-004 | yes |
| WS frames, one turn per connection, close codes 1008/4409/4400/1009 | RH2-WSK-001..003 | yes |
| Fake mode script (`echo: `, `/tool`, `/error`, fixed usage), `X-Prismal-Fake-LLM: 1` | RH2-FAK-001..003 | yes |
| Admin routes, 404 when disabled, 403 without scope | RH2-ADM-001..005 | yes |
| Error codes incl. `budget_exceeded` **402** with `scope/limit/consumed`, mid-stream with partial `usage`; host cites `SPEC-CS2-ERR-001` | RH2 §11 | **no** — SDK 1.0 had no ERR-001 and v0.1 documents `BudgetExceededError` as 429. Added ERR-001/002 |

Shared fixture: `tests/fixtures/usage_wire.json` vendored; byte-identical in engine
(`prismal/tests/fixtures/protocols/`) and host (`prismal-server/tests/fixtures/protocols/`).

## CS2-00-02 — Protocol pins (ADR-PRT-001)

| Topic | SDK SPEC 1.0 | Pinned fact | Amended |
|---|---|---|---|
| A2A negotiation | top-level card `protocolVersion` | v1 card has no top-level `protocolVersion`; it is per `supportedInterfaces[]` (`protocolBinding`, `protocolVersion`) | A2A-001 |
| A2A version signal | — | `A2A-Version: <Major.Minor>` header; **absent ⇒ 0.3** | A2A-002 |
| A2A v1 methods | `[verify]` | `SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`, `ListTasks` (v0.3: `message/send`, `message/stream`, `tasks/get`, `tasks/cancel`; no list) | A2A-002 table |
| `ListTasks` result | `next_page_token: str \| None` | `{tasks, nextPageToken, pageSize, totalSize}` all required; last page ⇒ `""`; `pageSize` max 100 | `TaskListPage`, A2A-003 |
| v1 payload shapes | — | `Part` without `kind`, `TASK_STATE_*`, `ROLE_*` | A2A-005 (SDK does not convert) |
| AG-UI version | — | `"1.0"` in `RUN_STARTED.protocolVersion` | `RunStarted` |
| AG-UI interrupt | `Interrupt` event | no `INTERRUPT`; `RUN_FINISHED.outcome = {type: "interrupt", interrupts: [...]}` | removed class; `RunFinished.outcome` |
| AG-UI sub-agents | `subagent_id` | `subagentRunId` (+ `description`, `parent*`); `SUBAGENT_ERROR` exists | `Subagent*` models |
| AG-UI usage | `CUSTOM prismal.usage` only | also native `RUN_FINISHED.usage` / `RUN_ERROR.usage` = `TokenUsage[]` | kept raw on `RunFinished`/`RunError` |
| AG-UI event set | "31 types [verify]" | 31 types listed in ADR §2.3 | `AGUI_EVENT_TYPES` covers all 31 |

## CS2-00-03 — `websockets` floor

Floor **`websockets>=13.0`**: first release with both `websockets.sync.client.connect` and the new
`websockets.asyncio.client.connect`, each taking `additional_headers=`; `ConnectionClosed` carries
`rcvd` (the received close frame, `.code`). Verified by installing exactly 13.0 on Python 3.10
(`requires-python` floor). Lock resolves 17.2 (16.1.1 on 3.10 markers). Added as extra `[ws]` and to
`[dev]`; base `dependencies` unchanged. The risk-register fallback (sync over a private event-loop
thread) is not needed.

## CS2-00-04 — Contract CI job

`ci.yml` `contract` job (dispatch-only, input `server_image`, default
`ghcr.io/prismal-ai/prismal-server:0.2.0`) runs the host as a service container with
`PRISMAL_SERVER_HOST_FAKE_LLM_MODE=true` (+ WS, AG-UI, admin enabled), asserts the
`X-Prismal-Fake-LLM: 1` header before testing (a skip would be a false green), and runs
`pytest -m contract` with `PRISMAL_BASE_URL`. Version bumped to `0.2.0.dev0`.

**`BLOCKED` (run only):** on 2026-10-12 the host has only RH2-0 and RH2-1 `DONE`; fake mode
(RH2-06) and the image (RH2-07-04) do not exist yet. The job is wired; its first green run is
CS2-05-01.

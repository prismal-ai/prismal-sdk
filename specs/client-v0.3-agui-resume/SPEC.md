# prismal-sdk — Technical Specification (Client v0.3: AG-UI run input & interrupt resume)

| Field | Value |
|---|---|
| **Status** | `READY` |
| **Version** | 1.0 |
| **Date** | 2026-11-02 |
| **Author** | Ernesto Crespo |
| **Companion** | [`TASKS.md`](./TASKS.md) |

Requirement IDs are `SPEC-CS3-<AREA>-NNN`; priority per RFC 2119; acceptance in EARS. v0.1
(`SPEC-CSB-*`) and v0.2 (`SPEC-CS2-*`) requirements remain in force unless MODIFIED here.

## 0. Why

`prismal-server` **0.3.0** (2026-11-02, engine `prismal-ai>=3.22.1`) adds AG-UI interrupt resume
(host RH3-02, `prismal-server/specs/host-v0.3-agui-resume/DESIGN.md`, `docs/agui.md`). An
interrupted AG-UI run ends with `RUN_FINISHED.outcome = {"type": "interrupt", "interrupts": [...]}`,
and the only way back is a `RunAgentInput` with `resume` on `POST /v1/agui`. The SDK v0.2 never
calls `POST /v1/agui`, so an SDK user can see an interrupt but cannot answer it.

What else changed in the host 0.3 / engine 3.22 releases, and why it needs no SDK change:

| Host / engine change | SDK impact |
|---|---|
| Per-request OpenTelemetry traces (RH3-01) | None — export is host-side and there is no inbound `traceparent` in this version |
| `decision_ollama_timeout_ms_by_tier` tenant key (H-322) | None — tenant config is operator-authored; admin reads keep unknown keys (`extra="allow"`) |
| Engine graph close at shutdown (H-320/H-3221) | None — process lifecycle only |
| `POST /v1/agui` validates the body after auth (`401` before `422`) | None — codes map by `code` (`SPEC-CS2-ERR-001`) |

### Scope boundary (CLAUDE.md "the one hard rule")

The SDK sends the caller's resume payload verbatim and reads interrupts verbatim. It never maps
a payload to approve/reject, never keeps its own record of pending interrupts (the engine
checkpoint is the only source of truth), and never retries a resume.

## 1. Interrupts and resume entries (`prismal_sdk.agui`)

```python
ResumeStatus = Literal["resolved", "cancelled"]

class AgUiInterrupt(BaseModel):              # extra="allow", camelCase aliases
    id: str                                   # opaque "<engine id>.<checkpoint id>"; never parsed
    reason: str | None = None
    message: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] | None = None

    def resolve(self, payload: Any = None) -> ResumeEntry: ...

class ResumeEntry(BaseModel):                 # camelCase on the wire
    interrupt_id: str                         # min length 1
    status: ResumeStatus | str = "resolved"
    payload: Any = None
    metadata: dict[str, Any] | None = None

    def to_wire(self) -> dict[str, Any]: ... # {"interruptId", "status", "payload"[, "metadata"]}

class RunFinished(AgUiEvent):
    @property
    def is_interrupted(self) -> bool: ...     # outcome.type == "interrupt"
    @property
    def interrupts(self) -> list[AgUiInterrupt]: ...  # [] unless interrupted
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS3-INT-001 | `RunFinished.interrupts` MUST return the `outcome.interrupts[]` entries parsed as `AgUiInterrupt` when `outcome.type == "interrupt"`, and `[]` otherwise (no outcome, `success`, or a malformed list). `is_interrupted` is `True` exactly when `outcome.type == "interrupt"`. | `MUST` |
| SPEC-CS3-INT-002 | Interrupt ids MUST be kept verbatim, including the host's checkpoint suffix; the SDK never splits or validates them. | `MUST` |
| SPEC-CS3-INT-003 | `ResumeEntry.to_wire()` MUST emit `interruptId`, `status` and `payload` (default `null`, as the host expects) and emit `metadata` only when set. `interrupt_id` MUST be non-empty. | `MUST` |
| SPEC-CS3-INT-004 | `AgUiInterrupt.resolve(payload)` MUST return `ResumeEntry(interrupt_id=self.id, status="resolved", payload=payload)`. The SDK MUST NOT interpret payloads. | `MUST` |
| SPEC-CS3-INT-005 | `status="cancelled"` MUST be sent as given. The host 0.3 refuses it (`422 unsupported_resume`); cancel semantics are the engine's to define. | `MUST` |

## 2. `run_agui` — `POST /v1/agui` (`PrismalClient` and `AsyncPrismalClient`)

```python
def run_agui(
    self,
    thread_id: str,
    content: str | None = None,
    *,
    resume: Sequence[ResumeEntry] | None = None,
    run_id: str | None = None,
    org_id: str | None = None,
) -> Iterator[AgUiEvent]: ...          # AsyncIterator[AgUiEvent] on the async client
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS3-RUN-001 | `run_agui` MUST `POST /v1/agui` a full AG-UI 1.0 `RunAgentInput`: `threadId`, `runId`, `messages`, `tools: []`, `context: []`, `state: {}`, `forwardedProps: {}`, plus `resume` when resuming. `runId` is `run_id`, or a fresh `uuid4` hex when `None`. | `MUST` |
| SPEC-CS3-RUN-002 | Exactly one of `content` and a non-empty `resume` MUST be given; otherwise raise `ValueError` before any I/O. | `MUST` |
| SPEC-CS3-RUN-003 | With `content`, `messages` MUST be `[{"id": <uuid4 hex>, "role": "user", "content": content}]` and `resume` absent. With `resume`, `messages` MUST be `[]` and `resume` the entries' `to_wire()` in the caller's order. | `MUST` |
| SPEC-CS3-RUN-004 | The response MUST be handled like `send_message(protocol="ag-ui")` (`SPEC-CS2-AGU-002..005`): data-only frames parsed by `parse_agui_event`; `RunFinished` yielded last; `RUN_ERROR` raises the mapped error; a non-2xx response raises the mapped `PrismalAPIError` before any event. | `MUST` |
| SPEC-CS3-RUN-005 | `POST /v1/agui` MUST NOT be retried — not on connect failure or timeout either (`SPEC-CSB-RSL-002`). A resume is never re-sent by the SDK. | `MUST` |
| SPEC-CS3-RUN-006 | `thread_id` travels in the JSON body verbatim (no path encoding); auth and `X-Org-Id` follow `SPEC-CSB-AUT-*` with the per-call `org_id` override. | `MUST` |

**EARS:** WHEN a run ends with `RunFinished.is_interrupted`, THE SYSTEM SHALL let the caller resume
it with `run_agui(thread_id, resume=[i.resolve(payload) for i in finished.interrupts])`.

**EARS:** WHEN the caller re-sends a resume that the host already consumed, THE SYSTEM SHALL raise
`ResumeConflictError` with `code == "no_pending_interrupt"` before yielding.

## 3. Error map (MODIFIES SPEC-CS2-ERR-001's table)

| Host code | HTTP | Exception |
|---|---|---|
| `no_pending_interrupt` | 409 | `ResumeConflictError` (new, subclass of `PrismalAPIError`) |
| `resume_in_progress` | 409 | `ResumeConflictError` |
| `invalid_resume` | 422 | `ValidationError` |
| `unsupported_resume` | 422 | `ValidationError` |

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS3-ERR-001 | The four codes above MUST map through the single code table (`SPEC-CS2-ERR-001`), by `code`, never by status. | `MUST` |

## 4. Fixture, contract, release

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS3-FIX-001 | The host fixture `fixtures/agui/interrupt-resume.json` MUST be vendored unchanged as `tests/fixtures/agui_resume/interrupt_resume.json` (its own directory: the golden-stream loader globs `tests/fixtures/agui/`) and replayed offline: the body `run_agui` builds equals each run's `input` (modulo generated ids), and every recorded event parses. | `MUST` |
| SPEC-CS3-CTR-001 | (MODIFIES `SPEC-CS2-CTR-001`) The contract suite MUST run in CI against `prismal-server` **0.3.x installed from PyPI** in fake-LLM mode, on every pull request and on dispatch. This replaces the private GHCR image (`CS2-00-04`). | `MUST` |
| SPEC-CS3-CTR-002 | The contract suite MUST cover: `/interrupt` → interrupted `RunFinished` → resume → `resumed:` text → `success`; a retried resume → `no_pending_interrupt`; an unknown id → `invalid_resume`; a `cancelled` entry → `unsupported_resume`; a resume with nothing pending → `no_pending_interrupt`. | `MUST` |
| SPEC-CS3-REL-001 | The package is released as **0.3.0** (0.2.0 was never tagged; its content ships in 0.3.0). Publishing MUST run from `main` through PyPI trusted publishing (OIDC, environment `pypi`, no stored token), MUST skip a version already on PyPI, and MUST tag `v<version>` after a successful upload. | `MUST` |
| SPEC-CS3-NFR-001 | No new dependency; sync/async parity (`SPEC-CSB-NFR-001`) covers `run_agui` by name, kind and default. | `MUST` |

## Changelog

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-11-02 | Ernesto Crespo | Initial: run input, resume, four error codes, PyPI-host contract job, 0.3.0 release |

# prismal-sdk — Technical Specification (Client v0.2: Usage, AG-UI, WebSocket, A2A v1)

| Field | Value |
|---|---|
| **Status** | `READY` |
| **Version** | 1.0 |
| **Date** | 2026-10-04 |
| **Author** | Ernesto Crespo |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`TASKS.md`](./TASKS.md) |

Requirement IDs are `SPEC-CS2-<AREA>-NNN`; priority per RFC 2119; acceptance in EARS. v0.1
requirements (`SPEC-CSB-*`) remain in force unless MODIFIED here. Host clauses are cited as
`SPEC-RH2-*` (`prismal-server/specs/host-v0.2-usage-gateways-agui/SPEC.md`). Field names below are
identical to the host wire — no renaming, no aliases.

---

## 1. Usage model (MODIFIES SPEC-CSB-CHT-003)

```python
CostSource = Literal["gateway", "litellm", "table", "subscription", "none", "mixed"]

class Usage(BaseModel):                       # 12 keys, order = SPEC-RH2-USG-002
    model_config = ConfigDict(extra="allow", frozen=True)
    prompt_tokens: int = 0                    # incl. cache_read + cache_write
    completion_tokens: int = 0                # incl. reasoning
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    cost_source: CostSource | str = "none"    # unknown future values tolerated
    estimated: bool = True
    served_model: str | None = None
    gateway: str | None = None

    @property
    def cache_hit_ratio(self) -> float: ...   # cache_read_tokens / prompt_tokens, 0.0 if prompt == 0

class DoneEvent(BaseModel):
    thread_id: str
    finish_reason: str
    usage: Usage | None = None                # NEW; None when the host sent null or omitted it (v0.1 host)
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-USG-001 | `Usage` MUST declare exactly the 12 fields of `SPEC-RH2-USG-002` with the same names and types; `model_dump()` of the shared fixture MUST equal the fixture. | `MUST` |
| SPEC-CS2-USG-002 | `DoneEvent` MUST be yielded as the final item of a native `send_message()` iteration, then iteration ends; `usage` is `None` when absent or `null`. | `MUST` |
| SPEC-CS2-USG-003 | The SDK MUST NOT compute, re-price or adjust any usage value; `cache_hit_ratio` is the only derived property. | `MUST` |

**EARS:** WHEN a v0.1 host sends `done` without `usage`, THE SYSTEM SHALL yield `DoneEvent(usage=None)` without error.

## 2. Usage & budget reports

```python
class UsageTurn(BaseModel):
    thread_id: str; turn_id: str; finished_at: datetime; finish_reason: str; usage: Usage

class UsageReport(BaseModel):
    org_id: str | None; thread_id: str | None; since: datetime; until: datetime
    totals: Usage; cache_hit_ratio: float; by_model: list[Usage]; turns: list[UsageTurn]
    next_cursor: str | None = None

class BudgetAmounts(BaseModel):
    tokens: int | None = None; cost_usd: float | None = None
    calls: int | None = None; wall_clock_s: float | None = None

class QuotaWindow(BaseModel):
    model_config = ConfigDict(extra="allow")
    gateway: str; window: str; unit: str      # credit|5h|daily|weekly|monthly ; usd|usd_equivalent|requests|tokens
    limit: float | None = None; used: float | None = None; remaining: float | None = None
    resets_at: datetime | None = None; source: str; as_of: datetime   # source: api|ledger

class BudgetReport(BaseModel):
    org_id: str | None; enabled: bool; scope: str        # turn|session|tenant
    status: Literal["within", "soft_exceeded", "hard_exceeded", "disabled", "unknown"] | str
    breached_dimension: str | None = None
    soft_ratio: float | None = None; hard_cap: bool | None = None
    limits: BudgetAmounts | None = None; consumed: BudgetAmounts | None = None
    remaining: BudgetAmounts | None = None
    gateways: list[QuotaWindow] = []; as_of: datetime

# on PrismalClient (sync) and AsyncPrismalClient (async, same signatures)
def usage(self, *, thread_id: str | None = None, since: datetime | None = None,
          until: datetime | None = None, limit: int = 100, cursor: str | None = None,
          org_id: str | None = None) -> UsageReport: ...
def iter_usage_turns(self, *, thread_id: str | None = None, since: datetime | None = None,
                     until: datetime | None = None, page_size: int = 100,
                     org_id: str | None = None) -> Iterator[UsageTurn]: ...   # AsyncIterator on async
def budget(self, *, thread_id: str | None = None, org_id: str | None = None) -> BudgetReport: ...
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-USE-001 | `usage()` MUST `GET /v1/usage` with only non-`None` query params; datetimes serialized RFC 3339 UTC (naive datetimes rejected with `ValueError` before I/O). | `MUST` |
| SPEC-CS2-USE-002 | `iter_usage_turns()` MUST follow `next_cursor` until `None`; it is idempotent `GET` and MAY be retried per SPEC-CSB-RSL-001. | `SHOULD` |
| SPEC-CS2-BUD-001 | `budget()` MUST `GET /v1/budget` and return `BudgetReport`; `status="unknown"` is a valid value, not an error. | `MUST` |
| SPEC-CS2-BUD-002 | Unknown enum values (`status`, `window`, `unit`, `cost_source`) MUST parse as plain strings (forward compatibility). | `MUST` |

## 3. AG-UI streaming

```python
class AgUiEvent(BaseModel):                    # base for all 31 AG-UI 1.0 types [verify names]
    model_config = ConfigDict(extra="allow", alias_generator=to_camel, populate_by_name=True)
    type: str; timestamp: int | None = None; run_id: str | None = None; thread_id: str | None = None

class RunStarted(AgUiEvent): ...
class RunFinished(AgUiEvent): result: Any | None = None
class RunError(AgUiEvent): message: str; code: str | None = None
class TextMessageStart(AgUiEvent): message_id: str; role: str | None = None
class TextMessageContent(AgUiEvent): message_id: str; delta: str
class TextMessageEnd(AgUiEvent): message_id: str
class ToolCallStart(AgUiEvent): tool_call_id: str; tool_call_name: str; parent_message_id: str | None = None
class ToolCallArgs(AgUiEvent): tool_call_id: str; delta: str
class ToolCallEnd(AgUiEvent): tool_call_id: str
class ToolCallResult(AgUiEvent): tool_call_id: str; content: Any; message_id: str | None = None
class StateSnapshot(AgUiEvent): snapshot: dict[str, Any]
class StateDelta(AgUiEvent): delta: list[dict[str, Any]]           # RFC 6902
class SubagentStarted(AgUiEvent): subagent_id: str; name: str | None = None
class SubagentFinished(AgUiEvent): subagent_id: str
class Interrupt(AgUiEvent): ...                                    # payload fields kept via extra
class CustomEvent(AgUiEvent): name: str; value: Any = None
class PrismalUsageEvent(CustomEvent):                              # name == "prismal.usage"
    @property
    def usage(self) -> Usage: ...

AGUI_EVENT_TYPES: Mapping[str, type[AgUiEvent]]                    # type string → model
def parse_agui_event(data: Mapping[str, Any]) -> AgUiEvent: ...   # unknown type ⇒ base AgUiEvent

@overload
def send_message(self, thread_id: str, content: str, *, role: str = "user",
                 metadata: dict[str, Any] | None = None, org_id: str | None = None,
                 protocol: Literal["prismal"] = "prismal") -> Iterator[ChatEvent]: ...
@overload
def send_message(self, thread_id: str, content: str, *, role: str = "user",
                 metadata: dict[str, Any] | None = None, org_id: str | None = None,
                 protocol: Literal["ag-ui"]) -> Iterator[AgUiEvent]: ...
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-AGU-001 | With `protocol="ag-ui"`, the request MUST carry `Accept: text/event-stream; profile=ag-ui` (`SPEC-RH2-AGU-001`); the body is unchanged. | `MUST` |
| SPEC-CS2-AGU-002 | The parser MUST accept data-only frames (no `event:` line), decode JSON, dispatch on `type` via `parse_agui_event`, and keep ignoring heartbeat comments. | `MUST` |
| SPEC-CS2-AGU-003 | `RunFinished` MUST be yielded last and end iteration; a `RunError` MUST raise the `PrismalAPIError` subclass mapped from its `code` (same table as native `error`). | `MUST` |
| SPEC-CS2-AGU-004 | `CUSTOM` events named `prismal.usage` MUST parse as `PrismalUsageEvent` whose `.usage` is a `Usage` (12 keys). | `MUST` |
| SPEC-CS2-AGU-005 | `406 protocol_not_enabled` MUST raise `ProtocolNotEnabledError` before any event is yielded. | `MUST` |
| SPEC-CS2-AGU-006 | Default `protocol="prismal"` MUST behave exactly as v0.1 apart from `DoneEvent.usage`. | `MUST` |

## 4. WebSocket client (extra `[ws]`)

```python
class WsSession:                               # AsyncWsSession mirrors it with async methods
    def send_message(self, content: str, *, role: str = "user", metadata: dict[str, Any] | None = None,
                     protocol: Literal["prismal", "ag-ui"] = "prismal") -> Iterator[ChatEvent | AgUiEvent]: ...
    def cancel(self) -> None: ...
    def close(self) -> None: ...               # also via context manager

def ws(self, thread_id: str, *, org_id: str | None = None) -> WsSession: ...   # on both clients
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-WSK-001 | `ws()` MUST connect to `ws(s)://<base>/ws/threads/{id}` with the same `Authorization` / `X-Org-Id` headers as HTTP; the `websockets` import is deferred and its absence raises `WebSocketUnavailableError` with an install hint. | `SHOULD` |
| SPEC-CS2-WSK-002 | Client frames and server frames MUST follow `SPEC-RH2-WSK-002`; `{"event":<native>,"data":…}` frames parse into the v0.1 event models, `{"event":"agui","data":…}` via `parse_agui_event`; `heartbeat`/`pong` are never yielded. | `SHOULD` |
| SPEC-CS2-WSK-003 | Close codes MUST map to exceptions: `1008` → `AuthenticationError`, `4409` → `TurnInProgressError`, `4400` → `WebSocketProtocolError`, `1009` → `MessageTooLargeError`, `1011` → `PrismalAPIError`; all subclass `PrismalWebSocketError(PrismalTransportError)`. | `SHOULD` |
| SPEC-CS2-WSK-004 | WebSocket turns MUST NOT be retried automatically (SPEC-CSB-RSL-002 applies). | `MUST` |

## 5. A2A v1.0

```python
A2AVersion = Literal["0.3", "1.0"]

class TaskListPage(BaseModel):
    model_config = ConfigDict(extra="allow", alias_generator=to_camel, populate_by_name=True)
    tasks: list[dict[str, Any]]; next_page_token: str | None = None

# constructor kwarg on both clients (parity): a2a_protocol: Literal["auto", "0.3", "1.0"] = "auto"
class A2ANamespace:
    def agent_card(self, *, org_id: str | None = None, protocol_version: A2AVersion | None = None) -> AgentCard: ...
    def negotiated_version(self) -> A2AVersion: ...    # from card protocolVersion; cached per client
    def tasks_list(self, *, context_id: str | None = None, status: str | None = None,
                   page_size: int = 50, page_token: str | None = None,
                   tenant: str | None = None) -> TaskListPage: ...
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-A2A-001 | With `a2a_protocol="auto"`, the SDK MUST read `protocolVersion` from the Agent Card (major `1` ⇒ `"1.0"`, else `"0.3"`) once and cache it. | `MUST` |
| SPEC-CS2-A2A-002 | Typed wrappers (`message_send`, `message_stream`, `tasks_get`, `tasks_cancel`) MUST use the method names of the negotiated version from a single constants table (v1 names pinned from engine `ADR-PRT-001` **[verify]**). | `MUST` |
| SPEC-CS2-A2A-003 | `tasks_list()` against a `"0.3"` peer MUST raise `A2AVersionError` (subclass of `PrismalSDKError`, not of `A2AJsonRpcError`) without sending a request. | `MUST` |
| SPEC-CS2-A2A-004 | `agent_card(protocol_version=…)` MUST send `?protocolVersion=` (`SPEC-RH2-A2A-002`). | `SHOULD` |

## 6. Admin reads (admin-scoped token)

```python
class ReportWindow(BaseModel): since: datetime; until: datetime

class DecisionIntegrationReport(BaseModel):          # SPEC-RH2-ADM-004 row
    model_config = ConfigDict(extra="allow")
    integration: str; mode: str; samples: int; agreement_ratio: float | None
    accepted: int; escalated: int; abstained: int; llm_calls_avoided: int; window: ReportWindow

class DecisionShadowReport(BaseModel):
    org_id: str | None; enabled: bool; window: ReportWindow
    integrations: list[DecisionIntegrationReport]; as_of: datetime

class RoutingPolicyReport(BaseModel):                # SPEC-RH2-ADM-005 row
    model_config = ConfigDict(extra="allow")
    policy: str; decisions: int; decisions_by_tier: dict[str, int]; escalations: int
    escalations_by_reason: dict[str, int]; plan_cache_hits: int; estimated_savings_usd: float
    window: ReportWindow

class RoutingSavingsReport(BaseModel):
    org_id: str | None; enabled: bool; mode: str; window: ReportWindow
    policies: list[RoutingPolicyReport]; as_of: datetime

class AuditEntry(BaseModel):
    seq: int; ts: datetime; event: str; actor: str | None; org_id: str | None
    hash: str; prev_hash: str | None; fields: dict[str, Any]
class AuditChain(BaseModel):
    status: Literal["valid", "broken", "unverified"] | str; checked: int; first_broken_seq: int | None
class AuditPage(BaseModel):
    page: int; page_size: int; total: int | None; entries: list[AuditEntry]; chain: AuditChain
class TenantSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    org_id: str; live: bool; created_at: datetime | None; last_used_at: datetime | None
    gateways: list[str]; a2a_protocol_version: str | None; config_source: str

# on both clients (async variants identical)
def decisions_report(self, *, since: datetime | None = None, until: datetime | None = None,
                     org_id: str | None = None) -> DecisionShadowReport: ...
def routing_report(self, *, since: datetime | None = None, until: datetime | None = None,
                   org_id: str | None = None) -> RoutingSavingsReport: ...
def audit(self, page: int = 1, page_size: int = 50, *, since: datetime | None = None,
          org_id: str | None = None) -> AuditPage: ...
def tenants(self) -> list[TenantSummary]: ...
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-ADM-001 | `decisions_report()` / `routing_report()` MUST `GET /v1/admin/decisions` / `/v1/admin/routing` and return the typed reports; `enabled=false` is a valid result, not an error. | `MUST` |
| SPEC-CS2-ADM-002 | `audit()` MUST `GET /v1/admin/audit?page=&page_size=` and `tenants()` MUST `GET /v1/admin/tenants` (unwrapping `tenants`). | `MUST` |
| SPEC-CS2-ADM-003 | `404` on any admin route MUST raise `AdminDisabledError`; `403` MUST raise `ForbiddenError`; the SDK MUST NOT recompute agreement, savings or chain status. | `MUST` |

**EARS:** WHEN the host reports `"agreement_ratio": null`, THE SYSTEM SHALL expose `None` without error.

## 7. Errors (extends SPEC-CSB-ERR-001 map)

| Host code | Exception (base) |
|---|---|
| `protocol_not_enabled` | `ProtocolNotEnabledError(PrismalAPIError)` |
| `invalid_window` | `InvalidRequestError(PrismalAPIError)` |
| `forbidden_tenant` | `ForbiddenError(PrismalAPIError)` |
| `tenant_config_invalid` | `ServerConfigurationError(PrismalAPIError)` |
| `cancelled` (stream `error`) | `TurnCancelledError(PrismalAPIError)` |
| `admin_disabled` | `AdminDisabledError(PrismalAPIError)` |
| `budget_exceeded` (HTTP 402 or stream `error`) | `BudgetExceededError(PrismalAPIError)` with `.scope`, `.limit`, `.consumed`, `.usage` |

## 8. Contract suite & non-functional

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-CTR-001 | `tests/contract/` MUST run against `prismal-server` 0.2 with `host_fake_llm_mode=true` and assert the `X-Prismal-Fake-LLM: 1` header; it MUST skip (exit 0) when no host is reachable. | `MUST` |
| SPEC-CS2-CTR-002 | It MUST cover: health/ready; native turn (`"echo: …"` tokens, `DoneEvent.usage` equal to `SPEC-RH2-FAK-002`); `/tool` → `ToolCallEvent`; `/error` → mapped exception; AG-UI turn (`RunStarted` … `PrismalUsageEvent` → `RunFinished`); `usage()` contains the turn; `budget()` parses; WS turn (when `[ws]`); Agent Card + A2A v1 `tasks_list` (when A2A enabled); admin `decisions_report`/`routing_report`/`audit`/`tenants` (when `host_admin_enabled`). | `MUST` |
| SPEC-CS2-NFR-001 | The AST import guard (SPEC-CSB-TRN-004) MUST still forbid `prismal` / `prismal_server` imports. | `MUST` |
| SPEC-CS2-NFR-002 | The parity test (SPEC-CSB-NFR-001) MUST include `usage`, `iter_usage_turns`, `budget`, `ws`, `send_message(protocol=…)`, `a2a.tasks_list`, `a2a.negotiated_version`, `decisions_report`, `routing_report`, `audit`, `tenants`. | `MUST` |
| SPEC-CS2-NFR-003 | Python ≥ 3.10, `py.typed`, `mypy --strict`; `websockets` only under `[ws]`. | `MUST` |

**EARS:** WHEN the contract suite runs against a fake-mode host with no provider credentials, THE
SYSTEM SHALL pass every CTR-002 case (closes CSB-05-01).

## 9. Traceability (RF → SPEC)

| RF | Covered by |
|---|---|
| RF-CS2-001 | SPEC-CS2-USG-* |
| RF-CS2-002 | SPEC-CS2-USE-*, SPEC-CS2-BUD-* |
| RF-CS2-003 | SPEC-CS2-AGU-* |
| RF-CS2-004 | SPEC-CS2-WSK-* |
| RF-CS2-005 | SPEC-CS2-A2A-* |
| RF-CS2-006 | SPEC-CS2-CTR-* |
| RF-CS2-007 | SPEC-CS2-NFR-002 |
| RF-CS2-008 | SPEC-CS2-NFR-001/003 |
| RF-CS2-009 | SPEC-CS2-ADM-* |

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-10-04 | Ernesto Crespo | Initial technical spec for client v0.2 |

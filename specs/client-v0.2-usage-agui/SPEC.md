# prismal-sdk — Technical Specification (Client v0.2: Usage, AG-UI, WebSocket, A2A v1)

| Field | Value |
|---|---|
| **Status** | `READY` |
| **Version** | 1.5 |
| **Date** | 2026-10-12 |
| **Author** | Ernesto Crespo |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`TASKS.md`](./TASKS.md) · [`VERIFY-CS2-00.md`](./VERIFY-CS2-00.md) |

Requirement IDs are `SPEC-CS2-<AREA>-NNN`; priority per RFC 2119; acceptance in EARS. v0.1
requirements (`SPEC-CSB-*`) remain in force unless MODIFIED here. Host clauses are cited as
`SPEC-RH2-*` (`prismal-server/specs/host-v0.2-usage-gateways-agui/SPEC.md`). Field names below are
identical to the host wire — no renaming, no aliases.

> **v1.1 (CS2-00-02).** Every protocol name that v1.0 marked **[verify]** is now pinned from engine
> `prismal/docs/adr/ADR-PRT-001-protocol-pins.md` (2026-10-06). Where the ADR contradicted v1.0 the
> text below was amended in place; the full diff is recorded in [`VERIFY-CS2-00.md`](./VERIFY-CS2-00.md).

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
class AgUiEvent(BaseModel):                    # base for all 31 AG-UI 1.0 types (ADR-PRT-001 §2.3)
    model_config = ConfigDict(extra="allow", alias_generator=to_camel, populate_by_name=True)
    type: str; timestamp: int | None = None; run_id: str | None = None; thread_id: str | None = None

# AG-UI 1.0 has no USAGE and no INTERRUPT event (ADR-PRT-001 §2.3):
#   usage     → RUN_FINISHED.usage / RUN_ERROR.usage (TokenUsage[], camelCase, kept raw)
#               and, from prismal, CUSTOM "prismal.usage" (the 12-key wire, below)
#   interrupt → RUN_FINISHED.outcome = {"type": "interrupt", "interrupts": [...]}
class RunStarted(AgUiEvent): protocol_version: str | None = None    # "1.0"
class RunFinished(AgUiEvent):
    result: Any | None = None; outcome: dict[str, Any] | None = None
    usage: list[dict[str, Any]] | None = None
class RunError(AgUiEvent): message: str; code: str | None = None; usage: list[dict[str, Any]] | None = None
class TextMessageStart(AgUiEvent): message_id: str; role: str | None = None
class TextMessageContent(AgUiEvent): message_id: str; delta: str
class TextMessageEnd(AgUiEvent): message_id: str
class ToolCallStart(AgUiEvent): tool_call_id: str; tool_call_name: str; parent_message_id: str | None = None
class ToolCallArgs(AgUiEvent): tool_call_id: str; delta: str
class ToolCallEnd(AgUiEvent): tool_call_id: str
class ToolCallResult(AgUiEvent): tool_call_id: str; content: Any; message_id: str | None = None
class StateSnapshot(AgUiEvent): snapshot: dict[str, Any]
class StateDelta(AgUiEvent): delta: list[dict[str, Any]]           # RFC 6902
class SubagentStarted(AgUiEvent):
    subagent_run_id: str; name: str; description: str | None = None
    parent_subagent_run_id: str | None = None; parent_tool_call_id: str | None = None
    parent_message_id: str | None = None
class SubagentFinished(AgUiEvent): subagent_run_id: str; result: Any | None = None; outcome: Any | None = None
class SubagentError(AgUiEvent): subagent_run_id: str             # remaining fields kept via extra
class CustomEvent(AgUiEvent): name: str; value: Any = None

# The other pinned types (TEXT_MESSAGE_CHUNK, TOOL_CALL_CHUNK, MESSAGES_SNAPSHOT, ACTIVITY_*, RAW,
# STEP_*, REASONING_*) are registered in AGUI_EVENT_TYPES as thin subclasses with no required
# fields beyond `type`; their payload is kept via extra="allow".
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
| SPEC-CS2-AGU-003 | `RunFinished` MUST be yielded last and end iteration; a `RunError` MUST raise the `PrismalAPIError` subclass mapped from its `code` (same table as native `error`; missing `code` ⇒ `internal_error`). The 12-key `usage` handed to that exception (ERR-002) is the run's last `prismal.usage` value, since `RUN_ERROR.usage` is native `TokenUsage[]` and is not converted. | `MUST` |
| SPEC-CS2-AGU-004 | `CUSTOM` events named `prismal.usage` MUST parse as `PrismalUsageEvent` whose `.usage` is a `Usage` (12 keys). | `MUST` |
| SPEC-CS2-AGU-005 | `406 protocol_not_enabled` MUST raise `ProtocolNotEnabledError` before any event is yielded. | `MUST` |
| SPEC-CS2-AGU-006 | Default `protocol="prismal"` MUST behave exactly as v0.1 apart from `DoneEvent.usage`; data-only frames reaching the native path are ignored without decoding. | `MUST` |
| SPEC-CS2-AGU-007 | WHEN `protocol="ag-ui"` gets a 2xx response without `X-Prismal-Stream-Protocol: ag-ui` (`SPEC-RH2-AGU-002`), THE SYSTEM SHALL raise `ProtocolNotEnabledError` before yielding — a host that ignores the profile would otherwise stream native frames that the AG-UI path drops, i.e. a silent empty turn. | `MUST` |

## 4. WebSocket client (extra `[ws]`)

```python
class WsSession:                               # AsyncWsSession mirrors it with async methods
    def connect(self) -> None: ...             # on `with` entry, or lazily on the first turn
    def send_message(self, content: str, *, role: str = "user", metadata: dict[str, Any] | None = None,
                     protocol: Literal["prismal", "ag-ui"] = "prismal") -> Iterator[ChatEvent | AgUiEvent]: ...
    def cancel(self) -> None: ...              # sync: callable from another thread
    def close(self) -> None: ...               # idempotent; also via context manager

def ws(self, thread_id: str, *, org_id: str | None = None) -> WsSession: ...   # on both clients
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-WSK-001 | `ws()` MUST connect to `ws(s)://<base>/ws/threads/{id}` with the same `Authorization` / `X-Org-Id` headers as HTTP; the `websockets` import is deferred and its absence raises `WebSocketUnavailableError` with an install hint. | `SHOULD` |
| SPEC-CS2-WSK-002 | Client frames and server frames MUST follow `SPEC-RH2-WSK-002`; `{"event":<native>,"data":…}` frames parse into the v0.1 event models, `{"event":"agui","data":…}` via `parse_agui_event`; `heartbeat`/`pong` are never yielded. | `SHOULD` |
| SPEC-CS2-WSK-003 | Close codes MUST map to exceptions: `1008` → `WebSocketAuthenticationError`, `4409` → `TurnInProgressError`, `4400` → `WebSocketProtocolError` (also an undecodable server frame), `1009` → `MessageTooLargeError`, `1011` → `WebSocketServerError`, any other code → `PrismalWebSocketError`; all subclass `PrismalWebSocketError(PrismalTransportError)` and carry `close_code`/`reason`. A rejected upgrade is an HTTP response: its error body maps through the ERR-001 table. | `SHOULD` |
| SPEC-CS2-WSK-004 | WebSocket turns MUST NOT be retried automatically (SPEC-CSB-RSL-002 applies). | `MUST` |
| SPEC-CS2-WSK-005 | A session MUST run one turn at a time and keep turns apart: abandoning a turn's iterator before its terminal event MUST send `cancel` (the WS form of SPEC-CSB-CHT-006), and the next `send_message` MUST first drain the abandoned turn up to its `done`/`error`/`RUN_FINISHED`/`RUN_ERROR`; a `break` on the terminal event sends nothing. Each wait for a frame is bounded by the client `timeout_s` (like the SSE read timeout; the host heartbeats) and raises `PrismalTimeoutError`. | `SHOULD` |

## 5. A2A v1.0

```python
A2AVersion = Literal["0.3", "1.0"]

class TaskListPage(BaseModel):                 # ListTasks result: all four keys required (ADR-PRT-001 §2.1)
    model_config = ConfigDict(extra="allow", alias_generator=to_camel, populate_by_name=True)
    tasks: list[dict[str, Any]]
    next_page_token: str                       # "" on the last page — kept verbatim, never mapped to None
    page_size: int; total_size: int

# constructor kwarg on both clients (parity) and ClientConfig (PRISMAL_SDK_A2A_PROTOCOL):
#   a2a_protocol: Literal["auto", "0.3", "1.0"] = "0.3"      # default = v0.1 behaviour (A2A-006)
# on both clients (v0.1 location kept):
def agent_card(self, *, org_id: str | None = None, protocol_version: A2AVersion | None = None) -> AgentCard: ...

class A2ANamespace:                            # client.a2a
    def negotiated_version(self, *, org_id: str | None = None) -> A2AVersion: ...  # A2A-001; cached per tenant
    def tasks_list(self, *, context_id: str | None = None, status: str | None = None,
                   page_size: int = 50, page_token: str | None = None,
                   tenant: str | None = None, history_length: int | None = None,
                   status_timestamp_after: str | None = None, include_artifacts: bool | None = None,
                   request_id: str | int | None = None, org_id: str | None = None) -> TaskListPage: ...

# _a2a_methods.py — the single table (ADR-PRT-001 §2.1)
A2A_METHODS = {
    "0.3": {"message_send": "message/send", "message_stream": "message/stream",
            "tasks_get": "tasks/get", "tasks_cancel": "tasks/cancel"},            # no tasks_list
    "1.0": {"message_send": "SendMessage", "message_stream": "SendStreamingMessage",
            "tasks_get": "GetTask", "tasks_cancel": "CancelTask", "tasks_list": "ListTasks"},
}
```

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-A2A-001 | With `a2a_protocol="auto"`, the SDK MUST fetch the Agent Card once **per effective tenant** (`org_id` or the client default — hosts may pin `a2a_protocol_version` per tenant, `SPEC-RH2-TEN-002`) and cache the result: IF any `supportedInterfaces[]` entry with `protocolBinding == "JSONRPC"` has a `protocolVersion` of major `1`, THEN `"1.0"`; ELSE IF the card has a top-level `protocolVersion` (v0.3 card shape) of major `1`, THEN `"1.0"`; ELSE `"0.3"`. An explicit `"0.3"`/`"1.0"` skips the fetch. | `MUST` |
| SPEC-CS2-A2A-002 | Typed wrappers (`message_send`, `message_stream`, `tasks_get`, `tasks_cancel`, `tasks_list`) MUST use the method names of the negotiated version from `A2A_METHODS`; WHEN the negotiated version is `"1.0"`, every typed-wrapper `POST /a2a` MUST carry `A2A-Version: 1.0` (an absent header means 0.3 to the peer). Raw `send`/`stream` never negotiate: they carry the header only when the client was built with `a2a_protocol="1.0"`. | `MUST` |
| SPEC-CS2-A2A-003 | `tasks_list()` against a `"0.3"` peer MUST raise `A2AVersionError` (subclass of `PrismalSDKError`, not of `A2AJsonRpcError`) without sending a request; `page_size` outside `1..100` (protocol maximum) MUST raise `ValueError` before I/O. | `MUST` |
| SPEC-CS2-A2A-004 | `agent_card(protocol_version=…)` MUST send `?protocolVersion=` (`SPEC-RH2-A2A-002`). | `SHOULD` |
| SPEC-CS2-A2A-005 | v1 payload shapes (`Part` without `kind`, `TASK_STATE_*`, `ROLE_*`) are the caller's to build; the SDK MUST NOT convert v0.3 ⇄ v1 payloads (boundary rule: transport only). | `MUST` |
| SPEC-CS2-A2A-006 | The default `a2a_protocol` MUST be `"0.3"`: v0.1 call sites send exactly the v0.1 requests (no implicit Agent Card round-trip, slash method names, no version header). `"auto"` and `"1.0"` are opt-in. | `MUST` |
| SPEC-CS2-A2A-007 | JSON-RPC calls MUST go to `POST {base_url}/a2a`; interface URLs advertised by an Agent Card MUST NOT be followed, so the bearer token is never sent to a host the caller did not configure. | `MUST` |

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
| SPEC-CS2-ADM-003 | `404` on any admin route MUST raise `AdminDisabledError` and `403` MUST raise `ForbiddenError`, whatever the body (FastAPI `{"detail"}` included; the host's `code`/`message` kept when present); the SDK MUST NOT recompute agreement, savings or chain status. | `MUST` |
| SPEC-CS2-ADM-004 | On admin reads `org_id` MUST be sent as the `org_id` **query** parameter (`SPEC-RH2-ADM-003..005`; `"*"` = all tenants, needs `prismal:admin:global`), never as `X-Org-Id` — that header keeps the client's own tenant (`SPEC-RH2-USE-004` would answer `403 forbidden_tenant` to `X-Org-Id: *`). | `MUST` |

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

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-ERR-001 | Every host code above MUST map to its exception through the single v0.1 code table, for HTTP error bodies, native stream `error` events, AG-UI `RUN_ERROR` and WS `error` frames alike; the class is chosen by `code`, never by HTTP status. | `MUST` |
| SPEC-CS2-ERR-002 | `BudgetExceededError` MUST expose `scope`, `limit`, `consumed` (read verbatim from the `error` object of a `402` body) and `usage` (`Usage` from a mid-stream `error` event's partial usage); each is `None` when the host omits it. v0.1's `429` mapping stays valid — mapping is by code (ERR-001). | `MUST` |

## 8. Contract suite & non-functional

| ID | Requirement | Prio |
|---|---|---|
| SPEC-CS2-CTR-001 | `tests/contract/` MUST run against `prismal-server` 0.2 with `host_fake_llm_mode=true` and assert the `X-Prismal-Fake-LLM: 1` header; the base URL is read from `PRISMAL_BASE_URL` (default `http://localhost:8000`); it MUST skip (exit 0) when no host is reachable. | `MUST` |
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
| RF-CS2-002/003/009 (errors) | SPEC-CS2-ERR-001/002 |

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-10-04 | Ernesto Crespo | Initial technical spec for client v0.2 |
| 1.1 | 2026-10-12 | Ernesto Crespo | CS2-00: pins from ADR-PRT-001 — A2A negotiation via `supportedInterfaces` + `A2A-Version` header, PascalCase v1 methods table, `TaskListPage` (4 required keys, `""` last page), `page_size ≤ 100`, A2A-005; AG-UI without `Interrupt`, `subagentRunId`, `SubagentError`, `RunFinished.outcome/usage`; new ERR-001/002 (cited by `SPEC-RH2` §11); `PRISMAL_BASE_URL` in CTR-001 |
| 1.2 | 2026-10-12 | Ernesto Crespo | CS2-02: AGU-007 (negotiation header check), AGU-003 usage source on `RUN_ERROR`, AGU-006 data-only frames on the native path |
| 1.3 | 2026-10-12 | Ernesto Crespo | CS2-01-06/07: ADM-004 (`org_id` is a query filter on admin routes); ADM-003 maps 404/403 by status whatever the body |
| 1.4 | 2026-10-12 | Ernesto Crespo | CS2-03: WSK-003 names fixed (no `AuthenticationError` existed; `1011` is a WS error, consistent with "all subclass `PrismalWebSocketError`"); new WSK-005 session semantics; `connect()` on sessions |
| 1.5 | 2026-10-12 | Ernesto Crespo | CS2-04: default `a2a_protocol="0.3"` (new A2A-006; `"auto"` by default would add a card GET before every first call and break v0.1 call sites — PLAN §3 backward-compatibility metric); negotiation cached per tenant; raw-call header rule; `tasks_list` takes the remaining ADR `ListTasks` params + `request_id`/`org_id`; new A2A-007 (never follow card URLs) |

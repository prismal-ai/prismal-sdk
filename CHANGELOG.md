# Changelog

All notable changes to `prismal-sdk`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased] — 0.2.0

Targets `prismal-server` 0.2 (`specs/client-v0.2-usage-agui/`). Not tagged
until the contract suite passes against a fake-LLM `prismal-server` 0.2 image
(DD-CS2-008); the version stays `0.2.0.dev0` until then.

Every v0.1 call keeps its behaviour: the new parameters default to the v0.1
behaviour, and the base install adds no dependency.

### Added

- **Usage.** `DoneEvent.usage` is a typed `Usage` (the 12-key wire shared
  with the engine and host; `None` on a v0.1 host) with a
  `cache_hit_ratio` property. `client.usage()`, `client.iter_usage_turns()`
  (lazy pagination) and `client.budget()` read `GET /v1/usage` and
  `GET /v1/budget` → `UsageReport`, `UsageTurn`, `BudgetReport`,
  `BudgetAmounts`, `QuotaWindow`. See `docs/usage.md`.
- **AG-UI 1.0.** `send_message(..., protocol="ag-ui")` yields the 31 AG-UI
  event models of `prismal_sdk.agui` (plus `PrismalUsageEvent`), typed via
  `typing.overload`. `RUN_ERROR` raises the mapped exception, and a host that
  did not negotiate AG-UI raises `ProtocolNotEnabledError` instead of
  returning an empty run. See `docs/agui.md`.
- **WebSocket.** `client.ws(thread_id)` → `WsSession` / `AsyncWsSession`
  with `send_message` (native or AG-UI), `cancel` and `close`. It is optional,
  installed with `pip install 'prismal-sdk[ws]'`, which adds
  `websockets>=13.0`. See `docs/websocket.md`.
- **A2A v1.0.**
  - The `a2a_protocol="0.3" | "1.0" | "auto"` client option
    (`PRISMAL_SDK_A2A_PROTOCOL`) and `client.a2a.negotiated_version()`,
    which reads the Agent Card's `supportedInterfaces` and caches the answer
    per tenant.
  - The typed wrappers use the version's method names and the `A2A-Version`
    header.
  - `client.a2a.tasks_list()` → `TaskListPage`.
  - `agent_card(protocol_version=)` and `AgentCard.supported_interfaces`.

  See `docs/a2a-v1.md`.
- **Admin reads.** `decisions_report()`, `routing_report()`, `audit()` and
  `tenants()` on `GET /v1/admin/*`. See `docs/admin.md`.
- **Errors.**
  - `ProtocolNotEnabledError`, `InvalidRequestError`, `ForbiddenError`,
    `ServerConfigurationError`, `TurnCancelledError` and `AdminDisabledError`.
  - The `PrismalWebSocketError` family, mapped by close code:
    `WebSocketAuthenticationError`, `TurnInProgressError`,
    `WebSocketProtocolError`, `MessageTooLargeError` and
    `WebSocketServerError`.
  - `WebSocketUnavailableError` and `A2AVersionError`.
  - `BudgetExceededError` now has `scope`, `limit`, `consumed` and `usage`.
- The contract suite `tests/contract/test_v02_contract.py` runs against a
  fake-LLM host; `PRISMAL_BASE_URL` selects the host.

### Changed

- Error classes are chosen by the error `code` for every surface: REST
  bodies, SSE `error` frames, AG-UI `RUN_ERROR` and WebSocket `error` frames.
  The exception is the admin routes, which map `404`/`403` by status.
- `BudgetExceededError` also maps the v0.2 host's `402` (v0.1 used `429`).
- SSE frames with only `data:` lines are delivered as event `message`.

### Notes

- `a2a_protocol` defaults to `"0.3"` rather than `"auto"`. With `"auto"`,
  existing A2A code would need an extra card request and could change method
  names.
- The SDK never follows URLs advertised in an Agent Card, so the bearer token
  only goes to the configured base URL.

## [0.1.0] — 2026-07-20

First release (`specs/client-sdk-bootstrap/`). Tagged; not yet on PyPI.

### Added

- `PrismalClient` (sync) and `AsyncPrismalClient` (async) over `httpx`, with
  matching methods (enforced by a parity test).
- `healthz()`, `readyz()`, `create_thread()`, and `send_message()` streaming
  typed SSE events: `TokenEvent`, `ToolCallEvent`, `StateEvent` and
  `DoneEvent`. A terminal `error` frame raises from inside the iterator.
- A2A v0.3: `agent_card()`, `client.a2a.send()` / `stream()` and the
  `message_send` / `message_stream` / `tasks_get` / `tasks_cancel` wrappers.
  JSON-RPC errors raise `A2AJsonRpcError`.
- `Authorization: Bearer` and `X-Org-Id` auth; `ClientConfig` reads the
  `PRISMAL_SDK_*` environment variables.
- The `PrismalAPIError` hierarchy, plus `PrismalConnectionError` and
  `PrismalTimeoutError`.
- Bounded retry, only for connect and timeout failures on idempotent
  requests.
- `py.typed`, `mypy --strict`, and an import guard: the SDK never imports
  `prismal` or `prismal_server`.

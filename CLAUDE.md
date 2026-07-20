# CLAUDE.md — prismal-sdk

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this repo is

`prismal-sdk` is the **Python client** for [`prismal-server`](https://github.com/prismal-ai/prismal-server):
a thin, typed wrapper over its REST + SSE chat contract and its standard A2A
v0.3.x JSON-RPC surface. It ships two mirrored clients, `PrismalClient`
(sync) and `AsyncPrismalClient` (async), both over `httpx`.

The full design lives in
[`specs/client-sdk-bootstrap/`](./specs/client-sdk-bootstrap/) (`PLAN.md` ·
`ARCHITECTURE.md` · `SPEC.md` · `TASKS.md`). Read those before implementing.

## The one hard rule — a client, not a co-host

> **contract → `prismal-server` (`SPEC-RHB-SDK-*` in that repo's `SPEC.md`);
> transport, typing, ergonomics → this SDK. No agent, RAG, tool, or business
> logic lives here.**

This SDK imports **nothing** from `prismal` (the engine) or `prismal_server`
(the host). It is verified against their **documented wire contract**, never
against their source:

| Surface | Wire contract owner |
|---|---|
| Chat (`POST /threads`, `POST /threads/{id}/messages` SSE) | `prismal-server/specs/reference-host-bootstrap/SPEC.md` §3 |
| A2A (`GET /.well-known/agent-card.json`, `POST /a2a`) | same, §4, standard A2A v0.3.x |
| Auth (`Authorization: Bearer`, `X-Org-Id`) | same, §5/§6, §9 (SDK contract) |

Adding a dependency on `prismal-ai` or `prismal-server`, embedding a local
copy of engine/host logic, or growing the SDK beyond typed transport
(caching, prompt construction, multi-turn orchestration, retries beyond
transient network errors) is a bug.

## Review checklist (enforce on every PR)

- [ ] No import of `prismal` or `prismal_server` anywhere in `src/` — the
      AST import-guard test (`tests/unit/test_import_guard.py`) must stay
      green.
- [ ] `PrismalClient` and `AsyncPrismalClient` expose the same public method
      names and parameter shapes (parity test).
- [ ] New capability traces to a `SPEC-CSB-*` requirement — if the wire
      contract needs to change, that change is negotiated in
      `prismal-server` first, not invented here.
- [ ] No secret (`token`) ever appears in a log line, exception message, or
      `repr()`.
- [ ] Streaming errors (`SPEC-RHB-CHT-006`) raise from inside the event
      iterator; they are never silently swallowed.
- [ ] No retry on 4xx or on an established SSE/A2A stream — only bounded
      retry on connect/timeout for idempotent requests.
- [ ] New behaviour is **test-first** (TDD): failing test → minimal code →
      green.
- [ ] Unit tests run fully offline (`respx`/`httpx.MockTransport`); anything
      touching a live server goes in the opt-in `tests/contract/` suite.
- [ ] `mypy --strict` and `ruff check .` are clean; `py.typed` ships.

## Common commands

```bash
uv pip install -e ".[dev]"
uv run pytest                      # unit (no network)
uv run pytest -m contract          # opt-in: against a running prismal-server
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Boundary examples

- Need to know if a chat turn finished? **No new import** — the `done` SSE
  event already carries `finish_reason`; parse it in `_sse.py`, don't reach
  for engine internals.
- Need richer A2A error context? **No** — `A2AJsonRpcError` carries exactly
  what the JSON-RPC `error` member has; do not guess at engine-side causes.
- Want to cache thread state client-side? **No** — that's application logic
  for the caller (dashboard/TUI/chatbot), not this SDK.
- Want to add a WebSocket client? **Not yet** — `prismal-server` hasn't
  shipped a WS endpoint; see `CSB-FUTURE-01` in `TASKS.md`.

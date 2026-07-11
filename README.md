# prismal-sdk

Typed Python client for [`prismal-server`](https://github.com/prismal-ai/prismal-server)
— the reference host for the [`prismal`](https://github.com/prismal-ai/prismal)
agent engine. `prismal-sdk` speaks only the wire contract the host already
fixed (REST + SSE chat, standard A2A v0.3.x JSON-RPC): it is a thin,
business-logic-free client, not a second copy of the engine.

## Status

**Bootstrap (v0.1.0.dev0).** The transport, chat streaming, and A2A client
are implemented and unit-tested offline against the documented wire contract.
The opt-in `contract` suite (against a live `prismal-server`) and the
`v0.1.0` release tag are the two items still open — see
[`specs/client-sdk-bootstrap/TASKS.md`](./specs/client-sdk-bootstrap/TASKS.md).
The full SDD lives under
[`specs/client-sdk-bootstrap/`](./specs/client-sdk-bootstrap/)
([`PLAN`](./specs/client-sdk-bootstrap/PLAN.md) ·
[`ARCHITECTURE`](./specs/client-sdk-bootstrap/ARCHITECTURE.md) ·
[`SPEC`](./specs/client-sdk-bootstrap/SPEC.md) ·
[`TASKS`](./specs/client-sdk-bootstrap/TASKS.md)).

## Why this exists

`prismal` is a pure agent engine (no server). `prismal-server` puts it on the
network and fixed a wire contract specifically so a client could be built
against it independently (`prismal-server/specs/reference-host-bootstrap/SPEC.md`
§9, "SDK wire contract"). `prismal-sdk` is that client — and the last piece
blocking every front-end repo in the `prismal-ai` organization
(`prismal-tui`, `prismal-dashboard`, `prismal-webchat`, `prismal-chatbot`),
none of which can start until there is a typed, tested way to create a
thread, stream a chat turn, and talk A2A over HTTP.

## Install

```bash
uv add prismal-sdk          # once published
# or, from a clone:
uv pip install -e ".[dev]"
```

Requires Python **3.10+** — deliberately wider than the engine's `>=3.13`
floor, because the SDK has zero import-time dependency on `prismal` or
`prismal_server` (see `ARCHITECTURE.md` ADR-003/004).

## Quickstart

```python
from prismal_sdk import PrismalClient

with PrismalClient("http://localhost:8000") as client:
    print(client.healthz())                       # HealthStatus(status='ok')

    thread = client.create_thread()
    for event in client.send_message(thread.thread_id, "Hello, prismal!"):
        print(type(event).__name__, event)
```

Async:

```python
import asyncio
from prismal_sdk import AsyncPrismalClient

async def main():
    async with AsyncPrismalClient("http://localhost:8000") as client:
        thread = await client.create_thread()
        async for event in client.send_message(thread.thread_id, "Hello!"):
            print(event)

asyncio.run(main())
```

A2A:

```python
with PrismalClient("http://localhost:8000") as client:
    card = client.agent_card()
    result = client.a2a.message_send({"message": {"role": "user", "parts": [{"text": "Hi"}]}})
```

More in [`examples/`](./examples/): `quickstart.py`, `streaming_chat.py`,
`a2a_agent_card.py`.

## What's in the box

| Capability | Sync | Async |
|---|---|---|
| Health / readiness | `PrismalClient.healthz()` / `.readyz()` | `AsyncPrismalClient.healthz()` / `.readyz()` |
| Threads & chat streaming | `.create_thread()` / `.send_message()` | same, `async`/`await` + `async for` |
| A2A (Agent Card + JSON-RPC) | `.agent_card()` / `.a2a.send()` / `.a2a.stream()` | same |
| Typed exceptions | `PrismalAPIError` hierarchy + `A2AJsonRpcError` | shared with sync |
| Auth | `Authorization: Bearer` + optional `X-Org-Id` | shared with sync |
| Retry/backoff | bounded, transient network errors only | shared with sync |

See [`docs/streaming.md`](./docs/streaming.md), [`docs/auth.md`](./docs/auth.md),
and [`docs/errors.md`](./docs/errors.md) for the details.

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest                      # unit suite (no network)
uv run pytest -m contract          # opt-in: against a running prismal-server
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

The unit suite runs fully offline against `httpx.MockTransport` fakes; the
`contract` suite (deselected by default) round-trips against a real
`prismal-server` — start one locally first:

```bash
# in a prismal-server checkout
uv pip install -e ".[dev]"
uvicorn prismal_server.app:app --reload
```

## The contract with the host

This SDK imports **nothing** from `prismal` or `prismal_server` — an AST
import-guard test enforces it (`tests/unit/test_import_guard.py`), and the
rule + review checklist live in [`CLAUDE.md`](./CLAUDE.md). It is verified
against `prismal-server`'s documented wire contract, never against its
source:

- `POST /threads` → `{thread_id}`, `POST /threads/{id}/messages` → SSE
  (`token`/`tool_call`/`state`/`done`/`error`).
- `GET /.well-known/agent-card.json`, `POST /a2a` — standard A2A v0.3.x
  JSON-RPC/SSE.
- `Authorization: Bearer` (+ optional `X-Org-Id`) — the only two
  prismal-specific headers.
- `GET /openapi.json` — available for verifying the SDK's hand-written
  models stay in sync with the host.

## Related repos

- [`prismal-ai/prismal`](https://github.com/prismal-ai/prismal) — the engine (v3.10.1, 21/21 specs).
- [`prismal-ai/prismal-server`](https://github.com/prismal-ai/prismal-server) — the reference host this SDK talks to (v0.1 — reference host bootstrap complete).
- [`prismal-ai/prisma-notebooks`](https://github.com/prismal-ai/prisma-notebooks) — example notebooks against the engine directly (not this SDK).

## License

See [`LICENSE`](./LICENSE).

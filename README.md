# prismal-sdk

Typed Python client for [`prismal-server`](https://github.com/prismal-ai/prismal-server)
— the reference host for the [`prismal`](https://github.com/prismal-ai/prismal)
agent engine. `prismal-sdk` speaks only the wire contract the host already
fixed (REST + SSE chat, AG-UI, WebSocket, usage/budget reads, standard A2A
v0.3 and v1.0 JSON-RPC): it is a thin,
business-logic-free client, not a second copy of the engine.

## Status

**v0.3.0** — targets `prismal-server` 0.3. On top of v0.1 (threads, SSE chat,
A2A v0.3), it adds per-turn **usage** and the usage/budget reads, **AG-UI
1.0** streaming and **interrupt resume** (`run_agui`), **WebSocket** sessions
with cancellation, **A2A v1.0** (negotiation, `ListTasks`) and the **admin**
reports. Unit-tested offline against the documented wire contract (≈ 640
tests, 98% branch coverage), and the `contract` suite runs in CI on every pull
request against `prismal-server` from PyPI in fake-LLM mode. See
[`CHANGELOG.md`](./CHANGELOG.md).

```bash
pip install prismal-sdk          # or: pip install 'prismal-sdk[ws]' for client.ws()
```

SDDs: v0.3 in [`specs/client-v0.3-agui-resume/`](./specs/client-v0.3-agui-resume/)
([`SPEC`](./specs/client-v0.3-agui-resume/SPEC.md) ·
[`TASKS`](./specs/client-v0.3-agui-resume/TASKS.md)); v0.2 in
[`specs/client-v0.2-usage-agui/`](./specs/client-v0.2-usage-agui/)
([`PLAN`](./specs/client-v0.2-usage-agui/PLAN.md) ·
[`ARCHITECTURE`](./specs/client-v0.2-usage-agui/ARCHITECTURE.md) ·
[`SPEC`](./specs/client-v0.2-usage-agui/SPEC.md) ·
[`TASKS`](./specs/client-v0.2-usage-agui/TASKS.md)); v0.1 in
[`specs/client-sdk-bootstrap/`](./specs/client-sdk-bootstrap/).

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
uv add 'prismal-sdk[ws]'    # + the WebSocket client (adds `websockets`)
# or, from a clone:
uv pip install -e ".[dev]"
```

The base install depends on `httpx` and `pydantic` only; `websockets` comes
with the `[ws]` extra and is imported only when you open a WebSocket session.

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

Usage, AG-UI and WebSocket (v0.2):

```python
with PrismalClient("http://localhost:8000") as client:
    thread = client.create_thread()
    for event in client.send_message(thread.thread_id, "Hola"):
        if isinstance(event, DoneEvent) and event.usage:
            print(event.usage.total_tokens, event.usage.cost_usd)

    for event in client.send_message(thread.thread_id, "Hola", protocol="ag-ui"):
        print(event.type)                         # RUN_STARTED … RUN_FINISHED

    print(client.budget().status)                 # within / soft_exceeded / …

    with client.ws(thread.thread_id) as session:  # needs prismal-sdk[ws]
        for event in session.send_message("¿Seguimos?"):
            ...
```

AG-UI interrupt resume (v0.3, host ≥ 0.3):

```python
with PrismalClient("http://localhost:8000") as client:
    thread_id = client.create_thread().thread_id
    events = list(client.run_agui(thread_id, "Deploy the release"))
    finished = events[-1]                         # RunFinished
    if finished.is_interrupted:
        answers = [i.resolve({"action": "approve"}) for i in finished.interrupts]
        events = list(client.run_agui(thread_id, resume=answers))
```

More in [`examples/`](./examples/): `quickstart.py`, `streaming_chat.py`,
`a2a_agent_card.py`, `usage_and_budget.py`, `agui_stream.py`,
`agui_resume.py`, `websocket_chat.py`, `a2a_v1_tasks.py`, `admin_reports.py`.

## What's in the box

| Capability | Sync | Async |
|---|---|---|
| Health / readiness | `PrismalClient.healthz()` / `.readyz()` | `AsyncPrismalClient.healthz()` / `.readyz()` |
| Threads & chat streaming | `.create_thread()` / `.send_message()` | same, `async`/`await` + `async for` |
| A2A (Agent Card + JSON-RPC) | `.agent_card()` / `.a2a.send()` / `.a2a.stream()` | same |
| Per-turn usage (v0.2) | `DoneEvent.usage` / `PrismalUsageEvent` | same |
| Usage & budget reads (v0.2) | `.usage()` / `.iter_usage_turns()` / `.budget()` | same |
| AG-UI 1.0 streaming (v0.2) | `.send_message(..., protocol="ag-ui")` | same |
| AG-UI run input & interrupt resume (v0.3) | `.run_agui(thread_id, content)` / `.run_agui(thread_id, resume=[...])` | same, `async for` |
| WebSocket sessions (v0.2, `[ws]`) | `.ws(thread_id)` → `send_message` / `cancel` | same, `async with` |
| A2A v1.0 (v0.2) | `a2a_protocol=` · `.a2a.negotiated_version()` · `.a2a.tasks_list()` | same |
| Admin reads (v0.2) | `.decisions_report()` / `.routing_report()` / `.audit()` / `.tenants()` | same |
| Typed exceptions | `PrismalAPIError` hierarchy + `PrismalWebSocketError` + `A2AJsonRpcError` | shared with sync |
| Auth | `Authorization: Bearer` + optional `X-Org-Id` | shared with sync |
| Retry/backoff | bounded, transient network errors only | shared with sync |

See [`docs/`](./docs/) for the details:
[`streaming`](./docs/streaming.md) · [`agui`](./docs/agui.md) ·
[`websocket`](./docs/websocket.md) · [`usage`](./docs/usage.md) ·
[`a2a-v1`](./docs/a2a-v1.md) · [`admin`](./docs/admin.md) ·
[`auth`](./docs/auth.md) · [`errors`](./docs/errors.md).

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest                      # unit suite (no network)
uv run pytest -m contract          # opt-in: against a running prismal-server
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

The unit suite runs fully offline against `httpx.MockTransport` fakes and an
in-process WebSocket server; the `contract` suite (deselected by default)
round-trips against a real `prismal-server` and skips when none answers.
The v0.2 and v0.3 parts (`tests/contract/test_v0{2,3}_contract.py`) need a
0.3 host in **fake-LLM mode** — deterministic answers, no provider
credentials. The published wheel is enough (it needs Python 3.13, so keep it
in its own venv):

```bash
uv venv --python 3.13 /tmp/host && uv pip install --python /tmp/host/bin/python 'prismal-server>=0.3,<0.4'
PRISMAL_SERVER_HOST_FAKE_LLM_MODE=true PRISMAL_SERVER_HOST_WS_ENABLED=true \
PRISMAL_SERVER_HOST_AGUI_ENABLED=true PRISMAL_AGUI_EVENTS_ENABLED=true \
PRISMAL_SERVER_HOST_ADMIN_ENABLED=true /tmp/host/bin/uvicorn prismal_server.app:app

# here (the WebSocket turn needs the [ws] extra)
PRISMAL_BASE_URL=http://localhost:8000 uv run --extra ws pytest -m contract
```

Two cases skip by design against a fake-mode host: `tasks_list` (fake mode
composes no inbound A2A handler) and the admin `200` bodies (set
`PRISMAL_ADMIN_TOKEN` to a token holding `prismal:admin`; without it the
suite checks that each admin read raises `ForbiddenError`).

CI runs the same suite on every pull request (job `contract`): it installs
`prismal-server` from PyPI and starts it exactly like this. Dispatch the `CI`
workflow with `server_version` to pin another host version.

## Releasing

Releases ship from `main` (`.github/workflows/release.yml`). Set the final
version in `pyproject.toml` **and** `src/prismal_sdk/__init__.py`, update
`CHANGELOG.md`, and merge `develop` into `main`. The workflow publishes to
PyPI with trusted publishing when that version is not on PyPI yet, then tags
`v<version>` and creates the GitHub release; a `.devN` version or an
already-published one ends green without uploading.

One-time PyPI setup (maintainer account): add a trusted publisher — a
*pending* publisher until the project exists — at
<https://pypi.org/manage/account/publishing/> with project `prismal-sdk`,
owner `prismal-ai`, repository `prismal-sdk`, workflow `release.yml`,
environment `pypi`.

## The contract with the host

This SDK imports **nothing** from `prismal` or `prismal_server` — an AST
import-guard test enforces it (`tests/unit/test_import_guard.py`), and the
rule + review checklist live in [`CLAUDE.md`](./CLAUDE.md). It is verified
against `prismal-server`'s documented wire contract, never against its
source:

- `POST /threads` → `{thread_id}`, `POST /threads/{id}/messages` → SSE
  (`token`/`tool_call`/`state`/`done`/`error`).
- `GET /.well-known/agent-card.json`, `POST /a2a` — standard A2A v0.3.x
  and v1.0 JSON-RPC/SSE (`A2A-Version` header).
- v0.2: `GET /v1/usage`, `GET /v1/budget`, `GET /v1/admin/*`,
  `GET /ws/threads/{id}` (WebSocket), and AG-UI on the chat route via
  `Accept: text/event-stream; profile=ag-ui`.
- v0.3: `POST /v1/agui` (AG-UI `RunAgentInput`, including `resume`).
- `Authorization: Bearer` (+ optional `X-Org-Id`) — the only two
  prismal-specific headers.
- `GET /openapi.json` — available for verifying the SDK's hand-written
  models stay in sync with the host.

## Related repos

- [`prismal-ai/prismal`](https://github.com/prismal-ai/prismal) — the engine (tested through host 0.3, engine 3.22.1).
- [`prismal-ai/prismal-server`](https://github.com/prismal-ai/prismal-server) — the reference host this SDK talks to (0.3.0 on PyPI).
- [`prismal-ai/prisma-notebooks`](https://github.com/prismal-ai/prisma-notebooks) — example notebooks against the engine directly (not this SDK).

## License

See [`LICENSE`](./LICENSE).

# A2A v1.0

`prismal-server` 0.2 speaks A2A **v0.3** and **v1.0** side by side. The SDK
can talk either, choosing per client:

```python
PrismalClient(url, a2a_protocol="0.3")    # default — exactly the v0.1 SDK behaviour
PrismalClient(url, a2a_protocol="1.0")    # always v1
PrismalClient(url, a2a_protocol="auto")   # read the Agent Card, then decide
```

(`ClientConfig` reads it from `PRISMAL_SDK_A2A_PROTOCOL`.)

**Why `"0.3"` and not `"auto"` by default:** `"auto"` costs an extra
`GET /.well-known/agent-card.json` before the first call to each tenant, and
would switch method names under existing v0.1 code. Opt in when you want it
(`SPEC-CS2-A2A-006`).

## Negotiation (`"auto"`)

`client.a2a.negotiated_version(org_id=...)` returns `"0.3"` or `"1.0"`:

- A v1 card lists `supportedInterfaces`; the SDK picks v1 when the
  `JSONRPC` binding (the one `POST /a2a` speaks) has a `1.x`
  `protocolVersion`.
- A v0.3 card has a top-level `protocolVersion` instead; anything else means
  0.3.
- The answer is cached **per tenant** — a host can pin
  `a2a_protocol_version` per tenant, so one client may speak 0.3 to one org
  and 1.0 to another. A fixed `a2a_protocol` never does I/O.

The SDK reads the card only to choose a version. It **never follows the URLs
the card advertises**: every call still goes to the client's own base URL,
so a card cannot redirect your bearer token to another host
(`SPEC-CS2-A2A-007`).

`client.agent_card(protocol_version="1.0")` asks the host for a specific
stack's card (`?protocolVersion=`); `card.supported_interfaces` holds the
parsed `AgentInterface` entries.

## Typed wrappers

The wrappers use the negotiated version's method name and, on v1, send the
`A2A-Version: 1.0` header:

| Wrapper | v0.3 method | v1.0 method |
|---|---|---|
| `a2a.message_send(params)` | `message/send` | `SendMessage` |
| `a2a.message_stream(params)` | `message/stream` | `SendStreamingMessage` |
| `a2a.tasks_get(params)` | `tasks/get` | `GetTask` |
| `a2a.tasks_cancel(params)` | `tasks/cancel` | `CancelTask` |
| `a2a.tasks_list(...)` | — | `ListTasks` |

**Payloads are not converted.** v1 changed message and task shapes (e.g.
`TASK_STATE_*` enums); building the right `params` for the version you speak
is your job — `negotiated_version()` tells you which. Results come back as
the peer sent them.

The raw `a2a.send(method, params)` / `a2a.stream(...)` never negotiate: they
add `A2A-Version: 1.0` only when the client was built with
`a2a_protocol="1.0"`.

## Listing tasks

```python
with PrismalClient(url, a2a_protocol="1.0") as client:
    token = None
    while True:
        page = client.a2a.tasks_list(context_id="ctx-1", page_size=50, page_token=token)
        for task in page.tasks:            # raw v1 task dicts
            print(task["id"], task["status"]["state"])
        if page.next_page_token == "":     # "" marks the last page
            break
        token = page.next_page_token
```

`TaskListPage` has `tasks`, `next_page_token`, `page_size` and `total_size`,
all required by the protocol. Other filters: `status`, `tenant`,
`history_length`, `status_timestamp_after`, `include_artifacts`.

`tasks_list` raises before sending anything when it cannot succeed:
`A2AVersionError` against a 0.3 peer, `ValueError` for a `page_size` outside
`1..100`.

## Errors

JSON-RPC errors stay `A2AJsonRpcError` (integer `code`), as in v0.1; a v1
peer that rejects the version answers `-32009`
(`A2A_VERSION_NOT_SUPPORTED`). `A2AVersionError` is the SDK's own,
pre-flight refusal. `A2ANotEnabledError` still means the host has A2A off.

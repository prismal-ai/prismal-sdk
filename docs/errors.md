# Error hierarchy

Every exception the SDK raises subclasses `PrismalSDKError` — catch that for
a blanket handler, or something more specific for targeted recovery.

```
PrismalSDKError
├── PrismalAPIError                  # REST: {"error": {"code","message"}}
│   ├── RuntimeCompositionError      # 503 — default runtime not ready
│   ├── PolicyDeniedError            # 403
│   ├── PermissionDeniedError        # 403
│   ├── BudgetExceededError          # 429
│   ├── A2AAgentUnavailableError     # 502
│   ├── ValidationError              # 422
│   └── A2ANotEnabledError           # 404 on the two A2A routes
├── PrismalTransportError            # no response was ever received
│   ├── PrismalConnectionError       # DNS / refused / reset
│   └── PrismalTimeoutError          # connect or read timeout
└── A2AJsonRpcError                  # JSON-RPC `error` member from POST /a2a
```

## Why `A2AJsonRpcError` is not a `PrismalAPIError`

`prismal-server` never wraps A2A errors in the REST `{"error": {...}}`
envelope — A2A stays JSON-RPC end to end (`SPEC-RHB-SDK-002`, "no
prismal-specific extension"), so a JSON-RPC failure carries an integer
`code` and a `message`, not the REST error's string `code`. Catch it
separately:

```python
from prismal_sdk.exceptions import A2AJsonRpcError, PrismalAPIError

try:
    result = client.a2a.message_send({...})
except A2AJsonRpcError as exc:
    ...  # exc.code is an int, e.g. -32001 (unauthenticated)
except PrismalAPIError as exc:
    ...  # exc.code is a str, e.g. "a2a_agent_unavailable"
```

## Every `PrismalAPIError` carries

- `status_code: int` — the HTTP status.
- `code: str` — the stable code from the response body; branch on this, not
  the status alone, since e.g. both `PolicyDeniedError` and
  `PermissionDeniedError` are `403`.
- `message: str` — a human-readable message (never a secret, never a raw
  traceback — the server keeps `500` bodies opaque by design).

## Mid-stream errors

A chat turn's terminal `error` SSE frame and any REST failure raise the
*same* exception types — see [`streaming.md`](./streaming.md) for how that
interacts with iterating `send_message()`.

## Retries

Only `PrismalConnectionError`/`PrismalTimeoutError` on idempotent requests
(`GET`, `POST /threads`) are retried automatically, with bounded exponential
backoff (`max_retries`, default `2`). A `PrismalAPIError` (any 4xx/5xx with a
body) is never retried automatically — set `max_retries=0` to disable
retrying altogether.

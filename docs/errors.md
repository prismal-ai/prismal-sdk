# Error hierarchy

Every exception the SDK raises subclasses `PrismalSDKError` — catch that for
a blanket handler, or something more specific for targeted recovery.

```
PrismalSDKError
├── PrismalAPIError                  # REST: {"error": {"code","message"}}
│   ├── RuntimeCompositionError      # 503 — default runtime not ready
│   ├── PolicyDeniedError            # 403
│   ├── PermissionDeniedError        # 403
│   ├── BudgetExceededError          # 402 (v0.2 host) / 429 (v0.1), or a stream error
│   ├── A2AAgentUnavailableError     # 502
│   ├── ValidationError              # 422
│   ├── A2ANotEnabledError           # 404 on the two A2A routes
│   ├── ProtocolNotEnabledError      # 406 — AG-UI disabled (v0.2)
│   ├── InvalidRequestError          # 400 invalid_window (v0.2)
│   ├── ForbiddenError               # 403 forbidden_tenant (v0.2)
│   ├── ServerConfigurationError     # 500 tenant_config_invalid (v0.2)
│   ├── TurnCancelledError           # stream error `cancelled` (v0.2)
│   └── AdminDisabledError           # 404 on /v1/admin/* (v0.2)
├── PrismalTransportError            # no response was ever received
│   ├── PrismalConnectionError       # DNS / refused / reset
│   ├── PrismalTimeoutError          # connect or read timeout
│   └── PrismalWebSocketError        # a WS session ended abnormally (v0.2)
│       ├── WebSocketAuthenticationError   # close 1008
│       ├── MessageTooLargeError           # close 1009
│       ├── WebSocketServerError           # close 1011
│       ├── WebSocketProtocolError         # close 4400 / undecodable frame
│       └── TurnInProgressError            # close 4409
├── WebSocketUnavailableError        # client.ws() without the [ws] extra (also ImportError)
├── A2AJsonRpcError                  # JSON-RPC `error` member from POST /a2a
└── A2AVersionError                  # A2A call needs another version than the peer speaks (v0.2)
```

The class is chosen by the body's `code`, never by the HTTP status alone, so
a REST error, a native `error` frame, an AG-UI `RUN_ERROR` and a WebSocket
`error` frame with the same code raise the same class. Unknown codes raise
the base `PrismalAPIError`. The admin routes are the exception: they map
`404`/`403` by status (see [`admin.md`](./admin.md)).

`BudgetExceededError` also carries the host's `scope`, `limit`, `consumed`
and, when a running turn was stopped, the partial `usage` (see
[`usage.md`](./usage.md)).

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

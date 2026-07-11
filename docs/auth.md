# Authentication & tenancy

The SDK sends exactly one credential header and one tenancy header — nothing
else — matching `prismal-server`'s own contract
(`SPEC-RHB-SDK-003`: "the SDK must not need any other prismal-specific header
beyond optional `X-Org-Id`").

```
Authorization: Bearer <token>     (sent only if `token` is set)
X-Org-Id: <org_id>                (sent only if `org_id` is set)
```

## Setting credentials

```python
from prismal_sdk import PrismalClient

client = PrismalClient(
    "https://prismal.example.com",
    token="s3cr3t",     # or leave unset for a `none`-auth (dev) server
    org_id="acme",       # optional; per-call override also available
)
```

Or via environment variables (`PRISMAL_SDK_` prefix), through
`ClientConfig`:

```bash
export PRISMAL_SDK_BASE_URL=https://prismal.example.com
export PRISMAL_SDK_TOKEN=s3cr3t
export PRISMAL_SDK_ORG_ID=acme
```

```python
from prismal_sdk import ClientConfig, PrismalClient

client = PrismalClient.from_config(ClientConfig())
```

## Per-call tenancy override

A single client instance can address multiple tenants:

```python
client.send_message(thread_id, "hi", org_id="other-org")
client.agent_card(org_id="other-org")
```

## What the SDK does *not* do

- It does not perform an OAuth/OIDC login flow — `token` acquisition is the
  caller's responsibility (browser flow, secret manager, static config).
- It never logs, reprs, or includes `token` in an exception message
  (`SPEC-CSB-NFR-005`) — it is stored as `pydantic.SecretStr` in
  `ClientConfig`.
- It does not enforce auth itself — a `none`-auth dev server accepts
  requests with no `Authorization` header at all; a strict server rejects
  them with a mapped `401`/`-32001`, which the SDK surfaces as the usual
  typed exception.

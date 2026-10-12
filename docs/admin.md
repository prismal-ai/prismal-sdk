# Admin reads

Read-only operator reports from `prismal-server` 0.2. They are **off by
default** on the host (`host_admin_enabled=false`) and need a token holding
the host's admin scope (default `prismal:admin`).

| Method | Route | Returns |
|---|---|---|
| `decisions_report(since=, until=, org_id=)` | `GET /v1/admin/decisions` | `DecisionShadowReport` — shadow-mode agreement per decision integration |
| `routing_report(since=, until=, org_id=)` | `GET /v1/admin/routing` | `RoutingSavingsReport` — decisions by tier, escalations, estimated savings |
| `audit(page=1, page_size=50, since=, org_id=)` | `GET /v1/admin/audit` | `AuditPage` — one 1-based page of the hash-chained audit log |
| `tenants()` | `GET /v1/admin/tenants` | `list[TenantSummary]` — no secret values |

```python
from datetime import datetime, timedelta, timezone

with PrismalClient(url, token=admin_token) as client:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    for row in client.routing_report(since=since).policies:
        print(row.policy, row.decisions, row.estimated_savings_usd)

    page = client.audit(page=1, page_size=100)
    print(page.chain.status)          # the engine's verification, not re-checked here
    for entry in page.entries:
        print(entry.seq, entry.event, entry.actor)
```

- **`org_id` is a report filter here**, sent as a query parameter
  (`"*"` = every tenant, which needs `prismal:admin:global`). The client's
  `X-Org-Id` is unchanged (`SPEC-CS2-ADM-004`). The host defaults to the last
  7 days.
- Values are the host's, verbatim: the SDK never recomputes ratios, savings
  or the audit chain. A feature that is off is a result (`enabled=False`,
  empty rows), not an error.
- Datetimes must be timezone-aware.

## Errors

These routes map by **status**, whatever the body: `404` raises
`AdminDisabledError` (admin routes off) and `403` raises `ForbiddenError`
(missing scope, or a tenant you may not read).

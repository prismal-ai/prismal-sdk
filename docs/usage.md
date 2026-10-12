# Usage & budget

Since v0.2 every chat turn reports what it cost, and two read-only endpoints
expose the history and the budget. The SDK **never computes** these numbers:
tokens, costs and totals are the host's values, taken verbatim
(`SPEC-CS2-USG-003`).

## Per-turn usage

`DoneEvent.usage` carries the turn's 12-key usage (`None` on a v0.1 host, or
when the host had no summary for the turn):

```python
for event in client.send_message(thread_id, "Hola"):
    if isinstance(event, DoneEvent) and event.usage:
        u = event.usage
        print(u.total_tokens, u.cost_usd, u.cost_source, u.served_model)
```

| Field | Type | Notes |
|---|---|---|
| `prompt_tokens` / `completion_tokens` | `int` | |
| `cache_read_tokens` / `cache_write_tokens` | `int` | prompt-cache traffic |
| `reasoning_tokens` | `int` | |
| `total_tokens` | `int` | |
| `calls` | `int` | LLM calls in the turn |
| `cost_usd` | `float` | |
| `cost_source` | `str` | `gateway` · `litellm` · `table` · `subscription` · `none` · `mixed` (unknown values kept as plain strings) |
| `estimated` | `bool` | `True` when any part of the cost is an estimate |
| `served_model` / `gateway` | `str \| None` | who actually answered |

`Usage` is frozen and keeps unknown keys (`extra="allow"`), so a newer host
does not break an older SDK. `usage.cache_hit_ratio` (a property, never
serialised) is the only derived value: `cache_read_tokens / prompt_tokens`.

The same object appears in AG-UI streams as `PrismalUsageEvent.value` (see
[`agui.md`](./agui.md)) and on `BudgetExceededError.usage` when a budget stops
a turn mid-way.

## Usage history — `usage()` / `iter_usage_turns()`

`GET /v1/usage` — the caller's org only; the host defaults to the last 24 h.

```python
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
report = client.usage(since=now - timedelta(days=7), until=now, limit=100)
print(report.totals.cost_usd, report.cache_hit_ratio)
for row in report.by_model:
    print(row.served_model, row.total_tokens)

# Every turn in the window, one page at a time, lazily:
for turn in client.iter_usage_turns(thread_id=thread_id, page_size=200):
    print(turn.turn_id, turn.finish_reason, turn.usage.cost_usd)
```

- Datetimes **must be timezone-aware** (a naive one raises `ValueError`
  before any I/O); they go out as RFC 3339 UTC.
- `totals`, `by_model` and `cache_hit_ratio` cover the **whole window**, not
  the page; `next_cursor` is `None` on the last page.
- A window the host rejects raises `InvalidRequestError`
  (`invalid_window`, `400`); the host accepts `limit` in `1..500`.
- `org_id=` picks the tenant through `X-Org-Id`, as on every other call; a
  tenant your identity may not read raises `ForbiddenError`.

## Budget — `budget()`

`GET /v1/budget` — the engine's budget status, field for field:

```python
b = client.budget()                      # or budget(thread_id=...)
print(b.status)                          # within · soft_exceeded · hard_exceeded · disabled · unknown
if b.limits and b.consumed:
    print(b.consumed.cost_usd, "/", b.limits.cost_usd)   # 0 on limits = unlimited
for q in b.gateways:                     # gateway quota windows, when known
    print(q.gateway, q.window, q.remaining, q.resets_at)
```

`status="unknown"` is a valid answer (the host could not ask the engine), not
an error.

## When the budget runs out

The host answers `402` before a turn starts, or ends a running stream with an
`error` event; both raise `BudgetExceededError` with the host's details:

```python
from prismal_sdk import BudgetExceededError

try:
    for event in client.send_message(thread_id, "..."):
        ...
except BudgetExceededError as exc:
    print(exc.scope, exc.limit, exc.consumed)
    if exc.usage:                         # what the partial turn consumed
        print(exc.usage.total_tokens)
```

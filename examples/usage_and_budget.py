"""Per-turn usage, the usage history and the budget (prismal-server 0.2).

Run against a local prismal-server; fake mode needs no LLM credentials:

    PRISMAL_SERVER_HOST_FAKE_LLM_MODE=true uvicorn prismal_server.app:app
    python examples/usage_and_budget.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from prismal_sdk import BudgetExceededError, DoneEvent, PrismalClient


def main() -> None:
    with PrismalClient("http://localhost:8000") as client:
        thread = client.create_thread()
        try:
            for event in client.send_message(thread.thread_id, "Hola"):
                if isinstance(event, DoneEvent) and event.usage is not None:
                    u = event.usage
                    print(
                        f"turn: {u.total_tokens} tokens, ${u.cost_usd:.6f} "
                        f"({u.cost_source}, model={u.served_model})"
                    )
        except BudgetExceededError as exc:
            print(f"budget exceeded ({exc.scope}): {exc.consumed} of {exc.limit}")

        since = datetime.now(timezone.utc) - timedelta(days=1)
        report = client.usage(since=since)
        print(
            f"last 24h: {report.totals.total_tokens} tokens, "
            f"${report.totals.cost_usd:.4f}, cache hit {report.cache_hit_ratio:.0%}"
        )
        for turn in client.iter_usage_turns(thread_id=thread.thread_id):
            print(f"  {turn.turn_id} {turn.finish_reason} {turn.usage.total_tokens}")

        budget = client.budget()
        print(f"budget: {budget.status} (scope={budget.scope})")


if __name__ == "__main__":
    main()

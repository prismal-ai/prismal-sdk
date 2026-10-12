"""Admin reads: routing savings, audit log, tenants (prismal-server 0.2).

Needs ``host_admin_enabled=true`` and a token with the host's admin scope:

    PRISMAL_SDK_TOKEN=... python examples/admin_reports.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from prismal_sdk import AdminDisabledError, ClientConfig, ForbiddenError, PrismalClient


def main() -> None:
    with PrismalClient.from_config(ClientConfig()) as client:
        try:
            tenants = client.tenants()
        except AdminDisabledError:
            print("admin routes are disabled on this host")
            return
        except ForbiddenError:
            print("this token lacks the admin scope")
            return
        for tenant in tenants:
            print(f"tenant {tenant.org_id} live={tenant.live}")

        since = datetime.now(timezone.utc) - timedelta(days=7)
        routing = client.routing_report(since=since)
        for policy in routing.policies:
            print(f"{policy.policy}: ${policy.estimated_savings_usd:.2f} saved")

        page = client.audit(page=1, page_size=20)
        print(f"audit chain: {page.chain.status}")
        for entry in page.entries:
            print(f"  #{entry.seq} {entry.event}")


if __name__ == "__main__":
    main()

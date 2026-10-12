"""A2A v1.0: negotiate the version, then page through ListTasks.

Run against a local prismal-server with A2A enabled:

    python examples/a2a_v1_tasks.py
"""

from __future__ import annotations

from prismal_sdk import A2ANotEnabledError, A2AVersionError, PrismalClient


def main() -> None:
    with PrismalClient("http://localhost:8000", a2a_protocol="auto") as client:
        try:
            version = client.a2a.negotiated_version()
        except A2ANotEnabledError:
            print("A2A is not enabled on this host")
            return
        print(f"peer speaks A2A {version}")

        token: str | None = None
        try:
            while True:
                page = client.a2a.tasks_list(page_size=20, page_token=token)
                for task in page.tasks:
                    print(task["id"], task["status"]["state"])
                if page.next_page_token == "":
                    break
                token = page.next_page_token
        except A2AVersionError as exc:
            print(exc)  # a 0.3 peer has no ListTasks


if __name__ == "__main__":
    main()

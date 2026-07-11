"""Quickstart — create a thread and send one message, synchronously.

Run against a local prismal-server:

    uvicorn prismal_server.app:app --reload   # in a prismal-server checkout
    python examples/quickstart.py
"""

from __future__ import annotations

from prismal_sdk import PrismalClient


def main() -> None:
    with PrismalClient("http://localhost:8000") as client:
        print(client.healthz())

        thread = client.create_thread()
        print(f"thread_id={thread.thread_id}")

        for event in client.send_message(thread.thread_id, "Hello, prismal!"):
            print(type(event).__name__, event)


if __name__ == "__main__":
    main()

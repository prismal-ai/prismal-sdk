"""Fetch the A2A Agent Card and make one JSON-RPC `message/send` call.

Run against a local prismal-server with A2A enabled:

    PRISMAL_SERVER_A2A_ENABLED=true uvicorn prismal_server.app:app --reload
    python examples/a2a_agent_card.py
"""

from __future__ import annotations

from prismal_sdk import PrismalClient
from prismal_sdk.exceptions import A2AJsonRpcError, A2ANotEnabledError


def main() -> None:
    with PrismalClient("http://localhost:8000") as client:
        try:
            card = client.agent_card()
        except A2ANotEnabledError:
            print("A2A is not enabled on this prismal-server instance.")
            return

        print(f"Agent card: {card.name!r} (protocol {card.protocol_version})")

        try:
            result = client.a2a.message_send(
                {"message": {"role": "user", "parts": [{"text": "Hola"}]}}
            )
            print(f"result: {result}")
        except A2AJsonRpcError as exc:
            print(f"JSON-RPC error [{exc.code}]: {exc.message}")


if __name__ == "__main__":
    main()

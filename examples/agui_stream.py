"""Stream a turn as AG-UI 1.0 events (prismal-server 0.2).

Run against a local prismal-server:

    python examples/agui_stream.py
"""

from __future__ import annotations

from prismal_sdk import PrismalClient, ProtocolNotEnabledError, RunFinished
from prismal_sdk.agui import (
    PrismalUsageEvent,
    RunStarted,
    TextMessageContent,
    ToolCallStart,
)


def main() -> None:
    with PrismalClient("http://localhost:8000") as client:
        thread = client.create_thread()
        try:
            for event in client.send_message(
                thread.thread_id, "Hola", protocol="ag-ui"
            ):
                if isinstance(event, RunStarted):
                    print(f"[run {event.run_id}]")
                elif isinstance(event, TextMessageContent):
                    print(event.delta, end="", flush=True)
                elif isinstance(event, ToolCallStart):
                    print(f"\n[tool] {event.tool_call_name}")
                elif isinstance(event, PrismalUsageEvent):
                    print(f"\n[usage] {event.value.total_tokens} tokens")
                elif isinstance(event, RunFinished):
                    print("[finished]")
                else:
                    print(f"\n[{event.type}]")
        except ProtocolNotEnabledError:
            print("AG-UI is not enabled on this host/tenant")


if __name__ == "__main__":
    main()

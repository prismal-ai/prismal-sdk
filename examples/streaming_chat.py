"""Async streaming chat — typed events, with terminal-error handling.

Run against a local prismal-server:

    uvicorn prismal_server.app:app --reload   # in a prismal-server checkout
    python examples/streaming_chat.py
"""

from __future__ import annotations

import asyncio

from prismal_sdk import AsyncPrismalClient, DoneEvent, TokenEvent, ToolCallEvent
from prismal_sdk.exceptions import PrismalAPIError


async def main() -> None:
    async with AsyncPrismalClient("http://localhost:8000") as client:
        thread = await client.create_thread()

        try:
            async for event in client.send_message(
                thread.thread_id, "Analyze data/sales.csv"
            ):
                if isinstance(event, TokenEvent):
                    print(event.delta, end="", flush=True)
                elif isinstance(event, ToolCallEvent):
                    print(f"\n[tool_call] {event.name}({event.args!r})")
                elif isinstance(event, DoneEvent):
                    print(f"\n[done] finish_reason={event.finish_reason}")
        except PrismalAPIError as exc:
            print(f"\n[error] {exc.code}: {exc.message}")


if __name__ == "__main__":
    asyncio.run(main())

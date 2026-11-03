"""Several turns, and a cancellation, over one WebSocket (prismal-server 0.2).

Needs the optional extra and a host with ``host_ws_enabled=true``:

    pip install 'prismal-ai-sdk[ws]'
    python examples/websocket_chat.py
"""

from __future__ import annotations

import asyncio

from prismal_sdk import (
    AsyncPrismalClient,
    DoneEvent,
    TokenEvent,
    TurnCancelledError,
)


async def main() -> None:
    async with AsyncPrismalClient("http://localhost:8000") as client:
        thread = await client.create_thread()
        async with client.ws(thread.thread_id) as session:
            for prompt in ("Hola", "¿Qué puedes hacer?"):
                async for event in session.send_message(prompt):
                    if isinstance(event, TokenEvent):
                        print(event.delta, end="", flush=True)
                    elif isinstance(event, DoneEvent):
                        print(f"\n[done] {event.finish_reason}")

            # Stop a turn after its first token.
            try:
                async for event in session.send_message("Una respuesta larga"):
                    if isinstance(event, TokenEvent):
                        await session.cancel()
            except TurnCancelledError:
                print("[cancelled]")


if __name__ == "__main__":
    asyncio.run(main())

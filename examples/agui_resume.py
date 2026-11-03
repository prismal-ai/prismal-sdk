"""Answer an AG-UI interrupt with ``run_agui(..., resume=...)`` (prismal-server 0.3).

Against a fake-LLM host, ``/interrupt <message>`` pauses the run on purpose:

    PRISMAL_SERVER_HOST_FAKE_LLM_MODE=true PRISMAL_AGUI_EVENTS_ENABLED=true \\
        uvicorn prismal_server.app:app
    python examples/agui_resume.py
"""

from __future__ import annotations

from prismal_sdk import PrismalClient, ResumeConflictError
from prismal_sdk.agui import AgUiEvent, RunFinished, TextMessageContent


def _print_run(events: list[AgUiEvent]) -> RunFinished | None:
    text = "".join(e.delta for e in events if isinstance(e, TextMessageContent))
    if text:
        print(text)
    finished = events[-1] if events else None
    return finished if isinstance(finished, RunFinished) else None


def main() -> None:
    with PrismalClient("http://localhost:8000") as client:
        thread_id = client.create_thread().thread_id
        finished = _print_run(
            list(client.run_agui(thread_id, "/interrupt Approve the plan?"))
        )
        while finished is not None and finished.is_interrupted:
            for interrupt in finished.interrupts:
                print(f"[{interrupt.reason}] {interrupt.message}")
            # The payload is yours: the SDK and the host pass it to the engine.
            answers = [i.resolve({"action": "approve"}) for i in finished.interrupts]
            try:
                events = list(client.run_agui(thread_id, resume=answers))
            except ResumeConflictError as exc:
                print(f"not resumed: {exc.code}")
                return
            finished = _print_run(events)


if __name__ == "__main__":
    main()

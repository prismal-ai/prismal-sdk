"""SSE frame parser (CSB-02-02, SPEC-CSB-CHT-002/005).

Mirrors ``prismal-server/src/prismal_server/streaming.py`` exactly: named
events are framed as ``event: NAME\\ndata: JSON\\n\\n``; heartbeats are a bare
comment line ``: heartbeat\\n\\n``. This module only frames lines into
``(event, data)`` pairs — it does not know about ``token``/``tool_call``/
``done``/``error`` semantics; that translation lives in ``client.py`` /
``async_client.py`` next to the typed models it produces.

Internal module (leading underscore) — not part of the public API.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator

#: A parsed SSE frame: (event name, raw ``data:`` payload joined by "\n").
SSEFrame = tuple[str, str]


class _FrameAccumulator:
    """Accumulates ``event:``/``data:`` lines into a frame, dispatched on blank line."""

    def __init__(self) -> None:
        self._event: str | None = None
        self._data_lines: list[str] = []

    def feed(self, line: str) -> SSEFrame | None:
        """Feed one line (no trailing newline); return a completed frame, if any."""
        if line == "":
            return self._flush()
        if line.startswith(":"):
            # Comment line (heartbeat or otherwise) — not part of a named event.
            return None
        if line.startswith("event:"):
            self._event = line[len("event:") :].strip()
            return None
        if line.startswith("data:"):
            self._data_lines.append(line[len("data:") :].strip())
            return None
        # Unrecognized line shape: ignore rather than raise, so a future
        # server-side field addition never breaks an installed SDK version.
        return None

    def _flush(self) -> SSEFrame | None:
        event, data_lines = self._event, self._data_lines
        self._event, self._data_lines = None, []
        if event is None:
            # A blank line with no preceding "event:" was just a heartbeat's
            # terminator (or stray whitespace) — nothing to dispatch.
            return None
        return event, "\n".join(data_lines)


def iter_sse_events(lines: Iterable[str]) -> Iterator[SSEFrame]:
    """Parse a sync line iterator into ``(event, data)`` frames.

    Heartbeat comments and blank noise are consumed silently
    (SPEC-CSB-CHT-005); only named events are yielded.
    """
    acc = _FrameAccumulator()
    for line in lines:
        frame = acc.feed(line)
        if frame is not None:
            yield frame


async def aiter_sse_events(lines: AsyncIterable[str]) -> AsyncIterator[SSEFrame]:
    """Async counterpart of :func:`iter_sse_events`."""
    acc = _FrameAccumulator()
    async for line in lines:
        frame = acc.feed(line)
        if frame is not None:
            yield frame

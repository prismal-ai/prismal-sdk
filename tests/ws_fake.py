"""In-process fake ``/ws/threads/{id}`` server for the WebSocket tests.

A real ``websockets`` sync server on ``127.0.0.1`` (ephemeral port, own
thread): no external network, and the SDK's client code runs unmodified
against an actual WebSocket handshake and close frames (ARCHITECTURE §7).
Each test scripts the server side with a plain handler function.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from websockets.sync.server import ServerConnection, serve


class Recorder:
    """What the fake server saw: handshake paths/headers and client frames."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.frames: list[dict[str, Any]] = []
        self.connections = 0
        self.lock = threading.Lock()

    def handshake(self, conn: ServerConnection) -> None:
        with self.lock:
            self.connections += 1
            assert conn.request is not None
            self.paths.append(conn.request.path)
            self.headers.append(
                {k.lower(): v for k, v in conn.request.headers.raw_items()}
            )

    def recv(self, conn: ServerConnection) -> dict[str, Any]:
        frame: dict[str, Any] = json.loads(conn.recv())
        with self.lock:
            self.frames.append(frame)
        return frame


def send(conn: ServerConnection, event: str, data: Any = None) -> None:
    frame: dict[str, Any] = {"event": event}
    if data is not None:
        frame["data"] = data
    conn.send(json.dumps(frame))


Handler = Callable[[ServerConnection, Recorder], None]


@contextmanager
def fake_ws_server(
    handler: Handler, *, process_request: Any = None
) -> Iterator[tuple[str, Recorder]]:
    """Run ``handler`` per connection; yield ``(http base url, recorder)``."""
    recorder = Recorder()

    def _handle(conn: ServerConnection) -> None:
        recorder.handshake(conn)
        try:
            handler(conn, recorder)
        except Exception:  # noqa: BLE001 — client went away mid-script
            pass

    server = serve(_handle, "127.0.0.1", 0, process_request=process_request)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", recorder
    finally:
        server.shutdown()
        thread.join(timeout=5)

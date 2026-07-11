"""Shared fixtures: offline `httpx.MockTransport` handlers, no network.

See SPEC-CSB-NFR-003.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from prismal_sdk.async_client import AsyncPrismalClient
from prismal_sdk.client import PrismalClient

Handler = Callable[[httpx.Request], httpx.Response]


def sse_frame(event: str, data: str) -> str:
    """One named SSE frame, mirroring prismal-server's ``streaming.py::sse_event``."""
    return f"event: {event}\ndata: {data}\n\n"


def sse_body(*frames: str) -> bytes:
    """Join pre-formatted SSE frames into the bytes a streaming response would send."""
    return "".join(frames).encode()


@pytest.fixture
def make_client() -> Callable[..., PrismalClient]:
    """Build a :class:`PrismalClient` wired to a fake handler (no network)."""

    def _make(handler: Handler, **kwargs: object) -> PrismalClient:
        return PrismalClient(
            "http://testserver", transport=httpx.MockTransport(handler), **kwargs
        )

    return _make


@pytest.fixture
def make_async_client() -> Callable[..., AsyncPrismalClient]:
    """Build an :class:`AsyncPrismalClient` wired to a fake handler (no network)."""

    def _make(handler: Handler, **kwargs: object) -> AsyncPrismalClient:
        return AsyncPrismalClient(
            "http://testserver", transport=httpx.MockTransport(handler), **kwargs
        )

    return _make

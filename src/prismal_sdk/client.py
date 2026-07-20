"""Synchronous client (CSB-01-04, CSB-02-03/04, CSB-03-*).

``PrismalClient`` is the sync half of the SDK's mirrored pair
(``ARCHITECTURE.md`` ADR-005) — see ``async_client.py`` for the async
counterpart, which must expose the same public surface (SPEC-CSB-NFR-001).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from types import TracebackType
from typing import Any

import httpx

from prismal_sdk import a2a as _a2a
from prismal_sdk._chat import translate_chat_frame
from prismal_sdk._sse import iter_sse_events
from prismal_sdk._transport import (
    backoff_delay_s,
    build_headers,
    decode_json,
    extract_detail,
    is_retryable,
    raise_for_response,
    wrap_transport_exception,
)
from prismal_sdk.config import DEFAULT_BASE_URL, ClientConfig
from prismal_sdk.exceptions import A2ANotEnabledError, PrismalAPIError, error_for_code
from prismal_sdk.models import (
    AgentCard,
    ChatEvent,
    DoneEvent,
    HealthStatus,
    MessageIn,
    ReadyStatus,
    ThreadCreated,
)


class _A2AResource:
    """``client.a2a`` — JSON-RPC helpers bound to a :class:`PrismalClient`."""

    def __init__(self, client: PrismalClient) -> None:
        self._client = client

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        """``POST /a2a`` (non-streaming), returning ``result`` (SPEC-CSB-A2A-002)."""
        body = _a2a.build_jsonrpc_request(method, params or {}, request_id=request_id)
        response = self._client._request("POST", "/a2a", json_body=body, org_id=org_id)
        _raise_if_a2a_not_enabled(response)
        raise_for_response(response)
        return _a2a.parse_jsonrpc_response(decode_json(response))

    def stream(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Iterator[Any]:
        """``POST /a2a`` with ``message/stream``, yielding decoded ``data:`` frames."""
        body = _a2a.build_jsonrpc_request(method, params or {}, request_id=request_id)
        headers = self._client._headers(org_id)
        with self._client._client.stream(
            "POST", "/a2a", json=body, headers=headers
        ) as response:
            if response.status_code == 404:
                response.read()
                raise A2ANotEnabledError(
                    404, "a2a_not_enabled", extract_detail(response)
                )
            if not response.is_success:
                response.read()
                raise_for_response(response)
            yield from _a2a.iter_a2a_data_frames(response.iter_lines())

    def message_send(
        self, params: dict[str, Any], *, request_id: str | int | None = None
    ) -> Any:
        return self.send(_a2a.MESSAGE_SEND, params, request_id=request_id)

    def message_stream(
        self, params: dict[str, Any], *, request_id: str | int | None = None
    ) -> Iterator[Any]:
        return self.stream(_a2a.MESSAGE_STREAM, params, request_id=request_id)

    def tasks_get(
        self, params: dict[str, Any], *, request_id: str | int | None = None
    ) -> Any:
        return self.send(_a2a.TASKS_GET, params, request_id=request_id)

    def tasks_cancel(
        self, params: dict[str, Any], *, request_id: str | int | None = None
    ) -> Any:
        return self.send(_a2a.TASKS_CANCEL, params, request_id=request_id)


def _raise_if_a2a_not_enabled(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise A2ANotEnabledError(404, "a2a_not_enabled", extract_detail(response))


class PrismalClient:
    """Synchronous client for ``prismal-server``'s REST/SSE + A2A surface."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        token: str | None = None,
        org_id: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._org_id = org_id
        self._max_retries = max_retries
        self._client = httpx.Client(
            base_url=self._base_url, timeout=timeout_s, transport=transport
        )
        self.a2a = _A2AResource(self)

    @classmethod
    def from_config(cls, config: ClientConfig) -> PrismalClient:
        """Construct from a :class:`ClientConfig` (SPEC-CSB-TRN-002)."""
        return cls(
            config.base_url,
            token=config.token.get_secret_value() if config.token else None,
            org_id=config.org_id,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
        )

    def __enter__(self) -> PrismalClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def _headers(self, org_id: str | None) -> dict[str, str]:
        return build_headers(token=self._token, org_id=org_id or self._org_id)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        org_id: str | None = None,
    ) -> httpx.Response:
        """One request with bounded retry on transient transport failures.

        Does **not** raise for a non-2xx status — callers interpret the
        response themselves, because the server's error body shape differs
        by route (generic ``{"error": {...}}`` vs. ``readyz``'s
        ``{"status", "reason"}`` vs. a plain ``HTTPException`` ``{"detail"}``
        on the A2A routes).
        """
        headers = self._headers(org_id)
        attempt = 0
        while True:
            try:
                return self._client.request(
                    method, path, json=json_body, headers=headers
                )
            except httpx.HTTPError as exc:
                if attempt < self._max_retries and is_retryable(method, path, exc):
                    time.sleep(backoff_delay_s(attempt))
                    attempt += 1
                    continue
                raise wrap_transport_exception(exc) from exc

    def healthz(self) -> HealthStatus:
        """``GET /healthz`` — liveness (SPEC-CSB-HLT-001)."""
        response = self._request("GET", "/healthz")
        raise_for_response(response)
        return HealthStatus.model_validate(decode_json(response))

    def readyz(self) -> ReadyStatus:
        """``GET /readyz`` — readiness (SPEC-CSB-HLT-002).

        Raises :class:`~prismal_sdk.exceptions.RuntimeCompositionError` (or
        the exception mapped from the body's ``reason`` code) on ``503``.
        """
        response = self._request("GET", "/readyz")
        body = decode_json(response)
        if response.status_code == 200:
            return ReadyStatus.model_validate(body)
        reason = (
            body.get("reason", "internal_error")
            if isinstance(body, dict)
            else "internal_error"
        )
        raise error_for_code(
            response.status_code, reason, "The default runtime is not ready"
        )

    def create_thread(self) -> ThreadCreated:
        """``POST /threads`` — mint a new opaque thread id (SPEC-CSB-THR-001)."""
        response = self._request("POST", "/threads")
        raise_for_response(response)
        return ThreadCreated.model_validate(decode_json(response))

    def send_message(
        self,
        thread_id: str,
        content: str,
        *,
        role: str = "user",
        metadata: dict[str, Any] | None = None,
        org_id: str | None = None,
    ) -> Iterator[ChatEvent]:
        """Stream a chat turn (``POST /threads/{id}/messages``, SPEC-CSB-CHT-001).

        Yields typed events in server order; raises the mapped
        :class:`~prismal_sdk.exceptions.PrismalAPIError` from within the
        iterator on a terminal ``error`` frame (SPEC-CSB-CHT-004). Iterate to
        completion, or use ``with`` / call ``.close()`` on the generator for
        a deterministic prompt disconnect (SPEC-CSB-CHT-006) — CPython closes
        it automatically once unreferenced, but that timing is not
        guaranteed on every Python implementation.
        """
        body = MessageIn(
            content=content, role=role, metadata=metadata or {}
        ).model_dump()
        headers = self._headers(org_id)
        try:
            with self._client.stream(
                "POST", f"/threads/{thread_id}/messages", json=body, headers=headers
            ) as response:
                if not response.is_success:
                    response.read()
                    raise_for_response(response)
                for event_name, data in iter_sse_events(response.iter_lines()):
                    parsed = translate_chat_frame(event_name, data)
                    if parsed is None:
                        continue
                    yield parsed
                    if isinstance(parsed, DoneEvent):
                        return
        except httpx.HTTPError as exc:
            # A transport failure mid-stream must surface as an SDK error, not
            # a raw httpx type (SPEC-CSB-ERR-003/004). The stream is never
            # retried (SPEC-CSB-RSL-002).
            raise wrap_transport_exception(exc) from exc

    def agent_card(self, *, org_id: str | None = None) -> AgentCard:
        """``GET /.well-known/agent-card.json`` (SPEC-CSB-A2A-001)."""
        response = self._request("GET", "/.well-known/agent-card.json", org_id=org_id)
        _raise_if_a2a_not_enabled(response)
        raise_for_response(response)
        return AgentCard.model_validate(decode_json(response))


__all__ = ["PrismalClient", "PrismalAPIError"]

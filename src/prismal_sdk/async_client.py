"""Asynchronous client (CSB-01-04, CSB-02-03/04, CSB-03-*).

``AsyncPrismalClient`` is the async half of the SDK's mirrored pair
(``ARCHITECTURE.md`` ADR-005) — see ``client.py`` for the sync counterpart.
Both expose the same public surface (SPEC-CSB-NFR-001); this module is the
``async``/``await`` translation of the same logic, sharing
``_transport.py``, ``_sse.py``, ``_chat.py``, and ``a2a.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from types import TracebackType
from typing import Any

import httpx

from prismal_sdk import a2a as _a2a
from prismal_sdk._chat import translate_chat_frame
from prismal_sdk._sse import aiter_sse_events
from prismal_sdk._transport import (
    backoff_delay_s,
    build_headers,
    build_query,
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
    BudgetReport,
    ChatEvent,
    DoneEvent,
    HealthStatus,
    MessageIn,
    ReadyStatus,
    ThreadCreated,
    UsageReport,
    UsageTurn,
)


class _AsyncA2AResource:
    """``client.a2a`` — JSON-RPC helpers bound to an :class:`AsyncPrismalClient`."""

    def __init__(self, client: AsyncPrismalClient) -> None:
        self._client = client

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        body = _a2a.build_jsonrpc_request(method, params or {}, request_id=request_id)
        response = await self._client._request(
            "POST", "/a2a", json_body=body, org_id=org_id
        )
        _raise_if_a2a_not_enabled(response)
        raise_for_response(response)
        return _a2a.parse_jsonrpc_response(decode_json(response))

    async def stream(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> AsyncIterator[Any]:
        body = _a2a.build_jsonrpc_request(method, params or {}, request_id=request_id)
        headers = self._client._headers(org_id)
        async with self._client._client.stream(
            "POST", "/a2a", json=body, headers=headers
        ) as response:
            if response.status_code == 404:
                await response.aread()
                raise A2ANotEnabledError(
                    404, "a2a_not_enabled", extract_detail(response)
                )
            if not response.is_success:
                await response.aread()
                raise_for_response(response)
            async for frame in _a2a.aiter_a2a_data_frames(response.aiter_lines()):
                yield frame

    async def message_send(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        return await self.send(
            _a2a.MESSAGE_SEND, params, request_id=request_id, org_id=org_id
        )

    def message_stream(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> AsyncIterator[Any]:
        return self.stream(
            _a2a.MESSAGE_STREAM, params, request_id=request_id, org_id=org_id
        )

    async def tasks_get(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        return await self.send(
            _a2a.TASKS_GET, params, request_id=request_id, org_id=org_id
        )

    async def tasks_cancel(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        return await self.send(
            _a2a.TASKS_CANCEL, params, request_id=request_id, org_id=org_id
        )


def _raise_if_a2a_not_enabled(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise A2ANotEnabledError(404, "a2a_not_enabled", extract_detail(response))


class AsyncPrismalClient:
    """Asynchronous client for ``prismal-server``'s REST/SSE + A2A surface."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        token: str | None = None,
        org_id: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._org_id = org_id
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout_s, transport=transport
        )
        self.a2a = _AsyncA2AResource(self)

    @classmethod
    def from_config(cls, config: ClientConfig) -> AsyncPrismalClient:
        """Construct from a :class:`ClientConfig` (SPEC-CSB-TRN-002)."""
        return cls(
            config.base_url,
            token=config.token.get_secret_value() if config.token else None,
            org_id=config.org_id,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
        )

    async def __aenter__(self) -> AsyncPrismalClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    def _headers(self, org_id: str | None) -> dict[str, str]:
        return build_headers(token=self._token, org_id=org_id or self._org_id)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        org_id: str | None = None,
    ) -> httpx.Response:
        """One request with bounded retry on transient transport failures.

        See :meth:`prismal_sdk.client.PrismalClient._request` for why this
        does not raise for a non-2xx status itself.
        """
        headers = self._headers(org_id)
        attempt = 0
        while True:
            try:
                return await self._client.request(
                    method, path, json=json_body, params=params, headers=headers
                )
            except httpx.HTTPError as exc:
                if attempt < self._max_retries and is_retryable(method, path, exc):
                    await asyncio.sleep(backoff_delay_s(attempt))
                    attempt += 1
                    continue
                raise wrap_transport_exception(exc) from exc

    async def healthz(self) -> HealthStatus:
        """``GET /healthz`` — liveness (SPEC-CSB-HLT-001)."""
        response = await self._request("GET", "/healthz")
        raise_for_response(response)
        return HealthStatus.model_validate(decode_json(response))

    async def readyz(self) -> ReadyStatus:
        """``GET /readyz`` — readiness (SPEC-CSB-HLT-002)."""
        response = await self._request("GET", "/readyz")
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

    async def create_thread(self) -> ThreadCreated:
        """``POST /threads`` — mint a new opaque thread id (SPEC-CSB-THR-001)."""
        response = await self._request("POST", "/threads")
        raise_for_response(response)
        return ThreadCreated.model_validate(decode_json(response))

    async def send_message(
        self,
        thread_id: str,
        content: str,
        *,
        role: str = "user",
        metadata: dict[str, Any] | None = None,
        org_id: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Stream a chat turn (``POST /threads/{id}/messages``, SPEC-CSB-CHT-001).

        Async-generator counterpart of
        :meth:`prismal_sdk.client.PrismalClient.send_message` — same event
        ordering, same terminal-``error``-raises-in-place behavior
        (SPEC-CSB-CHT-004).
        """
        body = MessageIn(
            content=content, role=role, metadata=metadata or {}
        ).model_dump()
        headers = self._headers(org_id)
        try:
            async with self._client.stream(
                "POST", f"/threads/{thread_id}/messages", json=body, headers=headers
            ) as response:
                if not response.is_success:
                    await response.aread()
                    raise_for_response(response)
                async for event_name, data in aiter_sse_events(response.aiter_lines()):
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

    async def usage(
        self,
        *,
        thread_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
        org_id: str | None = None,
    ) -> UsageReport:
        """``GET /v1/usage`` — usage report for the caller's org (SPEC-CS2-USE-001).

        Only non-``None`` filters are sent; datetimes must be timezone-aware
        and go out as RFC 3339 UTC. ``org_id`` selects the tenant through
        the ``X-Org-Id`` header, like every other call.
        """
        params = build_query(
            {
                "thread_id": thread_id,
                "since": since,
                "until": until,
                "limit": limit,
                "cursor": cursor,
            }
        )
        response = await self._request("GET", "/v1/usage", params=params, org_id=org_id)
        raise_for_response(response)
        return UsageReport.model_validate(decode_json(response))

    async def iter_usage_turns(
        self,
        *,
        thread_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        page_size: int = 100,
        org_id: str | None = None,
    ) -> AsyncIterator[UsageTurn]:
        """Every turn in the window, following ``next_cursor`` (SPEC-CS2-USE-002).

        Lazy: one ``GET /v1/usage`` page per ``page_size`` turns, fetched as
        iteration reaches it. Each page is an idempotent ``GET``, retried on
        connect/timeout failures like any other.
        """
        cursor: str | None = None
        while True:
            report = await self.usage(
                thread_id=thread_id,
                since=since,
                until=until,
                limit=page_size,
                cursor=cursor,
                org_id=org_id,
            )
            for turn in report.turns:
                yield turn
            cursor = report.next_cursor
            if cursor is None:
                return

    async def budget(
        self, *, thread_id: str | None = None, org_id: str | None = None
    ) -> BudgetReport:
        """``GET /v1/budget`` — the engine's budget status (SPEC-CS2-BUD-001)."""
        params = build_query({"thread_id": thread_id})
        response = await self._request(
            "GET", "/v1/budget", params=params, org_id=org_id
        )
        raise_for_response(response)
        return BudgetReport.model_validate(decode_json(response))

    async def agent_card(self, *, org_id: str | None = None) -> AgentCard:
        """``GET /.well-known/agent-card.json`` (SPEC-CSB-A2A-001)."""
        response = await self._request(
            "GET", "/.well-known/agent-card.json", org_id=org_id
        )
        _raise_if_a2a_not_enabled(response)
        raise_for_response(response)
        return AgentCard.model_validate(decode_json(response))


__all__ = ["AsyncPrismalClient", "PrismalAPIError"]

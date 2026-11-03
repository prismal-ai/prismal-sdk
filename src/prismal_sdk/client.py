"""Synchronous client (CSB-01-04, CSB-02-03/04, CSB-03-*).

``PrismalClient`` is the sync half of the SDK's mirrored pair
(``ARCHITECTURE.md`` ADR-005) — see ``async_client.py`` for the async
counterpart, which must expose the same public surface (SPEC-CSB-NFR-001).
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, Literal, overload

import httpx

from prismal_sdk import a2a as _a2a
from prismal_sdk._a2a_methods import (
    A2AProtocolMode,
    A2AVersion,
    check_mode,
    method_for,
    tasks_list_params,
    version_from_card,
    version_headers,
)
from prismal_sdk._chat import (
    AGUI_RUN_HEADERS,
    AGUI_RUN_PATH,
    AgUiTranslator,
    check_negotiated,
    run_agent_input,
    stream_profile,
)
from prismal_sdk._sse import iter_sse_events
from prismal_sdk._transport import (
    backoff_delay_s,
    build_headers,
    build_query,
    decode_json,
    extract_detail,
    is_retryable,
    path_segment,
    raise_for_response,
    wrap_transport_exception,
)
from prismal_sdk._ws import WsSession, require_websockets, ws_url
from prismal_sdk.admin import (
    AuditPage,
    DecisionShadowReport,
    RoutingSavingsReport,
    TenantsEnvelope,
    TenantSummary,
    raise_for_admin_response,
)
from prismal_sdk.agui import AgUiEvent, ResumeEntry, RunFinished, StreamProtocol
from prismal_sdk.config import DEFAULT_BASE_URL, ClientConfig
from prismal_sdk.exceptions import A2ANotEnabledError, PrismalAPIError, error_for_code
from prismal_sdk.models import (
    AgentCard,
    BudgetReport,
    ChatEvent,
    HealthStatus,
    MessageIn,
    ReadyStatus,
    TaskListPage,
    ThreadCreated,
    UsageReport,
    UsageTurn,
)


class _A2AResource:
    """``client.a2a`` — JSON-RPC helpers bound to a :class:`PrismalClient`.

    The typed wrappers speak the client's ``a2a_protocol`` version: method
    names from :data:`~prismal_sdk._a2a_methods.A2A_METHODS`, plus
    ``A2A-Version: 1.0`` on v1 (SPEC-CS2-A2A-002). Payloads are passed
    through unconverted — building v0.3 or v1 shapes is the caller's job
    (SPEC-CS2-A2A-005).
    """

    def __init__(self, client: PrismalClient) -> None:
        self._client = client
        # Per effective tenant: hosts may pin a2a_protocol_version per tenant.
        self._versions: dict[str | None, A2AVersion] = {}

    def negotiated_version(self, *, org_id: str | None = None) -> A2AVersion:
        """The A2A version spoken to this tenant's peer (SPEC-CS2-A2A-001).

        A fixed ``a2a_protocol`` is returned as-is, without I/O. ``"auto"``
        reads the Agent Card once per tenant and caches the answer.
        """
        mode = self._client._a2a_protocol
        if mode != "auto":
            return mode
        key = org_id or self._client._org_id
        if key not in self._versions:
            card = self._client.agent_card(org_id=org_id)
            self._versions[key] = version_from_card(card)
        return self._versions[key]

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        """``POST /a2a`` (non-streaming), returning ``result`` (SPEC-CSB-A2A-002).

        A raw call never negotiates: it carries ``A2A-Version: 1.0`` only
        when the client was built with ``a2a_protocol="1.0"``.
        """
        return self._post(
            method,
            params,
            self._fixed_version(),
            request_id=request_id,
            org_id=org_id,
        )

    def stream(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Iterator[Any]:
        """``POST /a2a`` streaming, yielding decoded ``data:`` frames.

        Same version-header rule as :meth:`send`.
        """
        yield from self._post_stream(
            method,
            params,
            self._fixed_version(),
            request_id=request_id,
            org_id=org_id,
        )

    def message_send(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        return self._call("message_send", params, request_id=request_id, org_id=org_id)

    def message_stream(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Iterator[Any]:
        return self._call_stream(
            "message_stream", params, request_id=request_id, org_id=org_id
        )

    def tasks_get(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        return self._call("tasks_get", params, request_id=request_id, org_id=org_id)

    def tasks_cancel(
        self,
        params: dict[str, Any],
        *,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> Any:
        return self._call("tasks_cancel", params, request_id=request_id, org_id=org_id)

    def tasks_list(
        self,
        *,
        context_id: str | None = None,
        status: str | None = None,
        page_size: int = 50,
        page_token: str | None = None,
        tenant: str | None = None,
        history_length: int | None = None,
        status_timestamp_after: str | None = None,
        include_artifacts: bool | None = None,
        request_id: str | int | None = None,
        org_id: str | None = None,
    ) -> TaskListPage:
        """A2A v1 ``ListTasks`` — one page of tasks (SPEC-CS2-A2A-003).

        ``page_size`` outside ``1..100`` raises ``ValueError`` and a 0.3 peer
        raises :class:`~prismal_sdk.exceptions.A2AVersionError`, both before
        anything is posted. The last page has ``next_page_token == ""``.
        """
        params = tasks_list_params(
            context_id=context_id,
            status=status,
            page_size=page_size,
            page_token=page_token,
            tenant=tenant,
            history_length=history_length,
            status_timestamp_after=status_timestamp_after,
            include_artifacts=include_artifacts,
        )
        result = self._call("tasks_list", params, request_id=request_id, org_id=org_id)
        return TaskListPage.model_validate(result)

    def _fixed_version(self) -> A2AVersion:
        mode = self._client._a2a_protocol
        return "0.3" if mode == "auto" else mode

    def _call(
        self,
        operation: str,
        params: dict[str, Any],
        *,
        request_id: str | int | None,
        org_id: str | None,
    ) -> Any:
        version = self.negotiated_version(org_id=org_id)
        return self._post(
            method_for(version, operation),
            params,
            version,
            request_id=request_id,
            org_id=org_id,
        )

    def _call_stream(
        self,
        operation: str,
        params: dict[str, Any],
        *,
        request_id: str | int | None,
        org_id: str | None,
    ) -> Iterator[Any]:
        version = self.negotiated_version(org_id=org_id)
        yield from self._post_stream(
            method_for(version, operation),
            params,
            version,
            request_id=request_id,
            org_id=org_id,
        )

    def _post_stream(
        self,
        method: str,
        params: dict[str, Any] | None,
        version: A2AVersion,
        *,
        request_id: str | int | None,
        org_id: str | None,
    ) -> Iterator[Any]:
        body = _a2a.build_jsonrpc_request(method, params or {}, request_id=request_id)
        headers = {**self._client._headers(org_id), **version_headers(version)}
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

    def _post(
        self,
        method: str,
        params: dict[str, Any] | None,
        version: A2AVersion,
        *,
        request_id: str | int | None,
        org_id: str | None,
    ) -> Any:
        body = _a2a.build_jsonrpc_request(method, params or {}, request_id=request_id)
        response = self._client._request(
            "POST",
            "/a2a",
            json_body=body,
            headers=version_headers(version),
            org_id=org_id,
        )
        _raise_if_a2a_not_enabled(response)
        raise_for_response(response)
        return _a2a.parse_jsonrpc_response(decode_json(response))


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
        a2a_protocol: A2AProtocolMode = "0.3",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._org_id = org_id
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._a2a_protocol: A2AProtocolMode = check_mode(a2a_protocol)
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
            a2a_protocol=config.a2a_protocol,
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
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        org_id: str | None = None,
    ) -> httpx.Response:
        """One request with bounded retry on transient transport failures.

        Does **not** raise for a non-2xx status — callers interpret the
        response themselves, because the server's error body shape differs
        by route (generic ``{"error": {...}}`` vs. ``readyz``'s
        ``{"status", "reason"}`` vs. a plain ``HTTPException`` ``{"detail"}``
        on the A2A routes).
        """
        request_headers = {**self._headers(org_id), **(headers or {})}
        attempt = 0
        while True:
            try:
                return self._client.request(
                    method, path, json=json_body, params=params, headers=request_headers
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

    @overload
    def send_message(
        self,
        thread_id: str,
        content: str,
        *,
        role: str = ...,
        metadata: dict[str, Any] | None = ...,
        org_id: str | None = ...,
        protocol: Literal["prismal"] = ...,
    ) -> Iterator[ChatEvent]: ...

    @overload
    def send_message(
        self,
        thread_id: str,
        content: str,
        *,
        role: str = ...,
        metadata: dict[str, Any] | None = ...,
        org_id: str | None = ...,
        protocol: Literal["ag-ui"],
    ) -> Iterator[AgUiEvent]: ...

    def send_message(
        self,
        thread_id: str,
        content: str,
        *,
        role: str = "user",
        metadata: dict[str, Any] | None = None,
        org_id: str | None = None,
        protocol: StreamProtocol = "prismal",
    ) -> Iterator[ChatEvent | AgUiEvent]:
        """Stream a chat turn (``POST /threads/{id}/messages``, SPEC-CSB-CHT-001).

        Yields typed events in server order; raises the mapped
        :class:`~prismal_sdk.exceptions.PrismalAPIError` from within the
        iterator on a terminal ``error`` frame (SPEC-CSB-CHT-004). Iterate to
        completion, or use ``with`` / call ``.close()`` on the generator for
        a deterministic prompt disconnect (SPEC-CSB-CHT-006) — CPython closes
        it automatically once unreferenced, but that timing is not
        guaranteed on every Python implementation.

        ``protocol="ag-ui"`` asks for AG-UI 1.0 events instead
        (SPEC-CS2-AGU-001): it yields :class:`~prismal_sdk.agui.AgUiEvent`
        models, ending with ``RunFinished``; a ``RUN_ERROR`` raises the mapped
        exception, and a host that cannot stream AG-UI raises
        :class:`~prismal_sdk.exceptions.ProtocolNotEnabledError` before any
        event. An unknown ``protocol`` raises ``ValueError`` before any I/O.
        """
        profile = stream_profile(protocol)
        body = MessageIn(
            content=content, role=role, metadata=metadata or {}
        ).model_dump()
        headers = {**self._headers(org_id), **profile.request_headers}
        try:
            with self._client.stream(
                "POST",
                f"/threads/{path_segment('thread_id', thread_id)}/messages",
                json=body,
                headers=headers,
            ) as response:
                if not response.is_success:
                    response.read()
                    raise_for_response(response)
                check_negotiated(profile, response)
                for event_name, data in iter_sse_events(response.iter_lines()):
                    parsed = profile.translate(event_name, data)
                    if parsed is None:
                        continue
                    yield parsed
                    if isinstance(parsed, profile.terminal):
                        return
        except httpx.HTTPError as exc:
            # A transport failure mid-stream must surface as an SDK error, not
            # a raw httpx type (SPEC-CSB-ERR-003/004). The stream is never
            # retried (SPEC-CSB-RSL-002).
            raise wrap_transport_exception(exc) from exc

    def run_agui(
        self,
        thread_id: str,
        content: str | None = None,
        *,
        resume: Sequence[ResumeEntry] | None = None,
        run_id: str | None = None,
        org_id: str | None = None,
    ) -> Iterator[AgUiEvent]:
        """Run an AG-UI turn from a ``RunAgentInput`` (``POST /v1/agui``).

        Pass ``content`` to start a run, or ``resume`` to answer the open
        interrupts of an interrupted one — exactly one of them, otherwise
        ``ValueError`` before any I/O (SPEC-CS3-RUN-002)::

            *events, finished = client.run_agui(thread_id, "Deploy it")
            if finished.is_interrupted:
                answers = [i.resolve({"ok": True}) for i in finished.interrupts]
                events = client.run_agui(thread_id, resume=answers)

        Yields AG-UI events like ``send_message(protocol="ag-ui")``, ending
        with ``RunFinished``; a ``RUN_ERROR`` raises the mapped exception and a
        refusal raises before any event (``ResumeConflictError`` for
        ``409 no_pending_interrupt`` / ``resume_in_progress``). ``run_id``
        defaults to a fresh uuid4 hex. Never retried (SPEC-CS3-RUN-005): a
        resume may already have run, so re-sending it is the caller's call.
        """
        body = run_agent_input(thread_id, content, resume, run_id)
        headers = {**self._headers(org_id), **AGUI_RUN_HEADERS}
        translate = AgUiTranslator()
        try:
            with self._client.stream(
                "POST", AGUI_RUN_PATH, json=body, headers=headers
            ) as response:
                if not response.is_success:
                    response.read()
                    raise_for_response(response)
                for event_name, data in iter_sse_events(response.iter_lines()):
                    parsed = translate(event_name, data)
                    if parsed is None:
                        continue
                    yield parsed
                    if isinstance(parsed, RunFinished):
                        return
        except httpx.HTTPError as exc:
            # Never retried, connect failures included (SPEC-CS3-RUN-005).
            raise wrap_transport_exception(exc) from exc

    def usage(
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
        response = self._request("GET", "/v1/usage", params=params, org_id=org_id)
        raise_for_response(response)
        return UsageReport.model_validate(decode_json(response))

    def iter_usage_turns(
        self,
        *,
        thread_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        page_size: int = 100,
        org_id: str | None = None,
    ) -> Iterator[UsageTurn]:
        """Every turn in the window, following ``next_cursor`` (SPEC-CS2-USE-002).

        Lazy: one ``GET /v1/usage`` page per ``page_size`` turns, fetched as
        iteration reaches it. Each page is an idempotent ``GET``, retried on
        connect/timeout failures like any other.
        """
        cursor: str | None = None
        while True:
            report = self.usage(
                thread_id=thread_id,
                since=since,
                until=until,
                limit=page_size,
                cursor=cursor,
                org_id=org_id,
            )
            yield from report.turns
            cursor = report.next_cursor
            if cursor is None:
                return

    def budget(
        self, *, thread_id: str | None = None, org_id: str | None = None
    ) -> BudgetReport:
        """``GET /v1/budget`` — the engine's budget status (SPEC-CS2-BUD-001)."""
        params = build_query({"thread_id": thread_id})
        response = self._request("GET", "/v1/budget", params=params, org_id=org_id)
        raise_for_response(response)
        return BudgetReport.model_validate(decode_json(response))

    def decisions_report(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        org_id: str | None = None,
    ) -> DecisionShadowReport:
        """``GET /v1/admin/decisions`` — decision shadow stats (SPEC-CS2-ADM-001).

        Needs an admin-scoped token. ``org_id`` is the report's tenant
        filter, sent as a query parameter (``"*"`` = every tenant, which
        needs ``prismal:admin:global``); ``X-Org-Id`` stays the client's.
        Host defaults: the last 7 days.
        """
        params = build_query({"org_id": org_id, "since": since, "until": until})
        response = self._request("GET", "/v1/admin/decisions", params=params)
        raise_for_admin_response(response)
        return DecisionShadowReport.model_validate(decode_json(response))

    def routing_report(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        org_id: str | None = None,
    ) -> RoutingSavingsReport:
        """``GET /v1/admin/routing`` — routing savings (SPEC-CS2-ADM-001).

        Same scope and ``org_id`` semantics as :meth:`decisions_report`.
        """
        params = build_query({"org_id": org_id, "since": since, "until": until})
        response = self._request("GET", "/v1/admin/routing", params=params)
        raise_for_admin_response(response)
        return RoutingSavingsReport.model_validate(decode_json(response))

    def audit(
        self,
        page: int = 1,
        page_size: int = 50,
        *,
        since: datetime | None = None,
        org_id: str | None = None,
    ) -> AuditPage:
        """``GET /v1/admin/audit`` — one 1-based page of the audit log.

        The chain status is the engine's verification, not re-checked here
        (SPEC-CS2-ADM-002/003). ``org_id`` as in :meth:`decisions_report`.
        """
        params = build_query(
            {"page": page, "page_size": page_size, "since": since, "org_id": org_id}
        )
        response = self._request("GET", "/v1/admin/audit", params=params)
        raise_for_admin_response(response)
        return AuditPage.model_validate(decode_json(response))

    def tenants(self) -> list[TenantSummary]:
        """``GET /v1/admin/tenants`` — the host's tenants (SPEC-CS2-ADM-002)."""
        response = self._request("GET", "/v1/admin/tenants")
        raise_for_admin_response(response)
        return TenantsEnvelope.model_validate(decode_json(response)).tenants

    def ws(self, thread_id: str, *, org_id: str | None = None) -> WsSession:
        """A WebSocket session on ``/ws/threads/{thread_id}`` (SPEC-CS2-WSK-001).

        Needs the optional extra (``pip install 'prismal-sdk[ws]'``);
        without it this raises
        :class:`~prismal_sdk.exceptions.WebSocketUnavailableError`. The
        handshake carries the same ``Authorization`` / ``X-Org-Id`` headers
        as HTTP calls, and ``timeout_s`` bounds the connect and each wait for
        a frame. No I/O happens here; the session connects on entry or on
        its first turn::

            with client.ws(thread_id) as session:
                for event in session.send_message("hi"):
                    ...

        Turns are never retried (SPEC-CS2-WSK-004).
        """
        require_websockets()
        return WsSession(
            ws_url(self._base_url, thread_id), self._headers(org_id), self._timeout_s
        )

    def agent_card(
        self,
        *,
        org_id: str | None = None,
        protocol_version: A2AVersion | None = None,
    ) -> AgentCard:
        """``GET /.well-known/agent-card.json`` (SPEC-CSB-A2A-001).

        ``protocol_version`` asks for the card of a given A2A stack
        (``?protocolVersion=``, SPEC-CS2-A2A-004).
        """
        params = build_query({"protocolVersion": protocol_version})
        response = self._request(
            "GET", "/.well-known/agent-card.json", params=params, org_id=org_id
        )
        _raise_if_a2a_not_enabled(response)
        raise_for_response(response)
        return AgentCard.model_validate(decode_json(response))


__all__ = ["PrismalClient", "PrismalAPIError"]

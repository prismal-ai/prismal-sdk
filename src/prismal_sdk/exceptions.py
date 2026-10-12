"""Exception hierarchy (CSB-01-02, SPEC-CSB-ERR-*).

Mirrors ``prismal-server/src/prismal_server/errors.py``'s stable error-code
table (``{"error": {"code", "message"}}``) on the client side, plus
transport-level failures that never reach the server at all. A2A JSON-RPC
errors are a deliberately separate surface (``A2AJsonRpcError``) — the host
never wraps A2A errors in the REST envelope (SPEC-RHB-SDK-002).

Every exception here subclasses :class:`PrismalSDKError` so a caller can
catch broadly with one ``except``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pydantic

from prismal_sdk.models import Usage


class PrismalSDKError(Exception):
    """Root of every exception raised by this SDK."""


# ── REST API errors (mirrors prismal-server errors.py::_NAME_MAP) ──────────


class PrismalAPIError(PrismalSDKError):
    """A non-2xx REST response with a mapped ``{"error": {code, message}}`` body."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"[{status_code}] {code}: {message}")

    @classmethod
    def from_wire(
        cls,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any],
    ) -> PrismalAPIError:
        """Build from the host's error object; subclasses may read extra keys.

        ``details`` is the whole ``error`` object of an HTTP body, or the
        ``data`` of a stream ``error`` event. The base ignores everything
        beyond ``code``/``message``.
        """
        return cls(status_code, code, message)


class RuntimeCompositionError(PrismalAPIError):
    """503 — the server's default runtime failed to compose (readiness)."""


class PolicyDeniedError(PrismalAPIError):
    """403 — a policy gate denied the request."""


class PermissionDeniedError(PrismalAPIError):
    """403 — a permission grant was missing or expired."""


class BudgetExceededError(PrismalAPIError):
    """A cost/token/call budget was exceeded (SPEC-CS2-ERR-002).

    Host v0.2 answers ``402`` before a turn starts, or ends a stream with an
    ``error`` event carrying the partial ``usage``; v0.1 hosts used ``429``.
    Mapping is by ``code``, so all three surface as this class. ``scope``,
    ``limit`` and ``consumed`` are the host's values verbatim; each detail
    is ``None`` when the host omits it.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        scope: str | None = None,
        limit: Any = None,
        consumed: Any = None,
        usage: Usage | None = None,
    ) -> None:
        super().__init__(status_code, code, message)
        self.scope = scope
        self.limit = limit
        self.consumed = consumed
        self.usage = usage

    @classmethod
    def from_wire(
        cls,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any],
    ) -> PrismalAPIError:
        scope = details.get("scope")
        return cls(
            status_code,
            code,
            message,
            scope=scope if isinstance(scope, str) else None,
            limit=details.get("limit"),
            consumed=details.get("consumed"),
            usage=_partial_usage(details.get("usage")),
        )


def _partial_usage(raw: Any) -> Usage | None:
    # A malformed partial usage must not replace the budget error being
    # raised with a pydantic ValidationError; the error itself still surfaces.
    if not isinstance(raw, dict):
        return None
    try:
        return Usage.model_validate(raw)
    except pydantic.ValidationError:
        return None


class A2AAgentUnavailableError(PrismalAPIError):
    """502 — a remote A2A agent could not be reached."""


class ValidationError(PrismalAPIError):
    """422 — the request body failed server-side validation."""


class A2ANotEnabledError(PrismalAPIError):
    """404 on an A2A route — the host has ``a2a_enabled=false`` (SPEC-RHB-A2A-005)."""


# ── Host v0.2 codes (SPEC-CS2-ERR-001; host SPEC-RH2 §11) ──────────────────


class ProtocolNotEnabledError(PrismalAPIError):
    """406 — the requested stream protocol (e.g. AG-UI) is disabled for the tenant."""


class InvalidRequestError(PrismalAPIError):
    """400 — a malformed request, e.g. an invalid usage window (``invalid_window``)."""


class ForbiddenError(PrismalAPIError):
    """403 — the identity may not act for that tenant (``forbidden_tenant``)."""


class ServerConfigurationError(PrismalAPIError):
    """500 — the tenant's host configuration is invalid (``tenant_config_invalid``)."""


class TurnCancelledError(PrismalAPIError):
    """A stream ``error`` with code ``cancelled`` — the turn was cancelled."""


class AdminDisabledError(PrismalAPIError):
    """404 — admin routes are disabled on the host (``admin_disabled``)."""


# code (from the response body) -> exception class. Unmapped codes, or a
# missing/non-JSON error body, fall back to the base PrismalAPIError
# (SPEC-CSB-ERR-002).
_ERROR_CODE_MAP: dict[str, type[PrismalAPIError]] = {
    "runtime_composition_error": RuntimeCompositionError,
    "policy_denied": PolicyDeniedError,
    "permission_denied": PermissionDeniedError,
    "budget_exceeded": BudgetExceededError,
    "a2a_agent_unavailable": A2AAgentUnavailableError,
    "validation_error": ValidationError,
    "protocol_not_enabled": ProtocolNotEnabledError,
    "invalid_window": InvalidRequestError,
    "forbidden_tenant": ForbiddenError,
    "tenant_config_invalid": ServerConfigurationError,
    "cancelled": TurnCancelledError,
    "admin_disabled": AdminDisabledError,
}


def error_for_code(
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> PrismalAPIError:
    """Build the mapped exception instance for a server error ``code``.

    The class is chosen by ``code``, never by HTTP status, so HTTP bodies and
    stream ``error`` events share one table (SPEC-CS2-ERR-001).
    """
    klass = _ERROR_CODE_MAP.get(code, PrismalAPIError)
    return klass.from_wire(status_code, code, message, details or {})


# ── Transport-level errors (never reached the server) ───────────────────────


class PrismalTransportError(PrismalSDKError):
    """A request never got a response (mirrors ``httpx`` transport failures)."""


class PrismalConnectionError(PrismalTransportError):
    """DNS failure, connection refused, or similar (``httpx.TransportError``)."""


class PrismalTimeoutError(PrismalTransportError):
    """Connect or read timeout (``httpx.TimeoutException``)."""


# ── WebSocket session errors (SPEC-CS2-WSK-003) ────────────────────────────


class PrismalWebSocketError(PrismalTransportError):
    """A WebSocket session ended abnormally.

    ``close_code``/``reason`` come from the close frame; ``close_code`` is
    ``None`` when there was none (e.g. a malformed server frame). Codes
    without a dedicated subclass raise this base class.
    """

    def __init__(
        self, message: str, *, close_code: int | None = None, reason: str = ""
    ) -> None:
        super().__init__(message)
        self.close_code = close_code
        self.reason = reason


class WebSocketAuthenticationError(PrismalWebSocketError):
    """Close ``1008`` — the handshake credential was rejected (strict mode)."""


class TurnInProgressError(PrismalWebSocketError):
    """Close ``4409`` — a ``message`` arrived while a turn was still running."""


class WebSocketProtocolError(PrismalWebSocketError):
    """Close ``4400``, or a server frame the SDK cannot decode."""


class MessageTooLargeError(PrismalWebSocketError):
    """Close ``1009`` — a frame exceeded the size limit."""


class WebSocketServerError(PrismalWebSocketError):
    """Close ``1011`` — the host failed internally."""


class WebSocketUnavailableError(PrismalSDKError, ImportError):
    """``client.ws()`` without the optional ``websockets`` dependency."""


# ── A2A JSON-RPC errors — a distinct surface, never a PrismalAPIError ──────


class A2AJsonRpcError(PrismalSDKError):
    """A JSON-RPC ``error`` member returned by ``POST /a2a``.

    Deliberately does **not** subclass :class:`PrismalAPIError`: A2A stays
    JSON-RPC end to end (SPEC-RHB-SDK-002, "no prismal-specific extension"),
    so its error shape (``code: int``, ``message: str``) is kept distinct
    from the REST ``{"error": {"code": str, ...}}`` envelope.
    """

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"A2A JSON-RPC error [{code}]: {message}")


# Well-known JSON-RPC codes emitted by prismal-server's inbound A2A routes.
A2A_UNAUTHENTICATED = -32001  # a2a_strict + no/invalid credential
A2A_HANDLER_UNAVAILABLE = -32000  # engine's inbound A2A is not composed

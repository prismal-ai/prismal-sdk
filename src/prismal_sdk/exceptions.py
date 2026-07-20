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


class RuntimeCompositionError(PrismalAPIError):
    """503 — the server's default runtime failed to compose (readiness)."""


class PolicyDeniedError(PrismalAPIError):
    """403 — a policy gate denied the request."""


class PermissionDeniedError(PrismalAPIError):
    """403 — a permission grant was missing or expired."""


class BudgetExceededError(PrismalAPIError):
    """429 — a cost/token/call budget was exceeded."""


class A2AAgentUnavailableError(PrismalAPIError):
    """502 — a remote A2A agent could not be reached."""


class ValidationError(PrismalAPIError):
    """422 — the request body failed server-side validation."""


class A2ANotEnabledError(PrismalAPIError):
    """404 on an A2A route — the host has ``a2a_enabled=false`` (SPEC-RHB-A2A-005)."""


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
}


def error_for_code(status_code: int, code: str, message: str) -> PrismalAPIError:
    """Build the mapped exception instance for a server error ``code``."""
    klass = _ERROR_CODE_MAP.get(code, PrismalAPIError)
    return klass(status_code, code, message)


# ── Transport-level errors (never reached the server) ───────────────────────


class PrismalTransportError(PrismalSDKError):
    """A request never got a response (mirrors ``httpx`` transport failures)."""


class PrismalConnectionError(PrismalTransportError):
    """DNS failure, connection refused, or similar (``httpx.TransportError``)."""


class PrismalTimeoutError(PrismalTransportError):
    """Connect or read timeout (``httpx.TimeoutException``)."""


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

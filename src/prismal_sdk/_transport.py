"""Shared request-building, error-mapping, and retry logic (CSB-01-03).

Both :class:`~prismal_sdk.client.PrismalClient` and
:class:`~prismal_sdk.async_client.AsyncPrismalClient` call into this module so
header injection (SPEC-CSB-AUT-001/002), error mapping (SPEC-CSB-ERR-*), and
retry policy (SPEC-CSB-RSL-*) can never drift between the sync and async
surfaces (ARCHITECTURE.md ADR-005).

Internal module (leading underscore) — not part of the public API.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from prismal_sdk.exceptions import (
    PrismalAPIError,
    PrismalConnectionError,
    PrismalTimeoutError,
    error_for_code,
)

# Methods safe to retry automatically: read-only, or POST /threads (minting a
# new thread id is safe to redo — SPEC-CSB-RSL-001). Never includes the chat
# message endpoint or an established stream (SPEC-CSB-RSL-002).
_IDEMPOTENT_METHODS = frozenset({"GET"})

DEFAULT_BACKOFF_BASE_S = 0.25
DEFAULT_BACKOFF_CAP_S = 4.0


def build_headers(
    *, token: str | None, org_id: str | None, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Build the request headers for one call (SPEC-CSB-AUT-001/002).

    Only ``Authorization`` and ``X-Org-Id`` are ever added — no other
    prismal-specific header, per SPEC-RHB-SDK-003.
    """
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if org_id:
        headers["X-Org-Id"] = org_id
    if extra:
        headers.update(extra)
    return headers


def parse_error_body(response: httpx.Response) -> tuple[str, str]:
    """Extract ``(code, message)`` from a REST error body, tolerating malformed JSON.

    Falls back to ``("internal_error", <opaque>)`` for a non-JSON or
    unexpectedly shaped body (SPEC-CSB-ERR-002) — the SDK never crashes on an
    unexpected error shape.
    """
    try:
        body: Any = response.json()
    except (json.JSONDecodeError, ValueError):
        return "internal_error", f"HTTP {response.status_code}"

    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "internal_error", f"HTTP {response.status_code}"

    code = error.get("code")
    message = error.get("message")
    return (
        code if isinstance(code, str) else "internal_error",
        message if isinstance(message, str) else f"HTTP {response.status_code}",
    )


def extract_detail(response: httpx.Response) -> str:
    """Best-effort human-readable detail from a non-standard error body.

    Some routes (the A2A ``404`` "not enabled" case) raise a plain FastAPI
    ``HTTPException``, whose default body is ``{"detail": "..."}`` — a
    different shape from the ``{"error": {"code","message"}}`` envelope the
    rest of the API guarantees. This helper reads that shape (or falls back
    to a generic message) without assuming either is present.
    """
    try:
        body: Any = response.json()
    except (json.JSONDecodeError, ValueError):
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
    return f"HTTP {response.status_code}"


def raise_for_response(response: httpx.Response) -> None:
    """Raise the mapped :class:`PrismalAPIError` subclass for a non-2xx response.

    A no-op for 2xx. Callers still parse the body into a typed model
    themselves; this only guards the error path (SPEC-CSB-ERR-001).
    """
    if response.is_success:
        return
    code, message = parse_error_body(response)
    raise error_for_code(response.status_code, code, message)


def wrap_transport_exception(exc: httpx.HTTPError) -> PrismalAPIError | Exception:
    """Translate an ``httpx`` transport-level failure to an SDK exception.

    Returns the exception to raise rather than raising directly, so callers
    can ``raise wrap_transport_exception(exc) from exc`` and preserve the
    original traceback context (SPEC-CSB-ERR-003).
    """
    if isinstance(exc, httpx.TimeoutException):
        return PrismalTimeoutError(str(exc))
    if isinstance(exc, httpx.TransportError):
        return PrismalConnectionError(str(exc))
    # Any other httpx.HTTPError (e.g. a protocol error) — surface as a
    # connection-class failure rather than letting a raw httpx type escape.
    return PrismalConnectionError(str(exc))


def is_retryable(method: str, exc: httpx.HTTPError) -> bool:
    """Whether one failed attempt is eligible for another try (SPEC-CSB-RSL-*).

    Only connect/timeout failures on idempotent methods are retried; 4xx
    responses never reach this function (they raise a mapped
    :class:`PrismalAPIError` instead, which the caller does not retry).
    """
    if method.upper() not in _IDEMPOTENT_METHODS:
        return False
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


def backoff_delay_s(
    attempt: int,
    *,
    base_s: float = DEFAULT_BACKOFF_BASE_S,
    cap_s: float = DEFAULT_BACKOFF_CAP_S,
) -> float:
    """Exponential backoff for retry attempt ``attempt`` (0-indexed), capped."""
    return float(min(cap_s, base_s * (2**attempt)))

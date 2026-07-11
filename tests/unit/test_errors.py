"""Error-mapping tests (SPEC-CSB-ERR-*)."""

from __future__ import annotations

import httpx
import pytest

from prismal_sdk._transport import (
    is_retryable,
    parse_error_body,
    wrap_transport_exception,
)
from prismal_sdk.exceptions import (
    BudgetExceededError,
    PrismalAPIError,
    PrismalConnectionError,
    PrismalTimeoutError,
    error_for_code,
)


@pytest.mark.parametrize(
    ("code", "expected_type"),
    [
        ("budget_exceeded", BudgetExceededError),
        ("totally_unknown_code", PrismalAPIError),
    ],
)
def test_error_for_code_maps_known_and_falls_back(code, expected_type):
    exc = error_for_code(429, code, "over budget")
    assert isinstance(exc, expected_type)
    assert exc.status_code == 429
    assert exc.code == code


def test_parse_error_body_handles_malformed_json():
    response = httpx.Response(500, content=b"not json")
    code, message = parse_error_body(response)
    assert code == "internal_error"
    assert "500" in message


def test_wrap_transport_exception_timeout():
    exc = wrap_transport_exception(httpx.ConnectTimeout("timed out"))
    assert isinstance(exc, PrismalTimeoutError)


def test_wrap_transport_exception_connection():
    exc = wrap_transport_exception(httpx.ConnectError("refused"))
    assert isinstance(exc, PrismalConnectionError)


def test_is_retryable_only_for_idempotent_get():
    exc = httpx.ConnectTimeout("timed out")
    assert is_retryable("GET", exc) is True
    assert is_retryable("POST", exc) is False


def test_is_retryable_false_for_non_transport_error():
    class NotATransportError(httpx.HTTPError):
        pass

    assert is_retryable("GET", NotATransportError("weird")) is False


def test_all_sdk_exceptions_share_one_root():
    from prismal_sdk.exceptions import A2AJsonRpcError, PrismalSDKError

    assert issubclass(PrismalAPIError, PrismalSDKError)
    assert issubclass(PrismalConnectionError, PrismalSDKError)
    assert issubclass(A2AJsonRpcError, PrismalSDKError)
    assert not issubclass(A2AJsonRpcError, PrismalAPIError)

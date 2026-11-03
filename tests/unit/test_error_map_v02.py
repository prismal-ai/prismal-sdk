"""Host v0.2 error codes (CS2-01-05, SPEC-CS2-ERR-001/002)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from prismal_sdk.exceptions import (
    AdminDisabledError,
    BudgetExceededError,
    ForbiddenError,
    InvalidRequestError,
    PrismalAPIError,
    ProtocolNotEnabledError,
    ServerConfigurationError,
    TurnCancelledError,
    ValidationError,
    error_for_code,
)
from prismal_sdk.models import Usage
from tests.conftest import sse_body, sse_frame
from tests.wire_v02 import USAGE_EXAMPLE

# (host code, HTTP status the host documents, exception) — SPEC-RH2 §11.
_V02_CODES = [
    ("protocol_not_enabled", 406, ProtocolNotEnabledError),
    ("invalid_window", 400, InvalidRequestError),
    ("forbidden_tenant", 403, ForbiddenError),
    ("tenant_config_invalid", 500, ServerConfigurationError),
    ("cancelled", 200, TurnCancelledError),
    ("admin_disabled", 404, AdminDisabledError),
    ("budget_exceeded", 402, BudgetExceededError),
    # Added to SPEC-RH2 §11 during host RH2-2…7 (host v0.2.0).
    ("invalid_cursor", 400, InvalidRequestError),
    ("invalid_thread_id", 422, ValidationError),
    ("invalid_input", 422, ValidationError),
    ("forbidden", 403, ForbiddenError),
]


def _error_response(status: int, error: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": error})

    return handler


def _stream_error(error: dict[str, Any]):
    body = sse_body(
        sse_frame("token", json.dumps({"delta": "par"})),
        sse_frame("error", json.dumps(error)),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    return handler


@pytest.mark.parametrize(("code", "status", "klass"), _V02_CODES)
def test_every_v02_code_maps_to_its_api_error(code, status, klass):
    exc = error_for_code(status, code, "msg")
    assert type(exc) is klass
    assert isinstance(exc, PrismalAPIError)
    assert (exc.status_code, exc.code, exc.message) == (status, code, "msg")


# `cancelled` only ever arrives inside a 200 stream, never as an HTTP status.
_HTTP_CODES = [c for c in _V02_CODES if c[1] != 200]


@pytest.mark.parametrize(("code", "status", "klass"), _HTTP_CODES)
def test_http_error_bodies_use_the_same_table(make_client, code, status, klass):
    handler = _error_response(status, {"code": code, "message": "nope"})
    with make_client(handler) as client, pytest.raises(klass):
        client.create_thread()


@pytest.mark.parametrize(("code", "status", "klass"), _V02_CODES)
def test_stream_error_events_use_the_same_table(make_client, code, status, klass):
    handler = _stream_error({"code": code, "message": "nope"})
    with make_client(handler) as client, pytest.raises(klass):
        list(client.send_message("t-1", "hi"))


@pytest.mark.parametrize("status", [402, 429])
def test_class_is_chosen_by_code_not_status(make_client, status):
    handler = _error_response(status, {"code": "budget_exceeded", "message": "x"})
    with make_client(handler) as client, pytest.raises(BudgetExceededError) as info:
        client.create_thread()
    assert info.value.status_code == status


def test_budget_exceeded_402_exposes_scope_limit_consumed_verbatim(make_client):
    limit = {"tokens": 1000, "cost_usd": 1.0}
    consumed = {"tokens": 1200, "cost_usd": 0.4}
    handler = _error_response(
        402,
        {
            "code": "budget_exceeded",
            "message": "hard cap",
            "scope": "tenant",
            "limit": limit,
            "consumed": consumed,
        },
    )
    with make_client(handler) as client, pytest.raises(BudgetExceededError) as info:
        client.create_thread()
    exc = info.value
    assert exc.scope == "tenant"
    assert exc.limit == limit
    assert exc.consumed == consumed
    assert exc.usage is None


def test_budget_exceeded_without_details_leaves_fields_none(make_client):
    handler = _error_response(402, {"code": "budget_exceeded", "message": "x"})
    with make_client(handler) as client, pytest.raises(BudgetExceededError) as info:
        client.create_thread()
    exc = info.value
    assert (exc.scope, exc.limit, exc.consumed, exc.usage) == (None, None, None, None)


def test_mid_stream_budget_exceeded_carries_partial_usage(make_client):
    handler = _stream_error(
        {"code": "budget_exceeded", "message": "cap", "usage": USAGE_EXAMPLE}
    )
    with make_client(handler) as client, pytest.raises(BudgetExceededError) as info:
        list(client.send_message("t-1", "hi"))
    assert info.value.usage == Usage.model_validate(USAGE_EXAMPLE)


async def test_async_mid_stream_budget_exceeded_carries_partial_usage(
    make_async_client,
):
    handler = _stream_error(
        {"code": "budget_exceeded", "message": "cap", "usage": USAGE_EXAMPLE}
    )
    async with make_async_client(handler) as client:
        with pytest.raises(BudgetExceededError) as info:
            _ = [e async for e in client.send_message("t-1", "hi")]
    assert info.value.usage == Usage.model_validate(USAGE_EXAMPLE)


async def test_async_http_budget_exceeded_exposes_details(make_async_client):
    handler = _error_response(
        402, {"code": "budget_exceeded", "message": "x", "scope": "turn"}
    )
    async with make_async_client(handler) as client:
        with pytest.raises(BudgetExceededError) as info:
            await client.create_thread()
    assert info.value.scope == "turn"


def test_malformed_partial_usage_does_not_mask_the_budget_error(make_client):
    # A broken `usage` must not turn a budget error into a validation crash.
    handler = _stream_error(
        {"code": "budget_exceeded", "message": "cap", "usage": {"calls": "many"}}
    )
    with make_client(handler) as client, pytest.raises(BudgetExceededError) as info:
        list(client.send_message("t-1", "hi"))
    assert info.value.usage is None


def test_details_are_ignored_by_codes_that_do_not_use_them(make_client):
    handler = _error_response(
        403, {"code": "forbidden_tenant", "message": "x", "scope": "tenant"}
    )
    with make_client(handler) as client, pytest.raises(ForbiddenError) as info:
        client.create_thread()
    assert not hasattr(info.value, "scope")

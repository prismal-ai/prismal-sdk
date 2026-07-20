"""Malformed-body robustness (SPEC-CSB-ERR-002/004).

A server (or an intermediary proxy) can return a non-JSON or unexpectedly
shaped body on any route. The SDK must never let a raw ``json`` or ``httpx``
exception escape — everything surfaces under the ``PrismalSDKError`` root.
"""

from __future__ import annotations

import httpx
import pytest

from prismal_sdk.exceptions import PrismalSDKError

# A gateway returning HTML instead of the documented JSON envelope.
_HTML = b"<html><body>502 Bad Gateway</body></html>"


def _handler(status: int, content: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    return handler


@pytest.mark.parametrize("status", [200, 503])
def test_readyz_non_json_body_raises_sdk_error(make_client, status):
    with make_client(_handler(status, _HTML)) as client:
        with pytest.raises(PrismalSDKError):
            client.readyz()


def test_healthz_non_json_body_raises_sdk_error(make_client):
    with make_client(_handler(200, _HTML)) as client:
        with pytest.raises(PrismalSDKError):
            client.healthz()


def test_create_thread_non_json_body_raises_sdk_error(make_client):
    with make_client(_handler(200, _HTML)) as client:
        with pytest.raises(PrismalSDKError):
            client.create_thread()


def test_agent_card_non_json_body_raises_sdk_error(make_client):
    with make_client(_handler(200, _HTML)) as client:
        with pytest.raises(PrismalSDKError):
            client.agent_card()


def test_a2a_send_non_json_body_raises_sdk_error(make_client):
    with make_client(_handler(200, _HTML)) as client:
        with pytest.raises(PrismalSDKError):
            client.a2a.send("message/send", {})


@pytest.mark.parametrize("status", [200, 503])
async def test_async_readyz_non_json_body_raises_sdk_error(make_async_client, status):
    async with make_async_client(_handler(status, _HTML)) as client:
        with pytest.raises(PrismalSDKError):
            await client.readyz()


async def test_async_a2a_send_non_json_body_raises_sdk_error(make_async_client):
    async with make_async_client(_handler(200, _HTML)) as client:
        with pytest.raises(PrismalSDKError):
            await client.a2a.send("message/send", {})

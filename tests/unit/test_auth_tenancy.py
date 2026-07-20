"""Auth & tenancy tests (CSB-04-01/02 — SPEC-CSB-AUT-001..004, NFR-005).

Closes the coverage gap for two tasks TASKS.md marked DONE without a test.
"""

from __future__ import annotations

import httpx
import pytest

from prismal_sdk.exceptions import PrismalSDKError

TOKEN = "super-secret-token-value"


def _capture(response: httpx.Response | None = None):
    """Handler recording every request it sees."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if response is not None:
            return response
        return httpx.Response(200, json={"status": "ok"})

    return handler, seen


# --- SPEC-CSB-AUT-003 / NFR-005: the token never leaks -----------------------


def test_token_absent_from_client_repr(make_client):
    handler, _ = _capture()
    with make_client(handler, token=TOKEN) as client:
        assert TOKEN not in repr(client)
        assert TOKEN not in str(client)
        assert TOKEN not in repr(client.a2a)


def test_token_absent_from_api_error_message(make_client):
    handler, _ = _capture(
        httpx.Response(401, json={"error": {"code": "unauthorized", "message": "nope"}})
    )
    with make_client(handler, token=TOKEN) as client:
        with pytest.raises(PrismalSDKError) as excinfo:
            client.healthz()
    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(excinfo.value)


def test_token_absent_from_transport_error_message(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with make_client(handler, token=TOKEN, max_retries=0) as client:
        with pytest.raises(PrismalSDKError) as excinfo:
            client.healthz()
    assert TOKEN not in str(excinfo.value)


# --- SPEC-CSB-AUT-001/002: headers on every route ---------------------------


def test_no_authorization_header_when_token_unset(make_client):
    handler, seen = _capture()
    with make_client(handler) as client:
        client.healthz()
    assert "authorization" not in seen[0].headers


def test_no_org_header_when_org_id_unset(make_client):
    handler, seen = _capture()
    with make_client(handler) as client:
        client.healthz()
    assert "x-org-id" not in seen[0].headers


def test_only_documented_prismal_headers_are_added(make_client):
    # SPEC-CSB-AUT-002: "MUST NOT send any other prismal-specific header".
    handler, seen = _capture()
    with make_client(handler, token=TOKEN, org_id="acme") as client:
        client.healthz()
    prismal_headers = {
        name for name in seen[0].headers if name.lower().startswith(("x-", "prismal"))
    }
    assert prismal_headers == {"x-org-id"}


# --- SPEC-CSB-AUT-004: per-call org_id override -----------------------------


def test_send_message_org_id_override(make_client):
    body = b'event: done\ndata: {"thread_id": "t1", "finish_reason": "stop"}\n\n'
    handler, seen = _capture(httpx.Response(200, content=body))
    with make_client(handler, org_id="default-org") as client:
        list(client.send_message("t1", "hola", org_id="acme"))
    assert seen[0].headers["x-org-id"] == "acme"


def test_agent_card_org_id_override(make_client):
    handler, seen = _capture(httpx.Response(200, json={"name": "agent"}))
    with make_client(handler, org_id="default-org") as client:
        client.agent_card(org_id="acme")
    assert seen[0].headers["x-org-id"] == "acme"


def test_a2a_send_org_id_override(make_client):
    handler, seen = _capture(httpx.Response(200, json={"jsonrpc": "2.0", "result": {}}))
    with make_client(handler, org_id="default-org") as client:
        client.a2a.send("message/send", {}, org_id="acme")
    assert seen[0].headers["x-org-id"] == "acme"


def test_client_default_org_id_used_when_no_override(make_client):
    handler, seen = _capture(httpx.Response(200, json={"jsonrpc": "2.0", "result": {}}))
    with make_client(handler, org_id="default-org") as client:
        client.a2a.send("message/send", {})
    assert seen[0].headers["x-org-id"] == "default-org"


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.a2a.message_send({}, org_id="acme"),
        lambda c: c.a2a.tasks_get({}, org_id="acme"),
        lambda c: c.a2a.tasks_cancel({}, org_id="acme"),
    ],
    ids=["message_send", "tasks_get", "tasks_cancel"],
)
def test_a2a_typed_wrappers_forward_org_id(make_client, call):
    # The typed wrappers must not drop the per-call tenant (SPEC-CSB-AUT-004);
    # a dropped X-Org-Id silently routes a call to the wrong tenant.
    handler, seen = _capture(httpx.Response(200, json={"jsonrpc": "2.0", "result": {}}))
    with make_client(handler, org_id="default-org") as client:
        call(client)
    assert seen[0].headers["x-org-id"] == "acme"

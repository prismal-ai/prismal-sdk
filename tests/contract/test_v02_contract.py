"""v0.2 contract suite (CS2-05-01, SPEC-CS2-CTR-001/002) — closes CSB-05-01.

Runs against a **fake-LLM** ``prismal-server`` 0.2 (``host_fake_llm_mode=true``,
SPEC-RH2-FAK-*), so every answer is deterministic and no provider credential
is needed. Opt-in, like the smoke suite::

    PRISMAL_BASE_URL=http://localhost:8000 uv run pytest -m contract

Every test skips when no healthy host answers ``/healthz``. A host that
answers but is *not* in fake mode fails instead: the assertions below pin the
fake script, so a skip there would be a false green. Optional host surfaces
skip when the host says they are off (A2A ``404``, admin ``404``); the
WebSocket turn skips only when the ``[ws]`` extra is not installed.

``PRISMAL_TOKEN`` / ``PRISMAL_ORG_ID`` are passed through when set. Without
the admin scope, the admin reads are checked live for their ``403`` →
``ForbiddenError`` mapping; their ``200`` bodies need ``PRISMAL_ADMIN_TOKEN``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from prismal_sdk import (
    A2AJsonRpcError,
    A2ANotEnabledError,
    AdminDisabledError,
    AsyncPrismalClient,
    ForbiddenError,
    InvalidRequestError,
    PrismalAPIError,
    PrismalClient,
    ValidationError,
)
from prismal_sdk.agui import (
    PrismalUsageEvent,
    RunFinished,
    RunStarted,
    TextMessageContent,
)
from prismal_sdk.models import DoneEvent, TokenEvent, ToolCallEvent, Usage

pytestmark = pytest.mark.contract

BASE_URL = os.environ.get("PRISMAL_BASE_URL", "http://localhost:8000")
TOKEN = os.environ.get("PRISMAL_TOKEN") or None
ORG_ID = os.environ.get("PRISMAL_ORG_ID") or None

FAKE_HEADER = "x-prismal-fake-llm"

#: ``done.usage`` of every fake turn (SPEC-RH2-FAK-002).
FAKE_USAGE = Usage.model_validate(
    {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 15,
        "calls": 1,
        "cost_usd": 0.0,
        "cost_source": "none",
        "estimated": True,
        "served_model": "fake/echo",
        "gateway": None,
    }
)

#: The fake script streams its reply in chunks of at most this many chars.
MAX_CHUNK = 16


def _healthz() -> httpx.Response | None:
    try:
        response = httpx.get(f"{BASE_URL}/healthz", timeout=1.0)
    except Exception:  # noqa: BLE001 — any network oddity means "no host"
        return None
    try:
        healthy = response.status_code == 200 and response.json().get("status") == "ok"
    except ValueError:
        return None
    return response if healthy else None


@pytest.fixture(scope="module")
def fake_host() -> httpx.Response:
    response = _healthz()
    if response is None:
        pytest.skip(f"no prismal-server reachable at {BASE_URL}")
    if response.headers.get(FAKE_HEADER) != "1":
        pytest.fail(
            f"{BASE_URL} is not a fake-LLM prismal-server 0.2 "
            f"(no '{FAKE_HEADER}: 1' header); start it with "
            "PRISMAL_SERVER_HOST_FAKE_LLM_MODE=true"
        )
    return response


@pytest.fixture
def client(fake_host: httpx.Response) -> Iterator[PrismalClient]:
    with PrismalClient(BASE_URL, token=TOKEN, org_id=ORG_ID) as c:
        yield c


def _content() -> str:
    return f"contract {uuid.uuid4().hex}"


def _native_turn(client: PrismalClient, content: str) -> tuple[str, list[Any]]:
    thread_id = client.create_thread().thread_id
    return thread_id, list(client.send_message(thread_id, content))


def _assert_echo(tokens: list[str], content: str) -> None:
    assert "".join(tokens) == "echo: " + content[:200]
    assert all(0 < len(token) <= MAX_CHUNK for token in tokens)


# ── health ──────────────────────────────────────────────────────────────────


def test_fake_llm_header_on_every_response(fake_host: httpx.Response) -> None:
    assert fake_host.headers[FAKE_HEADER] == "1"
    ready = httpx.get(f"{BASE_URL}/readyz", timeout=5.0)
    assert ready.headers.get(FAKE_HEADER) == "1"


def test_health_and_ready(client: PrismalClient) -> None:
    assert client.healthz().status == "ok"
    assert client.readyz().status == "ready"


# ── native chat (SPEC-RH2-FAK-002) ──────────────────────────────────────────


def test_native_turn_echoes_and_reports_usage(client: PrismalClient) -> None:
    content = _content()
    thread_id, events = _native_turn(client, content)

    tokens = [e.delta for e in events if isinstance(e, TokenEvent)]
    _assert_echo(tokens, content)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.thread_id == thread_id
    assert done.usage == FAKE_USAGE


def test_long_content_is_echoed_truncated(client: PrismalClient) -> None:
    content = "x" * 300
    _, events = _native_turn(client, content)
    _assert_echo([e.delta for e in events if isinstance(e, TokenEvent)], content)


def test_tool_command_yields_a_tool_call(client: PrismalClient) -> None:
    _, events = _native_turn(client, "/tool weather in Caracas")
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert calls == [ToolCallEvent(name="fake_tool", args={"q": "weather in Caracas"})]


def test_error_command_raises_the_mapped_error(client: PrismalClient) -> None:
    thread_id = client.create_thread().thread_id
    with pytest.raises(PrismalAPIError) as info:
        list(client.send_message(thread_id, "/error"))
    # `internal_error` has no dedicated class: the base type, not a subclass.
    assert type(info.value) is PrismalAPIError
    assert info.value.code == "internal_error"
    assert info.value.message == "fake error"


async def test_async_native_turn(fake_host: httpx.Response) -> None:
    content = _content()
    async with AsyncPrismalClient(BASE_URL, token=TOKEN, org_id=ORG_ID) as client:
        thread_id = (await client.create_thread()).thread_id
        events = [e async for e in client.send_message(thread_id, content)]
    _assert_echo([e.delta for e in events if isinstance(e, TokenEvent)], content)
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].usage == FAKE_USAGE


# ── AG-UI (SPEC-CS2-AGU-*) ──────────────────────────────────────────────────


def test_agui_turn(client: PrismalClient) -> None:
    content = _content()
    thread_id = client.create_thread().thread_id
    events = list(client.send_message(thread_id, content, protocol="ag-ui"))

    assert isinstance(events[0], RunStarted)
    assert isinstance(events[-1], RunFinished)
    text = "".join(e.delta for e in events if isinstance(e, TextMessageContent))
    assert text == "echo: " + content[:200]
    usage = [e for e in events if isinstance(e, PrismalUsageEvent)]
    assert len(usage) == 1
    assert usage[0].value == FAKE_USAGE
    assert events.index(usage[0]) == len(events) - 2  # just before RUN_FINISHED


# ── usage & budget (SPEC-CS2-USE-*, BUD-*) ──────────────────────────────────


def test_usage_contains_the_turn(client: PrismalClient) -> None:
    thread_id, _ = _native_turn(client, _content())

    report = client.usage(thread_id=thread_id)
    assert [turn.thread_id for turn in report.turns] == [thread_id]
    assert report.turns[0].usage == FAKE_USAGE
    assert report.totals.total_tokens == FAKE_USAGE.total_tokens

    turns = list(client.iter_usage_turns(thread_id=thread_id, page_size=1))
    assert [turn.turn_id for turn in turns] == [report.turns[0].turn_id]


def test_bad_usage_cursor_raises_invalid_request(client: PrismalClient) -> None:
    with pytest.raises(InvalidRequestError) as info:
        client.usage(cursor="not-a-cursor")
    assert info.value.code == "invalid_cursor"


def test_org_scoped_shaped_thread_id_raises_validation(client: PrismalClient) -> None:
    # Single-tenant hosts refuse a raw id shaped `^\d+:` (SPEC-RH2-THR-001).
    if ORG_ID is not None:
        pytest.skip("only a single-tenant host refuses `^\\d+:` thread ids")
    with pytest.raises(ValidationError) as info:
        list(client.send_message("1:contract", "hi"))
    assert info.value.code == "invalid_thread_id"


def test_budget_parses(client: PrismalClient) -> None:
    report = client.budget()
    assert isinstance(report.enabled, bool)
    assert report.status


# ── WebSocket (SPEC-CS2-WSK-*) ──────────────────────────────────────────────


def test_ws_turn(client: PrismalClient) -> None:
    pytest.importorskip("websockets", reason="needs the [ws] extra")
    content = _content()
    thread_id = client.create_thread().thread_id
    with client.ws(thread_id) as session:
        first = list(session.send_message(content))
        second = list(session.send_message(content, protocol="ag-ui"))

    _assert_echo([e.delta for e in first if isinstance(e, TokenEvent)], content)
    assert isinstance(first[-1], DoneEvent)
    assert first[-1].usage == FAKE_USAGE
    assert isinstance(second[-1], RunFinished)


# ── A2A v1 (SPEC-CS2-A2A-*), when the host enables A2A ──────────────────────


def test_agent_card_v1(client: PrismalClient) -> None:
    try:
        card = client.agent_card(protocol_version="1.0")
    except A2ANotEnabledError:
        pytest.skip("A2A is not enabled on this prismal-server instance")
    assert card.name
    assert any(
        i.protocol_binding == "JSONRPC" and (i.protocol_version or "").startswith("1.")
        for i in card.supported_interfaces or []
    )


def test_a2a_v1_tasks_list(client: PrismalClient) -> None:
    with PrismalClient(BASE_URL, token=TOKEN, org_id=ORG_ID, a2a_protocol="1.0") as v1:
        try:
            page = v1.a2a.tasks_list(page_size=10)
        except A2ANotEnabledError:
            pytest.skip("A2A is not enabled on this prismal-server instance")
        except A2AJsonRpcError as exc:
            # A fake-mode host serves the card but composes no inbound A2A
            # handler, so `POST /a2a` answers a JSON-RPC "not enabled" error
            # (prismal-server docs/fake-mode.md). Reaching here already proves
            # the SDK surfaced it typed, never swallowed (SPEC-CSB-A2A-003).
            pytest.skip(f"host composes no inbound A2A handler in fake mode: {exc}")
    assert isinstance(page.tasks, list)
    assert isinstance(page.next_page_token, str)


# ── admin reads (SPEC-CS2-ADM-*), when the host enables them ────────────────

#: A bearer token holding the host's admin scope (``prismal:admin``). The
#: host's built-in ``none``/``bearer`` backends never attach scopes, so a stock
#: fake-mode host can only be read with a token from a scope-granting backend.
ADMIN_TOKEN = os.environ.get("PRISMAL_ADMIN_TOKEN") or None


def _admin_reads(client: PrismalClient) -> list[Any]:
    return [
        client.tenants,
        client.decisions_report,
        client.routing_report,
        lambda: client.audit(page=1, page_size=10),
    ]


def test_admin_reads_without_scope_raise_forbidden(client: PrismalClient) -> None:
    if TOKEN is not None and TOKEN == ADMIN_TOKEN:
        pytest.skip("PRISMAL_TOKEN holds the admin scope")
    for read in _admin_reads(client):
        try:
            read()
        except AdminDisabledError:
            pytest.skip("admin routes are disabled on this prismal-server instance")
        except ForbiddenError as exc:
            assert exc.status_code == 403
            assert exc.code == "forbidden"
        else:
            pytest.fail(f"{read} succeeded without the admin scope")


def test_admin_reads(fake_host: httpx.Response) -> None:
    if ADMIN_TOKEN is None:
        pytest.skip("set PRISMAL_ADMIN_TOKEN to a token holding the admin scope")
    with PrismalClient(BASE_URL, token=ADMIN_TOKEN, org_id=ORG_ID) as client:
        try:
            tenants = client.tenants()
        except AdminDisabledError:
            pytest.skip("admin routes are disabled on this prismal-server instance")
        assert isinstance(tenants, list)
        client.decisions_report()
        client.routing_report()
        page = client.audit(page=1, page_size=10)
    assert isinstance(page.entries, list)

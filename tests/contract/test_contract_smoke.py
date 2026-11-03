"""Opt-in contract suite (CSB-05-01, SPEC-CSB-NFR-003).

Exercises a **running** ``prismal-server`` instance — not run by default.
Point it at a local host with:

    uvicorn prismal_server.app:app --reload   # in a prismal-server checkout
    PRISMAL_BASE_URL=http://localhost:8000 uv run pytest -m contract

``PRISMAL_BASE_URL`` defaults to ``http://localhost:8000`` (SPEC-CS2-CTR-001).

Deselected by default (`pytest.ini_options.addopts` carries `-m 'not
contract'`, which a command-line `-m contract` overrides); every test here is
marked ``contract`` and skips itself unless a *healthy* ``prismal-server``
answers the liveness probe, so `uv run pytest -m contract` never fails just
because no server — or some unrelated service — happens to be on the port.
"""

from __future__ import annotations

import os

import httpx
import pytest

from prismal_sdk import PrismalClient

pytestmark = pytest.mark.contract

BASE_URL = os.environ.get("PRISMAL_BASE_URL", "http://localhost:8000")


def _server_reachable() -> bool:
    # Liveness probe: require a *healthy prismal-server*, not merely "something
    # answered". A bare `httpx.get` that doesn't inspect the response treats an
    # unrelated service (or a 500-ing host) on the port as reachable, so the
    # suite runs and then fails instead of skipping. We insist on HTTP 200 with
    # the documented `{"status": "ok"}` body (SPEC-CSB-HLT-001). Any networking
    # oddity or unexpected shape degrades to "skip the contract suite".
    try:
        resp = httpx.get(f"{BASE_URL}/healthz", timeout=1.0)
        return resp.status_code == 200 and resp.json().get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def client():
    if not _server_reachable():
        pytest.skip(f"no prismal-server reachable at {BASE_URL}")
    with PrismalClient(BASE_URL) as c:
        yield c


def test_healthz(client: PrismalClient) -> None:
    assert client.healthz().status == "ok"


def test_create_thread_and_send_message(client: PrismalClient) -> None:
    thread = client.create_thread()
    assert thread.thread_id

    events = list(
        client.send_message(thread.thread_id, "Hello from the contract suite")
    )
    assert events, "expected at least one SSE event"


def test_agent_card_or_not_enabled(client: PrismalClient) -> None:
    from prismal_sdk.exceptions import A2ANotEnabledError

    try:
        card = client.agent_card()
        assert card.name
    except A2ANotEnabledError:
        pytest.skip("A2A is not enabled on this prismal-server instance")

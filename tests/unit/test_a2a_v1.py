"""A2A v1.0: version negotiation, method table, tasks_list (CS2-04-01..04).

SPEC-CS2-A2A-001..006 against the engine's A2A v1 fixtures (ADR-PRT-001
§2.1). Sync cases first; async mirrors at the end.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from prismal_sdk._a2a_methods import A2A_METHODS
from prismal_sdk.exceptions import (
    A2A_VERSION_NOT_SUPPORTED,
    A2AJsonRpcError,
    A2ANotEnabledError,
    A2AVersionError,
    PrismalSDKError,
)
from prismal_sdk.models import AgentCard, TaskListPage
from tests.wire_v02 import A2A_V03_CARD, A2A_V1

CARD_PATH = "/.well-known/agent-card.json"
V1_CARD = A2A_V1["agent_card"]
LIST_RESULT = A2A_V1["list_tasks_response"]["result"]


class FakeA2AHost:
    """Records requests; serves a card per X-Org-Id and JSON-RPC results."""

    def __init__(
        self,
        cards: dict[str | None, dict[str, Any]] | None = None,
        result: Any = None,
        stream_body: bytes | None = None,
    ) -> None:
        self.cards = cards if cards is not None else {None: V1_CARD}
        self.result = result if result is not None else {}
        self.stream_body = stream_body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == CARD_PATH:
            org = request.headers.get("x-org-id")
            return httpx.Response(200, json=self.cards.get(org, self.cards[None]))
        if self.stream_body is not None:
            return httpx.Response(200, content=self.stream_body)
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": self.result}
        )

    @property
    def posts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST"]

    @property
    def card_gets(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == CARD_PATH]

    def rpc(self, i: int = -1) -> dict[str, Any]:
        return json.loads(self.posts[i].content)


_WRAPPERS = [
    ("message_send", lambda a, **kw: a.message_send({"m": 1}, **kw)),
    ("tasks_get", lambda a, **kw: a.tasks_get({"id": "t"}, **kw)),
    ("tasks_cancel", lambda a, **kw: a.tasks_cancel({"id": "t"}, **kw)),
    ("message_stream", lambda a, **kw: list(a.message_stream({"m": 1}, **kw))),
]
_WRAPPER_IDS = [w[0] for w in _WRAPPERS]
_STREAM = b'data: {"result": {"n": 1}}\n\n'


# ── the method table (A2A-002) ─────────────────────────────────────────────


def test_method_table_is_pinned_from_adr_prt_001():
    assert A2A_METHODS["0.3"] == {
        "message_send": "message/send",
        "message_stream": "message/stream",
        "tasks_get": "tasks/get",
        "tasks_cancel": "tasks/cancel",
    }
    assert A2A_METHODS["1.0"] == {
        "message_send": "SendMessage",
        "message_stream": "SendStreamingMessage",
        "tasks_get": "GetTask",
        "tasks_cancel": "CancelTask",
        "tasks_list": "ListTasks",
    }


# ── modes and the default (A2A-001, A2A-006) ───────────────────────────────


@pytest.mark.parametrize(("op", "call"), _WRAPPERS, ids=_WRAPPER_IDS)
def test_default_mode_is_v01_behaviour(make_client, op, call):
    host = FakeA2AHost(stream_body=_STREAM if op == "message_stream" else None)
    with make_client(host) as client:
        call(client.a2a)
    assert host.card_gets == []  # no implicit negotiation round-trip
    assert host.rpc()["method"] == A2A_METHODS["0.3"][op]
    assert "a2a-version" not in host.posts[0].headers


@pytest.mark.parametrize(("op", "call"), _WRAPPERS, ids=_WRAPPER_IDS)
def test_explicit_v1_uses_v1_names_and_header_without_a_card(make_client, op, call):
    host = FakeA2AHost(stream_body=_STREAM if op == "message_stream" else None)
    with make_client(host, a2a_protocol="1.0") as client:
        call(client.a2a)
    assert host.card_gets == []
    assert host.rpc()["method"] == A2A_METHODS["1.0"][op]
    assert host.posts[0].headers["A2A-Version"] == "1.0"


@pytest.mark.parametrize(("op", "call"), _WRAPPERS, ids=_WRAPPER_IDS)
def test_auto_negotiates_once_from_the_card(make_client, op, call):
    host = FakeA2AHost(stream_body=_STREAM if op == "message_stream" else None)
    with make_client(host, a2a_protocol="auto") as client:
        call(client.a2a)
        call(client.a2a)
    assert len(host.card_gets) == 1
    assert [json.loads(p.content)["method"] for p in host.posts] == [
        A2A_METHODS["1.0"][op]
    ] * 2
    assert all(p.headers["A2A-Version"] == "1.0" for p in host.posts)


def test_invalid_mode_is_rejected_at_construction(make_client):
    with pytest.raises(ValueError, match="a2a_protocol"):
        make_client(FakeA2AHost(), a2a_protocol="2.0")


@pytest.mark.parametrize(
    ("card", "expected"),
    [
        pytest.param(V1_CARD, "1.0", id="v1-card-jsonrpc-1.0"),
        pytest.param(A2A_V03_CARD, "0.3", id="v03-card-top-level-0.3.0"),
        pytest.param(
            {"name": "x", "protocolVersion": "1.0"}, "1.0", id="v03-shape-1.0"
        ),
        pytest.param({"name": "x"}, "0.3", id="no-version-at-all"),
        pytest.param(
            {
                "supportedInterfaces": [
                    {
                        "url": "u",
                        "protocolBinding": "HTTP+JSON",
                        "protocolVersion": "1.0",
                    },
                    {
                        "url": "u",
                        "protocolBinding": "JSONRPC",
                        "protocolVersion": "0.3",
                    },
                ]
            },
            "0.3",
            id="v1-only-over-http-json",
        ),
        pytest.param(
            {
                "supportedInterfaces": [
                    {"protocolBinding": "JSONRPC", "protocolVersion": "1.0.1"}
                ]
            },
            "1.0",
            id="major-1-patch",
        ),
        pytest.param(
            {"name": "x", "protocolVersion": "10.0"}, "0.3", id="major-10-is-not-1"
        ),
    ],
)
def test_negotiated_version_from_card_shapes(make_client, card, expected):
    host = FakeA2AHost(cards={None: card})
    with make_client(host, a2a_protocol="auto") as client:
        assert client.a2a.negotiated_version() == expected
        assert client.a2a.negotiated_version() == expected
    assert len(host.card_gets) == 1


@pytest.mark.parametrize("mode", ["0.3", "1.0"])
def test_negotiated_version_in_explicit_mode_does_no_io(make_client, mode):
    host = FakeA2AHost()
    with make_client(host, a2a_protocol=mode) as client:
        assert client.a2a.negotiated_version() == mode
    assert host.requests == []


def test_negotiation_is_cached_per_tenant(make_client):
    # Hosts may pin a2a_protocol_version per tenant (SPEC-RH2-TEN-002).
    host = FakeA2AHost(cards={None: V1_CARD, "legacy": A2A_V03_CARD})
    with make_client(host, a2a_protocol="auto", org_id="acme") as client:
        assert client.a2a.negotiated_version() == "1.0"
        assert client.a2a.negotiated_version(org_id="legacy") == "0.3"
        client.a2a.tasks_get({"id": "t"}, org_id="legacy")
        client.a2a.tasks_get({"id": "t"})
    assert [r.headers["x-org-id"] for r in host.card_gets] == ["acme", "legacy"]
    assert [json.loads(p.content)["method"] for p in host.posts] == [
        "tasks/get",
        "GetTask",
    ]


def test_card_404_during_negotiation_raises_not_enabled(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    with make_client(handler, a2a_protocol="auto") as client:
        with pytest.raises(A2ANotEnabledError):
            client.a2a.message_send({})


# ── raw send/stream keep caller control ────────────────────────────────────


def test_raw_send_adds_the_header_only_in_explicit_v1_mode(make_client):
    host = FakeA2AHost()
    with make_client(host, a2a_protocol="1.0") as client:
        client.a2a.send("GetExtendedAgentCard", {})
    with make_client(host, a2a_protocol="auto") as client:
        client.a2a.send("SendMessage", {})
    with make_client(host) as client:
        client.a2a.send("message/send", {})
    first, second, third = host.posts
    assert first.headers["A2A-Version"] == "1.0"
    assert "a2a-version" not in second.headers  # raw call: no implicit negotiation
    assert "a2a-version" not in third.headers
    assert host.card_gets == []


def test_raw_stream_follows_the_same_header_rule(make_client):
    host = FakeA2AHost(stream_body=_STREAM)
    with make_client(host, a2a_protocol="1.0") as client:
        list(client.a2a.stream("SendStreamingMessage", {}))
    with make_client(host) as client:
        list(client.a2a.stream("message/stream", {}))
    assert host.posts[0].headers["A2A-Version"] == "1.0"
    assert "a2a-version" not in host.posts[1].headers


def test_stream_maps_a_non_404_error_body(make_client):
    from prismal_sdk.exceptions import BudgetExceededError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402, json={"error": {"code": "budget_exceeded", "message": "cap"}}
        )

    with make_client(handler, a2a_protocol="1.0") as client:
        with pytest.raises(BudgetExceededError):
            list(client.a2a.message_stream({}))


# ── payloads pass through unconverted (A2A-005) ────────────────────────────


@pytest.mark.parametrize(
    ("fixture", "call"),
    [
        ("send_message_request", lambda a, p: a.message_send(p)),
        ("get_task_request", lambda a, p: a.tasks_get(p)),
        ("cancel_task_request", lambda a, p: a.tasks_cancel(p)),
    ],
    ids=["SendMessage", "GetTask", "CancelTask"],
)
def test_v1_requests_match_the_engine_fixtures(make_client, fixture, call):
    expected = A2A_V1[fixture]
    host = FakeA2AHost()
    with make_client(host, a2a_protocol="1.0") as client:
        call(client.a2a, expected["params"])
    sent = host.rpc()
    assert (sent["jsonrpc"], sent["method"], sent["params"]) == (
        "2.0",
        expected["method"],
        expected["params"],
    )


# ── tasks_list (A2A-003) ───────────────────────────────────────────────────


def test_tasks_list_matches_the_engine_fixture(make_client):
    expected = A2A_V1["list_tasks_request"]
    host = FakeA2AHost(result=LIST_RESULT)
    with make_client(host, a2a_protocol="1.0") as client:
        page = client.a2a.tasks_list(
            tenant="acme",
            context_id="ctx-1",
            status="TASK_STATE_WORKING",
            page_size=50,
            page_token=expected["params"]["pageToken"],
            history_length=2,
            status_timestamp_after="2026-10-01T00:00:00Z",
            include_artifacts=True,
        )
    sent = host.rpc()
    assert sent["method"] == "ListTasks"
    assert sent["params"] == expected["params"]
    assert host.posts[0].headers["A2A-Version"] == "1.0"
    assert isinstance(page, TaskListPage)
    assert [t["id"] for t in page.tasks] == ["task-2", "task-1"]
    assert (page.page_size, page.total_size) == (50, 2)
    assert page.next_page_token == ""  # verbatim, not mapped to None


def test_tasks_list_sends_only_given_params(make_client):
    host = FakeA2AHost(result=LIST_RESULT)
    with make_client(host, a2a_protocol="1.0") as client:
        client.a2a.tasks_list()
    assert host.rpc()["params"] == {"pageSize": 50}


def test_tasks_list_paging_by_token(make_client):
    pages = {
        None: {**LIST_RESULT, "nextPageToken": "p2", "totalSize": 3},
        "p2": {**LIST_RESULT, "tasks": [{"id": "task-0"}], "nextPageToken": ""},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        result = pages[body["params"].get("pageToken")]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    ids: list[str] = []
    with make_client(handler, a2a_protocol="1.0") as client:
        token: str | None = None
        while True:
            page = client.a2a.tasks_list(page_token=token)
            ids += [t["id"] for t in page.tasks]
            if not page.next_page_token:
                break
            token = page.next_page_token
    assert ids == ["task-2", "task-1", "task-0"]


@pytest.mark.parametrize("missing", ["nextPageToken", "pageSize", "totalSize"])
def test_tasks_list_result_missing_a_required_key_fails_loudly(make_client, missing):
    import pydantic

    result = {k: v for k, v in LIST_RESULT.items() if k != missing}
    with make_client(FakeA2AHost(result=result), a2a_protocol="1.0") as client:
        with pytest.raises(pydantic.ValidationError):
            client.a2a.tasks_list()


def test_tasks_list_keeps_unknown_result_fields(make_client):
    host = FakeA2AHost(result={**LIST_RESULT, "cursorExpiresAt": "soon"})
    with make_client(host, a2a_protocol="1.0") as client:
        page = client.a2a.tasks_list()
    assert page.model_dump(by_alias=True)["cursorExpiresAt"] == "soon"


@pytest.mark.parametrize("mode", ["0.3", "auto"])
def test_tasks_list_against_a_v03_peer_raises_without_posting(make_client, mode):
    host = FakeA2AHost(cards={None: A2A_V03_CARD})
    with make_client(host, a2a_protocol=mode) as client:
        with pytest.raises(A2AVersionError) as info:
            client.a2a.tasks_list()
    assert host.posts == []
    assert isinstance(info.value, PrismalSDKError)
    assert not isinstance(info.value, A2AJsonRpcError)
    assert "ListTasks" in str(info.value)


@pytest.mark.parametrize("page_size", [0, -1, 101])
def test_tasks_list_page_size_out_of_range_raises_before_io(make_client, page_size):
    host = FakeA2AHost()
    with make_client(host, a2a_protocol="auto") as client:
        with pytest.raises(ValueError, match="page_size"):
            client.a2a.tasks_list(page_size=page_size)
    assert host.requests == []


@pytest.mark.parametrize("page_size", [1, 100])
def test_tasks_list_page_size_bounds_are_inclusive(make_client, page_size):
    host = FakeA2AHost(result=LIST_RESULT)
    with make_client(host, a2a_protocol="1.0") as client:
        client.a2a.tasks_list(page_size=page_size)
    assert host.rpc()["params"]["pageSize"] == page_size


def test_tasks_list_forwards_org_id_and_request_id(make_client):
    host = FakeA2AHost(result=LIST_RESULT)
    with make_client(host, a2a_protocol="auto", org_id="home") as client:
        client.a2a.tasks_list(org_id="acme", request_id="r-9")
    assert host.card_gets[0].headers["x-org-id"] == "acme"
    assert host.posts[0].headers["x-org-id"] == "acme"
    assert host.rpc()["id"] == "r-9"


def test_tasks_list_404_raises_not_enabled(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    with make_client(handler, a2a_protocol="1.0") as client:
        with pytest.raises(A2ANotEnabledError):
            client.a2a.tasks_list()


def test_version_not_supported_is_a_jsonrpc_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=A2A_V1["error_version_not_supported"])

    with make_client(handler, a2a_protocol="1.0") as client:
        with pytest.raises(A2AJsonRpcError) as info:
            client.a2a.message_send({})
    assert info.value.code == A2A_VERSION_NOT_SUPPORTED == -32009


# ── agent_card(protocol_version=) (A2A-004) ────────────────────────────────


def test_agent_card_requests_a_protocol_version(make_client):
    host = FakeA2AHost()
    with make_client(host) as client:
        card = client.agent_card(protocol_version="1.0")
        client.agent_card()
    assert dict(host.requests[0].url.params) == {"protocolVersion": "1.0"}
    assert dict(host.requests[1].url.params) == {}
    assert isinstance(card, AgentCard)
    assert card.name == "Billing Agent"
    assert card.protocol_version is None  # v1 cards have no top-level version
    assert card.supported_interfaces is not None
    first = card.supported_interfaces[0]
    assert (first.protocol_binding, first.protocol_version, first.tenant) == (
        "JSONRPC",
        "1.0",
        "acme",
    )
    assert card.model_dump(by_alias=True)["capabilities"]["extendedAgentCard"]


def test_v03_card_keeps_parsing_as_in_v01(make_client):
    host = FakeA2AHost(cards={None: A2A_V03_CARD})
    with make_client(host) as client:
        card = client.agent_card()
    assert (card.name, card.protocol_version) == ("prismal", "0.3.0")
    assert card.supported_interfaces is None


# ── async mirrors (NFR-002) ────────────────────────────────────────────────


async def test_async_auto_negotiation_and_v1_wrappers(make_async_client):
    host = FakeA2AHost()
    async with make_async_client(host, a2a_protocol="auto") as client:
        assert await client.a2a.negotiated_version() == "1.0"
        await client.a2a.message_send({"m": 1})
        await client.a2a.tasks_get({"id": "t"})
        await client.a2a.tasks_cancel({"id": "t"})
    assert len(host.card_gets) == 1
    assert [json.loads(p.content)["method"] for p in host.posts] == [
        "SendMessage",
        "GetTask",
        "CancelTask",
    ]
    assert all(p.headers["A2A-Version"] == "1.0" for p in host.posts)


async def test_async_message_stream_v1(make_async_client):
    host = FakeA2AHost(stream_body=_STREAM)
    async with make_async_client(host, a2a_protocol="1.0") as client:
        frames = [f async for f in client.a2a.message_stream({"m": 1})]
    assert frames == [{"result": {"n": 1}}]
    assert host.rpc()["method"] == "SendStreamingMessage"
    assert host.posts[0].headers["A2A-Version"] == "1.0"


async def test_async_default_mode_is_v01_behaviour(make_async_client):
    host = FakeA2AHost()
    async with make_async_client(host) as client:
        await client.a2a.message_send({})
    assert host.card_gets == []
    assert host.rpc()["method"] == "message/send"


async def test_async_tasks_list(make_async_client):
    host = FakeA2AHost(result=LIST_RESULT)
    async with make_async_client(host, a2a_protocol="1.0") as client:
        page = await client.a2a.tasks_list(context_id="ctx-1", org_id="acme")
    assert page.next_page_token == ""
    assert host.rpc()["params"] == {"contextId": "ctx-1", "pageSize": 50}
    assert host.posts[0].headers["x-org-id"] == "acme"


async def test_async_tasks_list_v03_and_bounds(make_async_client):
    host = FakeA2AHost(cards={None: A2A_V03_CARD})
    async with make_async_client(host, a2a_protocol="auto") as client:
        with pytest.raises(ValueError):
            await client.a2a.tasks_list(page_size=101)
        assert host.requests == []
        with pytest.raises(A2AVersionError):
            await client.a2a.tasks_list()
    assert host.posts == []


async def test_async_negotiation_cached_per_tenant(make_async_client):
    host = FakeA2AHost(cards={None: V1_CARD, "legacy": A2A_V03_CARD})
    async with make_async_client(host, a2a_protocol="auto") as client:
        assert await client.a2a.negotiated_version(org_id="legacy") == "0.3"
        assert await client.a2a.negotiated_version(org_id="legacy") == "0.3"
        assert await client.a2a.negotiated_version() == "1.0"
    assert len(host.card_gets) == 2


async def test_async_agent_card_protocol_version(make_async_client):
    host = FakeA2AHost()
    async with make_async_client(host) as client:
        await client.agent_card(protocol_version="0.3")
    assert dict(host.requests[0].url.params) == {"protocolVersion": "0.3"}


async def test_async_raw_stream_header_in_explicit_v1(make_async_client):
    host = FakeA2AHost(stream_body=_STREAM)
    async with make_async_client(host, a2a_protocol="1.0") as client:
        _ = [f async for f in client.a2a.stream("SendStreamingMessage", {})]
    assert host.posts[0].headers["A2A-Version"] == "1.0"


async def test_async_raw_send_header_only_in_explicit_v1(make_async_client):
    host = FakeA2AHost()
    async with make_async_client(host, a2a_protocol="1.0") as client:
        await client.a2a.send("GetTask", {})
    async with make_async_client(host, a2a_protocol="auto") as client:
        await client.a2a.send("GetTask", {})
    assert host.posts[0].headers["A2A-Version"] == "1.0"
    assert "a2a-version" not in host.posts[1].headers


def test_from_config_carries_a2a_protocol(monkeypatch):
    from prismal_sdk import AsyncPrismalClient, ClientConfig, PrismalClient

    monkeypatch.setenv("PRISMAL_SDK_A2A_PROTOCOL", "auto")
    config = ClientConfig()
    assert config.a2a_protocol == "auto"
    with PrismalClient.from_config(config) as client:
        assert client.a2a._client._a2a_protocol == "auto"
    assert AsyncPrismalClient.from_config(config)._a2a_protocol == "auto"

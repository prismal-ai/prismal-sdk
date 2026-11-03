"""Sync/async parity test (CSB-04-04, SPEC-CSB-NFR-001)."""

from __future__ import annotations

import inspect

from prismal_sdk._ws import AsyncWsSession, WsSession
from prismal_sdk.async_client import AsyncPrismalClient, _AsyncA2AResource
from prismal_sdk.client import PrismalClient, _A2AResource


def _public_methods(cls: type) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


# `close`/`aclose` is the one deliberate naming difference (mirrors
# httpx.Client.close() / httpx.AsyncClient.aclose()); every other method name
# must match exactly (SPEC-CSB-NFR-001).
_ASYNC_ONLY_ALIASES = {"aclose": "close"}


def test_client_public_methods_match():
    sync_names = _public_methods(PrismalClient)
    async_names = {
        _ASYNC_ONLY_ALIASES.get(n, n) for n in _public_methods(AsyncPrismalClient)
    }
    assert sync_names == async_names


def test_a2a_resource_public_methods_match():
    assert _public_methods(_A2AResource) == _public_methods(_AsyncA2AResource)


def test_client_public_method_signatures_match_by_parameter_names():
    sync_methods = _public_methods(PrismalClient)
    for name in sync_methods:
        async_name = "aclose" if name == "close" else name
        sync_sig = inspect.signature(getattr(PrismalClient, name))
        async_sig = inspect.signature(getattr(AsyncPrismalClient, async_name))
        assert list(sync_sig.parameters) == list(async_sig.parameters), name


# ── v0.2 (CS2-05-02, SPEC-CS2-NFR-002) ──────────────────────────────────────
#
# The set-equality tests above would stay green if a v0.2 method vanished from
# *both* clients, so the v0.2 surface is also named explicitly here, and its
# parameters are compared by name, kind and default — not just by name.

_V02_CLIENT_METHODS = {
    "usage",
    "iter_usage_turns",
    "budget",
    "ws",
    "send_message",
    "decisions_report",
    "routing_report",
    "audit",
    "tenants",
    "agent_card",
}
_V02_A2A_METHODS = {"tasks_list", "negotiated_version"}
_V02_KWARGS = {
    ("send_message", "protocol"),
    ("agent_card", "protocol_version"),
    ("__init__", "a2a_protocol"),
}


def _shape(func: object) -> list[tuple[str, object, object]]:
    sig = inspect.signature(func)  # type: ignore[arg-type]
    return [(p.name, p.kind, p.default) for p in sig.parameters.values()]


def _assert_same_shapes(sync_cls: type, async_cls: type, names: set[str]) -> None:
    aliases = {"close": "aclose"} if async_cls is AsyncPrismalClient else {}
    for name in sorted(names):
        async_name = aliases.get(name, name)
        assert _shape(getattr(sync_cls, name)) == _shape(
            getattr(async_cls, async_name)
        ), name


def test_v02_client_methods_exist_on_both_clients():
    for cls in (PrismalClient, AsyncPrismalClient):
        assert _V02_CLIENT_METHODS <= _public_methods(cls), cls.__name__


def test_v02_a2a_methods_exist_on_both_resources():
    for cls in (_A2AResource, _AsyncA2AResource):
        assert _V02_A2A_METHODS <= _public_methods(cls), cls.__name__


def test_v02_kwargs_exist_on_both_clients():
    for cls in (PrismalClient, AsyncPrismalClient):
        for method, kwarg in _V02_KWARGS:
            params = inspect.signature(getattr(cls, method)).parameters
            assert kwarg in params, f"{cls.__name__}.{method}({kwarg}=)"


def test_client_parameter_kinds_and_defaults_match():
    names = _public_methods(PrismalClient) | {"__init__"}
    _assert_same_shapes(PrismalClient, AsyncPrismalClient, names)


def test_a2a_resource_parameter_kinds_and_defaults_match():
    _assert_same_shapes(_A2AResource, _AsyncA2AResource, _public_methods(_A2AResource))


def test_ws_sessions_match():
    assert _public_methods(WsSession) == _public_methods(AsyncWsSession)
    assert {"connect", "send_message", "cancel", "close"} <= _public_methods(WsSession)
    _assert_same_shapes(WsSession, AsyncWsSession, _public_methods(WsSession))


# ── v0.3 (CS3-02-02, SPEC-CS3-NFR-001) ──────────────────────────────────────

_V03_CLIENT_METHODS = {"run_agui"}


def test_v03_client_methods_exist_on_both_clients():
    for cls in (PrismalClient, AsyncPrismalClient):
        assert _V03_CLIENT_METHODS <= _public_methods(cls), cls.__name__
    _assert_same_shapes(PrismalClient, AsyncPrismalClient, _V03_CLIENT_METHODS)

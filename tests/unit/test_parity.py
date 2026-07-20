"""Sync/async parity test (CSB-04-04, SPEC-CSB-NFR-001)."""

from __future__ import annotations

import inspect

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

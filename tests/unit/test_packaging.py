"""Packaging guard (CS2-05-03, SPEC-CS2-NFR-003).

``websockets`` is an optional extra: the base install stays ``httpx`` +
``pydantic`` only, and importing the SDK never imports ``websockets`` — the
WebSocket client loads it on first use of ``client.ws()``.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import requires
from pathlib import Path

from packaging.requirements import Requirement

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "prismal_sdk"


def _requirements() -> list[Requirement]:
    return [Requirement(line) for line in requires("prismal-sdk") or []]


def _extras_of(name: str) -> set[str | None]:
    """Which extras pull in ``name`` (``None`` = the base install)."""
    found: set[str | None] = set()
    for req in _requirements():
        if req.name != name:
            continue
        if req.marker is None:
            found.add(None)
            continue
        for extra in ("ws", "dev"):
            if req.marker.evaluate({"extra": extra}):
                found.add(extra)
    return found


def test_base_install_is_httpx_and_pydantic_only():
    base = {r.name for r in _requirements() if r.marker is None}
    assert base == {"httpx", "pydantic", "pydantic-settings"}


def test_websockets_is_only_in_the_ws_and_dev_extras():
    assert _extras_of("websockets") == {"ws", "dev"}


def test_importing_the_sdk_does_not_import_websockets():
    code = (
        "import sys, prismal_sdk, prismal_sdk.client, prismal_sdk.async_client;"
        "sys.exit('websockets' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_py_typed_ships():
    assert (_SRC_ROOT / "py.typed").is_file()

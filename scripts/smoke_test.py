"""Post-build smoke test for a built distribution (CSB-05-06).

Run by the release workflow against the freshly built wheel and sdist, in an
isolated environment that has *only* the distribution and its runtime
dependencies installed:

    uv run --isolated --no-project --with dist/*.whl scripts/smoke_test.py

This catches the packaging failures the unit suite structurally cannot: a
module left out of the wheel, a missing ``py.typed``, or a version that
drifted between ``pyproject.toml`` and ``__init__.py``. It performs no
network I/O.

It deliberately lives outside ``tests/`` so pytest never collects it — the
name would otherwise match pytest's default ``*_test.py`` pattern and the
file would be imported during the unit run.
"""

from __future__ import annotations

import importlib.metadata
import pathlib
import sys

import prismal_sdk
from prismal_sdk import AsyncPrismalClient, PrismalClient
from prismal_sdk.exceptions import PrismalSDKError

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


# The documented public surface is importable from the top-level package.
check(PrismalClient is not None, "PrismalClient not importable")
check(AsyncPrismalClient is not None, "AsyncPrismalClient not importable")
check(issubclass(PrismalSDKError, Exception), "exception root not importable")

# Every name the package exports resolves, and the newest surface is there
# (v0.3: AG-UI run input and resume, SPEC-CS3-*).
missing = [n for n in prismal_sdk.__all__ if not hasattr(prismal_sdk, n)]
check(not missing, f"__all__ names missing from the package: {missing}")
for client_cls in (PrismalClient, AsyncPrismalClient):
    check(hasattr(client_cls, "run_agui"), f"{client_cls.__name__}.run_agui missing")
for name in ("ResumeEntry", "AgUiInterrupt", "ResumeConflictError"):
    check(name in prismal_sdk.__all__, f"{name} not exported")

# The typing marker must ship, or downstream mypy silently ignores the SDK
# (SPEC-CSB-NFR-004).
marker = pathlib.Path(prismal_sdk.__file__).parent / "py.typed"
check(marker.is_file(), f"py.typed missing from the built distribution ({marker})")

# The two version declarations must agree; they drift easily because one lives
# in pyproject.toml and the other in __init__.py.
installed = importlib.metadata.version("prismal-ai-sdk")
check(
    installed == prismal_sdk.__version__,
    f"version mismatch: metadata {installed!r} != __version__ "
    f"{prismal_sdk.__version__!r}",
)

# Constructing and closing a client must not require a server.
try:
    with PrismalClient("http://localhost:9") as client:
        check(client is not None, "client construction returned nothing")
except Exception as exc:  # noqa: BLE001
    failures.append(f"client construction raised {exc!r}")

if failures:
    print("SMOKE TEST FAILED:", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    sys.exit(1)

print(f"smoke test OK — prismal-ai-sdk {prismal_sdk.__version__} ({installed})")

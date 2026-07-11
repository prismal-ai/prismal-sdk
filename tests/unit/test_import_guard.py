"""Import-guard test (CSB-00-04, SPEC-CSB-TRN-004).

Mirrors ``prismal-server/tests/unit/test_import_guard.py``: an AST scan
proving the SDK never imports ``prismal`` (the engine) or ``prismal_server``
(the host) — see ``CLAUDE.md`` "the one hard rule".
"""

from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN_TOP_LEVEL_MODULES = {"prismal", "prismal_server"}
_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "prismal_sdk"


def _iter_source_files() -> list[Path]:
    return sorted(_SRC_ROOT.rglob("*.py"))


def _forbidden_imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_TOP_LEVEL_MODULES:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top = module.split(".")[0]
            if node.level == 0 and top in _FORBIDDEN_TOP_LEVEL_MODULES:
                found.append(module)
    return found


def test_no_engine_or_host_imports_anywhere_in_src():
    source_files = _iter_source_files()
    assert source_files, "expected to find source files under src/prismal_sdk"

    offenders = {
        str(path.relative_to(_SRC_ROOT)): imports
        for path in source_files
        if (imports := _forbidden_imports_in(path))
    }
    assert not offenders, (
        "prismal-sdk must never import `prismal` or `prismal_server` "
        f"(SPEC-CSB-TRN-004): {offenders}"
    )

"""Host v0.2 wire payloads shared by the CS2 unit tests.

Copied from the documented examples in
``prismal-server/specs/host-v0.2-usage-gateways-agui/SPEC.md`` (§3/§4) — the
SDK is verified against the wire contract, never against host source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"

#: The engine/host/SDK shared contract fixture (SPEC-CS2-USG-001).
USAGE_WIRE: dict[str, Any] = json.loads((FIXTURES / "usage_wire.json").read_text())
USAGE_EXAMPLE: dict[str, Any] = USAGE_WIRE["example"]

TOTALS = {
    "prompt_tokens": 52000,
    "completion_tokens": 9100,
    "cache_read_tokens": 39000,
    "cache_write_tokens": 4000,
    "reasoning_tokens": 1200,
    "total_tokens": 61100,
    "calls": 140,
    "cost_usd": 0.412345,
    "cost_source": "mixed",
    "estimated": True,
    "served_model": None,
    "gateway": None,
}


def usage_turn(turn_id: str, *, thread_id: str = "t-42") -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "finished_at": "2026-10-04T11:59:58Z",
        "finish_reason": "stop",
        "usage": USAGE_EXAMPLE,
    }


def usage_report(
    turns: list[dict[str, Any]] | None = None, next_cursor: str | None = None
) -> dict[str, Any]:
    return {
        "org_id": "acme",
        "thread_id": None,
        "since": "2026-10-03T12:00:00Z",
        "until": "2026-10-04T12:00:00Z",
        "totals": TOTALS,
        "cache_hit_ratio": 0.75,
        "by_model": [USAGE_EXAMPLE],
        "turns": turns if turns is not None else [usage_turn("01J-a")],
        "next_cursor": next_cursor,
    }


BUDGET_REPORT: dict[str, Any] = {
    "org_id": "acme",
    "enabled": True,
    "scope": "tenant",
    "status": "within",
    "breached_dimension": None,
    "soft_ratio": 0.8,
    "hard_cap": True,
    "limits": {"tokens": 2000000, "cost_usd": 50.0, "calls": 0, "wall_clock_s": 0.0},
    "consumed": {
        "tokens": 61100,
        "cost_usd": 0.412345,
        "calls": 140,
        "wall_clock_s": 312.5,
    },
    "remaining": {
        "tokens": 1938900,
        "cost_usd": 49.587655,
        "calls": None,
        "wall_clock_s": None,
    },
    "gateways": [
        {
            "gateway": "openrouter",
            "window": "credit",
            "unit": "usd",
            "limit": 50.0,
            "used": 8.8,
            "remaining": 41.2,
            "resets_at": None,
            "source": "api",
            "as_of": "2026-10-04T12:00:00Z",
        },
        {
            "gateway": "opencode_go",
            "window": "5h",
            "unit": "usd_equivalent",
            "limit": 2.0,
            "used": 0.6,
            "remaining": 1.4,
            "resets_at": "2026-10-04T15:10:00Z",
            "source": "ledger",
            "as_of": "2026-10-04T12:00:00Z",
        },
    ],
    "as_of": "2026-10-04T12:00:00Z",
}


#: AG-UI golden streams (engine `tests/fixtures/protocols/agui/`, vendored by
#: the host too). Each has the camelCase wire events under ``expected``.
AGUI_GOLDEN: dict[str, dict[str, Any]] = {
    path.stem: json.loads(path.read_text())
    for path in sorted((FIXTURES / "agui").glob("*.json"))
}

#: The 31 AG-UI 1.0 event types pinned by engine ADR-PRT-001 §2.3.
AGUI_1_0_TYPES = frozenset(
    {
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "TEXT_MESSAGE_CHUNK",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_CHUNK",
        "TOOL_CALL_RESULT",
        "STATE_SNAPSHOT",
        "STATE_DELTA",
        "MESSAGES_SNAPSHOT",
        "ACTIVITY_SNAPSHOT",
        "ACTIVITY_DELTA",
        "RAW",
        "CUSTOM",
        "RUN_STARTED",
        "RUN_FINISHED",
        "RUN_ERROR",
        "STEP_STARTED",
        "STEP_FINISHED",
        "REASONING_START",
        "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT",
        "REASONING_MESSAGE_END",
        "REASONING_MESSAGE_CHUNK",
        "REASONING_END",
        "REASONING_ENCRYPTED_VALUE",
        "SUBAGENT_STARTED",
        "SUBAGENT_FINISHED",
        "SUBAGENT_ERROR",
    }
)


def agui_body(events: list[dict[str, Any]], *, heartbeats: bool = True) -> bytes:
    """Frame AG-UI events as the host does: ``data: <json>\\n\\n``, no ``event:``."""
    chunks = [": heartbeat\n\n"] if heartbeats else []
    for event in events:
        chunks.append(f"data: {json.dumps(event)}\n\n")
        if heartbeats:
            chunks.append(": heartbeat\n\n")
    return "".join(chunks).encode()

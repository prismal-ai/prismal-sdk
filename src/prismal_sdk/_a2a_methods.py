"""A2A version table and negotiation (CS2-04-01, SPEC-CS2-A2A-001/002/003).

The single place that knows A2A method names per protocol version (DD-CS2-007),
pinned from the engine's ``ADR-PRT-001`` §2.1. Pure helpers shared by the
sync and async ``client.a2a`` resources.

Internal module (leading underscore) — not part of the public API.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from prismal_sdk.a2a import MESSAGE_SEND, MESSAGE_STREAM, TASKS_CANCEL, TASKS_GET
from prismal_sdk.exceptions import A2AVersionError
from prismal_sdk.models import AgentCard

#: A protocol version the SDK can speak.
A2AVersion = Literal["0.3", "1.0"]

#: Constructor setting: a fixed version, or ``"auto"`` (read the Agent Card).
A2AProtocolMode = Literal["auto", "0.3", "1.0"]

_MODES: frozenset[str] = frozenset({"auto", "0.3", "1.0"})

#: Typed-wrapper name -> JSON-RPC method, per version. v0.3 has no list.
A2A_METHODS: Mapping[A2AVersion, Mapping[str, str]] = {
    "0.3": {
        "message_send": MESSAGE_SEND,
        "message_stream": MESSAGE_STREAM,
        "tasks_get": TASKS_GET,
        "tasks_cancel": TASKS_CANCEL,
    },
    "1.0": {
        "message_send": "SendMessage",
        "message_stream": "SendStreamingMessage",
        "tasks_get": "GetTask",
        "tasks_cancel": "CancelTask",
        "tasks_list": "ListTasks",
    },
}

#: Request header naming the version; absent means 0.3 to the peer.
VERSION_HEADER = "A2A-Version"

#: ``ListTasks`` ``pageSize`` bounds (ADR-PRT-001: protocol maximum 100).
MAX_PAGE_SIZE = 100


def check_mode(mode: str) -> A2AProtocolMode:
    """Validate the ``a2a_protocol`` constructor setting."""
    if mode not in _MODES:
        raise ValueError(f"a2a_protocol must be 'auto', '0.3' or '1.0', got {mode!r}")
    return mode  # type: ignore[return-value]


def version_headers(version: A2AVersion) -> dict[str, str]:
    """``A2A-Version: 1.0`` for v1; nothing for 0.3 (its implicit default)."""
    return {VERSION_HEADER: "1.0"} if version == "1.0" else {}


def _is_major_1(version: str | None) -> bool:
    return isinstance(version, str) and version.split(".")[0] == "1"


def version_from_card(card: AgentCard) -> A2AVersion:
    """The version to speak to the peer behind ``card`` (SPEC-CS2-A2A-001).

    A v1 card lists ``supportedInterfaces``; only the ``JSONRPC`` binding
    counts, since that is what ``POST /a2a`` speaks. A v0.3 card has a
    top-level ``protocolVersion`` instead. Anything else means 0.3.
    """
    for interface in card.supported_interfaces or []:
        if interface.protocol_binding == "JSONRPC" and _is_major_1(
            interface.protocol_version
        ):
            return "1.0"
    return "1.0" if _is_major_1(card.protocol_version) else "0.3"


def method_for(version: A2AVersion, operation: str) -> str:
    """The JSON-RPC method for ``operation``; ``A2AVersionError`` if absent."""
    method = A2A_METHODS[version].get(operation)
    if method is None:
        v1_name = A2A_METHODS["1.0"][operation]
        raise A2AVersionError(
            f"{v1_name} needs an A2A 1.0 peer; this peer speaks {version}"
        )
    return method


def tasks_list_params(
    *,
    context_id: str | None,
    status: str | None,
    page_size: int,
    page_token: str | None,
    tenant: str | None,
    history_length: int | None,
    status_timestamp_after: str | None,
    include_artifacts: bool | None,
) -> dict[str, Any]:
    """``ListTasks`` params (camelCase wire names), dropping ``None``."""
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(
            f"page_size must be within 1..{MAX_PAGE_SIZE}, got {page_size}"
        )
    params: dict[str, Any] = {
        "tenant": tenant,
        "contextId": context_id,
        "status": status,
        "pageSize": page_size,
        "pageToken": page_token,
        "historyLength": history_length,
        "statusTimestampAfter": status_timestamp_after,
        "includeArtifacts": include_artifacts,
    }
    return {key: value for key, value in params.items() if value is not None}

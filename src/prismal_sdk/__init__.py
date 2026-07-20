"""prismal-sdk — a thin, typed Python client for ``prismal-server``.

Two mirrored clients, both built over ``httpx``:

- :class:`~prismal_sdk.client.PrismalClient` — synchronous.
- :class:`~prismal_sdk.async_client.AsyncPrismalClient` — asynchronous.

The SDK speaks only the wire contract ``prismal-server`` fixed
(``SPEC-RHB-SDK-*`` in that repo): thread/chat REST+SSE and the standard A2A
v0.3.x JSON-RPC surface. It never imports ``prismal`` or ``prismal_server``
— see ``CLAUDE.md`` and ``specs/client-sdk-bootstrap/`` for the full design.
"""

from __future__ import annotations

from prismal_sdk.async_client import AsyncPrismalClient
from prismal_sdk.client import PrismalClient
from prismal_sdk.config import ClientConfig
from prismal_sdk.exceptions import (
    A2AAgentUnavailableError,
    A2AJsonRpcError,
    A2ANotEnabledError,
    BudgetExceededError,
    PermissionDeniedError,
    PolicyDeniedError,
    PrismalAPIError,
    PrismalConnectionError,
    PrismalSDKError,
    PrismalTimeoutError,
    PrismalTransportError,
    RuntimeCompositionError,
    ValidationError,
)
from prismal_sdk.models import (
    AgentCard,
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    HealthStatus,
    MessageIn,
    ReadyStatus,
    StateEvent,
    ThreadCreated,
    TokenEvent,
    ToolCallEvent,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Clients
    "PrismalClient",
    "AsyncPrismalClient",
    "ClientConfig",
    # Models
    "AgentCard",
    "ChatEvent",
    "DoneEvent",
    "ErrorEvent",
    "HealthStatus",
    "MessageIn",
    "ReadyStatus",
    "StateEvent",
    "ThreadCreated",
    "TokenEvent",
    "ToolCallEvent",
    # Exceptions
    "PrismalSDKError",
    "PrismalAPIError",
    "PrismalTransportError",
    "PrismalConnectionError",
    "PrismalTimeoutError",
    "RuntimeCompositionError",
    "PolicyDeniedError",
    "PermissionDeniedError",
    "BudgetExceededError",
    "A2AAgentUnavailableError",
    "A2ANotEnabledError",
    "ValidationError",
    "A2AJsonRpcError",
]

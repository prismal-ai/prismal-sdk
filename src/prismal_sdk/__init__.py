"""prismal-sdk — a thin, typed Python client for ``prismal-server``.

Two mirrored clients, both built over ``httpx``:

- :class:`~prismal_sdk.client.PrismalClient` — synchronous.
- :class:`~prismal_sdk.async_client.AsyncPrismalClient` — asynchronous.

The SDK speaks only the wire contract ``prismal-server`` fixed
(``SPEC-RHB-SDK-*`` in that repo): thread/chat REST+SSE and the standard A2A
v0.3.x JSON-RPC surface, plus (v0.2) usage/budget reads and AG-UI streaming.
It never imports ``prismal`` or ``prismal_server`` — see ``CLAUDE.md``,
``specs/client-sdk-bootstrap/`` and ``specs/client-v0.2-usage-agui/``.
"""

from __future__ import annotations

from prismal_sdk.admin import (
    AuditPage,
    DecisionShadowReport,
    RoutingSavingsReport,
    TenantSummary,
)
from prismal_sdk.agui import (
    AgUiEvent,
    AgUiInterrupt,
    PrismalUsageEvent,
    ResumeEntry,
    RunFinished,
    StreamProtocol,
    parse_agui_event,
)
from prismal_sdk.async_client import AsyncPrismalClient
from prismal_sdk.client import PrismalClient
from prismal_sdk.config import ClientConfig
from prismal_sdk.exceptions import (
    A2AAgentUnavailableError,
    A2AJsonRpcError,
    A2ANotEnabledError,
    A2AVersionError,
    AdminDisabledError,
    BudgetExceededError,
    ForbiddenError,
    InvalidRequestError,
    MessageTooLargeError,
    PermissionDeniedError,
    PolicyDeniedError,
    PrismalAPIError,
    PrismalConnectionError,
    PrismalSDKError,
    PrismalTimeoutError,
    PrismalTransportError,
    PrismalWebSocketError,
    ProtocolNotEnabledError,
    ResumeConflictError,
    RuntimeCompositionError,
    ServerConfigurationError,
    TurnCancelledError,
    TurnInProgressError,
    ValidationError,
    WebSocketAuthenticationError,
    WebSocketProtocolError,
    WebSocketServerError,
    WebSocketUnavailableError,
)
from prismal_sdk.models import (
    AgentCard,
    AgentInterface,
    BudgetAmounts,
    BudgetReport,
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    HealthStatus,
    MessageIn,
    QuotaWindow,
    ReadyStatus,
    StateEvent,
    TaskListPage,
    ThreadCreated,
    TokenEvent,
    ToolCallEvent,
    Usage,
    UsageReport,
    UsageTurn,
)

__version__ = "0.2.0.dev0"

__all__ = [
    "__version__",
    # Clients
    "PrismalClient",
    "AsyncPrismalClient",
    "ClientConfig",
    # Models
    "AgentCard",
    "AgentInterface",
    "TaskListPage",
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
    "Usage",
    "UsageReport",
    "UsageTurn",
    "BudgetAmounts",
    "BudgetReport",
    "QuotaWindow",
    # Admin reads (full set in prismal_sdk.admin)
    "AuditPage",
    "DecisionShadowReport",
    "RoutingSavingsReport",
    "TenantSummary",
    # AG-UI (full set in prismal_sdk.agui)
    "AgUiEvent",
    "AgUiInterrupt",
    "PrismalUsageEvent",
    "ResumeEntry",
    "RunFinished",
    "StreamProtocol",
    "parse_agui_event",
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
    "ResumeConflictError",
    "ProtocolNotEnabledError",
    "InvalidRequestError",
    "ForbiddenError",
    "ServerConfigurationError",
    "TurnCancelledError",
    "AdminDisabledError",
    "PrismalWebSocketError",
    "WebSocketAuthenticationError",
    "TurnInProgressError",
    "WebSocketProtocolError",
    "MessageTooLargeError",
    "WebSocketServerError",
    "WebSocketUnavailableError",
    "A2AJsonRpcError",
    "A2AVersionError",
]

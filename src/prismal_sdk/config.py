"""Client configuration (CSB-01-01, SPEC-CSB-CFG-*).

``ClientConfig`` governs *client* construction only (base URL, credential,
tenancy default, timeout, retry budget). It has no relationship to
``prismal-server``'s ``HostSettings`` beyond sharing a naming convention
(env-var prefix); this module never imports anything server- or engine-side.
"""

from __future__ import annotations

from pydantic import AnyHttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BASE_URL = "http://localhost:8000"


class ClientConfig(BaseSettings):
    """Configuration for :class:`PrismalClient` / :class:`AsyncPrismalClient`.

    Loadable from environment variables prefixed ``PRISMAL_SDK_`` (e.g.
    ``PRISMAL_SDK_BASE_URL``, ``PRISMAL_SDK_TOKEN``) or constructed directly.
    """

    model_config = SettingsConfigDict(
        env_prefix="PRISMAL_SDK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = DEFAULT_BASE_URL
    token: SecretStr | None = None
    org_id: str | None = None
    timeout_s: float = 30.0
    max_retries: int = 2

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        """Fail fast on a malformed ``base_url`` (SPEC-CSB-CFG-001)."""
        # Delegate to pydantic's URL parser for validation only; keep the
        # stored value a plain str so httpx can consume it directly.
        AnyHttpUrl(value)
        return value.rstrip("/")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        # Never let a token leak through a default dataclass/BaseModel repr
        # (SPEC-CSB-AUT-003, SPEC-CSB-NFR-005). SecretStr already masks its
        # own repr, but we keep this explicit for defense in depth.
        token_repr = "SecretStr('**********')" if self.token else "None"
        return (
            f"ClientConfig(base_url={self.base_url!r}, token={token_repr}, "
            f"org_id={self.org_id!r}, timeout_s={self.timeout_s!r}, "
            f"max_retries={self.max_retries!r})"
        )

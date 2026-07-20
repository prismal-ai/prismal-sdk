"""ClientConfig tests (CSB-01-01 — SPEC-CSB-CFG-001/002, TRN-002/005).

Closes the coverage gap for a task TASKS.md marked DONE without a test.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from prismal_sdk.client import PrismalClient
from prismal_sdk.config import DEFAULT_BASE_URL, ClientConfig

_ENV_KEYS = (
    "PRISMAL_SDK_BASE_URL",
    "PRISMAL_SDK_TOKEN",
    "PRISMAL_SDK_ORG_ID",
    "PRISMAL_SDK_TIMEOUT_S",
    "PRISMAL_SDK_MAX_RETRIES",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Keep the ambient environment from leaking into these assertions."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_to_localhost_8000():
    # SPEC-CSB-TRN-005: matches prismal-server's default bind.
    assert ClientConfig().base_url == DEFAULT_BASE_URL


def test_loads_every_field_from_env(monkeypatch):
    # SPEC-CSB-TRN-002.
    monkeypatch.setenv("PRISMAL_SDK_BASE_URL", "https://prismal.example.com")
    monkeypatch.setenv("PRISMAL_SDK_TOKEN", "s3cret")
    monkeypatch.setenv("PRISMAL_SDK_ORG_ID", "acme")
    monkeypatch.setenv("PRISMAL_SDK_TIMEOUT_S", "5.5")
    monkeypatch.setenv("PRISMAL_SDK_MAX_RETRIES", "7")

    config = ClientConfig()

    assert config.base_url == "https://prismal.example.com"
    assert config.token is not None
    assert config.token.get_secret_value() == "s3cret"
    assert config.org_id == "acme"
    assert config.timeout_s == 5.5
    assert config.max_retries == 7


@pytest.mark.parametrize(
    "bad_url",
    ["not-a-url", "ftp://prismal.example.com", "/threads", ""],
)
def test_rejects_non_http_base_url(bad_url):
    # SPEC-CSB-CFG-001: fail fast at construction time.
    with pytest.raises(ValidationError):
        ClientConfig(base_url=bad_url)


def test_trailing_slash_is_normalized():
    assert ClientConfig(base_url="http://localhost:8000/").base_url == (
        "http://localhost:8000"
    )


def test_token_is_secretstr_and_masked_in_repr():
    # SPEC-CSB-CFG-002 / AUT-003 / NFR-005.
    config = ClientConfig(token="hunter2")
    assert isinstance(config.token, SecretStr)
    assert "hunter2" not in repr(config)
    assert "hunter2" not in str(config)


def test_from_config_sends_the_token_as_bearer():
    # SPEC-CSB-TRN-002 wired end-to-end: the secret survives from_config and
    # reaches the wire, without ClientConfig leaking it anywhere else.
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"status": "ok"})

    config = ClientConfig(base_url="http://testserver", token="hunter2", org_id="acme")
    client = PrismalClient.from_config(config)
    client._client = httpx.Client(
        base_url="http://testserver", transport=httpx.MockTransport(handler)
    )
    with client:
        client.healthz()

    assert seen["authorization"] == "Bearer hunter2"
    assert seen["x-org-id"] == "acme"

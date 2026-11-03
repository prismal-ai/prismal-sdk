"""`Usage` wire model (CS2-01-01, SPEC-CS2-USG-001/003)."""

from __future__ import annotations

import pydantic
import pytest

from prismal_sdk.models import Usage
from tests.wire_v02 import USAGE_EXAMPLE, USAGE_WIRE

_FIXTURE_TYPES = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "str|null": str | None,
}


def test_declares_exactly_the_fixture_keys_in_order():
    assert list(Usage.model_fields) == [k["name"] for k in USAGE_WIRE["keys"]]


def test_field_types_match_the_fixture():
    for key in USAGE_WIRE["keys"]:
        expected = _FIXTURE_TYPES[key["type"]]
        annotation = Usage.model_fields[key["name"]].annotation
        if key["name"] == "cost_source":
            # Literal | str: known values typed, unknown future values kept.
            assert str in getattr(annotation, "__args__", ())
        else:
            assert annotation == expected, key["name"]


def test_fixture_example_round_trips_identically():
    usage = Usage.model_validate(USAGE_EXAMPLE)
    assert usage.model_dump() == USAGE_EXAMPLE
    assert list(usage.model_dump()) == list(USAGE_EXAMPLE)
    assert Usage.model_validate_json(usage.model_dump_json()) == usage


def test_defaults_describe_an_empty_estimated_turn():
    usage = Usage()
    assert usage.total_tokens == 0
    assert usage.cost_usd == 0.0
    assert usage.cost_source == "none"
    assert usage.estimated is True
    assert usage.served_model is None
    assert usage.gateway is None


def test_unknown_cost_source_is_kept_as_a_plain_string():
    usage = Usage.model_validate({**USAGE_EXAMPLE, "cost_source": "barter"})
    assert usage.cost_source == "barter"


def test_unknown_extra_keys_are_tolerated_and_preserved():
    usage = Usage.model_validate({**USAGE_EXAMPLE, "carbon_g": 1.5})
    assert usage.model_dump()["carbon_g"] == 1.5


def test_is_frozen():
    usage = Usage.model_validate(USAGE_EXAMPLE)
    with pytest.raises(pydantic.ValidationError):
        usage.total_tokens = 1  # type: ignore[misc]


def test_cache_hit_ratio_is_cache_read_over_prompt():
    assert Usage.model_validate(USAGE_EXAMPLE).cache_hit_ratio == pytest.approx(
        800 / 1200
    )


def test_cache_hit_ratio_is_zero_without_prompt_tokens():
    assert Usage(cache_read_tokens=5).cache_hit_ratio == 0.0


def test_cache_hit_ratio_never_reaches_the_wire():
    # The only derived value (USG-003) is a property, not a serialized field.
    assert "cache_hit_ratio" not in Usage.model_validate(USAGE_EXAMPLE).model_dump()


def test_values_are_never_recomputed():
    # USG-003: an inconsistent host total is the host's to fix, not the SDK's.
    usage = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=999)
    assert usage.total_tokens == 999


@pytest.mark.parametrize(
    "name",
    [
        "Usage",
        "UsageReport",
        "UsageTurn",
        "BudgetAmounts",
        "BudgetReport",
        "QuotaWindow",
        "ProtocolNotEnabledError",
        "InvalidRequestError",
        "ForbiddenError",
        "ServerConfigurationError",
        "TurnCancelledError",
        "AdminDisabledError",
    ],
)
def test_v02_names_are_exported_from_the_package(name):
    import prismal_sdk

    assert name in prismal_sdk.__all__
    assert getattr(prismal_sdk, name) is not None

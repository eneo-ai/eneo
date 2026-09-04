"""Capability helpers on the MCP server entity module."""

from uuid import uuid4

import pytest

from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    duplicate_capability_purposes,
    validate_builtin_provider_config,
)


class TestDuplicateCapabilityPurposes:
    def test_general_servers_never_count(self):
        assert duplicate_capability_purposes(["general", "general", None]) == []

    def test_one_marker_per_purpose_is_clean(self):
        assert duplicate_capability_purposes(list(CAPABILITY_PURPOSES)) == []

    def test_repeated_purposes_are_reported_once_in_first_seen_order(self):
        first, second = CAPABILITY_PURPOSES[0], CAPABILITY_PURPOSES[1]
        purposes = [second, first, second, "general", first, second]

        assert duplicate_capability_purposes(purposes) == [second, first]


class TestValidateBuiltinProviderConfig:
    def test_normalizes_and_defaults(self):
        provider_id = uuid4()

        assert validate_builtin_provider_config(
            {"model_provider_id": provider_id, "model": " gpt-image-1 "}
        ) == {
            "model_provider_id": str(provider_id),
            "model": "gpt-image-1",
            "size": "auto",
            "quality": "auto",
        }

    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ("nope", "must be an object"),
            ({"model_provider_id": "x", "model": "m"}, "must be a UUID"),
            ({"model_provider_id": uuid4(), "model": "  "}, "model is required"),
            ({"model_provider_id": uuid4(), "model": "m" * 201}, "at most 200"),
            ({"model_provider_id": uuid4(), "model": "m", "size": "9x9"}, "size"),
            (
                {"model_provider_id": uuid4(), "model": "m", "quality": "ultra"},
                "quality",
            ),
        ],
    )
    def test_rejects_bad_input(self, config, message):
        with pytest.raises(ValueError, match=message):
            validate_builtin_provider_config(config)

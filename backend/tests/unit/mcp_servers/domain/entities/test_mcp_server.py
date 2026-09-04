"""Capability helpers on the MCP server entity module."""

from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    duplicate_capability_purposes,
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

"""Capability markers attached to a space: one per purpose."""

from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    MCPServer,
)
from eneo.spaces.space_service import SpaceService


def _server(purpose: str) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"{purpose} {uuid4().hex[:4]}",
        http_url="http://server.example/mcp",
        purpose=purpose,
    )


def _service() -> SpaceService:
    return SpaceService.__new__(SpaceService)


async def test_one_marker_per_purpose_is_accepted():
    servers = [_server("general"), _server("general")] + [
        _server(purpose) for purpose in CAPABILITY_PURPOSES
    ]

    await _service()._validate_capability_markers(servers, None)


async def test_second_marker_for_same_purpose_is_rejected():
    purpose = CAPABILITY_PURPOSES[0]
    servers = [_server(purpose), _server(purpose)]

    with pytest.raises(BadRequestException, match=purpose):
        await _service()._validate_capability_markers(servers, None)

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


async def test_classification_dry_run_reports_unavailable_capability_without_removing_selection(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from eneo.mcp_servers.domain.capabilities import CapabilityAvailability

    assistant = SimpleNamespace(
        enabled_capabilities=["image_generation"],
        completion_model=None,
        embedding_model_id=None,
    )
    space = SimpleNamespace(
        enabled_capabilities=["image_generation"],
        available_capabilities=[
            CapabilityAvailability(purpose="image_generation", available=True)
        ],
        completion_models=[],
        embedding_models=[],
        transcription_models=[],
        mcp_servers=[],
        assistants=[assistant],
        group_chats=[],
        apps=[],
        services=[],
        update=Mock(),
    )
    service = _service()
    service.get_space = AsyncMock(return_value=space)
    service._get_actor = Mock(return_value=SimpleNamespace(can_edit_space=lambda: True))
    service.security_classification_service = SimpleNamespace(
        get_security_classification=AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    )
    service.repo = SimpleNamespace(session=Mock())
    service.user = SimpleNamespace(tenant_id=uuid4())
    monkeypatch.setattr(
        "eneo.mcp_servers.application.capability_resolver.capability_availability",
        AsyncMock(
            return_value=[
                CapabilityAvailability(
                    purpose="image_generation", available=False, reason="classification"
                )
            ]
        ),
    )

    result = await service.security_classification_impact_analysis(uuid4(), uuid4())

    assert result.affected_capabilities == ["image_generation"]
    assert result.space.enabled_capabilities == ["image_generation"]
    assert result.space.assistants == [assistant]

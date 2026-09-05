"""Capability markers in a space are exempt from marker-level classification.

A space attaches a capability server (web search, image generation) as a
marker; the provider that serves each user is resolved at ask time and is
what the security classification applies to. The marker's own classification
must therefore neither block attaching nor cause the marker to be dropped
when the space's classification is raised. General servers keep the check.
"""

from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    MCPServer,
)
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space import Space


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"klass {level}",
        security_level=level,
        security_enabled=True,
    )


def _server(purpose: str, level: int | None = None) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"{purpose} server",
        http_url="http://server.example/mcp",
        purpose=purpose,
        security_classification=_classification(level) if level is not None else None,
    )


def _space(*, classification: SecurityClassification | None, servers: list[MCPServer]):
    return Space(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_space_id=None,
        user_id=None,
        name="Shared",
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=servers,
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        security_classification=classification,
    )


@pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
def test_unclassified_marker_can_be_attached_to_a_classified_space(purpose):
    space = _space(classification=_classification(1), servers=[])

    space.mcp_servers = [_server(purpose)]

    assert [s.purpose for s in space.mcp_servers] == [purpose]


def test_unclassified_general_server_is_still_rejected():
    space = _space(classification=_classification(1), servers=[])

    with pytest.raises(BadRequestException):
        space.mcp_servers = [_server("general")]


@pytest.mark.parametrize("purpose", CAPABILITY_PURPOSES)
def test_raising_the_classification_keeps_markers_and_drops_weak_servers(purpose):
    marker = _server(purpose, level=0)
    weak = _server("general", level=0)
    strong = _server("general", level=2)
    space = _space(classification=None, servers=[marker, weak, strong])

    space.update(security_classification=_classification(1))

    assert space.mcp_servers == [marker, strong]

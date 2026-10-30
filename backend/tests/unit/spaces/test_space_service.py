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
        id=uuid4(),
        enabled_capabilities=["image_generation"],
        completion_model=None,
        embedding_model_id=None,
    )
    space = SimpleNamespace(
        enabled_capabilities=["image_generation"],
        available_capabilities=[
            CapabilityAvailability(purpose="image_generation", available=True)
        ],
        linked_completion_models=[],
        linked_embedding_models=[],
        linked_transcription_models=[],
        linked_transcription_services=[],
        mcp_servers=[],
        assistants=[assistant],
        default_assistant=None,
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
    assert result.space.available_capabilities[0].available is True
    assert result.affected_assistant_ids == frozenset({assistant.id})
    space.update.assert_not_called()


async def test_impact_preview_keeps_every_resource_list_and_accounts_for_default_seats():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    unsafe = SimpleNamespace(id=uuid4(), security_classification="low")
    safe = SimpleNamespace(id=uuid4(), security_classification="high")
    default = SimpleNamespace(
        id=uuid4(),
        completion_model=unsafe,
        enabled_capabilities=[],
        embedding_model_id=None,
    )
    assistant = SimpleNamespace(
        id=uuid4(),
        completion_model=safe,
        enabled_capabilities=[],
        embedding_model_id=None,
    )
    chat = SimpleNamespace(id=uuid4(), get_assistants=lambda: [default])
    app = SimpleNamespace(id=uuid4(), completion_model=unsafe, transcription_model=None)
    service_item = SimpleNamespace(id=uuid4(), completion_model=safe, groups=[])
    space = SimpleNamespace(
        default_assistant=default,
        assistants=[assistant],
        group_chats=[chat],
        apps=[app],
        services=[service_item],
        linked_completion_models=[unsafe, safe],
        linked_embedding_models=[],
        linked_transcription_models=[],
        linked_transcription_services=[],
        mcp_servers=[],
        enabled_capabilities=[],
        available_capabilities=[],
        security_classification=None,
    )
    original = {
        key: list(value)
        for key, value in vars(space).items()
        if isinstance(value, list)
    }
    service = _service()
    service.get_space = AsyncMock(return_value=space)
    service._get_actor = Mock(return_value=SimpleNamespace(can_edit_space=lambda: True))
    service.security_classification_service = SimpleNamespace(
        get_security_classification=AsyncMock(
            return_value=SimpleNamespace(
                is_greater_than=lambda classification: classification == "low"
            )
        )
    )
    result = await service.security_classification_impact_analysis(uuid4(), uuid4())
    assert result.affected_group_chat_ids == frozenset({chat.id})
    assert result.affected_app_ids == frozenset({app.id})
    assert result.affected_service_ids == frozenset()
    assert space.security_classification is None
    assert {
        key: value for key, value in vars(space).items() if isinstance(value, list)
    } == original


async def test_classification_dry_run_lists_a_linked_model_below_it_as_affected():
    # Raising the space's classification removes the models it does not allow,
    # including one already below it; the preview has to name that one too.
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from eneo.spaces.space import Space

    def classification(level: int) -> SecurityClassification:
        return SecurityClassification(
            tenant_id=uuid4(),
            name=f"K{level}",
            description="",
            security_level=level,
            security_enabled=True,
        )

    def model(level: int) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid4(), can_access=True, security_classification=classification(level)
        )

    at_level, below, above = model(3), model(1), model(5)
    space = Space(
        id=uuid4(),
        tenant_id=None,
        tenant_space_id=None,
        user_id=None,
        name="Space",
        description=None,
        embedding_models=[],
        completion_models=[at_level, below, above],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        security_classification=classification(3),
    )
    service = _service()
    service.get_space = AsyncMock(return_value=space)
    service._get_actor = Mock(return_value=SimpleNamespace(can_edit_space=lambda: True))
    service.security_classification_service = SimpleNamespace(
        get_security_classification=AsyncMock(return_value=classification(4))
    )

    result = await service.security_classification_impact_analysis(uuid4(), uuid4())

    assert {m.id for m in result.affected_completion_models} == {at_level.id, below.id}


class _ProviderSession:
    """Answers capability-provider SELECTs from in-memory providers and
    counts them; no tenant tool overlay."""

    def __init__(self, providers):
        self.providers = providers
        self.provider_selects = 0

    async def scalars(self, statement):
        from unittest.mock import MagicMock

        self.provider_selects += 1
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        selected = [p for p in self.providers if f"'{p.purpose}'" in compiled]
        return MagicMock(all=lambda: selected)

    async def execute(self, statement):
        from unittest.mock import MagicMock

        return MagicMock(all=lambda: [])


def _classification(level: int):
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )

    return SecurityClassification(
        id=uuid4(),
        tenant_id=uuid4(),
        name=f"klass {level}",
        security_level=level,
        security_enabled=True,
    )


def _provider(purpose: str, level: int | None) -> MCPServer:
    server = _server(purpose)
    server.is_enabled = True
    server.security_classification = (
        _classification(level) if level is not None else None
    )
    return server


def _marker_service(monkeypatch, providers) -> tuple[SpaceService, _ProviderSession]:
    from types import SimpleNamespace

    from eneo.mcp_servers.application import capability_resolver

    monkeypatch.setattr(
        capability_resolver.MCPServerMapper, "to_entity", lambda record: record
    )
    session = _ProviderSession(providers)
    service = _service()
    service.repo = SimpleNamespace(session=session)
    service.user = SimpleNamespace(tenant_id=uuid4())
    return service, session


async def test_marker_is_rejected_when_no_provider_of_its_purpose_meets_the_space(
    monkeypatch,
):
    # The image provider meets the space; it must not vouch for web search.
    service, _ = _marker_service(
        monkeypatch,
        [_provider("web_search", 0), _provider("image_generation", 2)],
    )

    with pytest.raises(BadRequestException, match="Security classification"):
        await service._validate_capability_markers(
            [_server("web_search"), _server("image_generation")], _classification(1)
        )


async def test_markers_are_checked_against_one_provider_load(monkeypatch):
    service, session = _marker_service(
        monkeypatch,
        [
            _provider("web_search", 0),
            _provider("web_search", 1),
            _provider("image_generation", 2),
        ],
    )

    await service._validate_capability_markers(
        [
            _server("general"),
            _server("web_search"),
            _server("image_generation"),
            _server("charts"),
        ],
        _classification(1),
    )

    assert session.provider_selects == 1


async def test_markers_without_capabilities_load_no_providers(monkeypatch):
    service, session = _marker_service(monkeypatch, [_provider("web_search", 0)])

    await service._validate_capability_markers([_server("general")], _classification(1))

    assert session.provider_selects == 0

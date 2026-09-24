"""What AssistantService.ask runs for a widget visitor.

A visitor is a synthetic principal without a users row. The assistant serves
it as configured, knowledge tool included under the visitor's own scoped
token, less what needs a users row: generated files and the built-in image
provider.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from eneo.ai_models.completion_models.completion_model import GeneratedImage
from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.assistants.assistant_service import VISITOR_CAPABILITY_PURPOSES
from eneo.mcp_servers.application.capability_resolver import CapabilityResolution
from eneo.mcp_servers.domain.entities.mcp_server import (
    INTERNAL_AUTH_TYPE,
    MCPServer,
)
from eneo.widgets.application.visitor_user import build_visitor_user
from eneo.widgets.domain.widget import Widget
from tests.fixtures import TEST_MODEL_CHATGPT, TEST_TENANT, TEST_USER
from tests.unittests.assistants.test_governance_policy_runtime import (
    _empty_skill_service,
    _runtime_service,
)

TOOL_MODEL = TEST_MODEL_CHATGPT.model_copy(update={"supports_tool_calling": True})


def _visitor():
    widget = Widget.create(
        tenant_id=TEST_TENANT.id, space_id=uuid4(), target_id=uuid4(), name="w"
    ).model_copy(update={"id": uuid4()})
    return build_visitor_user(widget, uuid4(), TEST_TENANT)


def _server(name: str, **kwargs) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=TEST_TENANT.id,
        name=name,
        http_url=f"https://{name}.example.test/mcp",
        **kwargs,
    )


def _service(user, *, mcp_servers=(), capabilities=()):
    service, assistant, _ = _runtime_service(
        personal_default=False, skill_service=_empty_skill_service()
    )
    service.user = user
    assistant.completion_model = TOOL_MODEL
    assistant.mcp_servers = list(mcp_servers)
    assistant.enabled_capabilities = list(capabilities)
    space = service.space_repo.get_space_by_assistant.return_value
    space.enabled_capabilities = list(capabilities)
    space.security_classification = None
    return service, assistant


async def test_visitor_gets_the_knowledge_tool_under_its_own_identity():
    visitor = _visitor()
    service, assistant = _service(visitor)
    assistant.knowledge_mode = KnowledgeMode.TOOL
    assistant.has_knowledge.return_value = True

    with patch(
        "eneo.assistants.assistant_service.build_knowledge_mcp_server",
        new=AsyncMock(return_value=MagicMock()),
    ) as build_server:
        await service.ask(question="hello", assistant_id=assistant.id)

    build_server.assert_awaited_once()
    service.auth_service.create_scoped_mcp_token.assert_called_once_with(
        visitor, assistant_id=assistant.id
    )
    assert (
        assistant.ask.await_args.kwargs["knowledge_mcp_server"]
        is build_server.return_value
    )


async def test_visitor_is_offered_the_assistants_own_mcp_servers():
    casefiles = _server("casefiles", forward_identity=True)
    service, assistant = _service(_visitor(), mcp_servers=[casefiles])

    await service.ask(question="hello", assistant_id=assistant.id)

    kwargs = assistant.ask.await_args.kwargs
    assert kwargs["mcp_servers_override"] == [casefiles]
    assert kwargs["capability_mcp_servers"] == []


async def test_visitor_capabilities_are_web_search_from_an_external_provider():
    web_search = _server("search", purpose="web_search")
    builtin_search = _server(
        "builtin-search", purpose="web_search", http_auth_type=INTERNAL_AUTH_TYPE
    )
    resolve = AsyncMock(
        return_value=CapabilityResolution(
            general_servers=[], capability_servers=[web_search, builtin_search]
        )
    )
    service, assistant = _service(
        _visitor(), capabilities=["web_search", "image_generation"]
    )

    with patch("eneo.assistants.assistant_service.resolve_capability_servers", resolve):
        await service.ask(question="hello", assistant_id=assistant.id)

    assert VISITOR_CAPABILITY_PURPOSES == {"web_search"}
    assert resolve.await_args.kwargs["allowed_purposes"] == {"web_search"}
    # Eneo's only built-in provider makes images, which a visitor cannot own.
    assert assistant.ask.await_args.kwargs["capability_mcp_servers"] == [web_search]
    service.auth_service.create_scoped_mcp_token.assert_not_called()


async def test_staff_keep_image_generation_and_built_in_providers():
    web_search = _server("search", purpose="web_search")
    builtin_images = _server(
        "images", purpose="image_generation", http_auth_type=INTERNAL_AUTH_TYPE
    )
    resolve = AsyncMock(
        return_value=CapabilityResolution(
            general_servers=[], capability_servers=[web_search, builtin_images]
        )
    )
    service, assistant = _service(
        TEST_USER, capabilities=["web_search", "image_generation"]
    )

    with (
        patch("eneo.assistants.assistant_service.resolve_capability_servers", resolve),
        patch(
            "eneo.assistants.assistant_service.with_live_builtin_tools",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await service.ask(question="hello", assistant_id=assistant.id)

    assert resolve.await_args.kwargs["allowed_purposes"] == {
        "web_search",
        "image_generation",
    }
    offered = assistant.ask.await_args.kwargs["capability_mcp_servers"]
    assert [server.id for server in offered] == [web_search.id, builtin_images.id]


async def test_a_generated_image_is_never_saved_for_a_visitor():
    service, _ = _service(_visitor())
    service.file_service.save_image_from_bytes = AsyncMock()
    image = GeneratedImage(data=b"png", mime_type="image/png", tool_call_id="c")

    assert await service._save_generated_image(image) is None
    service.file_service.save_image_from_bytes.assert_not_awaited()

    service.user = TEST_USER
    assert await service._save_generated_image(image) is not None
    service.file_service.save_image_from_bytes.assert_awaited_once()

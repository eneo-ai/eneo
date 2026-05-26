from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.assistants.assistant_service import AssistantService
from intric.main.exceptions import BadRequestException
from intric.services.service import DatastoreResult
from intric.sessions.session import SessionInDB
from tests.fixtures import TEST_MODEL_CHATGPT, TEST_MODEL_GPT4, TEST_USER


def _service_with_effective_config(effective_config_service: AsyncMock):
    return AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        user=TEST_USER,
        auth_service=MagicMock(),
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=AsyncMock(),
        assistant_template_service=AsyncMock(),
        session_service=AsyncMock(),
        actor_manager=MagicMock(),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        effective_config_service=effective_config_service,
    )


async def test_ask_uses_effective_model_for_session_metadata_and_response():
    assistant_id = uuid4()
    session = SessionInDB(
        id=uuid4(),
        name="hello",
        user_id=TEST_USER.id,
        questions=[],
    )
    response = MagicMock()
    datastore_result = DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[])

    assistant = MagicMock()
    assistant.id = assistant_id
    assistant.name = "Personal assistant"
    assistant.description = None
    assistant.is_default = True
    assistant.completion_model = TEST_MODEL_CHATGPT
    assistant.tool_assistants = []
    assistant.ask = AsyncMock(return_value=(response, datastore_result))

    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.return_value = None
    space.is_personal.return_value = True

    actor = MagicMock()
    actor.can_read_assistant.return_value = True

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=True,
        available_models=[TEST_MODEL_GPT4],
        policy_default_model=TEST_MODEL_GPT4,
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=False,
        enforced_prompt_text=None,
    )

    service = AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(get_space_by_assistant=AsyncMock(return_value=space)),
        user=TEST_USER,
        auth_service=MagicMock(),
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=AsyncMock(get_files_by_ids=AsyncMock(return_value=[])),
        assistant_template_service=AsyncMock(),
        session_service=AsyncMock(
            create_session=AsyncMock(return_value=session),
            create_question_placeholder=AsyncMock(return_value=uuid4()),
        ),
        actor_manager=MagicMock(
            get_space_actor_from_space=MagicMock(return_value=actor)
        ),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        effective_config_service=effective_config_service,
    )
    service._handle_response = AsyncMock(return_value="answer")  # type: ignore[method-assign]

    result = await service.ask(question="hello", assistant_id=assistant_id)

    service._handle_response.assert_awaited_once()
    assert (
        service._handle_response.await_args.kwargs["completion_model"]
        is TEST_MODEL_GPT4
    )
    assert result.completion_model.id == TEST_MODEL_GPT4.id
    effective_config_service.resolve_for.assert_awaited_once_with(
        assistant, space_is_personal=True
    )


async def test_update_guard_rejects_disallowed_model_on_personal_default_assistant():
    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=True,
        available_models=[TEST_MODEL_GPT4],
        mcp_enforced=False,
        available_mcp_servers=[],
    )
    service = _service_with_effective_config(effective_config_service)

    space = MagicMock()
    space.is_personal.return_value = True
    assistant = SimpleNamespace(
        is_default=True,
        completion_model=TEST_MODEL_CHATGPT,
    )

    with pytest.raises(
        BadRequestException,
        match="Model not allowed by personal assistant governance policy",
    ):
        await service._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=uuid4(),
            mcp_server_ids=None,
        )


async def test_update_guard_ignores_non_personal_default_assistant():
    effective_config_service = AsyncMock()
    service = _service_with_effective_config(effective_config_service)

    space = MagicMock()
    space.is_personal.return_value = False
    assistant = SimpleNamespace(
        is_default=True,
        completion_model=TEST_MODEL_CHATGPT,
    )

    await service._ensure_governance_policy_allows_update(
        space=space,
        assistant=assistant,
        completion_model_id=uuid4(),
        mcp_server_ids=None,
    )

    effective_config_service.resolve_for.assert_not_called()


async def test_update_guard_grandfathers_already_attached_mcp_server():
    """Tightening the MCP whitelist must not block re-saving an assistant that
    still references a now-disallowed server it already had."""
    allowed = SimpleNamespace(id=uuid4())
    already_attached = SimpleNamespace(id=uuid4())  # no longer in the whitelist

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        mcp_enforced=True,
        available_mcp_servers=[allowed],
    )
    service = _service_with_effective_config(effective_config_service)

    space = MagicMock()
    space.is_personal.return_value = True
    assistant = SimpleNamespace(
        is_default=True,
        completion_model=TEST_MODEL_CHATGPT,
        mcp_servers=[already_attached],
    )

    # Keeping the grandfathered server (plus an allowed one) must not raise.
    await service._ensure_governance_policy_allows_update(
        space=space,
        assistant=assistant,
        completion_model_id=None,
        mcp_server_ids=[already_attached.id, allowed.id],
    )


async def test_update_guard_rejects_newly_added_disallowed_mcp_server():
    allowed = SimpleNamespace(id=uuid4())

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        mcp_enforced=True,
        available_mcp_servers=[allowed],
    )
    service = _service_with_effective_config(effective_config_service)

    space = MagicMock()
    space.is_personal.return_value = True
    assistant = SimpleNamespace(
        is_default=True,
        completion_model=TEST_MODEL_CHATGPT,
        mcp_servers=[],  # nothing attached → the new server is not grandfathered
    )

    with pytest.raises(
        BadRequestException,
        match="MCP servers not allowed by personal assistant governance policy",
    ):
        await service._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=None,
            mcp_server_ids=[uuid4()],
        )

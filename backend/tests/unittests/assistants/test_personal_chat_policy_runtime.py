from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from intric.assistants.assistant_service import AssistantService
from intric.services.service import DatastoreResult
from intric.sessions.session import SessionInDB
from tests.fixtures import TEST_MODEL_CHATGPT, TEST_MODEL_GPT4, TEST_USER


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
    assistant.name = "Personal chat"
    assistant.description = None
    assistant.is_default = True
    assistant.completion_model = TEST_MODEL_CHATGPT
    assistant.tool_assistants = []
    assistant.ask = AsyncMock(return_value=(response, datastore_result))

    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.return_value = None

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
        session_service=AsyncMock(create_session=AsyncMock(return_value=session)),
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

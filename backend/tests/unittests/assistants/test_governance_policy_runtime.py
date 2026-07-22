from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.assistants.assistant_service import AssistantService
from eneo.main.exceptions import BadRequestException
from eneo.services.service import DatastoreResult
from eneo.sessions.session import SessionInDB
from eneo.skills.domain.skill import (
    ResolvedSkillBinding,
    SkillComposition,
    SkillExecutionReference,
)
from tests.fixtures import TEST_MODEL_CHATGPT, TEST_MODEL_GPT4, TEST_USER


def _not_helper_role_repo():
    repo = AsyncMock()
    repo.exists_active_for_assistant.return_value = False
    return repo


def _not_helper_history_repo():
    repo = AsyncMock()
    repo.exists_for_assistant.return_value = False
    return repo


def _empty_skill_service():
    service = AsyncMock()
    service.compose_for_assistant.side_effect = (
        lambda *, assistant_id, base_instructions: SkillComposition(
            prompt=base_instructions, provenance=()
        )
    )
    return service


def _service_with_effective_config(effective_config_service: AsyncMock):
    return AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        user=TEST_USER,
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
        org_space_assistant_role_repo=_not_helper_role_repo(),
        help_assistant_assignment_history_repo=_not_helper_history_repo(),
        skill_service=_empty_skill_service(),
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
        governance_skill_bindings=(),
    )
    session_service = AsyncMock(
        create_session=AsyncMock(return_value=session),
        create_question_placeholder=AsyncMock(return_value=uuid4()),
        create_session_with_question_placeholder=AsyncMock(
            return_value=(session, uuid4())
        ),
    )

    service = AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(get_space_by_assistant=AsyncMock(return_value=space)),
        user=TEST_USER,
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=AsyncMock(get_files_by_ids=AsyncMock(return_value=[])),
        assistant_template_service=AsyncMock(),
        session_service=session_service,
        actor_manager=MagicMock(
            get_space_actor_from_space=MagicMock(return_value=actor)
        ),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=_not_helper_role_repo(),
        help_assistant_assignment_history_repo=_not_helper_history_repo(),
        skill_service=_empty_skill_service(),
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
    assert (
        session_service.create_session_with_question_placeholder.await_args.kwargs[
            "completion_model"
        ]
        is TEST_MODEL_GPT4
    )
    assert assistant.ask.await_args.kwargs["prompt_override"] is None
    assert (
        session_service.create_session_with_question_placeholder.await_args.kwargs[
            "skill_provenance"
        ]
        is None
    )
    effective_config_service.resolve_for.assert_awaited_once_with(
        assistant, space_is_personal=True
    )


async def test_ask_rejects_empty_model_policy_before_creating_history():
    assistant_id = uuid4()

    assistant = MagicMock()
    assistant.id = assistant_id
    assistant.name = "Personal assistant"
    assistant.description = None
    assistant.is_default = True
    assistant.completion_model = TEST_MODEL_CHATGPT
    assistant.tool_assistants = []

    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.return_value = None
    space.is_personal.return_value = True

    actor = MagicMock()
    actor.can_read_assistant.return_value = True

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=True,
        available_models=[],
        policy_default_model=None,
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=False,
        enforced_prompt_text=None,
        governance_skill_bindings=(),
    )
    session_service = AsyncMock(
        create_session=AsyncMock(),
        create_question_placeholder=AsyncMock(),
    )

    service = AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(get_space_by_assistant=AsyncMock(return_value=space)),
        user=TEST_USER,
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=AsyncMock(get_files_by_ids=AsyncMock(return_value=[])),
        assistant_template_service=AsyncMock(),
        session_service=session_service,
        actor_manager=MagicMock(
            get_space_actor_from_space=MagicMock(return_value=actor)
        ),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=_not_helper_role_repo(),
        help_assistant_assignment_history_repo=_not_helper_history_repo(),
        skill_service=_empty_skill_service(),
        effective_config_service=effective_config_service,
    )

    with pytest.raises(
        BadRequestException,
        match="Personal assistant governance policy has no allowed models",
    ):
        await service.ask(question="hello", assistant_id=assistant_id)

    session_service.create_session.assert_not_called()
    session_service.create_question_placeholder.assert_not_called()


async def test_ask_grants_policy_mcp_servers_to_personal_assistant():
    """GRANT semantics: a personal default assistant gets the policy's MCP
    servers at ask-time even though it has none attached on the entity."""
    assistant_id = uuid4()
    session = SessionInDB(
        id=uuid4(),
        name="hello",
        user_id=TEST_USER.id,
        questions=[],
    )
    response = MagicMock()
    datastore_result = DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[])
    policy_server = SimpleNamespace(id=uuid4(), name="Sundsvall.se")

    assistant = MagicMock()
    assistant.id = assistant_id
    assistant.name = "Personal assistant"
    assistant.description = None
    assistant.is_default = True
    assistant.completion_model = TEST_MODEL_CHATGPT
    assistant.tool_assistants = []
    assistant.mcp_servers = []  # nothing attached on the entity
    assistant.ask = AsyncMock(return_value=(response, datastore_result))

    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.return_value = None
    space.is_personal.return_value = True

    actor = MagicMock()
    actor.can_read_assistant.return_value = True

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        policy_default_model=None,
        mcp_enforced=True,
        available_mcp_servers=[policy_server],
        prompt_enforced=False,
        enforced_prompt_text=None,
        governance_skill_bindings=(),
    )

    service = AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(get_space_by_assistant=AsyncMock(return_value=space)),
        user=TEST_USER,
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
            create_session_with_question_placeholder=AsyncMock(
                return_value=(session, uuid4())
            ),
        ),
        actor_manager=MagicMock(
            get_space_actor_from_space=MagicMock(return_value=actor)
        ),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=_not_helper_role_repo(),
        help_assistant_assignment_history_repo=_not_helper_history_repo(),
        skill_service=_empty_skill_service(),
        effective_config_service=effective_config_service,
    )
    service._handle_response = AsyncMock(return_value="answer")  # type: ignore[method-assign]

    await service.ask(question="hello", assistant_id=assistant_id)

    assistant.ask.assert_awaited_once()
    assert assistant.ask.await_args.kwargs["mcp_servers_override"] == [policy_server]


async def test_ask_respects_disabled_mcp_server_ids():
    """A per-request opt-out narrows the effective MCP set (here the granted
    policy servers) by the servers the user switched off in the composer."""
    assistant_id = uuid4()
    session = SessionInDB(id=uuid4(), name="hello", user_id=TEST_USER.id, questions=[])
    response = MagicMock()
    datastore_result = DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[])
    server_a = SimpleNamespace(id=uuid4(), name="Sundsvall.se")
    server_b = SimpleNamespace(id=uuid4(), name="Confluence")

    assistant = MagicMock()
    assistant.id = assistant_id
    assistant.name = "Personal assistant"
    assistant.description = None
    assistant.is_default = True
    assistant.completion_model = TEST_MODEL_CHATGPT
    assistant.tool_assistants = []
    assistant.mcp_servers = []
    assistant.ask = AsyncMock(return_value=(response, datastore_result))

    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.return_value = None
    space.is_personal.return_value = True

    actor = MagicMock()
    actor.can_read_assistant.return_value = True

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        policy_default_model=None,
        mcp_enforced=True,
        available_mcp_servers=[server_a, server_b],
        prompt_enforced=False,
        enforced_prompt_text=None,
        governance_skill_bindings=(),
    )

    service = AssistantService(
        repo=AsyncMock(),
        space_repo=AsyncMock(get_space_by_assistant=AsyncMock(return_value=space)),
        user=TEST_USER,
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
            create_session_with_question_placeholder=AsyncMock(
                return_value=(session, uuid4())
            ),
        ),
        actor_manager=MagicMock(
            get_space_actor_from_space=MagicMock(return_value=actor)
        ),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=_not_helper_role_repo(),
        help_assistant_assignment_history_repo=_not_helper_history_repo(),
        skill_service=_empty_skill_service(),
        effective_config_service=effective_config_service,
    )
    service._handle_response = AsyncMock(return_value="answer")  # type: ignore[method-assign]

    await service.ask(
        question="hello",
        assistant_id=assistant_id,
        disabled_mcp_server_ids=[server_a.id],
    )

    assistant.ask.assert_awaited_once()
    assert assistant.ask.await_args.kwargs["mcp_servers_override"] == [server_b]


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


async def test_update_guard_rejects_prompt_change_when_prompt_enforced():
    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=True,
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
        match="Prompt is locked by personal assistant governance policy",
    ):
        await service._ensure_governance_policy_allows_update(
            space=space,
            assistant=assistant,
            completion_model_id=None,
            mcp_server_ids=None,
            prompt_changing=True,
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


async def test_update_guard_reuses_passed_effective_config_without_reresolving():
    """update_assistant resolves the effective config once (to also decide
    whether to skip the space-assignment check) and passes it in. The guard must
    reuse that config instead of issuing a second policy round-trip."""
    allowed = SimpleNamespace(id=uuid4())
    pre_resolved = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        mcp_enforced=True,
        available_mcp_servers=[allowed],
    )

    effective_config_service = AsyncMock()
    service = _service_with_effective_config(effective_config_service)

    space = MagicMock()
    space.is_personal.return_value = True
    assistant = SimpleNamespace(
        is_default=True,
        completion_model=TEST_MODEL_CHATGPT,
        mcp_servers=[],
    )

    await service._ensure_governance_policy_allows_update(
        space=space,
        assistant=assistant,
        completion_model_id=None,
        mcp_server_ids=[allowed.id],
        effective_config=pre_resolved,
    )

    effective_config_service.resolve_for.assert_not_called()


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


def _service_with_actor(actor, effective_config_service=None):
    service = _service_with_effective_config(effective_config_service or AsyncMock())
    service.actor_manager = MagicMock()
    service.actor_manager.get_space_actor_from_space.return_value = actor
    return service


def _personal_default_space(assistant):
    space = MagicMock()
    space.is_personal.return_value = True
    space.default_assistant = assistant
    space.get_assistant.return_value = assistant
    return space


async def test_get_effective_completion_model_enforces_read_auth():
    # Preflight is reachable with an arbitrary assistant_id; it must not return a
    # model for an assistant the caller cannot read.
    from eneo.main.exceptions import UnauthorizedException

    assistant = MagicMock()
    assistant.is_default = False
    assistant.completion_model = TEST_MODEL_CHATGPT

    space = MagicMock()
    space.is_personal.return_value = False
    space.default_assistant = None
    space.get_assistant.return_value = assistant

    actor = MagicMock()
    actor.can_read_assistants.return_value = False
    actor.can_read_default_assistant.return_value = False

    service = _service_with_actor(actor)
    service.space_repo = AsyncMock()
    service.space_repo.get_space_by_assistant = AsyncMock(return_value=space)

    with pytest.raises(UnauthorizedException):
        await service.get_effective_completion_model(assistant.id)


async def test_get_effective_completion_model_allows_personal_default_for_baseline_user():
    # A PERSONAL_CHAT-only user (no ASSISTANTS permission) can read their own
    # personal default assistant via the carve-out.
    assistant = MagicMock()
    assistant.id = uuid4()
    assistant.is_default = True
    assistant.completion_model = TEST_MODEL_CHATGPT

    space = _personal_default_space(assistant)

    actor = MagicMock()
    actor.can_read_assistants.return_value = False
    actor.can_read_default_assistant.return_value = True

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for = AsyncMock(
        return_value=SimpleNamespace(
            models_enforced=False,
            available_models=[],
            default_model=None,
            locked_model=None,
        )
    )

    service = _service_with_actor(actor, effective_config_service)
    service.space_repo = AsyncMock()
    service.space_repo.get_space_by_assistant = AsyncMock(return_value=space)

    model = await service.get_effective_completion_model(assistant.id)
    assert model is TEST_MODEL_CHATGPT


def _skill_reference(*, position: int = 0) -> SkillExecutionReference:
    return SkillExecutionReference(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        revision_number=3,
        content_digest="a" * 64,
        position=position,
    )


def _runtime_service(
    *,
    personal_default: bool,
    skill_service: AsyncMock,
    effective_config: SimpleNamespace | None = None,
):
    assistant = MagicMock()
    assistant.id = uuid4()
    assistant.name = "Assistant"
    assistant.description = None
    assistant.is_default = personal_default
    assistant.completion_model = TEST_MODEL_CHATGPT
    assistant.tool_assistants = []
    assistant.mcp_servers = []
    assistant.attachments = []
    assistant.get_prompt_text.return_value = "Stored base"
    assistant.ask = AsyncMock(
        return_value=(
            MagicMock(),
            DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[]),
        )
    )

    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.return_value = None
    space.is_personal.return_value = personal_default
    space.default_assistant = assistant if personal_default else None

    actor = MagicMock()
    actor.can_read_assistant.return_value = True
    actor.can_read_default_assistant.return_value = True

    effective_config_service = AsyncMock()
    effective_config_service.resolve_for.return_value = effective_config
    session = SessionInDB(
        id=uuid4(),
        name="hello",
        user_id=TEST_USER.id,
        questions=[],
    )
    session_service = AsyncMock(
        create_session=AsyncMock(return_value=session),
        create_question_placeholder=AsyncMock(return_value=uuid4()),
        create_session_with_question_placeholder=AsyncMock(
            return_value=(session, uuid4())
        ),
        get_session_by_uuid=AsyncMock(return_value=session),
    )
    service = _service_with_effective_config(effective_config_service)
    service.skill_service = skill_service
    service.space_repo.get_space_by_assistant.return_value = space
    service.actor_manager.get_space_actor_from_space.return_value = actor
    service.file_service.get_files_by_ids.return_value = []
    service.session_service = session_service
    service._handle_response = AsyncMock(return_value="answer")  # type: ignore[method-assign]
    return service, assistant, session_service


async def test_ordinary_assistant_uses_composed_prompt_and_persists_provenance():
    reference = _skill_reference()
    skill_service = AsyncMock()
    skill_service.compose_for_assistant.return_value = SkillComposition(
        prompt="Stored base\n\nSkill instructions",
        provenance=(reference,),
    )
    service, assistant, session_service = _runtime_service(
        personal_default=False,
        skill_service=skill_service,
    )

    await service.ask(question="hello", assistant_id=assistant.id)

    assert (
        assistant.ask.await_args.kwargs["prompt_override"]
        == "Stored base\n\nSkill instructions"
    )
    assert session_service.create_session_with_question_placeholder.await_args.kwargs[
        "skill_provenance"
    ] == (reference,)


async def test_existing_session_persists_composed_skill_provenance():
    reference = _skill_reference()
    skill_service = AsyncMock()
    skill_service.compose_for_assistant.return_value = SkillComposition(
        prompt="Stored base\n\nSkill instructions",
        provenance=(reference,),
    )
    service, assistant, session_service = _runtime_service(
        personal_default=False,
        skill_service=skill_service,
    )
    existing_session = session_service.get_session_by_uuid.return_value

    await service.ask(
        question="hello",
        assistant_id=assistant.id,
        session_id=existing_session.id,
    )

    session_service.create_session_with_question_placeholder.assert_not_awaited()
    assert session_service.create_question_placeholder.await_args.kwargs[
        "skill_provenance"
    ] == (reference,)


async def test_personal_default_rejects_invalid_direct_bindings_before_history():
    reference = _skill_reference()
    skill_service = AsyncMock()
    skill_service.compose_for_assistant.return_value = SkillComposition(
        prompt="invalid",
        provenance=(reference,),
    )
    effective_config = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=False,
        enforced_prompt_text=None,
        governance_skill_bindings=(),
    )
    service, assistant, session_service = _runtime_service(
        personal_default=True,
        skill_service=skill_service,
        effective_config=effective_config,
    )

    with pytest.raises(BadRequestException, match="invalid direct Skill bindings"):
        await service.ask(question="hello", assistant_id=assistant.id)

    session_service.create_session.assert_not_awaited()
    session_service.create_session_with_question_placeholder.assert_not_awaited()
    session_service.create_question_placeholder.assert_not_awaited()
    assistant.ask.assert_not_awaited()


async def test_governance_skill_composes_after_enforced_prompt():
    binding = ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        slug="payroll",
        revision_number=4,
        current_revision_number=4,
        display_name="Payroll",
        instructions="Use the approved payroll rules.",
        content_digest="b" * 64,
        position=0,
    )
    skill_service = _empty_skill_service()
    effective_config = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=True,
        enforced_prompt_text="Enforced tenant base",
        governance_skill_bindings=(binding,),
    )
    service, assistant, session_service = _runtime_service(
        personal_default=True,
        skill_service=skill_service,
        effective_config=effective_config,
    )

    await service.ask(question="hello", assistant_id=assistant.id)

    prompt_override = assistant.ask.await_args.kwargs["prompt_override"]
    assert prompt_override.startswith("Enforced tenant base\n\n")
    assert "Use the approved payroll rules." in prompt_override
    assert "Stored base" not in prompt_override
    provenance = (
        session_service.create_session_with_question_placeholder.await_args.kwargs[
            "skill_provenance"
        ]
    )
    assert provenance[0].skill_revision_id == binding.skill_revision_id


async def test_governance_prompt_rechecks_persistent_baseline_on_plain_turn():
    skill_service = _empty_skill_service()
    effective_config = SimpleNamespace(
        models_enforced=False,
        available_models=[],
        mcp_enforced=False,
        available_mcp_servers=[],
        prompt_enforced=True,
        enforced_prompt_text="Enforced tenant base",
        governance_skill_bindings=(),
    )
    service, assistant, _ = _runtime_service(
        personal_default=True,
        skill_service=skill_service,
        effective_config=effective_config,
    )
    service._assert_message_attachments_fit = AsyncMock()

    await service.ask(question="hello", assistant_id=assistant.id)

    assert (
        service._assert_message_attachments_fit.await_args.kwargs[
            "validate_persistent_baseline"
        ]
        is True
    )

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.assistants.assistant_service import AssistantService
from eneo.conversations.application.conversation_service import ConversationService
from eneo.main.exceptions import (
    BadRequestException,
    ConversationSettingsConflictException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.sessions.conversation_settings import (
    ConversationSettings,
    ConversationSettingsState,
)
from eneo.sessions.session import SessionAdd, SessionContext, SessionInDB
from eneo.sessions.session_service import SessionService
from tests.fixtures import TEST_USER


def test_settings_survive_database_json_serialization():
    model_id, server_id = uuid4(), uuid4()
    state = ConversationSettingsState(
        revision=3,
        settings=ConversationSettings(
            completion_model_id=model_id,
            reasoning_effort="high",
            mcp_server_states={server_id: False},
            capability_states={"web_search": True},
            require_tool_approval=True,
        ),
    )
    # BaseRepositoryDelegate uses Python-mode dumps; UUID values and map keys
    # must nevertheless be JSON-compatible when sent to the JSONB column.
    row = json.loads(json.dumps(SessionAdd(name="Saved", settings=state).model_dump()))
    restored = SessionInDB(id=uuid4(), **row)
    assert restored.settings == state


def test_new_tools_follow_current_defaults_but_explicit_choices_survive():
    opted_in, opted_out, newly_available = uuid4(), uuid4(), uuid4()
    settings = ConversationSettings(
        mcp_server_states={opted_in: True, opted_out: False},
        capability_states={"web_search": True},
    )
    assert set(settings.disabled_servers([opted_in, newly_available])) == {
        opted_out,
        newly_available,
    }
    assert settings.disabled_capabilities(["web_search", "image_generation"]) == [
        "image_generation"
    ]


def service_with_policy():
    model, old_model = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    server = SimpleNamespace(id=uuid4())
    assistant = SimpleNamespace(
        id=uuid4(),
        completion_model=old_model,
        mcp_servers=[],
        enabled_capabilities=[],
        inline_file_text=True,
    )
    policy = SimpleNamespace(
        models_enforced=True,
        available_models=[model, old_model],
        policy_default_model=model,
        mcp_enforced=True,
        available_mcp_servers=[server],
        enabled_capabilities=["web_search"],
        inline_file_text=None,
        default_disabled_mcp_server_ids=[server.id],
        default_disabled_capabilities=["image_generation"],
        reasoning_effort_user_configurable=False,
    )
    space = SimpleNamespace(
        is_personal=lambda: True,
        default_assistant=assistant,
        is_completion_model_available=lambda id: id in [model.id, old_model.id],
        get_completion_model=lambda id: model if id == model.id else old_model,
        validate_model_security_compatibility=lambda _model: None,
    )
    assistant_service = SimpleNamespace(
        get_assistant_with_effective_config=AsyncMock(
            return_value=(assistant, [], policy)
        ),
        resolve_personal_chat_model_override=AssistantService.resolve_personal_chat_model_override,
        ask=AsyncMock(),
    )
    session_service = SimpleNamespace(
        get_session_by_uuid=AsyncMock(),
        get_context=AsyncMock(),
        update_settings=AsyncMock(),
    )
    group_service = SimpleNamespace(
        get_group_chat=AsyncMock(), ask_group_chat=AsyncMock()
    )
    service = ConversationService(
        assistant_service,
        group_service,
        session_service,
        None,
        SimpleNamespace(get_space_by_assistant=AsyncMock(return_value=space)),
        None,
    )
    return service, assistant, model, server, policy


@pytest.mark.asyncio
async def test_each_new_personal_conversation_uses_policy_defaults():
    service, assistant, model, server, _ = service_with_policy()
    defaults = await service.settings_defaults(assistant_id=assistant.id)
    assert defaults.completion_model_id == model.id
    assert defaults.mcp_server_states == {server.id: False}
    defaults.mcp_server_states[server.id] = True
    assert (
        await service.settings_defaults(assistant_id=assistant.id)
    ).mcp_server_states == {server.id: False}


@pytest.mark.asyncio
async def test_saved_model_is_rechecked_against_current_policy():
    service, assistant, model, _, policy = service_with_policy()
    choices = ConversationSettings(completion_model_id=model.id)
    await service.validate_settings(
        choices, assistant_id=assistant.id, group_chat_id=None
    )
    policy.available_models = []
    with pytest.raises(BadRequestException, match="policy"):
        await service.validate_settings(
            choices, assistant_id=assistant.id, group_chat_id=None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "choices",
    [
        ConversationSettings(completion_model_id=uuid4()),
        ConversationSettings(reasoning_effort="high"),
        ConversationSettings(require_tool_approval=True),
    ],
)
async def test_group_settings_reject_controls_that_belong_to_responding_assistants(
    choices,
):
    service, *_ = service_with_policy()
    with pytest.raises(BadRequestException, match="Group chats"):
        await service.validate_settings(
            choices, assistant_id=None, group_chat_id=uuid4()
        )


@pytest.mark.asyncio
async def test_send_uses_persisted_choices_and_rejects_another_tabs_revision():
    service, assistant, model, server, _ = service_with_policy()
    state = ConversationSettingsState(
        revision=2,
        settings=ConversationSettings(
            completion_model_id=model.id,
            mcp_server_states={server.id: False},
        ),
    )
    session = SimpleNamespace(
        id=uuid4(), assistant_id=assistant.id, group_chat_id=None, settings=state
    )
    service.session_service.get_context.return_value = session
    with pytest.raises(ConversationSettingsConflictException):
        await service.ask_conversation(
            "hello", session_id=session.id, settings_revision=1
        )
    service.assistant_service.ask.assert_not_awaited()
    await service.ask_conversation("hello", session_id=session.id, settings_revision=2)
    assert (
        service.assistant_service.ask.await_args.kwargs["conversation_settings"]
        == state
    )


@pytest.mark.asyncio
async def test_group_send_keeps_shared_choices_without_a_global_model():
    service, *_ = service_with_policy()
    state = ConversationSettingsState(
        revision=1,
        settings=ConversationSettings(capability_states={"web_search": False}),
    )
    session = SimpleNamespace(
        id=uuid4(), assistant_id=None, group_chat_id=uuid4(), settings=state
    )
    service.session_service.get_context.return_value = session
    await service.ask_conversation("hello", session_id=session.id, settings_revision=1)
    assert (
        service.group_chat_service.ask_group_chat.await_args.kwargs[
            "conversation_settings"
        ]
        == state
    )
    service.assistant_service.ask.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_cannot_be_written_by_another_session_owner():
    repo = AsyncMock()
    repo.get_context.return_value = SessionContext(
        id=uuid4(),
        user_id=uuid4(),
        api_key_id=None,
        assistant_id=None,
        group_chat_id=None,
        space_id=None,
        settings=None,
    )
    service = SessionService(
        session_repo=repo, question_repo=AsyncMock(), user=TEST_USER
    )
    with pytest.raises(UnauthorizedException):
        await service.update_settings(
            repo.get_context.return_value.id, ConversationSettings(), 0
        )
    repo.update_settings.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("governed", [True, False])
async def test_defaults_only_snapshot_capabilities_currently_offered(governed):
    service, assistant, _, _, policy = service_with_policy()
    policy.mcp_enforced = governed
    assistant.enabled_capabilities = ["web_search"]
    defaults = await service.settings_defaults(assistant_id=assistant.id)
    assert defaults.capability_states == {"web_search": True}
    # Offering image generation later, default-off, must not inherit an opt-in.
    assert defaults.disabled_capabilities(["image_generation"]) == ["image_generation"]
    defaults.capability_states["image_generation"] = True
    assert defaults.disabled_capabilities(["image_generation"]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("configurable", [True, False])
async def test_inactive_saved_reasoning_does_not_block_other_settings(configurable):
    service, assistant, model, _, policy = service_with_policy()
    policy.reasoning_effort_user_configurable = configurable
    # Covers a newly locked policy and a model that no longer accepts "high".
    model.get_supported_model_kwargs = lambda: SimpleNamespace(
        reasoning_effort=SimpleNamespace(supported=False)
    )
    saved = ConversationSettings(completion_model_id=model.id, reasoning_effort="high")
    context = SimpleNamespace(
        assistant_id=assistant.id,
        group_chat_id=None,
        settings=ConversationSettingsState(revision=2, settings=saved),
    )
    service.session_service.get_context.return_value = context
    updated = saved.model_copy(update={"require_tool_approval": True})
    service.session_service.update_settings.return_value = ConversationSettingsState(
        revision=3, settings=updated
    )
    result = await service.update_settings(uuid4(), updated, 2)
    assert result.settings.require_tool_approval is True
    assert result.settings.reasoning_effort == "high"
    assert result.revision == 3
    with pytest.raises(BadRequestException):
        await service.update_settings(
            uuid4(), saved.model_copy(update={"reasoning_effort": "low"}), 2
        )


@pytest.mark.asyncio
async def test_new_conversation_cannot_submit_locked_reasoning():
    service, assistant, model, *_ = service_with_policy()
    with pytest.raises(BadRequestException, match="managed"):
        await service.validate_settings(
            ConversationSettings(completion_model_id=model.id, reasoning_effort="high"),
            assistant_id=assistant.id,
            group_chat_id=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [True, False])
async def test_preflight_and_first_send_use_the_same_current_policy_default(legacy):
    service, assistant, model, *_ = service_with_policy()
    model.name, model.token_limit, model.vision = "gpt-4o-mini", 8000, False
    model.provider_id = model.provider_type = None
    assistant.completion_model.name = "gpt-4o"
    assistant.completion_model.token_limit = 128000
    service.assistant_service.get_preflight_baseline = AsyncMock(
        return_value=SimpleNamespace(
            prompt_tokens=0, skill_context_tokens=0, attachments=[]
        )
    )
    session_id = uuid4()
    service.session_service.get_context.return_value = SimpleNamespace(
        assistant_id=assistant.id, group_chat_id=None, settings=None
    )

    async def save(_id, settings, _revision):
        return ConversationSettingsState(revision=1, settings=settings)

    service.session_service.update_settings.side_effect = save
    target = {"session_id": session_id} if legacy else {"assistant_id": assistant.id}
    estimate = await service.preflight_tokens(question="Hello", file_ids=[], **target)
    await service.ask_conversation("Hello", **target)
    saved = service.assistant_service.ask.await_args.kwargs["conversation_settings"]
    assert estimate.model_name == model.name
    assert estimate.context_window == model.token_limit
    assert saved.settings.completion_model_id == model.id


@pytest.mark.asyncio
@pytest.mark.parametrize("service_key", [True, False])
@pytest.mark.parametrize("same_owner", [True, False])
async def test_metadata_access_preserves_user_and_service_key_ownership(
    service_key, same_owner
):
    owner, other = uuid4(), uuid4()
    user = SimpleNamespace(
        id=owner,
        tenant_id=uuid4(),
        active_api_key=SimpleNamespace(id=owner, ownership="service")
        if service_key
        else None,
    )
    context = SessionContext(
        id=uuid4(),
        user_id=None if service_key else (owner if same_owner else other),
        api_key_id=(owner if same_owner else other) if service_key else None,
        assistant_id=None,
        group_chat_id=None,
        space_id=None,
        settings=None,
    )
    repo = AsyncMock()
    repo.get_context.return_value = context
    service = SessionService(repo, AsyncMock(), user)
    if same_owner:
        assert await service.get_context(context.id) == context
    else:
        with pytest.raises(UnauthorizedException):
            await service.get_context(context.id)
    repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_settings_update_rejects_a_missing_or_hidden_session():
    repo = AsyncMock()
    repo.get_context.return_value = None
    service = SessionService(repo, AsyncMock(), TEST_USER)
    with pytest.raises(NotFoundException):
        await service.update_settings(uuid4(), ConversationSettings(), 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_chat", [True, False])
async def test_settings_update_rechecks_access_to_the_current_chat_partner(group_chat):
    service, assistant, *_ = service_with_policy()
    service.session_service.get_context.return_value = SimpleNamespace(
        assistant_id=None if group_chat else assistant.id,
        group_chat_id=uuid4() if group_chat else None,
        settings=None,
    )
    lookup = (
        service.group_chat_service.get_group_chat
        if group_chat
        else service.assistant_service.get_assistant_with_effective_config
    )
    lookup.side_effect = UnauthorizedException("Access revoked")
    with pytest.raises(UnauthorizedException, match="Access revoked"):
        await service.update_settings(uuid4(), ConversationSettings(), 0)
    service.session_service.update_settings.assert_not_awaited()

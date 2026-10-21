"""Exercise preparation and ordinary asks through the real completion engine.

Only database repositories and the outbound provider are replaced. Assistant,
Space, actor policy, context building and the model adapter remain real.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import litellm
import pytest
from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices

from eneo.actors import ActorFactory, ActorManager
from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.assistants.assistant_service import AssistantService
from eneo.completion_models.domain.completion_model import CompletionModel
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.governance_policy.domain.policy_resolver import EffectiveConfig
from eneo.main.exceptions import (
    SecurityClassificationMismatchException,
    UnauthorizedException,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.prompts.prompt import Prompt
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.sessions.session import SessionInDB
from eneo.skills.domain.skill import (
    SkillRuntimePolicy,
    SkillRuntimeResolution,
    SkillTurnPlan,
)
from eneo.spaces.api.space_models import SpaceMember, SpaceRoleValue
from eneo.spaces.space import Space
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB, UserState


@dataclass
class TurnFixture:
    service: AssistantService
    assistant: Assistant
    space: Space
    user: UserInDB
    session: SessionInDB
    history: Mock
    provider: AsyncMock
    requests: list[dict[str, object]]


@pytest.fixture
def turn(monkeypatch: pytest.MonkeyPatch) -> TurnFixture:
    now = datetime.now(timezone.utc)
    tenant_id, user_id, space_id = uuid4(), uuid4(), uuid4()
    tenant = TenantInDB.model_construct(
        id=tenant_id, api_credentials={}, show_model_pricing=False
    )
    user = UserInDB.model_construct(
        id=user_id,
        tenant_id=tenant_id,
        tenant=tenant,
        state=UserState.ACTIVE,
        roles=[
            RoleInDB(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                tenant_id=tenant_id,
                name="Builder",
                permissions=[Permission.ASSISTANTS, Permission.GROUP_CHATS],
            )
        ],
    )
    classification = SecurityClassification(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Internal",
        security_level=1,
        security_enabled=True,
    )
    model = CompletionModel(
        user=user,
        id=uuid4(),
        created_at=now,
        updated_at=now,
        nickname="Proof model",
        name="gpt-4o-mini",
        max_input_tokens=8192,
        max_output_tokens=1024,
        vision=False,
        family="openai",
        hosting=None,
        org=None,
        stability=None,
        open_source=False,
        description=None,
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=True,
        reasoning=False,
        supports_tool_calling=True,
        security_classification=classification,
        tenant_id=tenant_id,
        provider_id=uuid4(),
        provider_type="openai",
    )
    assistant = Assistant(
        id=uuid4(),
        user=None,
        space_id=space_id,
        completion_model=model,
        name="Procurement",
        prompt=Prompt(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            text="Use the procurement policy.",
            description=None,
            user_id=user_id,
            tenant_id=tenant_id,
            is_selected=True,
            user=None,
        ),
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=[],
        published=True,
    )
    space = Space(
        id=space_id,
        tenant_id=tenant_id,
        tenant_space_id=uuid4(),
        user_id=None,
        name="Procurement space",
        description=None,
        embedding_models=[],
        completion_models=[model],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[assistant],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={
            user_id: SpaceMember.model_construct(id=user_id, role=SpaceRoleValue.EDITOR)
        },
        security_classification=classification,
    )
    session = SessionInDB(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="Purchase",
        user_id=user_id,
        questions=[],
    )
    history = Mock()
    history.create_session_with_question_placeholder = AsyncMock(
        return_value=(session, uuid4(), now)
    )
    history.create_question_placeholder = AsyncMock(return_value=(uuid4(), now))
    history.get_session_by_uuid = AsyncMock(return_value=session)
    history.complete_question_with_answer = AsyncMock()
    requests: list[dict[str, object]] = []

    async def complete(**kwargs: object):
        requests.append(kwargs)
        return litellm.ModelResponse(
            choices=[
                {"message": {"role": "assistant", "content": "Check the policy."}}
            ],
            usage={"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
        )

    provider = AsyncMock(side_effect=complete)
    adapter_module = (
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
    )
    monkeypatch.setattr(adapter_module + "_acompletion_call", provider)
    monkeypatch.setattr(
        adapter_module + "build_litellm_provider_kwargs",
        lambda resolver: {},
    )
    completion = CompletionService(context_builder=ContextBuilder())
    adapter = TenantModelAdapter(
        model=model, credential_resolver=Mock(), provider_type="openai"
    )
    monkeypatch.setattr(completion, "_get_adapter", AsyncMock(return_value=adapter))
    policy = SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=10,
        context_share_percent=25,
        max_activations_per_turn=5,
    )

    async def plan(
        *, base_instructions: str, resolution: SkillRuntimeResolution
    ) -> SkillTurnPlan:
        return SkillTurnPlan.create(
            base_instructions=base_instructions, resolution=resolution, policy=policy
        )

    skills = Mock()
    skills.resolve_assistant_bindings_for_runtime = AsyncMock(
        return_value=SkillRuntimeResolution(eligible=(), blocked=())
    )
    skills.create_turn_plan = AsyncMock(side_effect=plan)
    space_repo = Mock()
    space_repo.get_space_by_assistant = AsyncMock(return_value=space)
    files = Mock()
    files.get_files_by_ids = AsyncMock(return_value=[])
    roles = Mock()
    roles.exists_active_for_assistant = AsyncMock(return_value=False)
    helper_history = Mock()
    helper_history.exists_for_assistant = AsyncMock(return_value=False)
    repo = Mock()
    repo.session = None
    service = AssistantService(
        repo=repo,
        space_repo=space_repo,
        user=user,
        service_repo=Mock(),
        step_repo=Mock(),
        completion_model_crud_service=Mock(),
        space_service=Mock(),
        factory=Mock(),
        prompt_service=Mock(),
        file_service=files,
        assistant_template_service=Mock(),
        session_service=history,
        actor_manager=ActorManager(user=user, factory=ActorFactory()),
        integration_knowledge_repo=Mock(),
        completion_service=completion,
        references_service=Mock(),
        icon_repo=Mock(),
        org_space_assistant_role_repo=roles,
        help_assistant_assignment_history_repo=helper_history,
        auth_service=Mock(),
        skill_service=skills,
    )
    return TurnFixture(
        service, assistant, space, user, session, history, provider, requests
    )


async def test_prepare_does_not_start_inference_or_create_conversation(
    turn: TurnFixture,
):
    prepared = await turn.service._prepare_turn(
        question="Check <eneo-at-tag: @Procurement> the purchase",
        assistant_id=turn.assistant.id,
    )

    assert prepared.cleaned_question == "Check  the purchase"
    assert prepared.skill_runtime.prompt == "Use the procurement policy."
    assert prepared.effective_completion_model is turn.assistant.completion_model
    assert prepared.space.id == turn.space.id
    assert turn.requests == []
    assert turn.history.mock_calls == []


@pytest.mark.parametrize("existing", [False, True])
async def test_ordinary_ask_keeps_answer_usage_and_one_history_write(
    turn: TurnFixture,
    existing: bool,
):
    response = await turn.service.ask(
        question="Check the purchase",
        assistant_id=turn.assistant.id,
        session_id=turn.session.id if existing else None,
    )

    assert response.answer == "Check the policy."
    assert response.session.id == turn.session.id
    assert len(turn.requests) == 1
    messages = str(turn.requests[0]["messages"])
    assert "Use the procurement policy." in messages
    assert "Check the purchase" in messages
    writes = turn.history.complete_question_with_answer.call_args_list
    assert len(writes) == 1
    assert writes[0].kwargs["answer"] == response.answer
    assert writes[0].kwargs["num_tokens_question"] == 20
    assert writes[0].kwargs["num_tokens_answer"] == 7
    assert turn.history.create_session_with_question_placeholder.call_count == (
        not existing
    )
    assert turn.history.create_question_placeholder.call_count == existing


async def test_current_space_classification_rejects_before_inference_or_history(
    turn: TurnFixture,
):
    turn.space.security_classification = SecurityClassification(
        tenant_id=turn.user.tenant_id,
        name="Restricted",
        security_level=2,
        security_enabled=True,
    )
    with pytest.raises(SecurityClassificationMismatchException):
        await turn.service.ask(
            question="Restricted data", assistant_id=turn.assistant.id
        )
    assert turn.requests == []
    assert turn.history.mock_calls == []


async def test_governed_personal_ask_keeps_effective_model_and_instructions(
    turn: TurnFixture,
):
    model = turn.assistant.completion_model
    assert model is not None
    turn.assistant.is_default = True
    turn.assistant._completion_model = None
    turn.space.user_id = turn.user.id
    turn.space.default_assistant = turn.assistant
    turn.user.roles[0].permissions.append(Permission.PERSONAL_CHAT)
    governance = Mock()
    governance.resolve_for = AsyncMock(
        return_value=EffectiveConfig(
            models_enforced=True,
            available_models=[model],
            locked_model=model,
            policy_default_model=model,
            mcp_enforced=True,
            available_mcp_servers=[],
            prompt_enforced=True,
            enforced_prompt_text="Follow the governed instructions.",
        )
    )
    turn.service.effective_config_service = governance

    response = await turn.service.ask(
        question="Check the purchase",
        assistant_id=turn.assistant.id,
    )

    assert response.answer == "Check the policy."
    assert response.completion_model.id == model.id
    messages = str(turn.requests[0]["messages"])
    assert "Follow the governed instructions." in messages
    assert "Use the procurement policy." not in messages


async def test_streamed_ask_keeps_answer_and_completes_history_once(turn: TurnFixture):
    async def chunks():
        yield ModelResponseStream(
            choices=[
                StreamingChoices(
                    delta=Delta(content="Check the policy."), finish_reason="stop"
                )
            ],
        )
        yield ModelResponseStream(
            choices=[],
            usage={"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
        )

    async def stream_provider(**kwargs: object):
        turn.requests.append(kwargs)
        return chunks()

    turn.provider.side_effect = stream_provider
    response = await turn.service.ask(
        question="Check the purchase",
        assistant_id=turn.assistant.id,
        stream=True,
    )
    assert not isinstance(response.answer, str)
    events = [event async for event in response.answer]
    assert any(event.text == "Check the policy." for event in events)
    writes = turn.history.complete_question_with_answer.call_args_list
    assert len(writes) == 1
    assert writes[0].kwargs["answer"] == "Check the policy."
    assert writes[0].kwargs["num_tokens_question"] == 20
    assert writes[0].kwargs["num_tokens_answer"] == 7


async def test_revoked_space_membership_rejects_before_inference_or_history(
    turn: TurnFixture,
):
    turn.space.members.clear()
    with pytest.raises(UnauthorizedException):
        await turn.service.ask(
            question="Restricted data", assistant_id=turn.assistant.id
        )
    assert turn.requests == []
    assert turn.history.mock_calls == []


async def test_tool_opt_out_and_classification_filter_survive_preparation(
    turn: TurnFixture,
):
    opted_out = MCPServer(
        id=uuid4(),
        tenant_id=turn.user.tenant_id,
        name="Optional",
        http_url="https://tools.example/mcp",
        security_classification=turn.space.security_classification,
    )
    ineligible = MCPServer(
        id=uuid4(),
        tenant_id=turn.user.tenant_id,
        name="Unclassified",
        http_url="https://other.example/mcp",
    )
    turn.assistant.mcp_servers = [opted_out, ineligible]
    prepared = await turn.service._prepare_turn(
        question="Check the purchase",
        assistant_id=turn.assistant.id,
        disabled_mcp_server_ids=[opted_out.id],
    )
    assert prepared.mcp_servers_override == []
    assert turn.assistant.mcp_servers == [opted_out, ineligible]
    assert turn.requests == []
    assert turn.history.mock_calls == []


async def test_active_provider_work_is_cancelled_with_the_ask(turn: TurnFixture):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def slow_provider(**kwargs: object):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    turn.provider.side_effect = slow_provider
    async with asyncio.timeout(2):
        task = asyncio.create_task(
            turn.service.ask(
                question="Check the purchase", assistant_id=turn.assistant.id
            )
        )
        try:
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stopped.is_set()
            assert turn.history.complete_question_with_answer.call_count == 0
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

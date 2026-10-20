from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncGenerator
from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import litellm
import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ResponseType,
    ToolCallMetadata,
)
from eneo.assistants.assistant_service import AssistantCompletionFileInputs
from eneo.assistants.delegation import (
    CONSULT_ASSISTANT_TOOL,
    AssistantCandidate,
    AssistantDelegation,
    AssistantDelegationPlan,
    ConsultationRequest,
    current_assistant_delegation,
)
from eneo.completion_models.domain.execution_budget import (
    ExecutionBudget,
    ExecutionLimitReached,
    ExecutionLimits,
    current_execution_budget,
)
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    _acompletion_call as dispatch_completion,
)
from eneo.group_chat.domain.entities.group_chat import GroupChat, GroupChatAssistant
from eneo.main.exceptions import (
    SecurityClassificationMismatchException,
    UnauthorizedException,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.questions.question import ConsultationInfo, Question
from eneo.questions.question_protocol import to_question_public
from eneo.sessions.session_service import SessionService
from eneo.users.user import UserState
from tests.unit.test_mcp_proxy_session_resilience import _FakeMCPClient

if TYPE_CHECKING:
    from tests.unit.assistants.test_assistant_turn_preparation import TurnFixture

pytest_plugins = ["tests.unit.assistants.test_assistant_turn_preparation"]


def response(
    text: str = "",
    *,
    tool: str | None = None,
    arguments: str = "{}",
    stream: bool = False,
):
    if stream:

        async def chunks():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=text,
                            reasoning_content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call_reused_across_rounds",
                                    function=SimpleNamespace(
                                        name=tool, arguments=arguments
                                    ),
                                )
                            ]
                            if tool
                            else None,
                        ),
                        finish_reason="tool_calls" if tool else "stop",
                    )
                ],
                usage=litellm.Usage(
                    prompt_tokens=20, completion_tokens=7, total_tokens=27
                ),
            )

        return chunks()
    message: dict[str, object] = {"role": "assistant", "content": text}
    if tool:
        message["tool_calls"] = [
            {
                "id": "call_reused_across_rounds",
                "type": "function",
                "function": {"name": tool, "arguments": arguments},
            }
        ]
    return litellm.ModelResponse(
        choices=[
            {"message": message, "finish_reason": "tool_calls" if tool else "stop"}
        ],
        usage={"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27},
    )


@pytest.mark.parametrize(
    "stream, conversation, approved",
    [
        (False, False, None),
        (True, False, None),
        (True, True, True),
        (True, True, False),
    ],
)
async def test_configured_specialists_and_nested_mcp_share_the_parent_loop(
    turn: TurnFixture,
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
    conversation: bool,
    approved: bool | None,
):
    procurement = copy.deepcopy(turn.assistant)
    procurement.id = uuid4()
    it = copy.deepcopy(turn.assistant)
    it.id = uuid4()
    it.name = "IT"
    assert it.prompt is not None
    it.prompt.text = "Use the IT inventory."
    assert turn.assistant.prompt is not None
    turn.assistant.prompt.text = "Coordinate the specialists."
    turn.space.assistants.extend([procurement, it])
    server = MCPServer(
        id=uuid4(),
        tenant_id=turn.user.tenant_id,
        name="inventory",
        http_url="http://localhost:8080/mcp",
        security_classification=turn.space.security_classification,
        tools=[],
    )
    server.tools = [
        MCPServerTool(
            mcp_server_id=server.id,
            name="lookup",
            description="Read IT requirements",
            input_schema={"type": "object", "properties": {}},
            is_enabled_by_default=True,
        )
    ]
    it.mcp_servers = [server]
    turn.space.mcp_servers = [server]
    tool_calls: list[str] = []

    class InventoryClient(_FakeMCPClient):
        async def call_tool(self, name: str, arguments: dict[str, object]):
            assert not turn.service.repo.session.in_transaction()
            tool_calls.append(name)
            return {
                "content": [
                    {"type": "text", "text": "Inventory requires SSO and an exit plan."}
                ],
                "is_error": False,
            }

    monkeypatch.setattr(
        "eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session.MCPClient",
        InventoryClient,
    )
    parent_requests = 0
    child_tool_offers: list[set[str]] = []

    async def provider(**kwargs: object):
        nonlocal parent_requests
        assert not turn.service.repo.session.in_transaction()
        respond = partial(response, stream=bool(kwargs.get("stream")))
        messages = cast(list[dict[str, object]], kwargs["messages"])
        prompt = str(messages[0]["content"])
        offered = cast(list[dict[str, dict[str, object]]], kwargs.get("tools", []))
        names = {str(tool["function"]["name"]) for tool in offered}
        if "Coordinate the specialists." in prompt:
            parent_requests += 1
            assert CONSULT_ASSISTANT_TOOL in names
            if parent_requests <= 3:
                specialist = procurement if parent_requests == 1 else it
                question = (
                    "Purchase requirements"
                    if parent_requests == 1
                    else (
                        "IT requirements"
                        if parent_requests == 2
                        else "Clarify the IT exit plan"
                    )
                )
                return respond(
                    tool=CONSULT_ASSISTANT_TOOL,
                    arguments=json.dumps(
                        {
                            "assistant_id": str(specialist.id),
                            "question": question,
                            "attachment_ids": [],
                        }
                    ),
                )
            results = [
                str(item["content"]) for item in messages if item["role"] == "tool"
            ]
            assert len(results) == 3
            if approved is False:
                assert "denied" in results[1].lower()
                return respond("Review required; IT evidence is unavailable.")
            assert "SSO and an exit plan" in results[1]
            return respond("Procurement and IT require a review, SSO and an exit plan.")
        child_tool_offers.append(names)
        assert current_assistant_delegation() is None
        assert CONSULT_ASSISTANT_TOOL not in names
        if "Use the IT inventory." in prompt:
            if messages[-1]["role"] != "tool":
                return respond(
                    tool=next(name for name in names if name.endswith("__lookup"))
                )
            return respond(str(messages[-1]["content"]))
        return respond("Procurement requires a review.")

    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        dispatch_completion,
    )
    monkeypatch.setattr(
        "eneo.model_providers.infrastructure.litellm_transport.acompletion", provider
    )
    executed: list[UUID] = []

    async def execute(request: ConsultationRequest) -> AsyncGenerator[Completion, None]:
        executed.append(request.assistant_id)
        prepared = await turn.service._prepare_turn(
            question=request.question,
            assistant_id=request.assistant_id,
            file_ids=request.attachment_ids,
        )
        result, _ = await turn.service._execute_turn(
            prepared,
            turn.session,
            AssistantCompletionFileInputs([], []),
            stream=stream,
            version=2,
            require_tool_approval=False,
        )
        if isinstance(result.completion, Completion):
            yield result.completion
        else:
            async for chunk in cast(
                AsyncGenerator[Completion, None], result.completion
            ):
                yield chunk

    async def authorize(assistant_id: UUID) -> None:
        actor = turn.service.actor_manager.get_space_actor_from_space(turn.space)
        assistant = turn.space.get_assistant(assistant_id)
        if not actor.can_read_assistant(assistant):
            raise UnauthorizedException()
        turn.space.can_ask_assistant(assistant)

    budget = ExecutionBudget()
    runtime = AssistantDelegation(
        parent_assistant_id=turn.assistant.id,
        candidates=tuple(
            AssistantCandidate(a.id, a.name, a.name) for a in (procurement, it)
        ),
        attachment_ids=frozenset(),
        budget=budget,
        execute=execute,
        authorize=authorize,
    )
    if conversation:
        from eneo.mcp_servers.infrastructure.tool_approval import (
            ToolApprovalDecision,
            ToolApprovalWaitResult,
        )

        approval = Mock()
        approval.request_approval = AsyncMock()
        approval.wait_for_approval = AsyncMock(
            return_value=ToolApprovalWaitResult(
                decisions=[
                    ToolApprovalDecision(
                        tool_call_id="call_reused_across_rounds", approved=approved
                    )
                ]
            )
        )
        approval.cancel_approval = AsyncMock()
        monkeypatch.setattr(
            "eneo.completion_models.infrastructure.completion_service.get_approval_manager",
            lambda **kwargs: approval,
        )
        turn.service.completion_service.tenant = turn.user.tenant
        group = GroupChat.create(
            name="Purchase group", space_id=turn.space.id, user_id=turn.user.id
        )
        group.id = uuid4()
        group.published = True
        group.orchestrator_assistant_id = turn.assistant.id
        group.assistants = [GroupChatAssistant(a) for a in (procurement, it)]
        turn.space.group_chats = [group]
        turn.session.group_chat_id = group.id
        turn.service.space_repo.get_space_by_group_chat = AsyncMock(
            return_value=turn.space
        )
        turn.history.record_consultations = AsyncMock()
        monkeypatch.setattr(
            "eneo.assistants.assistant_service.UsersRepository.get_user_by_id_and_tenant_id",
            AsyncMock(return_value=turn.user),
        )
        create = turn.service._create_delegation

        async def capture(**kwargs):
            nonlocal runtime, budget
            runtime = await create(**kwargs)
            budget = runtime.budget
            return runtime

        monkeypatch.setattr(turn.service, "_create_delegation", capture)
        from eneo.group_chat.application.group_chat_service import GroupChatService

        turn.service.space_service.get_space_by_group_chat = AsyncMock(
            return_value=turn.space
        )
        group_service = GroupChatService(
            user=turn.user,
            space_service=turn.service.space_service,
            space_repo=turn.service.space_repo,
            group_chat_repo=Mock(),
            actor_manager=turn.service.actor_manager,
            assistant_service=turn.service,
            session_service=turn.history,
            completion_service=turn.service.completion_service,
            icon_repo=Mock(),
        )
        async with turn.service.repo.session.begin():
            answer_response = await group_service.ask_group_chat(
                question="What is required for this purchase?",
                group_chat_id=group.id,
                stream=True,
                version=2,
                require_tool_approval=True,
            )
            assert parent_requests == 0
        assert not isinstance(answer_response.answer, str)
        events = [event async for event in answer_response.answer]
        answer = "".join(event.text or "" for event in events).strip()
        assert not [
            event for event in events if event.response_type == ResponseType.ERROR
        ]
        saved = turn.history.complete_question_with_answer.call_args.kwargs
        assert [c.status for c in saved["consultations"]] == ["complete"] * 3
        assert saved["consultations"][1].tool_calls[0].tool_name == "lookup"
        assert len(saved["consultations"][1].tool_calls) == 1
        assert saved["consultations"][1].tool_calls[0].approved is approved
        assert approval.request_approval.await_count == 2
        assert all(
            call.kwargs["session_id"] == turn.session.id
            for call in approval.request_approval.call_args_list
        )
        assert any(
            event.consultations and event.consultations[0].status == "awaiting_approval"
            for event in events
        )
        assert saved["consultations"][1].completion_model_id == it.completion_model.id
        assert saved["num_tokens_question"] == 80  # Parent's four model rounds only.
        usage_event = next(
            event for event in events if event.response_type == ResponseType.TOKEN_USAGE
        )
        assert usage_event.usage.prompt_tokens == 180  # Parent + five child rounds.
        assert turn.history.create_session_with_question_placeholder.await_count == 1
        assert turn.history.complete_question_with_answer.await_count == 1
        executed = [item.assistant_id for item in runtime.consultations]
    else:
        prepared = await turn.service._prepare_turn(
            question="What is required for this purchase?",
            assistant_id=turn.assistant.id,
        )
        with runtime.bind():
            result, _ = await turn.service._execute_turn(
                prepared,
                turn.session,
                AssistantCompletionFileInputs([], []),
                stream=stream,
                version=2,
                require_tool_approval=False,
            )
            if isinstance(result.completion, Completion):
                answer = result.completion.text
            else:
                events = [
                    event
                    async for event in cast(
                        AsyncGenerator[Completion, None], result.completion
                    )
                ]
                answer = "".join(event.text or "" for event in events).strip()
                assert any(
                    event.consultations
                    and event.consultations[0].status == "running"
                    and event.consultations[0].tool_calls
                    for event in events
                )
    assert answer == (
        "Review required; IT evidence is unavailable."
        if approved is False
        else "Procurement and IT require a review, SSO and an exit plan."
    )
    assert executed == [procurement.id, it.id, it.id]
    assert budget.consultations == 3
    assert budget.model_requests == 9
    assert budget.tool_calls == (3 if approved is False else 5)
    assert tool_calls == ([] if approved is False else ["lookup", "lookup"])
    assert [step.ordinal for step in runtime.consultations] == [1, 2, 3]
    assert len({step.id for step in runtime.consultations}) == 3
    assert runtime.consultations[1].tool_calls[0].tool_name == "lookup"
    assert runtime.consultations[2].question == "Clarify the IT exit plan"
    assert current_execution_budget() is None
    if not conversation:
        turn.history.create_session_with_question_placeholder.assert_not_awaited()
        turn.history.complete_question_with_answer.assert_not_awaited()


async def test_model_limit_prevents_another_outbound_request(
    monkeypatch: pytest.MonkeyPatch,
):
    provider = AsyncMock(return_value=response("First answer"))
    monkeypatch.setattr(
        "eneo.model_providers.infrastructure.litellm_transport.acompletion", provider
    )
    budget = ExecutionBudget(ExecutionLimits(model_requests=1))
    with budget.bind():
        await dispatch_completion(
            model="test", messages=[{"role": "user", "content": "First"}]
        )
        with pytest.raises(ExecutionLimitReached):
            await dispatch_completion(
                model="test", messages=[{"role": "user", "content": "Second"}]
            )
    assert provider.await_count == 1


async def test_revoked_parent_receives_no_partial_evidence_after_child_timeout():
    parent, child = uuid4(), uuid4()
    revoked = False

    async def execute(request: ConsultationRequest) -> AsyncGenerator[Completion, None]:
        nonlocal revoked
        yield Completion(text="Protected evidence", response_type=ResponseType.TEXT)
        revoked = True
        raise TimeoutError()

    async def authorize(assistant_id: UUID) -> None:
        if assistant_id == parent and revoked:
            raise UnauthorizedException()

    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT requirements"),),
        attachment_ids=frozenset(),
        budget=ExecutionBudget(),
        execute=execute,
        authorize=authorize,
    )
    with runtime.bind():
        events = [
            event
            async for event in runtime.call(
                call_id="one",
                arguments=json.dumps(
                    {
                        "assistant_id": str(child),
                        "question": "Check",
                        "attachment_ids": [],
                    }
                ),
            )
        ]
    assert events[-1].consultations[0].status == "denied"
    assert "Protected evidence" not in runtime.result_for("one")


async def test_parent_cancellation_cleans_up_active_child():
    parent, child = uuid4(), uuid4()
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def execute(request: ConsultationRequest) -> AsyncGenerator[Completion, None]:
        try:
            started.set()
            await asyncio.Event().wait()
            yield Completion(text="unreachable")
        finally:
            cleaned.set()

    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT requirements"),),
        attachment_ids=frozenset(),
        budget=ExecutionBudget(),
        execute=execute,
        authorize=AsyncMock(),
    )

    async def consume() -> None:
        with runtime.bind():
            async for _ in runtime.call(
                call_id="one",
                arguments=json.dumps(
                    {
                        "assistant_id": str(child),
                        "question": "Check",
                        "attachment_ids": [],
                    }
                ),
            ):
                pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
    assert runtime.consultations[0].status == "cancelled"


def group_plan(turn: TurnFixture, monkeypatch: pytest.MonkeyPatch, specialist):
    group = GroupChat.create(name="Group", space_id=turn.space.id, user_id=turn.user.id)
    group.id = uuid4()
    group.published = True
    group.orchestrator_assistant_id = turn.assistant.id
    group.assistants = [GroupChatAssistant(specialist)]
    turn.space.assistants.append(specialist)
    turn.space.group_chats = [group]
    turn.session.group_chat_id = group.id
    turn.service.space_repo.get_space_by_group_chat = AsyncMock(return_value=turn.space)
    turn.history.record_consultations = AsyncMock()
    monkeypatch.setattr(
        "eneo.assistants.assistant_service.UsersRepository.get_user_by_id_and_tenant_id",
        AsyncMock(return_value=turn.user),
    )
    return AssistantDelegationPlan(
        group.id,
        turn.space.id,
        turn.assistant.id,
        (AssistantCandidate(specialist.id, specialist.name, "Specialist"),),
    )


@pytest.mark.parametrize(
    "change",
    ["membership", "disabled_user", "classification", "prompt", "skill_policy"],
)
async def test_changed_authorization_or_policy_prevents_next_handoff(
    turn: TurnFixture, monkeypatch: pytest.MonkeyPatch, change: str
):
    specialist = copy.deepcopy(turn.assistant)
    specialist.id = uuid4()
    plan = group_plan(turn, monkeypatch, specialist)
    async with turn.service.repo.session.begin():
        prepared = await turn.service._prepare_turn(
            question="Question", assistant_id=turn.assistant.id
        )
        runtime = await turn.service._create_delegation(
            plan=plan,
            prepared=prepared,
            session=turn.session,
            version=2,
            require_tool_approval=False,
            disabled_mcp_server_ids=None,
            disabled_capabilities=None,
        )
    await runtime.authorize(specialist.id)
    if change == "membership":
        turn.space.group_chats[0].assistants = []
    elif change == "disabled_user":
        turn.user.state = UserState.INACTIVE
    elif change == "classification":
        turn.space.security_classification = copy.deepcopy(
            turn.space.security_classification
        )
        turn.space.security_classification.security_level += 1
    elif change == "prompt":
        specialist.prompt.text = "Changed instructions"
    else:
        from dataclasses import replace

        original = turn.service.skill_service.create_turn_plan.side_effect

        async def changed_policy(**kwargs):
            plan = await original(**kwargs)
            return replace(
                plan, policy=replace(plan.policy, max_activations_per_turn=1)
            )

        turn.service.skill_service.create_turn_plan.side_effect = changed_policy
    with pytest.raises(
        (UnauthorizedException, SecurityClassificationMismatchException)
    ):
        await runtime.authorize(specialist.id)
    assert not turn.service.repo.session.in_transaction()
    turn.provider.assert_not_awaited()


@pytest.mark.parametrize("forgery", ["assistant", "attachment", "space"])
async def test_model_cannot_expand_delegation_scope(forgery: str):
    parent, child = uuid4(), uuid4()
    executed = False

    async def execute(request):
        nonlocal executed
        executed = True
        yield Completion(text="Forbidden")

    authorize = AsyncMock()
    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT"),),
        attachment_ids=frozenset(),
        budget=ExecutionBudget(),
        execute=execute,
        authorize=authorize,
    )
    arguments = {"assistant_id": str(child), "question": "Check", "attachment_ids": []}
    if forgery == "assistant":
        arguments["assistant_id"] = str(parent)
    elif forgery == "attachment":
        arguments["attachment_ids"] = [str(uuid4())]
    else:
        arguments["space_id"] = str(uuid4())
    with runtime.bind():
        assert [
            event
            async for event in runtime.call(
                call_id="forged", arguments=json.dumps(arguments)
            )
        ] == []
    assert not executed
    authorize.assert_not_awaited()
    assert json.loads(runtime.result_for("forged"))["outcome"] == "denied"


@pytest.mark.parametrize("tokens", [0, 100])
async def test_text_only_consultation_publishes_one_reply_and_marks_empty_incomplete(
    tokens,
):
    parent, child = uuid4(), uuid4()

    async def execute(request):
        for _ in range(tokens):
            yield Completion(response_type=ResponseType.TEXT, text="x")

    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT"),),
        attachment_ids=frozenset(),
        budget=ExecutionBudget(),
        execute=execute,
        authorize=AsyncMock(),
    )
    with runtime.bind():
        events = [
            event
            async for event in runtime.call(
                call_id="reply",
                arguments=json.dumps(
                    {
                        "assistant_id": str(child),
                        "question": "Check",
                        "attachment_ids": [],
                    }
                ),
            )
        ]
    assert len(events) == 2  # Start and result, rather than a full snapshot per token.
    saved = events[-1].consultations[0]
    assert saved.answer == "x" * tokens
    assert saved.status == ("complete" if tokens else "incomplete")


async def test_consultation_history_preserves_repeated_steps_but_hides_raw_results():
    parent, child = uuid4(), uuid4()

    async def execute(request):
        yield Completion(
            response_type=ResponseType.REASONING,
            reasoning_content="Private deliberation",
        )
        for output in ("First result", "Second result"):
            for status in ("pending", "succeeded"):
                yield Completion(
                    response_type=ResponseType.TOOL_CALL,
                    tool_calls_metadata=[
                        ToolCallMetadata(
                            server_name="inventory",
                            tool_name="lookup",
                            tool_call_id="reused",
                            result_status=status,
                            result=output if status == "succeeded" else None,
                        )
                    ],
                )
        yield Completion(
            response_type=ResponseType.TEXT, text="Actual specialist answer"
        )

    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT"),),
        attachment_ids=frozenset(),
        budget=ExecutionBudget(),
        execute=execute,
        authorize=AsyncMock(),
    )
    with runtime.bind():
        events = [
            event
            async for event in runtime.call(
                call_id="one",
                arguments=json.dumps({"assistant_id": str(child), "question": "Check"}),
            )
        ]
    stored = ConsultationInfo.from_execution(events[-1].consultations[0])
    restored = ConsultationInfo.model_validate_json(stored.model_dump_json())
    assert [step.result for step in restored.tool_calls] == [
        "First result",
        "Second result",
    ]
    assert len({step.step_id for step in restored.tool_calls}) == 2
    assert "Private deliberation" not in stored.model_dump_json()
    session_id, tenant_id = uuid4(), uuid4()
    question = Question(
        id=uuid4(),
        question="Parent question",
        answer="Synthesis",
        tenant_id=tenant_id,
        session_id=session_id,
        num_tokens_question=10,
        num_tokens_answer=5,
        consultations=[restored],
    )
    public = to_question_public(question)
    assert public.consultations[0].answer == "Actual specialist answer"
    assert all(step.result is None for step in public.consultations[0].tool_calls)
    from eneo.sessions.session import SessionInDB

    session = SessionInDB(
        id=session_id, user_id=uuid4(), name="Group", questions=[question]
    )
    # The route already authorizes the parent session before calling this reader.
    service = object.__new__(SessionService)
    for index, step in enumerate(restored.tool_calls):
        record = await service.get_tool_call_result(session, str(step.step_id))
        assert record.result == ["First result", "Second result"][index]
    assert await service.get_tool_call_result(session, "reused") is None


@pytest.mark.parametrize(
    "knowledge_mode, stop",
    [("inject", None), ("tool", None), ("tool", "cancel"), ("tool", "timeout")],
)
async def test_specialist_keeps_skill_and_knowledge_in_existing_execution_path(
    turn: TurnFixture,
    monkeypatch: pytest.MonkeyPatch,
    knowledge_mode: str,
    stop: str | None,
):
    import re

    from eneo.assistants.api.assistant_models import KnowledgeMode
    from eneo.collections.domain.collection import Collection
    from eneo.completion_models.domain.skill_activation import (
        SKILL_ACTIVATION_TOOL_NAME,
    )
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.info_blobs.info_blob import (
        InfoBlobChunkInDBWithScore,
        InfoBlobInDBWithScore,
    )
    from eneo.services.service import DatastoreResult
    from eneo.skills.domain.skill import (
        ResolvedSkillBinding,
        SkillActivationMode,
        SkillBindingSource,
        SkillRuntimeResolution,
    )

    child = copy.deepcopy(turn.assistant)
    child.id = uuid4()
    child.name = "IT"
    child.prompt.text = "Use the IT evidence."
    child.knowledge_mode = KnowledgeMode(knowledge_mode)
    embedding = EmbeddingModel(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        user=turn.user,
        nickname=None,
        name="text-embedding-3-small",
        family="openai",
        hosting=None,
        org=None,
        stability=None,
        open_source=False,
        description=None,
        hf_link=None,
        is_deprecated=False,
        is_org_enabled=True,
        max_input=8192,
        dimensions=1536,
        security_classification=turn.space.security_classification,
    )
    collection = Collection.create(
        space_id=turn.space.id,
        user=turn.user,
        name="IT policy",
        embedding_model=embedding,
    )
    child.collections = [collection]
    turn.space.collections = [collection]
    turn.space.embedding_models = [embedding]
    plan = group_plan(turn, monkeypatch, child)
    skill = ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=turn.space.id,
        slug="it-review",
        revision_number=1,
        current_revision_number=1,
        display_name="IT review",
        description="Review IT requirements",
        instructions="Apply the configured IT checklist.",
        content_digest="a" * 64,
        position=0,
        source=SkillBindingSource.SPACE,
        activation_mode=SkillActivationMode.ON_DEMAND,
    )

    async def resolve(*, assistant_id):
        return SkillRuntimeResolution(
            eligible=(skill,) if assistant_id == child.id else (), blocked=()
        )

    turn.service.skill_service.resolve_assistant_bindings_for_runtime.side_effect = (
        resolve
    )
    turn.service.auth_service.create_scoped_mcp_token.return_value = "test-scoped-token"
    source_id = uuid4()
    evidence = "The IT policy requires SSO and a documented exit plan."
    blob = InfoBlobInDBWithScore(
        id=source_id,
        embedding_model_id=embedding.id,
        user_id=turn.user.id,
        tenant_id=turn.user.tenant_id,
        size=len(evidence),
        source_id=uuid4(),
        version_state="current",
        text=evidence,
        title="IT policy",
        score=1,
    )
    chunk = InfoBlobChunkInDBWithScore(
        id=uuid4(),
        text=evidence,
        chunk_no=0,
        info_blob_id=source_id,
        tenant_id=turn.user.tenant_id,
        info_blob_title="IT policy",
        score=1,
    )
    turn.service.references_service.get_references = AsyncMock(
        return_value=DatastoreResult(
            chunks=[chunk], no_duplicate_chunks=[chunk], info_blobs=[blob]
        )
    )
    called = []
    started = asyncio.Event()
    clients = []

    class KnowledgeClient(_FakeMCPClient):
        async def call_tool(self, name, arguments):
            called.append(name)
            clients.append(self)
            assert name == "search_knowledge"
            if stop:
                started.set()
                await asyncio.Event().wait()
            return {
                "content": [
                    {
                        "type": "resource",
                        "uri": f"eneo://info-blob/{source_id}",
                        "mime_type": "text/plain",
                        "text": evidence,
                    }
                ],
                "is_error": False,
            }

    monkeypatch.setattr(
        "eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session.MCPClient",
        KnowledgeClient,
    )

    async def provider(**kwargs):
        messages = kwargs["messages"]
        system = str(messages[0]["content"])
        offered = {item["function"]["name"] for item in kwargs.get("tools", [])}
        if "Use the IT evidence." not in system:
            if messages[-1]["role"] != "tool":
                return response(
                    tool=CONSULT_ASSISTANT_TOOL,
                    arguments=json.dumps(
                        {
                            "assistant_id": str(child.id),
                            "question": "Review IT requirements",
                        }
                    ),
                    stream=True,
                )
            handoff = str(messages[-1]["content"])
            assert evidence in handoff
            return response("SSO and an exit plan are required.", stream=True)
        assert CONSULT_ASSISTANT_TOOL not in offered
        if "Apply the configured IT checklist." not in system:
            assert SKILL_ACTIVATION_TOOL_NAME in offered
            return response(
                tool=SKILL_ACTIVATION_TOOL_NAME,
                arguments='{"skill_key":"skill-1"}',
                stream=True,
            )
        if knowledge_mode == "tool":
            assert "knowledge__search_knowledge" in offered
            if "source_id:" not in str(messages[-1]["content"]):
                return response(
                    tool="knowledge__search_knowledge",
                    arguments='{"query":"IT requirements"}',
                    stream=True,
                )
            citation = re.search(
                r"source_id: ([a-f0-9]{8})", str(messages[-1]["content"])
            ).group(1)
        else:
            assert evidence in str(messages)
            citation = str(source_id)[:8]
        return response(f'{evidence} <inref id="{citation}"/>', stream=True)

    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        dispatch_completion,
    )
    monkeypatch.setattr(
        "eneo.model_providers.infrastructure.litellm_transport.acompletion", provider
    )
    partial_save = AsyncMock()
    monkeypatch.setattr(
        "eneo.sessions.session_service.persist_partial_question_answer", partial_save
    )
    monkeypatch.setattr(
        "eneo.sessions.session_service.schedule_background_save",
        lambda pending: pending.close(),
    )
    if stop == "timeout":
        monkeypatch.setattr(
            "eneo.assistants.assistant_service.ExecutionBudget",
            lambda: ExecutionBudget(ExecutionLimits(duration_seconds=0.1)),
        )
    async with turn.service.repo.session.begin():
        reply = await turn.service.ask(
            question="Review",
            assistant_id=turn.assistant.id,
            group_chat_id=plan.group_chat_id,
            delegation_plan=plan,
            stream=knowledge_mode == "tool",
            version=2,
        )
    if stop == "cancel":

        async def consume():
            return [event async for event in reply.answer]

        consumer = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=2)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert clients[0].disconnect_task is clients[0].connect_task
        saved = partial_save.call_args.kwargs["consultations"][0]
        assert saved.status == "cancelled"
        assert (saved.input_tokens, saved.output_tokens) == (40, 14)
        assert partial_save.call_args.kwargs["num_tokens_question"] == 20
        assert partial_save.call_args.kwargs["num_tokens_answer"] == 7
        turn.history.complete_question_with_answer.assert_not_awaited()
        return
    if knowledge_mode == "inject":
        from eneo.assistants.api.assistant_protocol import to_conversation_response

        public = await to_conversation_response(reply, stream=False)
        assert public.answer == "SSO and an exit plan are required."
        assert len(public.consultations) == 1
        assert all(step.result is None for step in public.consultations[0].tool_calls)
        events = []
    else:
        events = [event async for event in reply.answer]
    if stop == "timeout":
        assert events[-1].error_reason == "execution_limit_duration"
        assert clients[0].disconnect_task is clients[0].connect_task
        saved = partial_save.call_args.kwargs["consultations"][0]
        assert saved.status == "timeout"
        assert (saved.input_tokens, saved.output_tokens) == (40, 14)
        turn.history.complete_question_with_answer.assert_not_awaited()
        return
    assert not [event for event in events if event.response_type == ResponseType.ERROR]
    saved = turn.history.complete_question_with_answer.call_args.kwargs[
        "consultations"
    ][0]
    assert saved.status == "complete"
    assert evidence in saved.answer
    assert any(step.server_name == "skills" for step in saved.tool_calls)
    assert any(step.server_name == "knowledge" for step in saved.tool_calls)
    assert len(saved.references) == 1
    assert saved.references[0].content == evidence
    assert called == (["search_knowledge"] if knowledge_mode == "tool" else [])
    if knowledge_mode == "tool":
        turn.service.references_service.get_references.assert_not_awaited()
    else:
        turn.service.references_service.get_references.assert_awaited_once()

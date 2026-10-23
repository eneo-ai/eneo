from __future__ import annotations

import asyncio
import copy
import dataclasses
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
from eneo.assistants.assistant import AssistantSpecialist
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
from eneo.main.exceptions import (
    BadRequestException,
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
        give_specialists(turn, procurement, it)
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
        async with turn.service.repo.session.begin():
            # No plan is passed: the assistant orchestrates because it has
            # specialists and a tool-capable model.
            answer_response = await turn.service.ask(
                question="What is required for this purchase?",
                assistant_id=turn.assistant.id,
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
    budget = ExecutionBudget(
        ExecutionLimits(model_requests=1, reserved_model_requests=0)
    )
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


def give_specialists(turn: TurnFixture, *specialists, description: str = "Specialist"):
    """Make the fixture assistant orchestrate the given assistants."""
    for specialist in specialists:
        if specialist not in turn.space.assistants:
            turn.space.assistants.append(specialist)
    turn.assistant.specialists = [
        AssistantSpecialist(
            id=specialist.id,
            name=specialist.name,
            default_description=specialist.description,
            user_description=description,
        )
        for specialist in specialists
    ]
    turn.service.space_repo.get_space_by_assistant = AsyncMock(return_value=turn.space)


def specialist_plan(turn: TurnFixture, monkeypatch: pytest.MonkeyPatch, specialist):
    give_specialists(turn, specialist)
    turn.history.record_consultations = AsyncMock()
    monkeypatch.setattr(
        "eneo.assistants.assistant_service.UsersRepository.get_user_by_id_and_tenant_id",
        AsyncMock(return_value=turn.user),
    )
    return AssistantDelegationPlan(
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
    plan = specialist_plan(turn, monkeypatch, specialist)
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
        turn.assistant.specialists = []
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
    plan = specialist_plan(turn, monkeypatch, child)
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
            lambda: ExecutionBudget(
                ExecutionLimits(duration_seconds=0.1, reserved_seconds=0)
            ),
        )
    async with turn.service.repo.session.begin():
        reply = await turn.service.ask(
            question="Review",
            assistant_id=turn.assistant.id,
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
    if knowledge_mode == "inject":
        # Reference rows are keyed by their own id: reusing the blob id made
        # the second question citing the same blob violate the primary key.
        assert saved.references[0].id != source_id
        assert str(saved.references[0].id)[:8] == str(source_id)[:8]
    assert called == (["search_knowledge"] if knowledge_mode == "tool" else [])
    if knowledge_mode == "tool":
        turn.service.references_service.get_references.assert_not_awaited()
    else:
        turn.service.references_service.get_references.assert_awaited_once()


def _consultation_arguments(child: UUID) -> str:
    return json.dumps(
        {"assistant_id": str(child), "question": "Check", "attachment_ids": []}
    )


async def test_specialists_cannot_spend_the_parent_reserve():
    limits = ExecutionLimits(
        model_requests=3,
        reserved_model_requests=2,
        output_characters=10,
        reserved_output_characters=4,
    )
    budget = ExecutionBudget(limits)
    with budget.child_scope():
        budget.reserve_model_request(1)
        with pytest.raises(ExecutionLimitReached) as model_refusal:
            budget.reserve_model_request(1)
        budget.record_output("abcdef")
        with pytest.raises(ExecutionLimitReached) as output_refusal:
            budget.record_output("g")
    assert model_refusal.value.limit == "model_requests"
    assert output_refusal.value.limit == "output_characters"
    # The orchestrator still owns its reserved synthesis round and output.
    budget.reserve_model_request(1)
    budget.record_output("ghij")
    assert (budget.model_requests, budget.output_characters) == (2, 10)


async def test_consultation_is_refused_rather_than_started_on_the_reserve():
    parent, child = uuid4(), uuid4()
    started = False

    async def execute(request):
        nonlocal started
        started = True
        yield Completion(text="unreachable")

    budget = ExecutionBudget(
        ExecutionLimits(model_requests=3, reserved_model_requests=2)
    )
    budget.reserve_model_request(1)
    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT"),),
        attachment_ids=frozenset(),
        budget=budget,
        execute=execute,
        authorize=AsyncMock(),
    )
    with runtime.bind():
        events = [
            event
            async for event in runtime.call(
                call_id="one", arguments=_consultation_arguments(child)
            )
        ]
    assert events == []
    assert not started
    assert runtime.consultations == []
    assert json.loads(runtime.result_for("one")) == {
        "outcome": "incomplete",
        "reason": "execution_limit_reached",
    }
    assert budget.consultations == 0
    # The reserve is intact for the parent's final answer.
    budget.reserve_model_request(1)
    budget.reserve_model_request(1)


async def test_request_size_is_an_admission_limit_not_a_cumulative_charge(
    monkeypatch: pytest.MonkeyPatch,
):
    provider = AsyncMock(return_value=response("Answer"))
    monkeypatch.setattr(
        "eneo.model_providers.infrastructure.litellm_transport.acompletion", provider
    )
    budget = ExecutionBudget(ExecutionLimits(request_bytes=200, model_requests=5))
    with budget.bind():
        for _ in range(4):
            await dispatch_completion(
                model="test", messages=[{"role": "user", "content": "x" * 100}]
            )
        with pytest.raises(ExecutionLimitReached) as refusal:
            await dispatch_completion(
                model="test", messages=[{"role": "user", "content": "x" * 400}]
            )
    assert refusal.value.limit == "request_bytes"
    assert provider.await_count == 4
    assert budget.largest_request_bytes < 200


async def test_approval_wait_is_excluded_from_turn_and_consultation_deadlines():
    budget = ExecutionBudget(
        ExecutionLimits(
            duration_seconds=0.4,
            consultation_seconds=0.2,
            reserved_seconds=0.05,
        )
    )
    async with asyncio.timeout(budget.child_seconds) as deadline:
        with budget.deadline(deadline):
            before = deadline.when()
            assert before is not None
            async with budget.pause():
                await asyncio.sleep(0.25)
            after = deadline.when()
            assert after is not None
            assert after - before >= 0.25
            assert not deadline.expired()
            await asyncio.sleep(0.05)
    assert budget.paused_seconds >= 0.25
    assert budget.remaining_seconds > 0.25


async def test_awaiting_approval_names_only_the_calls_the_approval_decides():
    parent, child = uuid4(), uuid4()

    def step(call_id: str, status: str, internal: bool) -> ToolCallMetadata:
        return ToolCallMetadata(
            server_name="knowledge" if internal else "inventory",
            tool_name="search" if internal else "lookup",
            tool_call_id=call_id,
            result_status=status,
            is_internal=internal,
        )

    async def execute(request):
        yield Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[
                step("internal", "pending", True),
                step("external", "pending", False),
            ],
        )
        yield Completion(
            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
            approval_id="approval-1",
            tool_calls_metadata=[step("external", "awaiting_approval", False)],
        )
        yield Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[
                step("internal", "succeeded", True),
                step("external", "succeeded", False),
            ],
        )
        yield Completion(response_type=ResponseType.TEXT, text="Done")

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
                call_id="one", arguments=_consultation_arguments(child)
            )
        ]
    snapshots = [event.consultations[0] for event in events if event.consultations]
    awaiting = next(item for item in snapshots if item.status == "awaiting_approval")
    assert awaiting.approval_id == "approval-1"
    assert awaiting.awaiting_tool_call_ids == ["external"]
    assert {step.tool_call_id for step in awaiting.tool_calls} == {
        "internal",
        "external",
    }
    assert snapshots[-1].status == "complete"
    assert snapshots[-1].awaiting_tool_call_ids == []
    assert snapshots[-1].approval_id is None
    stored = ConsultationInfo.from_execution(awaiting)
    assert stored.awaiting_tool_call_ids == ["external"]


@pytest.mark.parametrize("readable", ["one", "none"])
async def test_unreadable_specialists_are_excluded_before_history_writes(
    turn: TurnFixture, monkeypatch: pytest.MonkeyPatch, readable: str
):
    from eneo.main.exceptions import BadRequestException

    hidden = copy.deepcopy(turn.assistant)
    hidden.id = uuid4()
    hidden.name = "Hidden legal"
    visible = copy.deepcopy(turn.assistant)
    visible.id = uuid4()
    visible.name = "IT"
    plan = specialist_plan(turn, monkeypatch, visible)
    give_specialists(turn, visible, hidden)
    unreadable = {hidden.id} if readable == "one" else {hidden.id, visible.id}
    plan = AssistantDelegationPlan(
        plan.space_id,
        plan.orchestrator_id,
        (
            *plan.candidates,
            AssistantCandidate(hidden.id, hidden.name, "Legal"),
        ),
    )
    prepare = turn.service._prepare_turn

    async def prepare_or_refuse(**kwargs):
        if kwargs["assistant_id"] in unreadable:
            raise UnauthorizedException(
                "You do not have permission to use this assistant."
            )
        return await prepare(**kwargs)

    monkeypatch.setattr(turn.service, "_prepare_turn", prepare_or_refuse)
    created: list[AssistantDelegation] = []
    create = turn.service._create_delegation

    async def capture(**kwargs):
        created.append(await create(**kwargs))
        return created[-1]

    monkeypatch.setattr(turn.service, "_create_delegation", capture)

    async def answer_without_consulting(**kwargs: object):
        return response("No specialist was needed.", stream=True)

    turn.provider.side_effect = answer_without_consulting

    if readable == "none":
        with pytest.raises(BadRequestException) as refusal:
            async with turn.service.repo.session.begin():
                await turn.service.ask(
                    question="Review",
                    assistant_id=turn.assistant.id,
                    delegation_plan=plan,
                    stream=True,
                    version=2,
                )
        assert refusal.value.code == "no_available_specialists"
        turn.history.create_session_with_question_placeholder.assert_not_awaited()
        turn.history.create_question_placeholder.assert_not_awaited()
        assert created == []
        return

    async with turn.service.repo.session.begin():
        reply = await turn.service.ask(
            question="Review",
            assistant_id=turn.assistant.id,
            delegation_plan=plan,
            stream=True,
            version=2,
        )
    events = [event async for event in reply.answer]
    assert not [event for event in events if event.response_type == ResponseType.ERROR]
    assert turn.history.create_session_with_question_placeholder.await_count == 1
    (runtime,) = created
    assert set(runtime.candidates) == {visible.id}
    assert runtime.unavailable_candidates == 1
    description = runtime.tool_definition.description
    assert "Hidden legal" not in description
    assert "1 configured specialist(s) are not available" in description


@pytest.mark.parametrize(
    "failure",
    [
        "ModelNotAvailableException",
        "NoModelSelectedException",
        "KnowledgeModelUnavailableException",
        "SecurityClassificationMismatchException",
    ],
)
async def test_specialists_with_unusable_configuration_are_left_out(
    turn: TurnFixture, monkeypatch: pytest.MonkeyPatch, failure: str
):
    """One member whose model or knowledge is unusable must not refuse the group."""
    from eneo.main import exceptions

    broken = copy.deepcopy(turn.assistant)
    broken.id = uuid4()
    broken.name = "Broken legal"
    visible = copy.deepcopy(turn.assistant)
    visible.id = uuid4()
    visible.name = "IT"
    plan = specialist_plan(turn, monkeypatch, visible)
    give_specialists(turn, visible, broken)
    plan = AssistantDelegationPlan(
        plan.space_id,
        plan.orchestrator_id,
        (
            *plan.candidates,
            AssistantCandidate(broken.id, broken.name, "Legal"),
        ),
    )
    prepare = turn.service._prepare_turn
    exc_type = getattr(exceptions, failure)

    async def prepare_or_fail(**kwargs):
        if kwargs["assistant_id"] == broken.id:
            raise exc_type("The selected AI model is not available in this space.")
        return await prepare(**kwargs)

    monkeypatch.setattr(turn.service, "_prepare_turn", prepare_or_fail)
    created: list[AssistantDelegation] = []
    create = turn.service._create_delegation

    async def capture(**kwargs):
        created.append(await create(**kwargs))
        return created[-1]

    monkeypatch.setattr(turn.service, "_create_delegation", capture)

    async def answer_without_consulting(**kwargs: object):
        return response("No specialist was needed.", stream=True)

    turn.provider.side_effect = answer_without_consulting

    async with turn.service.repo.session.begin():
        reply = await turn.service.ask(
            question="Review",
            assistant_id=turn.assistant.id,
            delegation_plan=plan,
            stream=True,
            version=2,
        )
    events = [event async for event in reply.answer]
    assert not [event for event in events if event.response_type == ResponseType.ERROR]
    (runtime,) = created
    assert set(runtime.candidates) == {visible.id}
    assert runtime.unavailable_candidates == 1
    assert "Broken legal" not in runtime.tool_definition.description


@pytest.mark.parametrize(
    ("failure", "status", "reason"),
    [
        (RuntimeError("provider setup exploded"), 500, "assistant_execution_failed"),
        (
            BadRequestException(
                "Attachments do not fit.", code="attachments_too_large"
            ),
            400,
            "attachments_too_large",
        ),
    ],
)
async def test_execution_failures_end_the_orchestrated_stream_with_an_error_event(
    turn: TurnFixture,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status: int,
    reason: str,
):
    """Headers are already sent when execution starts: no raw exception may escape."""
    specialist = copy.deepcopy(turn.assistant)
    specialist.id = uuid4()
    specialist.name = "IT"
    plan = specialist_plan(turn, monkeypatch, specialist)

    async def explode(*args: object, **kwargs: object):
        raise failure

    monkeypatch.setattr(turn.service, "_execute_turn", explode)

    async with turn.service.repo.session.begin():
        reply = await turn.service.ask(
            question="Review",
            assistant_id=turn.assistant.id,
            delegation_plan=plan,
            stream=True,
            version=2,
        )
    events = [event async for event in reply.answer]
    assert len(events) == 1
    (error,) = events
    assert error.response_type == ResponseType.ERROR
    assert error.error_code == status
    assert error.error_reason == reason
    assert error.stop is True


async def test_context_bindings_survive_finalization_in_another_context():
    """sse-starlette leaves the body iterator to the asyncgen GC hook on disconnect."""
    import contextvars

    budget = ExecutionBudget()
    runtime = AssistantDelegation(
        parent_assistant_id=uuid4(),
        candidates=(AssistantCandidate(uuid4(), "IT", "IT"),),
        attachment_ids=frozenset(),
        budget=budget,
        execute=AsyncMock(),
        authorize=AsyncMock(),
    )

    async def stream() -> AsyncGenerator[int, None]:
        with runtime.bind():
            yield 1
            yield 2

    generator = stream()
    assert await generator.__anext__() == 1
    # Closing in a fresh context is what the finalizer does; the finally
    # blocks must run to completion there without a ValueError, and leave
    # that context clean. (The owning context is the finished request's.)
    finalizer = contextvars.Context()
    await asyncio.create_task(generator.aclose(), context=finalizer)
    assert generator.ag_frame is None
    assert finalizer.run(current_execution_budget) is None
    assert finalizer.run(current_assistant_delegation) is None


async def test_refused_consultation_costs_no_budget():
    parent, child = uuid4(), uuid4()

    async def execute(request: ConsultationRequest) -> AsyncGenerator[Completion, None]:
        raise AssertionError("a refused specialist never executes")
        yield  # pragma: no cover

    async def authorize(assistant_id: UUID) -> None:
        if assistant_id == child:
            raise UnauthorizedException()

    budget = ExecutionBudget()
    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT requirements"),),
        attachment_ids=frozenset(),
        budget=budget,
        execute=execute,
        authorize=authorize,
    )
    with runtime.bind():
        events = [
            event
            async for event in runtime.call(
                call_id="one", arguments=_consultation_arguments(child)
            )
        ]
    assert events == []
    assert json.loads(runtime.result_for("one")) == {"outcome": "denied"}
    assert (budget.consultations, budget.tool_calls) == (0, 0)


async def test_specialist_answering_after_an_approval_timeout_completes():
    parent, child = uuid4(), uuid4()

    async def execute(request: ConsultationRequest) -> AsyncGenerator[Completion, None]:
        step = ToolCallMetadata(
            server_name="inventory",
            tool_name="lookup",
            tool_call_id="external",
            result_status="pending",
            is_internal=False,
        )
        yield Completion(
            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
            tool_calls_metadata=[step],
            approval_id="approval-1",
        )
        yield Completion(
            response_type=ResponseType.TOOL_APPROVAL_TIMEOUT,
            tool_calls_metadata=[dataclasses.replace(step, result_status="timeout")],
        )
        yield Completion(
            text="Without the lookup: 25 days.", response_type=ResponseType.TEXT
        )

    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "HR", "HR"),),
        attachment_ids=frozenset(),
        budget=ExecutionBudget(),
        execute=execute,
        authorize=AsyncMock(),
    )
    with runtime.bind():
        events = [
            event
            async for event in runtime.call(
                call_id="one", arguments=_consultation_arguments(child)
            )
        ]
    final = events[-1].consultations[0]
    assert final.status == "complete"
    assert final.answer == "Without the lookup: 25 days."
    assert final.approval_id is None
    assert json.loads(runtime.result_for("one"))["outcome"] == "complete"


async def test_child_deadline_expiring_while_the_parent_is_busy_times_out_the_consultation():
    """The parent consumes slowly (persisting, writing the response); the child
    deadline must still end only the consultation, as a timeout, not the turn."""
    parent, child = uuid4(), uuid4()
    cleaned = asyncio.Event()

    async def execute(request: ConsultationRequest) -> AsyncGenerator[Completion, None]:
        try:
            yield Completion(text="Partial ", response_type=ResponseType.TEXT)
            await asyncio.sleep(10)
            yield Completion(text="never", response_type=ResponseType.TEXT)
        finally:
            cleaned.set()

    budget = ExecutionBudget(
        ExecutionLimits(
            duration_seconds=5, consultation_seconds=0.05, reserved_seconds=0
        )
    )
    runtime = AssistantDelegation(
        parent_assistant_id=parent,
        candidates=(AssistantCandidate(child, "IT", "IT requirements"),),
        attachment_ids=frozenset(),
        budget=budget,
        execute=execute,
        authorize=AsyncMock(),
    )
    with runtime.bind():
        events = []
        async for event in runtime.call(
            call_id="one", arguments=_consultation_arguments(child)
        ):
            events.append(event)
            # Away from the generator for longer than the child deadline.
            await asyncio.sleep(0.2)
    final = events[-1].consultations[0]
    assert final.status == "timeout"
    assert final.answer == "Partial "
    assert cleaned.is_set()
    assert json.loads(runtime.result_for("one"))["outcome"] == "timeout"
    assert budget.remaining_seconds > 1


async def test_nested_pauses_account_the_waited_time_once():
    budget = ExecutionBudget(
        ExecutionLimits(duration_seconds=5, consultation_seconds=1, reserved_seconds=0)
    )
    async with asyncio.timeout(budget.child_seconds) as deadline:
        with budget.deadline(deadline):
            before = deadline.when()
            assert before is not None
            async with budget.pause():
                async with budget.pause():
                    await asyncio.sleep(0.1)
                # Still suspended: only the outermost pause resumes the clock.
                assert deadline.when() is None
                await asyncio.sleep(0.05)
            after = deadline.when()
            assert after is not None
            assert 0.15 <= after - before < 0.3
    assert 0.15 <= budget.paused_seconds < 0.3


async def test_turn_deadline_is_suspended_while_the_response_writer_holds_control(
    turn: TurnFixture, monkeypatch: pytest.MonkeyPatch
):
    """Time spent by the consumer between chunks is not the turn's execution time."""
    specialist = copy.deepcopy(turn.assistant)
    specialist.id = uuid4()
    specialist.name = "IT"
    plan = specialist_plan(turn, monkeypatch, specialist)
    monkeypatch.setattr(
        "eneo.assistants.assistant_service.ExecutionBudget",
        lambda: ExecutionBudget(
            ExecutionLimits(duration_seconds=0.3, reserved_seconds=0)
        ),
    )

    def streamed(*parts: str):
        async def chunks():
            for index, part in enumerate(parts):
                await asyncio.sleep(0.01)
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=part, reasoning_content=None, tool_calls=None
                            ),
                            finish_reason="stop" if index == len(parts) - 1 else None,
                        )
                    ],
                    usage=litellm.Usage(
                        prompt_tokens=20, completion_tokens=7, total_tokens=27
                    ),
                )

        return chunks()

    async def answer_in_parts(**kwargs: object):
        return streamed("One ", "two ", "three.")

    turn.provider.side_effect = answer_in_parts

    async with turn.service.repo.session.begin():
        reply = await turn.service.ask(
            question="Count",
            assistant_id=turn.assistant.id,
            delegation_plan=plan,
            stream=True,
            version=2,
        )
    texts: list[str] = []
    async for event in reply.answer:
        assert event.response_type != ResponseType.ERROR, event.error_reason
        if event.text:
            texts.append(event.text)
        # Slow writer: three waits exceed the whole 0.3 s turn deadline.
        await asyncio.sleep(0.2)
    assert "".join(texts) == "One two three."
    turn.history.complete_question_with_answer.assert_awaited_once()

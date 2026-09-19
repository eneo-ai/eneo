"""The step scope a session's next turn edits, projected for the client.

The scope the user accepted lives on the conversation (the persisted edit
context of the newest accepted user turn); the client restores its chip and
its transport from this projection after a reload instead of keeping a second
copy. Labels are resolved against the flow or the current plan at read time,
and anything that no longer resolves projects nothing rather than raising.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_for_user_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderSession,
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_flow_review import AIBuilderRunFailureContext
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    AIBuilderSavedFlowStepEditContext,
)
from eneo.flows.ai_builder.ai_builder_service import AIBuilderService
from eneo.flows.domain.flow import FlowStep
from eneo.main.exceptions import NotFoundException


def _service(user) -> AIBuilderService:
    return AIBuilderService(
        user=user,
        repo=AsyncMock(),
        flow_service=AsyncMock(),
        completion_service=AsyncMock(),
        space_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        flow_review_service=SimpleNamespace(),
    )


def _flow(flow_id: UUID, *names: str):
    return SimpleNamespace(
        id=flow_id,
        steps=[
            FlowStep(
                id=uuid4(),
                flow_id=flow_id,
                tenant_id=uuid4(),
                assistant_id=uuid4(),
                step_order=order,
                user_description=name,
                input_source="flow_input" if order == 1 else "previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
            for order, name in enumerate(names, 1)
        ],
    )


def _session(user, *messages: ConversationMessage, flow_id: UUID, latest_plan_id=None):
    return BuilderSession(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        target_kind=TargetKind.EDIT,
        flow_id=flow_id,
        latest_plan_id=latest_plan_id,
        conversation=list(messages),
    )


def _user(content: str, **metadata) -> ConversationMessage:
    return ConversationMessage(
        role="user",
        content=content,
        metadata=metadata_for_user_message(**metadata) if metadata else None,
    )


def _plan(
    plan_id: UUID,
    *steps: tuple[str, str | None, str],
    scoped: tuple[str | None, str | None] | None = None,
):
    """(plan_step_ref, existing_step_ref, name) per step; ``scoped`` is the
    (plan ref, existing ref) target the proposal was produced for."""
    spec = SimpleNamespace(
        steps=[
            SimpleNamespace(
                plan_step_ref=plan_ref, existing_step_ref=existing_ref, name=name
            )
            for plan_ref, existing_ref, name in steps
        ]
    )
    edit = (
        SimpleNamespace(
            scoped_target_plan_step_ref=scoped[0],
            scoped_target_existing_step_ref=scoped[1],
        )
        if scoped
        else None
    )
    return SimpleNamespace(
        id=plan_id,
        spec=spec,
        proposal=SimpleNamespace(content=SimpleNamespace(edit=edit)),
    )


def _projected_plan_context(
    scope, plan_id: UUID, plan_ref: str | None, existing_ref: str | None
):
    assert scope.context.kind == "proposed_plan"
    assert scope.context.scope == "step"
    assert scope.context.plan_id == plan_id
    assert scope.context.target_plan_step_ref == plan_ref
    assert scope.context.target_existing_step_ref == existing_ref


@pytest.mark.asyncio
async def test_an_accepted_saved_step_turn_projects_that_step_by_its_current_name(user):
    service = _service(user)
    flow = _flow(uuid4(), "Transkribera", "Sammanfatta", "Skapa PDF")
    service.flow_service.get_flow.return_value = flow
    target = flow.steps[1]
    context = AIBuilderSavedFlowStepEditContext(flow_step_id=target.id)
    session = _session(
        user,
        _user("Gör instruktionen tydligare", edit_context=context),
        flow_id=flow.id,
    )

    scope = await service.describe_session_edit_scope(session)

    assert scope is not None
    assert scope.context == context
    assert scope.step_number == 2
    assert scope.step_name == "Sammanfatta"
    assert scope.preserves_output_contract is False
    service.flow_service.get_flow.assert_awaited_once_with(flow.id)


@pytest.mark.asyncio
async def test_the_newest_accepted_turn_owns_the_scope(user):
    """A later unscoped turn clears it; a later scoped turn moves it."""
    service = _service(user)
    flow = _flow(uuid4(), "Ett", "Två", "Tre")
    service.flow_service.get_flow.return_value = flow
    scoped = _user(
        "ändra",
        edit_context=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id),
    )
    unscoped = _user("och beskriv hela flödet")
    assert (
        await service.describe_session_edit_scope(
            _session(user, scoped, unscoped, flow_id=flow.id)
        )
        is None
    )
    moved = _user(
        "byt modell på steg 3",
        edit_context=AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[2].id),
    )
    scope = await service.describe_session_edit_scope(
        _session(user, scoped, unscoped, moved, flow_id=flow.id)
    )
    assert scope is not None and (scope.step_number, scope.step_name) == (3, "Tre")


@pytest.mark.asyncio
async def test_a_saved_step_turn_that_produced_a_plan_projects_its_target_on_that_plan(
    user,
):
    """The persisted context is the turn's input; a saved-step context is
    refused once a plan exists, so the projection is the proposal's own
    scoped target as a plan context the next turn may send."""
    service = _service(user)
    flow_id, plan_id = uuid4(), uuid4()
    service.repo.get_plan.return_value = _plan(
        plan_id,
        ("step_1", "existing_step_1", "Först"),
        ("step_2", "existing_step_2", "Sammanfatta"),
        scoped=("step_2", "existing_step_2"),
    )
    saved = _user(
        "tydligare",
        edit_context=AIBuilderSavedFlowStepEditContext(flow_step_id=uuid4()),
    )
    scope = await service.describe_session_edit_scope(
        _session(user, saved, flow_id=flow_id, latest_plan_id=plan_id)
    )
    assert scope is not None
    _projected_plan_context(scope, plan_id, "step_2", "existing_step_2")
    assert (scope.step_number, scope.step_name) == (2, "Sammanfatta")
    service.flow_service.get_flow.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_plan_step_turn_that_produced_the_next_plan_follows_its_target(user):
    """Editing step 14 of P1 produced P2: the scope is step 14 on P2."""
    service = _service(user)
    flow_id, p1, p2 = uuid4(), uuid4(), uuid4()
    service.repo.get_plan.return_value = _plan(
        p2,
        ("step_1", "existing_step_1", "Först"),
        ("step_14", "existing_step_14", "Skriv brukarversionen"),
        scoped=("step_14", "existing_step_14"),
    )
    against_p1 = AIBuilderPlanEditContext(
        scope="step", plan_id=p1, target_plan_step_ref="step_14"
    )
    scope = await service.describe_session_edit_scope(
        _session(
            user,
            _user("kortare", edit_context=against_p1),
            flow_id=flow_id,
            latest_plan_id=p2,
        )
    )
    assert scope is not None
    _projected_plan_context(scope, p2, "step_14", "existing_step_14")
    assert (scope.step_number, scope.step_name) == (2, "Skriv brukarversionen")
    service.repo.get_plan.assert_awaited_once_with(plan_id=p2, tenant_id=user.tenant_id)


@pytest.mark.asyncio
async def test_a_declined_turn_keeps_its_newer_target_against_the_unchanged_plan(user):
    """P1 concerned step 1; the user then asked about step 2 and the Builder
    declined, so P1 is still current: the newer accepted target wins."""
    service = _service(user)
    flow_id, p1 = uuid4(), uuid4()
    service.repo.get_plan.return_value = _plan(
        p1,
        ("step_1", "existing_step_1", "Först"),
        ("step_2", "existing_step_2", "Andra"),
        scoped=("step_1", "existing_step_1"),
    )
    newer = AIBuilderPlanEditContext(
        scope="step", plan_id=p1, target_plan_step_ref="step_2"
    )
    scope = await service.describe_session_edit_scope(
        _session(
            user,
            _user("byt modell", edit_context=newer),
            flow_id=flow_id,
            latest_plan_id=p1,
        )
    )
    assert scope is not None
    _projected_plan_context(scope, p1, "step_2", "existing_step_2")
    assert (scope.step_number, scope.step_name) == (2, "Andra")

    # A whole-plan scope names no step.
    whole = AIBuilderPlanEditContext(scope="whole_plan", plan_id=p1)
    assert (
        await service.describe_session_edit_scope(
            _session(
                user, _user("x", edit_context=whole), flow_id=flow_id, latest_plan_id=p1
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_a_failure_repair_projects_its_step_with_the_contract_restriction(user):
    """The repair's step scope is an ordinary edit context on the turn; the
    inherited restriction rides beside it, on every later turn too."""
    service = _service(user)
    flow = _flow(uuid4(), "Läs", "Strukturera")
    service.flow_service.get_flow.return_value = flow
    reference = AIBuilderRunFailureContext(
        flow_version=1, definition_checksum="sum", run_id=uuid4(), step_order=2
    )
    context = AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[1].id)
    handoff = _user(
        "Åtgärda felet i steg 2",
        edit_context=context,
        review_context=reference,
        review_evidence_level=2,
        acts_on_review=True,
    )
    later = _user("gör den tydligare", edit_context=context, acts_on_review=True)

    for conversation in ([handoff], [handoff, later]):
        scope = await service.describe_session_edit_scope(
            _session(user, *conversation, flow_id=flow.id)
        )
        assert scope is not None
        assert (scope.step_number, scope.step_name) == (2, "Strukturera")
        assert scope.preserves_output_contract is True


@pytest.mark.asyncio
@pytest.mark.parametrize("gone", ["step", "flow", "plan", "unscoped_plan", "metadata"])
async def test_a_scope_that_no_longer_resolves_projects_nothing(user, gone):
    service = _service(user)
    flow = _flow(uuid4(), "Ett")
    plan_id = uuid4()
    if gone == "step":
        service.flow_service.get_flow.return_value = flow
        context = AIBuilderSavedFlowStepEditContext(flow_step_id=uuid4())
        session = _session(user, _user("x", edit_context=context), flow_id=flow.id)
    elif gone == "flow":
        service.flow_service.get_flow.side_effect = NotFoundException("gone")
        context = AIBuilderSavedFlowStepEditContext(flow_step_id=flow.steps[0].id)
        session = _session(user, _user("x", edit_context=context), flow_id=flow.id)
    elif gone == "plan":
        service.repo.get_plan.side_effect = NotFoundException("gone")
        context = AIBuilderPlanEditContext(
            scope="step", plan_id=plan_id, target_plan_step_ref="step_9"
        )
        session = _session(
            user,
            _user("x", edit_context=context),
            flow_id=flow.id,
            latest_plan_id=plan_id,
        )
    else:
        session = _session(
            user,
            ConversationMessage(
                role="user", content="x", metadata={"edit_context": {"kind": "future"}}
            ),
            flow_id=flow.id,
        )
    assert await service.describe_session_edit_scope(session) is None

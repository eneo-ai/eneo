from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    FlowBuilderEditApproval,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    LintSeverity,
    LintWarning,
)
from eneo.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    FlowEditDiff,
    StepChange,
)
from eneo.flows.ai_builder.ai_builder_plan_store import (
    _persist_active_send_plan_proposal,
    append_plan_messages,
    build_flow_builder_proposal,
    build_lint_warnings,
    store_plan_and_update_conversation,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationResult,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


def test_build_lint_warnings_hides_internal_info_level_quality_lints() -> None:
    validation = SpecValidationResult()
    validation.warnings.extend(
        [
            LintWarning(
                step_ref="step_d",
                code="json_output_text_interpolation",
                message=(
                    "Underlag interpolates output.text from a JSON-producing step. "
                    "Prefer output.structured.<field> when only specific fields are needed."
                ),
                severity=LintSeverity.INFO,
            ),
            LintWarning(
                step_ref="step_e",
                code="all_previous_overuse",
                message="Too many steps use all_previous_steps.",
                severity=LintSeverity.WARNING,
            ),
        ]
    )

    visible_warnings = build_lint_warnings(validation)

    assert visible_warnings == [
        LintWarning(
            step_ref="step_e",
            code="all_previous_overuse",
            message="Too many steps use all_previous_steps.",
            severity=LintSeverity.WARNING,
        )
    ]


def test_build_flow_builder_proposal_promotes_full_compiled_candidate() -> None:
    validation = SpecValidationResult()
    validation.add_warning(
        step_ref="step_a",
        code="internal_quality_note",
        message="Internal note.",
        severity=LintSeverity.INFO,
    )
    validation.add_warning(
        step_ref="step_a",
        code="visible_warning",
        message="Visible warning.",
    )
    binding = _make_binding()
    edit_diff = FlowEditDiff(
        step_changes=[
            StepChange(kind="unchanged", step_name="Step A"),
            StepChange(
                kind="removed",
                step_name="Old step",
                step_ref="existing_step_2",
                details="Removed from the approved edit.",
            ),
        ],
        net_steps_removed=1,
        flow_property_changes={"flow_description": ("old", "new")},
    )
    edit = FlowBuilderEditApproval(
        diff=edit_diff,
        base_flow_revision=7,
        removed_existing_step_refs=frozenset({"existing_step_2"}),
        warnings=["Review before applying."],
        advisories=[
            EditAdvisory(
                code="flow_description_update_required",
                message="Review the flow description.",
                severity="warning",
            )
        ],
        risk_flags=["type_downgrade"],
        confidence="needs_review",
    )
    compiled = CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=_make_turn_spec(),
            assumptions=["Assumption"],
            plan_rationale="Use one step.",
            edit=edit,
        ),
        reasoning="Internal reasoning.",
        validation=validation,
        resource_bindings=(binding,),
    )

    proposal = build_flow_builder_proposal(compiled)

    assert proposal.spec == compiled.content.spec
    assert proposal.content.assumptions == ["Assumption"]
    assert proposal.content.plan_rationale == "Use one step."
    assert proposal.reasoning == "Internal reasoning."
    assert proposal.resource_bindings == (binding,)
    assert not hasattr(proposal, "edit_result")
    assert proposal.content.description_override_manual is False
    assert proposal.content.risk_acknowledgments == []
    assert proposal.content.edit is not None
    assert proposal.content.edit.base_flow_revision == 7
    assert proposal.content.edit.removed_existing_step_refs == frozenset(
        {"existing_step_2"}
    )
    assert proposal.content.edit.diff == edit_diff
    assert proposal.content.edit.warnings == ["Review before applying."]
    assert proposal.content.edit.advisories[0].code == (
        "flow_description_update_required"
    )
    assert proposal.content.edit.risk_flags == ["type_downgrade"]
    assert proposal.content.edit.confidence == "needs_review"
    assert proposal.content.lint_warnings == [
        LintWarning(
            step_ref="step_a",
            code="visible_warning",
            message="Visible warning.",
            severity=LintSeverity.WARNING,
        )
    ]


def test_build_flow_builder_proposal_rejects_prepopulated_lint_warnings() -> None:
    compiled = CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=_make_turn_spec(),
            lint_warnings=[
                LintWarning(
                    step_ref="step_a",
                    code="producer_owned_lint",
                    message="Producers must not pre-populate lint warnings.",
                )
            ],
        ),
        validation=SpecValidationResult(),
    )

    with pytest.raises(ValueError, match="derived from compiled.validation"):
        build_flow_builder_proposal(compiled)


def test_append_plan_messages_uses_single_active_submission_tool_name() -> None:
    conversation: list[ConversationMessage] = []
    spec = FlowDraftSpecCore(
        flow_name="Kommunärende",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extrahera",
                assistant_spec=AssistantSpec(instructions="Extrahera."),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )

    append_plan_messages(
        conversation=conversation,
        assistant_content="Här är planen.",
        tool_call_id="call_create",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={"plan_rationale": "Struktur först."},
        spec=spec,
        assumptions=["Antagande"],
    )

    assert conversation[0].tool_calls is not None
    assert conversation[0].tool_calls[0]["name"] == PROPOSE_FLOW_TOOL_NAME


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


def _make_repo_mock() -> AsyncMock:
    repo = AsyncMock()
    repo.savepoint = _noop_savepoint
    repo.append_session_messages = AsyncMock(return_value=[])
    repo.create_plan = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    repo.load_planning_state = AsyncMock(return_value=None)
    return repo


def _make_turn_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Unit plan",
        flow_description="Unit plan description",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=None,
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do work."),
                mcp_policy=MCPPolicy.INHERIT,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


def _make_binding() -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=uuid4(),
    )


def _compiled_proposal(
    *,
    spec: FlowDraftSpecCore | None = None,
    validation: SpecValidationResult | None = None,
    resource_bindings: tuple[LocalResourceBinding, ...] = tuple(),
) -> CompiledProposal:
    return CompiledProposal(
        content=FlowBuilderProposalContent(spec=spec or _make_turn_spec()),
        validation=validation or SpecValidationResult(),
        resource_bindings=resource_bindings,
    )


def _make_turn(
    *,
    tenant_id=None,
    session_id=None,
    base_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_version,
    )


@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_saves_planning_state_inside_savepoint() -> (
    None
):
    repo = _make_repo_mock()
    spec = _make_turn_spec()

    await store_plan_and_update_conversation(
        repo=repo,
        turn=_make_turn(base_version=7),
        conversation=[],
        new_messages_start=0,
        assistant_content="plan ready",
        tool_call_id="call-unit-1",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={},
        compiled=_compiled_proposal(spec=spec),
    )

    repo.save_planning_state.assert_awaited_once()
    assert repo.save_planning_state.await_args is not None
    saved_state = repo.save_planning_state.await_args.kwargs["state"]
    assert isinstance(saved_state, PlanningState)
    assert "phase" not in saved_state.model_dump(mode="json")
    assert repo.save_planning_state.await_args.kwargs["base_version"] == 7
    repo.update_session_latest_plan.assert_awaited_once()
    assert repo.update_session_latest_plan.await_args.kwargs["plan_id"] == (
        repo.create_plan.return_value.id
    )


@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_passes_resource_bindings_to_repo() -> (
    None
):
    repo = _make_repo_mock()
    binding = _make_binding()

    await store_plan_and_update_conversation(
        repo=repo,
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        assistant_content="plan ready",
        tool_call_id="call-unit-1",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={},
        compiled=_compiled_proposal(resource_bindings=(binding,)),
    )

    assert repo.create_plan.await_args is not None
    assert repo.create_plan.await_args.kwargs["proposal"].resource_bindings == (
        binding,
    )


@pytest.mark.asyncio
async def test_active_send_plan_proposal_uses_only_bindings_for_current_plan() -> None:
    repo = _make_repo_mock()
    tenant_id = uuid4()
    session_id = uuid4()
    first_binding = _make_binding()
    second_binding = _make_binding()
    spec = _make_turn_spec()

    await _persist_active_send_plan_proposal(
        repo=repo,
        turn=_make_turn(tenant_id=tenant_id, session_id=session_id),
        proposal=FlowBuilderProposal(
            content=FlowBuilderProposalContent(spec=spec),
            resource_bindings=(first_binding,),
        ),
    )
    await _persist_active_send_plan_proposal(
        repo=repo,
        turn=_make_turn(tenant_id=tenant_id, session_id=session_id),
        proposal=FlowBuilderProposal(
            content=FlowBuilderProposalContent(spec=spec),
            resource_bindings=(second_binding,),
        ),
    )

    first_call, second_call = repo.create_plan.await_args_list
    assert first_call.kwargs["proposal"].resource_bindings == (first_binding,)
    assert second_call.kwargs["proposal"].resource_bindings == (second_binding,)
    assert first_binding not in second_call.kwargs["proposal"].resource_bindings
    assert repo.supersede_existing_plans.await_count == 2

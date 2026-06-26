"""Storage-boundary tests for FlowBuilderProposal / builder_plans rows."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.database.tables.flow_tables import BuilderPlans
from intric.flows.ai_builder.ai_builder_domain_models import (
    FlowBuilderEditApproval,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    LintSeverity,
    LintWarning,
    PlanStatus,
)
from intric.flows.ai_builder.ai_builder_edit_preview_models import (
    FlowEditDiff,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_repo import (
    _plan_from_row,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


def _make_spec(flow_name: str = "Spec A") -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name=flow_name,
        flow_description="test",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do X."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            )
        ],
    )


def _row(
    *,
    proposal: FlowBuilderProposal,
    spec_hash: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        status=PlanStatus.PROPOSED.value,
        proposal_json=proposal.storage_json(),
        spec_hash=spec_hash or proposal.spec_hash,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _binding() -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=uuid4(),
    )


def _edit_approval() -> FlowBuilderEditApproval:
    return FlowBuilderEditApproval(
        base_flow_revision=1,
        removed_existing_step_refs=frozenset({"existing_step_2"}),
        diff=FlowEditDiff(
            step_changes=[
                StepChange(kind="unchanged", step_name="Step A"),
                StepChange(
                    kind="removed",
                    step_name="Old step",
                    step_ref="existing_step_2",
                ),
            ],
            net_steps_removed=1,
        ),
    )


def test_plan_response_does_not_expose_resource_bindings() -> None:
    assert "resource_bindings" not in FlowBuilderProposalContent.model_fields
    assert "resource_bindings_json" not in FlowBuilderProposalContent.model_fields
    assert "reasoning" not in FlowBuilderProposalContent.model_fields
    assert "edit_result" not in FlowBuilderProposalContent.model_fields


def test_builder_plans_table_uses_single_proposal_json_storage() -> None:
    column_names = set(BuilderPlans.__table__.columns.keys())

    assert {"proposal_json", "spec_hash"}.issubset(column_names)
    assert column_names.isdisjoint(
        {
            "spec_json",
            "envelope_json",
            "resource_bindings_json",
            "edit_result_json",
        }
    )


def test_plan_from_row_rehydrates_spec_from_proposal_json() -> None:
    spec = _make_spec("Canonical from proposal_json")
    proposal = FlowBuilderProposal(
        content=FlowBuilderProposalContent(
            spec=spec,
            assumptions=["user wants text"],
        )
    )
    plan = _plan_from_row(_row(proposal=proposal))
    assert plan.proposal.content.spec.flow_name == "Canonical from proposal_json"
    assert plan.spec.flow_name == "Canonical from proposal_json"
    assert plan.spec.spec_hash() == plan.proposal.content.spec.spec_hash()


def test_plan_from_row_rehydrates_complete_proposal_from_proposal_json() -> None:
    spec = _make_spec("Proposal roundtrip")
    binding = _binding()
    edit = _edit_approval()
    warning = LintWarning(
        step_ref="step_a",
        code="needs_review",
        message="Review the generated step.",
        severity=LintSeverity.WARNING,
    )
    expected = FlowBuilderProposal(
        content=FlowBuilderProposalContent(
            spec=spec,
            assumptions=["The input is plain text."],
            lint_warnings=[warning],
            risk_acknowledgments=["Generated summaries need review."],
            plan_rationale="One-step summary flow.",
            description_override_manual=True,
            edit=edit,
        ),
        reasoning="Internal planning note.",
        resource_bindings=(binding,),
    )

    plan = _plan_from_row(
        _row(
            proposal=expected,
        )
    )

    assert plan.proposal == expected
    assert plan.spec == expected.spec
    assert plan.spec_hash == expected.spec_hash
    assert plan.proposal.content == expected.content
    assert plan.resource_bindings == (binding,)
    assert plan.proposal.content.edit == edit


def test_plan_from_row_rehydrates_resource_bindings() -> None:
    spec = _make_spec("Binding roundtrip")
    binding = _binding()
    plan = _plan_from_row(
        _row(
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(spec=spec),
                resource_bindings=(binding,),
            ),
        )
    )

    assert plan.resource_bindings == (binding,)
    assert plan.resource_bindings[0].slot_ref.label == "Fast model"


def test_plan_from_row_rehydrates_populated_edit_approval() -> None:
    spec = _make_spec("Edit approval roundtrip")
    edit = _edit_approval()

    plan = _plan_from_row(
        _row(
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(
                    spec=spec,
                    edit=edit,
                ),
            ),
        )
    )

    assert plan.proposal.content.edit == edit


def test_plan_from_row_rejects_legacy_content_edit_result() -> None:
    proposal = FlowBuilderProposal(
        content=FlowBuilderProposalContent(spec=_make_spec())
    )
    row = _row(proposal=proposal)
    row.proposal_json["content"]["edit_result"] = {"description_override_manual": True}

    with pytest.raises(ValidationError, match="edit_result"):
        _plan_from_row(row)


def test_plan_from_row_rejects_unknown_proposal_json_fields() -> None:
    proposal = FlowBuilderProposal(
        content=FlowBuilderProposalContent(spec=_make_spec())
    )
    row = _row(proposal=proposal)
    row.proposal_json["legacy_extra"] = True

    with pytest.raises(ValidationError, match="legacy_extra"):
        _plan_from_row(row)


def test_plan_from_row_rejects_mismatched_stored_spec_hash() -> None:
    proposal = FlowBuilderProposal(
        content=FlowBuilderProposalContent(spec=_make_spec())
    )

    with pytest.raises(
        ValueError,
        match="Persisted builder plan spec_hash does not match proposal_json",
    ):
        _plan_from_row(_row(proposal=proposal, spec_hash="stale"))

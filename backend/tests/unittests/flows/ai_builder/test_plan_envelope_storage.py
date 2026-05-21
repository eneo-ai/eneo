"""Storage-boundary tests for PlannerPlanEnvelope / builder_plans rows.

The envelope carries a `spec` at the API layer, but the stored JSONB shape is
metadata-only — spec lives in `spec_json`, not `envelope_json`. These tests
pin the slim-on-write / rehydrate-on-read contract that prevents silent drift
between the two columns.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from intric.flows.ai_builder.ai_builder_api_models import PlanResponse
from intric.flows.ai_builder.ai_builder_domain_models import (
    PlannerPlanEnvelope,
    PlanStatus,
)
from intric.flows.ai_builder.ai_builder_edit_models import (
    BuilderPlanEditResult,
    CompiledEditResult,
    FlowEditDiff,
    FlowEditDraft,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_repo import (
    _envelope_json_for_storage,
    _plan_from_row,
    _resource_bindings_json_for_storage,
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
    spec: FlowDraftSpecCore,
    envelope_json: dict[str, object],
    resource_bindings_json: list[dict[str, object]] | None = None,
    edit_result_json: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        status=PlanStatus.PROPOSED.value,
        spec_json=spec.model_dump(mode="json"),
        spec_hash=spec.spec_hash(),
        envelope_json=envelope_json,
        resource_bindings_json=resource_bindings_json or [],
        edit_result_json=edit_result_json,
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


def _compiled_edit_result(spec: FlowDraftSpecCore) -> CompiledEditResult:
    return CompiledEditResult(
        compiled_spec=spec,
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Step A")]
        ),
        original_draft=FlowEditDraft(operations=[]),
        base_flow_revision=1,
    )


def test_envelope_json_for_storage_drops_spec() -> None:
    spec = _make_spec()
    envelope = PlannerPlanEnvelope(spec=spec, assumptions=["A1"], plan_rationale="why")
    stored = _envelope_json_for_storage(envelope)
    assert "spec" not in stored
    assert stored["assumptions"] == ["A1"]
    assert stored["plan_rationale"] == "why"
    assert "resource_bindings" not in stored
    assert "resource_bindings_json" not in stored


def test_plan_response_does_not_expose_resource_bindings() -> None:
    assert "resource_bindings" not in PlanResponse.model_fields
    assert "resource_bindings_json" not in PlanResponse.model_fields


def test_plan_from_row_rehydrates_spec_from_spec_json() -> None:
    spec = _make_spec("Canonical from spec_json")
    envelope_json = {
        "assumptions": ["user wants text"],
        "lint_warnings": [],
        "risk_acknowledgments": [],
        "reasoning": None,
        "plan_rationale": None,
    }
    plan = _plan_from_row(_row(spec=spec, envelope_json=envelope_json))
    assert plan.envelope.spec.flow_name == "Canonical from spec_json"
    assert plan.spec.flow_name == "Canonical from spec_json"
    assert plan.spec.spec_hash() == plan.envelope.spec.spec_hash()


def test_plan_from_row_rehydrates_resource_bindings() -> None:
    spec = _make_spec("Binding roundtrip")
    binding = _binding()
    plan = _plan_from_row(
        _row(
            spec=spec,
            envelope_json={
                "assumptions": [],
                "lint_warnings": [],
                "risk_acknowledgments": [],
                "reasoning": None,
                "plan_rationale": None,
            },
            resource_bindings_json=_resource_bindings_json_for_storage((binding,)),
        )
    )

    assert plan.resource_bindings == (binding,)
    assert plan.resource_bindings[0].slot_ref.label == "Fast model"


def test_plan_from_row_rehydrates_populated_edit_result() -> None:
    spec = _make_spec("Edit result roundtrip")
    compiled = _compiled_edit_result(spec)
    stored_edit_result = BuilderPlanEditResult(compiled_edit=compiled).model_dump(
        mode="json",
        exclude_none=True,
    )

    plan = _plan_from_row(
        _row(
            spec=spec,
            envelope_json={
                "assumptions": [],
                "lint_warnings": [],
                "risk_acknowledgments": [],
                "reasoning": None,
                "plan_rationale": None,
            },
            edit_result_json=stored_edit_result,
        )
    )

    assert plan.edit_result == BuilderPlanEditResult(compiled_edit=compiled)


def test_plan_from_row_ignores_legacy_envelope_spec_copy() -> None:
    """Legacy rows may still carry a stale `spec` inside envelope_json.

    `spec_json` is the single source of truth — the envelope.spec that the
    consumer sees must match spec_json, never the stale duplicate.
    """
    canonical = _make_spec("Canonical")
    stale = _make_spec("Stale duplicate")
    envelope_json = {
        "spec": stale.model_dump(mode="json"),
        "assumptions": [],
        "lint_warnings": [],
        "risk_acknowledgments": [],
        "reasoning": None,
        "plan_rationale": None,
    }
    plan = _plan_from_row(_row(spec=canonical, envelope_json=envelope_json))
    assert plan.envelope.spec.flow_name == "Canonical"
    assert plan.spec.flow_name == "Canonical"

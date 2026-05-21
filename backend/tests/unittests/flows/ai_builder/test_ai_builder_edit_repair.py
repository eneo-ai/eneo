"""Tests for AI Builder edit constrained repair logic."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    FlowSemanticSignature,
    _description_hash,
)
from intric.flows.ai_builder.ai_builder_edit_models import EditAdvisory
from intric.flows.ai_builder.ai_builder_edit_repair import (
    should_attempt_description_repair,
    validate_repair_invariance,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)


def _spec(*, description: str = "Test flow", **kwargs) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Test",
        flow_description=description,
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Step",
                assistant_spec=AssistantSpec(instructions="Do."),
                input_source=InputSource.FLOW_INPUT,
                input_type=kwargs.get("input_type", InputType.TEXT),
                output_type=kwargs.get("output_type", OutputType.TEXT),
            )
        ],
    )


class TestShouldAttemptDescriptionRepair:
    def test_returns_true_when_advisory_present_and_builder_managed_and_hash_matches(
        self,
    ) -> None:
        current_desc = "Old description"
        provenance = DescriptionProvenance(
            mode="builder_managed",
            semantic_signature=FlowSemanticSignature(
                entry_input_type="audio",
                entry_input_source="flow_input",
                terminal_output_type="text",
                terminal_output_mode="transcribe_only",
            ),
            last_generated_hash=_description_hash(current_desc),
        )
        advisories = [
            EditAdvisory(
                code="flow_description_update_required",
                message="...",
                severity="warning",
                field="flow_description",
            )
        ]
        assert (
            should_attempt_description_repair(
                advisories=advisories,
                current_description=current_desc,
                current_provenance=provenance,
            )
            is True
        )

    def test_returns_false_when_no_advisory(self) -> None:
        provenance = DescriptionProvenance(mode="builder_managed")
        assert (
            should_attempt_description_repair(
                advisories=[],
                current_description="Any",
                current_provenance=provenance,
            )
            is False
        )

    def test_returns_false_when_manual_provenance(self) -> None:
        provenance = DescriptionProvenance(mode="manual")
        advisories = [
            EditAdvisory(
                code="flow_description_update_required",
                message="...",
                severity="warning",
                field="flow_description",
            )
        ]
        assert (
            should_attempt_description_repair(
                advisories=advisories,
                current_description="Any",
                current_provenance=provenance,
            )
            is False
        )

    def test_returns_false_when_hash_mismatch(self) -> None:
        """Hash mismatch means description was manually edited — don't repair."""
        provenance = DescriptionProvenance(
            mode="builder_managed",
            last_generated_hash=_description_hash("Original"),
        )
        advisories = [
            EditAdvisory(
                code="flow_description_update_required",
                message="...",
                severity="warning",
                field="flow_description",
            )
        ]
        assert (
            should_attempt_description_repair(
                advisories=advisories,
                current_description="User edited this manually",
                current_provenance=provenance,
            )
            is False
        )

    def test_returns_false_when_no_provenance(self) -> None:
        advisories = [
            EditAdvisory(
                code="flow_description_update_required",
                message="...",
                severity="warning",
                field="flow_description",
            )
        ]
        assert (
            should_attempt_description_repair(
                advisories=advisories,
                current_description="Any",
                current_provenance=None,
            )
            is False
        )


class TestValidateRepairInvariance:
    def test_accepts_when_only_description_changed(self) -> None:
        original = _spec(description="Old")
        repaired = _spec(description="New")
        assert validate_repair_invariance(original, repaired) is True

    def test_rejects_when_steps_changed(self) -> None:
        original = _spec(description="Old")
        repaired = FlowDraftSpecCore(
            flow_name="Test",
            flow_description="New",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Different Step",
                    assistant_spec=AssistantSpec(instructions="Changed."),
                    input_source=InputSource.FLOW_INPUT,
                ),
            ],
        )
        assert validate_repair_invariance(original, repaired) is False

    def test_rejects_when_flow_name_changed(self) -> None:
        original = _spec(description="Same")
        repaired = original.model_copy(update={"flow_name": "Different Name"})
        assert validate_repair_invariance(original, repaired) is False

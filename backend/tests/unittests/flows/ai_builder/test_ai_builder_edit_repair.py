"""Tests for AI Builder edit constrained repair logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from intric.flows.ai_builder.ai_builder_edit_models import (
    BuilderPlanEditResult,
    CompiledEditResult,
    EditAdvisory,
    FlowEditDiff,
    FlowEditDraft,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_edit_repair import (
    attempt_description_repair,
    repair_compiled_edit_description_if_needed,
    should_attempt_description_repair,
    validate_repair_invariance,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.application.flow_authoring_description_semantics import (
    DescriptionProvenance,
    FlowSemanticSignature,
    description_hash,
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


def _compiled_edit_proposal(
    *,
    spec: FlowDraftSpecCore,
    advisories: list[EditAdvisory],
) -> CompiledProposal:
    compiled_edit = CompiledEditResult(
        compiled_spec=spec,
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Step")]
        ),
        original_draft=FlowEditDraft(operations=[]),
        base_flow_revision=1,
        advisories=advisories,
    )
    return CompiledProposal(
        spec=spec,
        assumptions=(),
        plan_rationale="Update the flow.",
        reasoning=None,
        validation=SpecValidationResult(),
        edit_result=BuilderPlanEditResult(compiled_edit=compiled_edit),
    )


def _description_advisory() -> EditAdvisory:
    return EditAdvisory(
        code="flow_description_update_required",
        message="Refresh the flow description.",
        severity="warning",
        field="flow_description",
    )


def _builder_description_metadata(current_description: str) -> dict[str, object]:
    return {
        "ai_builder": {
            "description": DescriptionProvenance(
                mode="builder_managed",
                last_generated_hash=description_hash(current_description),
            ).model_dump(mode="json")
        }
    }


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
            last_generated_hash=description_hash(current_desc),
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
            last_generated_hash=description_hash("Original"),
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

    def test_accepts_when_only_description_changed_with_writer_refs(self) -> None:
        original = FlowDraftSpecCore(
            flow_name="Test",
            flow_description="Old",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Step",
                    assistant_spec=AssistantSpec(instructions="Do."),
                    input_source=InputSource.FLOW_INPUT,
                )
            ],
            document_body_writer_step_refs=("step_a",),
        )
        repaired = original.model_copy(update={"flow_description": "New"})

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


@pytest.mark.asyncio
async def test_attempt_description_repair_uses_completion_boundary_only_for_description() -> (
    None
):
    completion = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="New generated description")
                )
            ]
        )
    )
    original = _spec(description="Old generated description")

    repaired = await attempt_description_repair(
        call_proposal_completion=completion,
        compiled_spec=original,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"timeout": 30},
        max_output_tokens=128,
    )

    assert repaired is not None
    assert repaired.flow_description == "New generated description"
    assert repaired.flow_name == original.flow_name
    assert repaired.steps == original.steps
    completion.assert_awaited_once()
    assert completion.await_args.args[0].tool_schemas == []


@pytest.mark.asyncio
async def test_repair_compiled_edit_description_repairs_builder_managed_stale_description() -> (
    None
):
    original = _spec(description="Old generated description")
    repaired = original.model_copy(
        update={"flow_description": "New generated description"}
    )
    compiled = _compiled_edit_proposal(
        spec=original,
        advisories=[_description_advisory()],
    )
    flow = SimpleNamespace(
        description="Old generated description",
        metadata_json=_builder_description_metadata("Old generated description"),
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_edit_repair.attempt_description_repair",
        new=AsyncMock(return_value=repaired),
    ) as repair:
        result = await repair_compiled_edit_description_if_needed(
            compiled=compiled,
            flow=flow,
            call_proposal_completion=AsyncMock(),
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={"timeout": 30},
            max_output_tokens=4096,
        )

    assert result is not compiled
    assert result.spec.flow_description == "New generated description"
    assert result.edit_result is not None
    assert result.edit_result.compiled_edit is not None
    assert result.edit_result.compiled_edit.compiled_spec is result.spec
    assert result.edit_result.compiled_edit.advisories == []
    repair.assert_awaited_once()
    assert repair.await_args.kwargs["max_output_tokens"] == 256


@pytest.mark.asyncio
async def test_repair_compiled_edit_description_leaves_unowned_description_unchanged() -> (
    None
):
    compiled = _compiled_edit_proposal(
        spec=_spec(description="Manual description"),
        advisories=[_description_advisory()],
    )
    flow = SimpleNamespace(
        description="Manual description",
        metadata_json=None,
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_edit_repair.attempt_description_repair",
        new=AsyncMock(return_value=_spec(description="Should not be used")),
    ) as repair:
        result = await repair_compiled_edit_description_if_needed(
            compiled=compiled,
            flow=flow,
            call_proposal_completion=AsyncMock(),
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            max_output_tokens=4096,
        )

    assert result is compiled
    repair.assert_not_awaited()


@pytest.mark.asyncio
async def test_repair_compiled_edit_description_keeps_original_when_repair_fails() -> (
    None
):
    compiled = _compiled_edit_proposal(
        spec=_spec(description="Old generated description"),
        advisories=[_description_advisory()],
    )
    flow = SimpleNamespace(
        description="Old generated description",
        metadata_json=_builder_description_metadata("Old generated description"),
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_edit_repair.attempt_description_repair",
        new=AsyncMock(return_value=None),
    ) as repair:
        result = await repair_compiled_edit_description_if_needed(
            compiled=compiled,
            flow=flow,
            call_proposal_completion=AsyncMock(),
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            max_output_tokens=4096,
        )

    assert result is compiled
    repair.assert_awaited_once()

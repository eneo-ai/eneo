"""Contract tests for the AI Builder materialization / translation bridge.

The bridge is the single seam from orchestrator v2 planner output
(``ArchitectureCommit`` + ``DraftPlanEnvelope``) into flows-domain draft
types (``FlowDraftSpecCore`` + ``FlowChangeSet``). These tests pin the
contract the bridge exposes to its callers:

- the envelope step count must match the committed tuples_chain length
- each envelope step's per-step tuple must match the commit's tuple at
  the same index — the commit is authoritative
- extra top-level fields on an envelope step are rejected (the bridge
  validates via ``NewStepDraft`` with ``extra="forbid"``)
- on success the bridge emits a pair: the canonical
  ``FlowDraftSpecCore`` and the already-compiled ``FlowChangeSet`` so
  consumers skip re-compilation
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intric.flows.ai_builder.ai_builder_materialization_bridge import (
    MaterializationError,
    MaterializedDraft,
    materialize,
)
from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore
from intric.flows.ai_builder.ai_builder_orchestrator import DraftPlanEnvelope
from intric.flows.ai_builder.planning_state import ArchitectureCommit, StepTriple

_FIXED_COMMIT_TIMESTAMP = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)


def _architecture_commit(
    *,
    tuples_chain: list[StepTriple] | None = None,
    chosen_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
) -> ArchitectureCommit:
    """Build an ArchitectureCommit with defaults sensible for a single-step
    summarize_text flow.
    """
    return ArchitectureCommit(
        tuples_chain=tuples_chain
        or [
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=chosen_patterns or ["summarize_text"],
        required_capabilities=required_capabilities or ["summarize_text"],
        committed_at=_FIXED_COMMIT_TIMESTAMP,
        architecture_hash="a" * 64,
    )


def _summarize_text_step_dict() -> dict[str, object]:
    """Envelope step matching the summarize_text single-step triple."""
    return {
        "name": "Summarize the provided text",
        "instructions": "Skriv en kort sammanfattning av texten.",
        "input_source": "flow_input",
        "input_type": "text",
        "output_type": "text",
    }


class TestHappyPath:
    def test_single_step_summarize_text_yields_spec_and_changeset(self) -> None:
        commit = _architecture_commit()
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[_summarize_text_step_dict()],
            form_fields=[],
        )

        result = materialize(
            architecture_commit=commit,
            draft_plan=envelope,
            flow_name="Text summarization flow",
            flow_description="Summarizes the provided text.",
            plan_rationale="Single-step summarize_text realisation.",
        )

        assert isinstance(result, MaterializedDraft)
        assert isinstance(result.spec, FlowDraftSpecCore)
        # Spec carries the planner's naming verbatim (after normalize_flow_name).
        assert result.spec.flow_name == "Text summarization flow"
        assert result.spec.flow_description == "Summarizes the provided text."
        assert len(result.spec.steps) == 1
        step_spec = result.spec.steps[0]
        assert step_spec.name == "Summarize the provided text"
        assert (
            step_spec.assistant_spec.instructions
            == "Skriv en kort sammanfattning av texten."
        )
        # Per-step tuple aligned with commit.
        assert step_spec.input_type.value == "text"
        assert step_spec.output_type.value == "text"
        assert step_spec.output_mode.value == "pass_through"
        assert step_spec.input_source.value == "flow_input"
        # Changeset already compiled against create mode (no current_flow).
        assert result.changeset.flow_name == "Text summarization flow"
        assert len(result.changeset.assistants_to_create) == 1
        assert not result.changeset.assistants_to_update
        assert not result.changeset.assistants_to_delete


class TestStepCountMismatch:
    def test_envelope_shorter_than_tuples_chain_raises(self) -> None:
        commit = _architecture_commit(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="text",
                    output_mode="pass_through",
                ),
                StepTriple(
                    input_type="text",
                    output_type="text",
                    output_mode="pass_through",
                ),
            ]
        )
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[_summarize_text_step_dict()],
            form_fields=[],
        )

        with pytest.raises(MaterializationError) as exc_info:
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Two-step flow",
                plan_rationale="Mismatch test.",
            )

        assert "2" in str(exc_info.value)
        assert "1" in str(exc_info.value)

    def test_envelope_longer_than_tuples_chain_raises(self) -> None:
        commit = _architecture_commit()
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[
                _summarize_text_step_dict(),
                _summarize_text_step_dict(),
            ],
            form_fields=[],
        )

        with pytest.raises(MaterializationError):
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Two-step flow",
                plan_rationale="Mismatch test.",
            )


class TestPerStepTupleConsistency:
    def test_input_type_divergence_raises(self) -> None:
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        envelope_step["input_type"] = "document"
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[envelope_step],
            form_fields=[],
        )

        with pytest.raises(MaterializationError) as exc_info:
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Flow",
                plan_rationale="Divergence test.",
            )

        assert "input_type" in str(exc_info.value).lower()

    def test_output_type_divergence_raises(self) -> None:
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        envelope_step["output_type"] = "json"
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[envelope_step],
            form_fields=[],
        )

        with pytest.raises(MaterializationError) as exc_info:
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Flow",
                plan_rationale="Divergence test.",
            )

        assert "output_type" in str(exc_info.value).lower()


class TestOutputModeDerivationMismatch:
    """The post-compile check guards against an ArchitectureCommit whose
    declared output_mode diverges from what the create compiler derives
    for the committed (input_type, output_type) pair. The commit can be
    internally inconsistent (StepTriple validates per-axis, not
    cross-axis), and the bridge is the layer that catches it.
    """

    def test_audio_to_text_commit_with_pass_through_mode_is_rejected(self) -> None:
        commit = ArchitectureCommit(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="text",
                    output_mode="pass_through",
                ),
            ],
            chosen_patterns=["audio_transcription"],
            required_capabilities=["audio_transcription"],
            committed_at=_FIXED_COMMIT_TIMESTAMP,
            architecture_hash="b" * 64,
        )
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[
                {
                    "name": "Transcribe the audio",
                    "instructions": "Transkribera ljudet till text.",
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_type": "text",
                },
            ],
            form_fields=[],
        )

        with pytest.raises(MaterializationError) as exc_info:
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Audio flow",
                plan_rationale="Post-compile mode check.",
            )

        assert "output_mode" in str(exc_info.value).lower()


class TestEnvelopeExtraFieldRejection:
    def test_extra_top_level_field_on_step_raises(self) -> None:
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        envelope_step["surprise_key"] = "planner-hallucinated-field"
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[envelope_step],
            form_fields=[],
        )

        with pytest.raises(MaterializationError):
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Flow",
                plan_rationale="Extra-field drift test.",
            )


class TestPublicSurface:
    def test_module_exports_materialize_and_error(self) -> None:
        from intric.flows.ai_builder import ai_builder_materialization_bridge as bridge

        assert hasattr(bridge, "materialize")
        assert hasattr(bridge, "MaterializationError")
        assert hasattr(bridge, "MaterializedDraft")
        assert issubclass(bridge.MaterializationError, ValueError)

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
from unittest.mock import create_autospec
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import PlannerPlanEnvelope
from intric.flows.ai_builder.ai_builder_materialization_bridge import (
    MaterializationError,
    MaterializedDraft,
    apply_to_draft,
    materialize,
)
from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore
from intric.flows.ai_builder.ai_builder_orchestrator import DraftPlanEnvelope
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
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
                    # Audio flow_input requires runtime_upload=True — passes
                    # semantic validation so the post-compile output_mode
                    # guard can fire on the inconsistent StepTriple.
                    "runtime_upload": True,
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


class TestCreateDraftSemanticValidator:
    """The bridge must run ``validate_create_draft`` before compile so
    semantic rejections (``first_step_invalid_source``, ``empty_steps``,
    ``file_flow_input_requires_runtime_upload``, and friends) surface
    consistently with the proposal-processor path instead of silently
    materialising into a structurally-valid-but-semantically-broken
    draft.
    """

    def test_first_step_with_previous_step_source_is_rejected(self) -> None:
        """First envelope step declaring ``previous_step`` input_source
        structurally coerces through ``FlowCreateDraft`` but is a
        semantic error — there is no previous step at index 0.
        ``validate_create_draft`` raises ``first_step_invalid_source``.
        """
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        envelope_step["input_source"] = "previous_step"
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
                plan_rationale="First-step invalid-source test.",
            )

        assert "first_step_invalid_source" in str(exc_info.value)

    def test_empty_envelope_and_empty_commit_are_rejected(self) -> None:
        """A commit with no tuples_chain entries and an envelope with no
        steps pass step-count parity but are semantically empty — the
        create validator rejects ``empty_steps``.
        """
        commit = ArchitectureCommit(
            tuples_chain=[],
            chosen_patterns=["summarize_text"],
            required_capabilities=["summarize_text"],
            committed_at=_FIXED_COMMIT_TIMESTAMP,
            architecture_hash="c" * 64,
        )
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[],
            form_fields=[],
        )

        with pytest.raises(MaterializationError) as exc_info:
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Flow",
                plan_rationale="Empty-steps test.",
            )

        assert "empty_steps" in str(exc_info.value)


class TestUnsupportedCommitOutputMode:
    """Commits carrying an output_mode the create compiler cannot derive
    (``http_post`` today) are rejected up-front by the bridge. The
    alternative — letting them through — surfaces as a misleading
    post-compile ``output_mode`` mismatch. This guard gives a clear,
    create-specific error that names the unsupported mode.
    """

    def test_http_post_commit_is_rejected_with_explicit_message(self) -> None:
        commit = ArchitectureCommit(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="text",
                    output_mode="http_post",
                ),
            ],
            chosen_patterns=["http_post_call"],
            required_capabilities=["http_post_call"],
            committed_at=_FIXED_COMMIT_TIMESTAMP,
            architecture_hash="d" * 64,
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
                flow_name="Flow",
                plan_rationale="Unsupported-mode test.",
            )

        message = str(exc_info.value)
        assert "http_post" in message
        assert "unsupported" in message.lower()


class TestEnvelopeStepMustDeclareTupleAxes:
    """``NewStepDraft`` defaults ``input_type`` and ``output_type`` to
    ``text``. Without an explicit-key requirement, a text/text commit
    would silently accept an envelope step that omits both axes — the
    envelope would pretend to declare the tuple but actually lean on
    defaults. The bridge forces the envelope to name the axes so the
    "commit is authoritative" contract stays honest.
    """

    def test_missing_input_type_is_rejected(self) -> None:
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        del envelope_step["input_type"]
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
                plan_rationale="Missing-input-type test.",
            )

        assert "input_type" in str(exc_info.value)

    def test_missing_output_type_is_rejected(self) -> None:
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        del envelope_step["output_type"]
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
                plan_rationale="Missing-output-type test.",
            )

        assert "output_type" in str(exc_info.value)


class TestCompiledSpecValidatorGate:
    """After compile, the bridge runs the same compiled-spec acceptance
    gate the proposal processor uses — duplicate step names, chaining
    violations, and other hard errors block materialization instead of
    silently producing a spec the write surface would reject.
    """

    def test_duplicate_step_name_case_insensitive_is_rejected(self) -> None:
        """Two steps with names differing only in case (``"Same"`` /
        ``"same"``) pass strict structural validation, tuple parity, and
        the create-draft semantic validator, but the compiled-spec
        validator rejects them as ``duplicate_step_name``. Without the
        gate, the bridge would hand callers a spec that the proposal
        processor would reject the moment it tried to accept it.
        """
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
            steps=[
                {
                    "name": "Same",
                    "instructions": "Första steget.",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                },
                {
                    "name": "same",
                    "instructions": "Andra steget.",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                },
            ],
            form_fields=[],
        )

        with pytest.raises(MaterializationError) as exc_info:
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="Duplicate-name flow",
                plan_rationale="Compiled-spec validator test.",
            )

        assert "duplicate_step_name" in str(exc_info.value)


class TestApplyToDraft:
    """``apply_to_draft`` is the bridge's write path. It wraps the
    materialized spec in a ``PlannerPlanEnvelope`` (spec-bearing,
    post-acceptance shape) and calls ``AIBuilderRepository.create_plan``.
    The helper is deliberately thin — the bridge is not the right place
    to carry retry budgets, cataloged resource resolution, or plan-store
    eviction policy; callers own that.
    """

    def _canonical_materialized(self) -> MaterializedDraft:
        """A real ``MaterializedDraft`` produced by ``materialize`` so
        the test exercises the write path against the canonical shape,
        not a hand-mocked spec that could drift from what the compiler
        emits.
        """
        return materialize(
            architecture_commit=_architecture_commit(),
            draft_plan=DraftPlanEnvelope(
                plan_id="plan_apply_to_draft_contract",
                steps=[_summarize_text_step_dict()],
                form_fields=[],
            ),
            flow_name="Apply-to-draft flow",
            flow_description="Canonical MaterializedDraft for the write-path tests.",
            plan_rationale="apply-to-draft contract test",
        )

    @pytest.mark.asyncio
    async def test_passes_spec_and_envelope_through_to_repo(self) -> None:
        repo = create_autospec(AIBuilderRepository, instance=True)
        sentinel_plan = object()
        repo.create_plan.return_value = sentinel_plan
        session_id = uuid4()
        tenant_id = uuid4()
        materialized = self._canonical_materialized()

        result = await apply_to_draft(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
            materialized=materialized,
        )

        assert result is sentinel_plan
        repo.create_plan.assert_awaited_once()
        kwargs = repo.create_plan.call_args.kwargs
        assert kwargs["session_id"] == session_id
        assert kwargs["tenant_id"] == tenant_id
        assert kwargs["spec"] is materialized.spec
        envelope = kwargs["envelope"]
        assert isinstance(envelope, PlannerPlanEnvelope)
        assert envelope.spec is materialized.spec
        # Rationale flows from MaterializedDraft, not a separate kwarg —
        # one source of truth prevents silent drift between the value
        # validated by materialize() and the value persisted here.
        assert envelope.plan_rationale == materialized.plan_rationale
        assert envelope.assumptions == []
        assert envelope.risk_acknowledgments == []
        assert envelope.reasoning is None

    @pytest.mark.asyncio
    async def test_forwards_optional_fields_to_envelope(self) -> None:
        repo = create_autospec(AIBuilderRepository, instance=True)
        materialized = self._canonical_materialized()

        await apply_to_draft(
            repo=repo,
            session_id=uuid4(),
            tenant_id=uuid4(),
            materialized=materialized,
            assumptions=["User supplied input text."],
            risk_acknowledgments=["Redaction not applied."],
            reasoning="Chose summarize_text because single-step.",
        )

        envelope = repo.create_plan.call_args.kwargs["envelope"]
        assert envelope.assumptions == ["User supplied input text."]
        assert envelope.risk_acknowledgments == ["Redaction not applied."]
        assert envelope.reasoning == "Chose summarize_text because single-step."

    @pytest.mark.asyncio
    async def test_envelope_assumptions_do_not_alias_caller_list(self) -> None:
        """Caller mutating the assumptions list after the await must not
        bleed into the persisted envelope. The helper must take a defensive
        copy — otherwise a caller that recycles its assumptions buffer
        across turns would retroactively mutate what was persisted.
        """
        repo = create_autospec(AIBuilderRepository, instance=True)
        materialized = self._canonical_materialized()
        caller_assumptions = ["first", "second"]
        caller_risks = ["initial-risk"]

        await apply_to_draft(
            repo=repo,
            session_id=uuid4(),
            tenant_id=uuid4(),
            materialized=materialized,
            assumptions=caller_assumptions,
            risk_acknowledgments=caller_risks,
        )
        caller_assumptions.append("third")
        caller_risks.append("added-after-apply")

        envelope = repo.create_plan.call_args.kwargs["envelope"]
        assert envelope.assumptions == ["first", "second"]
        assert envelope.risk_acknowledgments == ["initial-risk"]

    @pytest.mark.asyncio
    async def test_does_not_forward_edit_result_json(self) -> None:
        """``apply_to_draft`` is create-scope. ``edit_result_json`` is
        an edit-mode parameter on ``create_plan`` and must not leak from
        the bridge until edit-path materialization exists.
        """
        repo = create_autospec(AIBuilderRepository, instance=True)
        materialized = self._canonical_materialized()

        await apply_to_draft(
            repo=repo,
            session_id=uuid4(),
            tenant_id=uuid4(),
            materialized=materialized,
        )

        kwargs = repo.create_plan.call_args.kwargs
        assert "edit_result_json" not in kwargs

    def test_materialize_stamps_plan_rationale_on_draft(self) -> None:
        """The rationale passed to ``materialize`` must ride back on the
        returned ``MaterializedDraft`` so the write path has exactly one
        source of truth and cannot drift.
        """
        materialized = materialize(
            architecture_commit=_architecture_commit(),
            draft_plan=DraftPlanEnvelope(
                plan_id="plan_rationale_stamp",
                steps=[_summarize_text_step_dict()],
                form_fields=[],
            ),
            flow_name="Flow",
            plan_rationale="Chosen because the user needs a quick summary.",
        )
        assert materialized.plan_rationale == (
            "Chosen because the user needs a quick summary."
        )


class TestPublicSurface:
    def test_module_exports_materialize_and_error(self) -> None:
        from intric.flows.ai_builder import ai_builder_materialization_bridge as bridge

        assert hasattr(bridge, "materialize")
        assert hasattr(bridge, "apply_to_draft")
        assert hasattr(bridge, "MaterializationError")
        assert hasattr(bridge, "MaterializedDraft")
        assert issubclass(bridge.MaterializationError, ValueError)

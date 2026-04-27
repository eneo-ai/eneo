"""Contract tests for the AI Builder materialization / translation bridge.

The bridge is the single seam from orchestrator v2 planner output
(``ArchitectureCommit`` + ``DraftPlanEnvelope``) into flows-domain draft
types (``FlowDraftSpecCore`` + ``FlowChangeSet``). These tests pin the
contract the bridge exposes to its callers:

- the committed architecture constrains primary runtime input and
  terminal output, not exact implementation step count
- each envelope step must still declare explicit tuple axes so the
  Flow compiler and validator see intentional capability choices
- extra top-level fields on an envelope step are rejected (the bridge
  validates via ``NewStepDraft`` with ``extra="forbid"``)
- on success the bridge emits a pair: the canonical
  ``FlowDraftSpecCore`` and the already-compiled ``FlowChangeSet`` so
  consumers skip re-compilation
- materialize spans every positive archetype in the Pattern Registry,
  not just ``summarize_text`` — per-pattern parameterized coverage
  guards against any future archetype drift that would silently break
  the general-purpose builder contract
- the bridge hands off to ``compile_changeset`` for its final output,
  so the modify/delete routing an edit-path caller expects is pinned
  at the bridge's seam even while the edit-mode entry point is still
  under construction
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import create_autospec
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import (
    AssistantSpec,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    PlannerPlanEnvelope,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_draft_plan import DraftPlanEnvelope
from intric.flows.ai_builder.ai_builder_materialization_bridge import (
    MaterializationError,
    MaterializedDraft,
    apply_to_draft,
    materialize,
)
from intric.flows.ai_builder.ai_builder_materializer import compile_changeset
from intric.flows.ai_builder.ai_builder_models import FlowDraftSpecCore
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.planning_state import ArchitectureCommit, StepTriple
from intric.flows.domain.flow import Flow, FlowStep
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
)

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


class TestArchitectureEnvelope:
    def test_multistep_plan_can_materialize_against_single_commit_envelope(
        self,
    ) -> None:
        """Architecture commit constrains user intent, not implementation size.

        A single document->text architecture envelope must allow the
        materializer to create an intermediate JSON extraction step when
        that is the better flow design.
        """
        commit = _architecture_commit(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[
                {
                    "name": "Extrahera fakta",
                    "instructions": "Extrahera relevanta fakta från dokumentet.",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "json",
                    "runtime_upload": True,
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "array",
                            "description": "Relevanta fakta från dokumentet.",
                        },
                    ],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv en tydlig rapport från extraktionen.",
                    "input_source": "previous_step",
                    "input_type": "json",
                    "output_type": "text",
                },
            ],
            form_fields=[],
        )

        result = materialize(
            architecture_commit=commit,
            draft_plan=envelope,
            flow_name="Two-step flow",
            plan_rationale="Use structured extraction before final writing.",
        )

        assert len(result.spec.steps) == 2
        assert result.spec.steps[0].input_type.value == "document"
        assert result.spec.steps[0].output_type.value == "json"
        assert result.spec.steps[-1].output_type.value == "text"

    def test_terminal_output_divergence_raises(self) -> None:
        commit = _architecture_commit()
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[
                {
                    **_summarize_text_step_dict(),
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Sammanfattningen.",
                        },
                    ],
                },
            ],
            form_fields=[],
        )

        with pytest.raises(MaterializationError) as exc_info:
            materialize(
                architecture_commit=commit,
                draft_plan=envelope,
                flow_name="JSON flow",
                plan_rationale="Terminal mismatch test.",
            )

        assert "terminal" in str(exc_info.value).lower()


class TestPerStepTupleConsistency:
    def test_input_type_divergence_raises(self) -> None:
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        envelope_step["input_type"] = "document"
        envelope_step["runtime_upload"] = True
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
    semantic rejections (``empty_steps``, unsupported output fields,
    and friends) surface consistently with the proposal-processor path.
    Safe backend-owned mechanics are normalized before validation so
    legacy envelopes do not fail only because the model authored a
    deterministic wiring default.
    """

    def test_first_step_with_previous_step_source_is_normalized(self) -> None:
        """First envelope step declaring ``previous_step`` input_source
        is a model-authored wiring mistake. The bridge normalizes it to
        ``flow_input`` before strict semantic validation.
        """
        commit = _architecture_commit()
        envelope_step = _summarize_text_step_dict()
        envelope_step["input_source"] = "previous_step"
        envelope = DraftPlanEnvelope(
            plan_id="plan_1",
            steps=[envelope_step],
            form_fields=[],
        )

        result = materialize(
            architecture_commit=commit,
            draft_plan=envelope,
            flow_name="Flow",
            plan_rationale="First-step invalid-source test.",
        )

        assert result.spec.steps[0].input_source == "flow_input"

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


# ---------------------------------------------------------------------------
# Per-archetype coverage
# ---------------------------------------------------------------------------


def _archetype_case(
    *,
    pattern_id: str,
    tuples_chain: list[StepTriple],
    envelope_steps: list[dict[str, Any]],
    envelope_form_fields: list[dict[str, Any]] | None = None,
    expected_assistants_to_create: int,
    expected_output_modes: list[str],
    expected_mcp_server_refs_by_step: list[list[str]] | None = None,
    expected_mcp_tool_refs_by_step: list[list[str]] | None = None,
) -> dict[str, Any]:
    """Bundle the per-pattern fixture so the parametrize table is readable.

    The bridge asserts each returned field against the compiled spec /
    changeset, so the fixture is the ground truth for what ``materialize``
    is expected to produce for this archetype shape.
    """
    return {
        "pattern_id": pattern_id,
        "tuples_chain": tuples_chain,
        "envelope_steps": envelope_steps,
        "envelope_form_fields": envelope_form_fields or [],
        "expected_assistants_to_create": expected_assistants_to_create,
        "expected_output_modes": expected_output_modes,
        "expected_mcp_server_refs_by_step": expected_mcp_server_refs_by_step,
        "expected_mcp_tool_refs_by_step": expected_mcp_tool_refs_by_step,
    }


_ARCHETYPE_CASES: tuple[dict[str, Any], ...] = (
    # summarize_text — the single-archetype baseline the other
    # bridge contract tests already exercise, restated here so the
    # registry coverage set is complete.
    _archetype_case(
        pattern_id="summarize_text",
        tuples_chain=[
            StepTriple(
                input_type="text", output_type="text", output_mode="pass_through"
            ),
        ],
        envelope_steps=[
            {
                "name": "Sammanfatta texten",
                "instructions": "Skriv en kort sammanfattning av texten.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["pass_through"],
    ),
    # extract_structured_fields — text → json → pass_through with
    # structured output_fields. output_fields are what turn a text/json
    # step into a working structured-extraction flow.
    _archetype_case(
        pattern_id="extract_structured_fields",
        tuples_chain=[
            StepTriple(
                input_type="text", output_type="json", output_mode="pass_through"
            ),
        ],
        envelope_steps=[
            {
                "name": "Extrahera fält",
                "instructions": "Extrahera namn och datum från texten.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [
                    {
                        "name": "customer_name",
                        "field_type": "string",
                        "description": "Kundens namn.",
                    },
                    {
                        "name": "issued_at",
                        "field_type": "string",
                        "description": "Utfärdandedatum.",
                    },
                ],
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["pass_through"],
    ),
    # document_to_structured_report — document → text with runtime_upload
    # declared on the first step (the create validator rejects document
    # flow_input without runtime_upload).
    _archetype_case(
        pattern_id="document_to_structured_report",
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        envelope_steps=[
            {
                "name": "Rapport från dokument",
                "instructions": "Sammanfatta dokumentet som en strukturerad rapport.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_upload": True,
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["pass_through"],
    ),
    # document_to_docx_template — canonical 3-step chain ending in
    # template_fill. The final step flips document_delivery_mode to
    # "template_fill" so the compiler derives OutputMode.TEMPLATE_FILL.
    _archetype_case(
        pattern_id="document_to_docx_template",
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="json",
                output_mode="pass_through",
            ),
            StepTriple(
                input_type="json", output_type="text", output_mode="pass_through"
            ),
            StepTriple(
                input_type="text", output_type="docx", output_mode="template_fill"
            ),
        ],
        envelope_steps=[
            {
                "name": "Läs in dokument",
                "instructions": "Läs in dokumentet och extrahera nyckelvärden.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "runtime_upload": True,
                "output_fields": [
                    {
                        "name": "reference_id",
                        "field_type": "string",
                        "description": "Referensnummer.",
                    },
                ],
            },
            {
                "name": "Skriv brödtext",
                "instructions": "Förbered den text som ska fyllas i mallen.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
            },
            {
                "name": "Fyll DOCX-mall",
                "instructions": "Fyll i DOCX-mallen med brödtexten.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "document_delivery_mode": "template_fill",
            },
        ],
        expected_assistants_to_create=3,
        expected_output_modes=["pass_through", "pass_through", "template_fill"],
    ),
    # document_to_pdf_report — document → pdf → pass_through, single
    # step, runtime_upload required.
    _archetype_case(
        pattern_id="document_to_pdf_report",
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="pdf",
                output_mode="pass_through",
            ),
        ],
        envelope_steps=[
            {
                "name": "PDF-rapport",
                "instructions": "Producera en strukturerad PDF-rapport.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "pdf",
                "runtime_upload": True,
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["pass_through"],
    ),
    # audio_transcription — audio → text derives transcribe_only
    # unconditionally; runtime_upload required for audio flow_input.
    _archetype_case(
        pattern_id="audio_transcription",
        tuples_chain=[
            StepTriple(
                input_type="audio",
                output_type="text",
                output_mode="transcribe_only",
            ),
        ],
        envelope_steps=[
            {
                "name": "Transkribera ljud",
                "instructions": "Transkribera inspelningen till text.",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "runtime_upload": True,
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["transcribe_only"],
    ),
    # audio_to_artifact_report — audio intake must still start with a
    # transcribe_only step before an artifact-generating terminal step.
    _archetype_case(
        pattern_id="audio_to_artifact_report",
        tuples_chain=[
            StepTriple(
                input_type="audio",
                output_type="text",
                output_mode="transcribe_only",
            ),
            StepTriple(
                input_type="text",
                output_type="pdf",
                output_mode="pass_through",
            ),
        ],
        envelope_steps=[
            {
                "name": "Transkribera ljud",
                "instructions": "Transkribera inspelningen till text.",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "runtime_upload": True,
            },
            {
                "name": "Skapa PDF-rapport",
                "instructions": "Skapa en PDF-rapport från transkriptionen.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
            },
        ],
        expected_assistants_to_create=2,
        expected_output_modes=["transcribe_only", "pass_through"],
    ),
    # multi_step_quality_chain — 4-step chain: document intake, JSON
    # extraction, text review, text terminal. Each step explicitly
    # declares its tuple so the bridge's tuple-authoritative contract
    # is exercised end-to-end.
    _archetype_case(
        pattern_id="multi_step_quality_chain",
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="json",
                output_mode="pass_through",
            ),
            StepTriple(
                input_type="json", output_type="text", output_mode="pass_through"
            ),
            StepTriple(
                input_type="text", output_type="text", output_mode="pass_through"
            ),
            StepTriple(
                input_type="text", output_type="text", output_mode="pass_through"
            ),
        ],
        envelope_steps=[
            {
                "name": "Extrahera struktur",
                "instructions": "Extrahera strukturerade fält från dokumentet.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "runtime_upload": True,
                "output_fields": [
                    {
                        "name": "topic",
                        "field_type": "string",
                        "description": "Huvudämnet i dokumentet.",
                    },
                ],
            },
            {
                "name": "Skriv utkast",
                "instructions": "Skapa ett första utkast baserat på extraktionen.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
            },
            {
                "name": "Granska kvalitet",
                "instructions": "Granska utkastet och föreslå förbättringar.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Slutresultat",
                "instructions": "Producera den slutgiltiga texten.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
        ],
        expected_assistants_to_create=4,
        expected_output_modes=[
            "pass_through",
            "pass_through",
            "pass_through",
            "pass_through",
        ],
    ),
    # comparison — single-step realization over a document input. The
    # pattern's multi-document variant routes additional inputs through
    # form_fields; the bridge just needs to not reject the shape here —
    # the richer multi-input composition is exercised by the goldens
    # coverage matrix.
    _archetype_case(
        pattern_id="comparison",
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        envelope_steps=[
            {
                "name": "Jämför dokument",
                "instructions": "Jämför dokumentet mot de angivna referenserna.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_upload": True,
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["pass_through"],
    ),
    # sectioned_form_intake — 2-step chain. Step 1 captures rubric text
    # via uses_form_fields, step 2 composes the sections into the final
    # output. Requires flow-level form_fields to resolve the references.
    _archetype_case(
        pattern_id="sectioned_form_intake",
        tuples_chain=[
            StepTriple(
                input_type="text", output_type="text", output_mode="pass_through"
            ),
            StepTriple(
                input_type="text", output_type="text", output_mode="pass_through"
            ),
        ],
        envelope_steps=[
            {
                "name": "Fånga sektioner",
                "instructions": "Ta in rubriktext för varje angiven sektion.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
                "uses_form_fields": ["bakgrund", "analys"],
            },
            {
                "name": "Komponera resultat",
                "instructions": "Sammanställ sektionerna till ett slutresultat.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
        ],
        envelope_form_fields=[
            {
                "variable_name": "bakgrund",
                "label": "Bakgrund",
                "field_type": "text",
                "required": True,
            },
            {
                "variable_name": "analys",
                "label": "Analys",
                "field_type": "text",
                "required": True,
            },
        ],
        expected_assistants_to_create=2,
        expected_output_modes=["pass_through", "pass_through"],
    ),
    # form_field_runtime_inputs — text/text/pass_through single step
    # where the runtime variables live entirely on flow-level form_fields
    # and step 1 references them via uses_form_fields.
    _archetype_case(
        pattern_id="form_field_runtime_inputs",
        tuples_chain=[
            StepTriple(
                input_type="text", output_type="text", output_mode="pass_through"
            ),
        ],
        envelope_steps=[
            {
                "name": "Generera svar",
                "instructions": "Svara med utgångspunkt från formulärfälten.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
                "uses_form_fields": ["reference_id", "owning_unit"],
            },
        ],
        envelope_form_fields=[
            {
                "variable_name": "reference_id",
                "label": "Referens-ID",
                "field_type": "text",
                "required": True,
            },
            {
                "variable_name": "owning_unit",
                "label": "Ansvarig enhet",
                "field_type": "text",
                "required": False,
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["pass_through"],
    ),
    # mcp_tool_step — runtime MCP access is step-scoped. The bridge
    # carries refs through the normal new-step compiler; actual MCP
    # execution remains runtime-only.
    _archetype_case(
        pattern_id="mcp_tool_step",
        tuples_chain=[
            StepTriple(
                input_type="text", output_type="text", output_mode="pass_through"
            ),
        ],
        envelope_steps=[
            {
                "name": "Hämta ärendedata",
                "instructions": "Använd ärendesystemets MCP-verktyg för att hämta live-data.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
                "mcp_server_refs": ["11111111-1111-4111-8111-111111111111"],
                "mcp_tool_refs": ["22222222-2222-4222-8222-222222222222"],
            },
        ],
        expected_assistants_to_create=1,
        expected_output_modes=["pass_through"],
        expected_mcp_server_refs_by_step=[["11111111-1111-4111-8111-111111111111"]],
        expected_mcp_tool_refs_by_step=[["22222222-2222-4222-8222-222222222222"]],
    ),
)


class TestArchetypeCoverage:
    """Per-archetype coverage that the bridge materialises every positive
    pattern in the Pattern Registry.

    The rest of this file's contract tests exercise
    ``summarize_text`` only. A future archetype drift (e.g. the
    compiler stops deriving ``transcribe_only`` for audio, or a new
    pattern lands without a matching envelope shape) would not fail
    the single-archetype suite. This parameterized case set keeps the
    general-purpose builder contract in view: every registered
    positive pattern has a known-good fixture that round-trips
    through the bridge.
    """

    def test_every_positive_pattern_has_a_fixture(self) -> None:
        """Structural guard: if a positive pattern lands in the registry
        without a corresponding case here, the archetype set goes stale
        silently and new shapes ride into production untested.
        """
        positive_registry_ids = {
            pattern.id
            for pattern in PATTERN_REGISTRY.values()
            if pattern.polarity == "positive"
        }
        covered_ids = {case["pattern_id"] for case in _ARCHETYPE_CASES}
        missing = positive_registry_ids - covered_ids
        assert not missing, (
            "Every positive pattern in PATTERN_REGISTRY must have a coverage "
            f"case in _ARCHETYPE_CASES; missing: {sorted(missing)}"
        )
        unknown = covered_ids - positive_registry_ids
        assert not unknown, (
            "_ARCHETYPE_CASES references patterns absent from the registry: "
            f"{sorted(unknown)}"
        )

    @pytest.mark.parametrize(
        "case",
        _ARCHETYPE_CASES,
        ids=[case["pattern_id"] for case in _ARCHETYPE_CASES],
    )
    def test_archetype_materializes_through_bridge(self, case: dict[str, Any]) -> None:
        commit = _architecture_commit(
            tuples_chain=case["tuples_chain"],
            chosen_patterns=[case["pattern_id"]],
            required_capabilities=[case["pattern_id"]],
        )
        envelope = DraftPlanEnvelope(
            plan_id=f"plan_{case['pattern_id']}",
            steps=case["envelope_steps"],
            form_fields=case["envelope_form_fields"],
        )

        result = materialize(
            architecture_commit=commit,
            draft_plan=envelope,
            flow_name=f"{case['pattern_id']} flow",
            flow_description=f"Archetype coverage fixture for {case['pattern_id']}.",
            plan_rationale=f"Canonical {case['pattern_id']} realisation.",
        )

        assert isinstance(result, MaterializedDraft)
        assert isinstance(result.spec, FlowDraftSpecCore)
        assert len(result.spec.steps) == len(case["envelope_steps"])
        for step_index, expected_mode in enumerate(case["expected_output_modes"]):
            assert result.spec.steps[step_index].output_mode.value == expected_mode, (
                f"{case['pattern_id']} step[{step_index}] output_mode "
                f"{result.spec.steps[step_index].output_mode.value!r} did not "
                f"match expected {expected_mode!r}"
            )
        if case["expected_mcp_server_refs_by_step"] is not None:
            assert [
                step.assistant_spec.mcp_server_refs for step in result.spec.steps
            ] == case["expected_mcp_server_refs_by_step"]
        if case["expected_mcp_tool_refs_by_step"] is not None:
            assert [
                step.assistant_spec.mcp_tool_refs for step in result.spec.steps
            ] == case["expected_mcp_tool_refs_by_step"]
            assert [
                assistant.assistant_spec.mcp_tool_refs
                for assistant in result.changeset.assistants_to_create
            ] == case["expected_mcp_tool_refs_by_step"]
        if case["expected_mcp_server_refs_by_step"] is not None:
            assert [
                assistant.assistant_spec.mcp_server_refs
                for assistant in result.changeset.assistants_to_create
            ] == case["expected_mcp_server_refs_by_step"]
        assert (
            len(result.changeset.assistants_to_create)
            == case["expected_assistants_to_create"]
        )
        assert not result.changeset.assistants_to_update
        assert not result.changeset.assistants_to_delete


# ---------------------------------------------------------------------------
# Edit-mode delegation contract
# ---------------------------------------------------------------------------


def _edit_step_spec(
    *,
    plan_step_ref: str,
    name: str,
    existing_step_ref: str | None = None,
    input_source: InputSource = InputSource.FLOW_INPUT,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_step_ref,
        existing_step_ref=existing_step_ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=f"{name} instructions."),
        mcp_policy=MCPPolicy.INHERIT,
        input_source=input_source,
        input_type=InputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        output_type=OutputType.TEXT,
    )


def _edit_flow_step(*, step_order: int) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Existing step {step_order}",
        input_source=FlowInputSource.FLOW_INPUT
        if step_order == 1
        else FlowInputSource.PREVIOUS_STEP,
        input_type=FlowInputType.TEXT,
        output_mode=FlowOutputMode.PASS_THROUGH,
        output_type=FlowOutputType.TEXT,
        mcp_policy=FlowMcpPolicy.INHERIT,
    )


def _edit_flow(*, step_orders: list[int]) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Existing flow",
        steps=[_edit_flow_step(step_order=order) for order in step_orders],
    )


class TestBridgeEditModeDelegation:
    """Edit-mode tests with a real ``current_flow`` fixture exercise the
    modify / delete paths the bridge ultimately hands off to through
    ``compile_changeset``.

    ``materialize`` is create-only today: it always invokes
    ``compile_changeset(spec, current_flow=None)``. The edit-mode entry
    point is future work and will dispatch on ``target_kind``.
    These tests pin the compile-changeset delegation contract at the
    bridge's seam so that when edit-mode materialisation lands, the
    downstream routing (modified → ``assistants_to_update``, unreferenced
    existing step → ``assistants_to_delete``, mixed → both) already has
    regression coverage the bridge can rely on.
    """

    def test_modify_routes_into_assistants_to_update(self) -> None:
        """A spec step whose ``existing_step_ref`` matches an existing
        ``step_order`` must route to the update lane — not create a
        second step with the same semantics and not silently fall back
        to create-mode.
        """
        spec = FlowDraftSpecCore(
            flow_name="Edit modify",
            flow_description="",
            steps=[
                _edit_step_spec(
                    plan_step_ref="step_a",
                    name="Updated step",
                    existing_step_ref="existing_step_1",
                ),
            ],
        )
        current_flow = _edit_flow(step_orders=[1])

        changeset = compile_changeset(spec, current_flow)

        assert len(changeset.assistants_to_update) == 1
        assert not changeset.assistants_to_create
        assert not changeset.assistants_to_delete
        assert len(changeset.compiled_steps) == 1
        assert changeset.compiled_steps[0].change_kind.value == "modified"

    def test_unreferenced_existing_step_routes_into_assistants_to_delete(
        self,
    ) -> None:
        """Existing steps the new spec does not reference must land in
        the delete lane. Without this, a user who removes a step via the
        builder would see it persist as an orphan assistant.
        """
        spec = FlowDraftSpecCore(
            flow_name="Edit delete",
            flow_description="",
            steps=[
                _edit_step_spec(
                    plan_step_ref="step_a",
                    name="Only remaining step",
                    existing_step_ref="existing_step_1",
                ),
            ],
        )
        current_flow = _edit_flow(step_orders=[1, 2])

        changeset = compile_changeset(spec, current_flow)

        assert len(changeset.assistants_to_update) == 1
        assert not changeset.assistants_to_create
        assert len(changeset.assistants_to_delete) == 1
        # The delete targets the unreferenced existing_step_2.
        deleted_ids = {
            entry.step_id for entry in changeset.assistants_to_delete if entry.step_id
        }
        existing_ids = {step.id for step in current_flow.steps if step.step_order == 2}
        assert deleted_ids == existing_ids

    def test_mixed_add_modify_delete_produces_all_three_lanes(self) -> None:
        """The canonical edit shape: insert a new step, modify one
        existing, delete one existing. All three lanes populate in a
        single compile pass — the contract the bridge will delegate to
        once edit-mode materialisation lands.
        """
        spec = FlowDraftSpecCore(
            flow_name="Edit mixed",
            flow_description="",
            steps=[
                _edit_step_spec(
                    plan_step_ref="step_a",
                    name="Brand-new first step",
                ),
                _edit_step_spec(
                    plan_step_ref="step_b",
                    name="Modified middle step",
                    existing_step_ref="existing_step_2",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        )
        current_flow = _edit_flow(step_orders=[1, 2, 3])

        changeset = compile_changeset(spec, current_flow)

        assert len(changeset.assistants_to_create) == 1
        assert len(changeset.assistants_to_update) == 1
        # Existing steps 1 and 3 are unreferenced → deleted.
        assert len(changeset.assistants_to_delete) == 2
        deleted_orders = {
            step.step_order
            for step in current_flow.steps
            if step.id in {entry.step_id for entry in changeset.assistants_to_delete}
        }
        assert deleted_orders == {1, 3}
        # Compiled steps keep the spec order: ADD then MODIFY.
        kinds = [step.change_kind.value for step in changeset.compiled_steps]
        assert kinds == ["added", "modified"]

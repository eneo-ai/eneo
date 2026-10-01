"""Producer-resolution behavior of the canonical checkpoint predicate."""

from eneo.flows.ai_builder.ai_builder_checkpoint_contract import (
    CheckpointIntentMismatch,
    checkpoint_intent_mismatches,
    project_checkpoint_intents,
)
from eneo.flows.ai_builder.planning_state import CheckpointIntent
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy


def _text_step(
    ref: str,
    *,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    existing_step_ref: str | None = None,
    reviewed_mode: FlowStepReviewMode | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        existing_step_ref=existing_step_ref,
        name=f"Step {ref}",
        assistant_spec=AssistantSpec(instructions=f"Write {ref}."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_mode=output_mode,
        output_type=output_type,
        review_policy=(
            FlowStepReviewPolicy(mode=reviewed_mode)
            if reviewed_mode is not None
            else None
        ),
    )


def _report_intent() -> CheckpointIntent:
    return CheckpointIntent(
        evidence_level="explicit",
        producer_kind="report_text",
        operation="set",
        mode=FlowStepReviewMode.EDIT,
        confidence="high",
        evidence=["quote:user_message:1:Edit the report."],
    )


def test_report_checkpoint_targets_last_referenced_body_writer() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Multi-writer report",
        steps=[
            _text_step("writer_a"),
            _text_step("writer_b", reviewed_mode=FlowStepReviewMode.EDIT),
            _text_step("composer", output_mode=OutputMode.COMPOSE_TEXT),
        ],
        document_body_writer_step_refs=("writer_a", "writer_b"),
    )

    assert checkpoint_intent_mismatches(spec, [_report_intent()]) == ()

    wrong_writer = FlowDraftSpecCore(
        flow_name="Multi-writer report",
        steps=[
            _text_step("writer_a", reviewed_mode=FlowStepReviewMode.EDIT),
            _text_step("writer_b"),
            _text_step("composer", output_mode=OutputMode.COMPOSE_TEXT),
        ],
        document_body_writer_step_refs=("writer_a", "writer_b"),
    )

    kinds = {
        mismatch.kind
        for mismatch in checkpoint_intent_mismatches(wrong_writer, [_report_intent()])
    }
    assert kinds == {"review_missing", "unexpected_review"}


def _clear_structured_intent() -> CheckpointIntent:
    return CheckpointIntent(
        evidence_level="explicit",
        producer_kind="structured_result",
        operation="clear",
        mode=None,
        confidence="high",
        evidence=["quote:user_message:1:Remove the JSON approval."],
    )


def _set_structured_intent() -> CheckpointIntent:
    return CheckpointIntent(
        evidence_level="explicit",
        producer_kind="structured_result",
        operation="set",
        mode=FlowStepReviewMode.EDIT,
        confidence="high",
        evidence=["quote:user_message:1:Edit the extracted data."],
    )


def test_clear_survives_producer_retyped_by_the_same_edit() -> None:
    baseline = FlowDraftSpecCore(
        flow_name="baseline",
        steps=[
            _text_step(
                "existing-1",
                output_type=OutputType.JSON,
                existing_step_ref="existing-1",
                reviewed_mode=FlowStepReviewMode.VIEW,
            )
        ],
    )
    proposed = FlowDraftSpecCore(
        flow_name="Retyped producer",
        steps=[
            _text_step(
                "existing-1",
                output_type=OutputType.TEXT,
                existing_step_ref="existing-1",
            )
        ],
    )

    # The requested clear releases the baseline JSON checkpoint even though
    # the step is no longer a structured producer in the proposed spec.
    assert (
        checkpoint_intent_mismatches(
            proposed,
            [_clear_structured_intent()],
            baseline_spec=baseline,
        )
        == ()
    )
    # Without the typed clear the same removal is an unsolicited change.
    assert checkpoint_intent_mismatches(proposed, [], baseline_spec=baseline)


def test_set_acts_on_the_saved_review_while_it_stays_json() -> None:
    """A set changes the saved review where it is; it follows the review to a
    new step only when the saved step stops being a structured result."""

    baseline = FlowDraftSpecCore(
        flow_name="baseline",
        steps=[
            _text_step(
                "existing-1",
                output_type=OutputType.JSON,
                existing_step_ref="existing-1",
                reviewed_mode=FlowStepReviewMode.VIEW,
            )
        ],
    )

    def proposed(
        *,
        old_reviewed: bool,
        new_reviewed: bool,
        old_type: OutputType = OutputType.JSON,
    ) -> FlowDraftSpecCore:
        return FlowDraftSpecCore(
            flow_name="Relocated producer",
            steps=[
                _text_step(
                    "existing-1",
                    output_type=old_type,
                    existing_step_ref="existing-1",
                    reviewed_mode=(FlowStepReviewMode.VIEW if old_reviewed else None),
                ),
                _text_step(
                    "new_terminal",
                    output_type=OutputType.JSON,
                    reviewed_mode=(FlowStepReviewMode.EDIT if new_reviewed else None),
                ),
            ],
        )

    def kinds(spec: FlowDraftSpecCore) -> set[tuple[str, str | None]]:
        return _kinds_and_refs(
            checkpoint_intent_mismatches(
                spec, [_set_structured_intent()], baseline_spec=baseline
            )
        )

    assert kinds(proposed(old_reviewed=False, new_reviewed=True)) == {
        ("review_missing", "existing-1")
    }
    retyped = proposed(old_reviewed=False, new_reviewed=True, old_type=OutputType.TEXT)
    assert kinds(retyped) == set()
    # Two reviewed structured results name no single reviewed result.
    assert {
        kind for kind, _ in kinds(proposed(old_reviewed=True, new_reviewed=True))
    } == {
        "producer_unbound",
        "unexpected_review",
    }


def test_report_relocation_releases_the_baseline_body_writer() -> None:
    """A requested report review follows a relocated body writer.

    The persisted baseline has a reviewed compose writer feeding a renderer,
    plus a later text step. The edit retypes the old writer and makes the
    later step the new reviewed body writer; the typed set intent must
    release the baseline writer's checkpoint instead of pinning it.
    """
    from uuid import uuid4

    from eneo.flows.ai_builder.ai_builder_checkpoint_contract import (
        baseline_spec_from_flow_steps,
    )
    from eneo.flows.domain.flow import FlowStep

    flow_id = uuid4()
    tenant_id = uuid4()

    def _flow_step(
        order: int,
        *,
        output_mode: str,
        output_type: str = "text",
        reviewed: bool,
    ) -> FlowStep:
        return FlowStep(
            id=uuid4(),
            flow_id=flow_id,
            tenant_id=tenant_id,
            assistant_id=uuid4(),
            step_order=order,
            user_description=f"Step {order}",
            input_source="previous_step",
            input_type="text",
            output_mode=output_mode,
            output_type=output_type,
            review_policy=(
                FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW) if reviewed else None
            ),
        )

    baseline = baseline_spec_from_flow_steps(
        [
            _flow_step(1, output_mode="compose_text", reviewed=True),
            _flow_step(
                2,
                output_mode="render_verbatim",
                output_type="pdf",
                reviewed=False,
            ),
            _flow_step(3, output_mode="pass_through", reviewed=False),
        ]
    )
    assert baseline.document_body_writer_step_refs == ("existing_step_1",)

    set_report_intent = CheckpointIntent(
        evidence_level="explicit",
        producer_kind="report_text",
        operation="set",
        mode=FlowStepReviewMode.EDIT,
        confidence="high",
        evidence=["quote:user_message:1:Edit the report body."],
    )
    proposed = FlowDraftSpecCore(
        flow_name="Relocated report writer",
        steps=[
            _text_step(
                "existing_step_1",
                output_type=OutputType.JSON,
                existing_step_ref="existing_step_1",
            ),
            _text_step(
                "existing_step_3",
                output_mode=OutputMode.COMPOSE_TEXT,
                existing_step_ref="existing_step_3",
                reviewed_mode=FlowStepReviewMode.EDIT,
            ),
            _text_step(
                "existing_step_2",
                output_mode=OutputMode.RENDER_VERBATIM,
                output_type=OutputType.PDF,
                existing_step_ref="existing_step_2",
            ),
        ],
        document_body_writer_step_refs=("existing_step_3",),
    )

    assert (
        checkpoint_intent_mismatches(
            proposed,
            [set_report_intent],
            baseline_spec=baseline,
        )
        == ()
    )


def test_report_checkpoint_falls_back_to_last_compose_step() -> None:
    spec = FlowDraftSpecCore(
        flow_name="No body-writer refs",
        steps=[
            _text_step("draft"),
            _text_step(
                "composer",
                output_mode=OutputMode.COMPOSE_TEXT,
                reviewed_mode=FlowStepReviewMode.EDIT,
            ),
        ],
    )

    assert checkpoint_intent_mismatches(spec, [_report_intent()]) == ()


def test_template_fill_checkpoint_targets_prefill_producer_and_refuses_renderer_review() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Template report",
        steps=[
            _text_step(
                "analyze",
                output_type=OutputType.JSON,
                existing_step_ref="existing_analyze",
            ),
            _text_step(
                "validate",
                output_type=OutputType.JSON,
                existing_step_ref="existing_validate",
                reviewed_mode=FlowStepReviewMode.EDIT,
            ),
            _text_step("write", existing_step_ref="existing_write"),
            _text_step(
                "fill",
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
                existing_step_ref="existing_fill",
            ),
        ],
    )
    intent = _set_structured_intent()

    projected = project_checkpoint_intents(spec, [intent])

    assert projected.steps[1].review_policy is not None
    assert projected.steps[1].review_policy.mode is FlowStepReviewMode.EDIT
    assert projected.steps[2].review_policy is None
    assert projected.steps[-1].review_policy is None
    assert checkpoint_intent_mismatches(projected, [intent]) == ()

    reviewed_fill = projected.model_copy(
        update={
            "steps": [
                *projected.steps[:-1],
                projected.steps[-1].model_copy(
                    update={
                        "review_policy": FlowStepReviewPolicy(
                            mode=FlowStepReviewMode.VIEW
                        )
                    }
                ),
            ]
        }
    )
    mismatches = checkpoint_intent_mismatches(reviewed_fill, [intent])
    assert [mismatch.kind for mismatch in mismatches] == [
        "template_fill_review_forbidden"
    ]
    apply_mismatches = checkpoint_intent_mismatches(
        reviewed_fill,
        [intent],
        enforce_unrequested_reviews=False,
    )
    assert [mismatch.kind for mismatch in apply_mismatches] == [
        "template_fill_review_forbidden"
    ]
    assert (
        checkpoint_intent_mismatches(
            projected,
            [intent],
            baseline_spec=reviewed_fill,
        )
        == ()
    )


# ── The reviewed structured result is the one reviewed JSON step ─────────


def _json_step(
    ref: str,
    *,
    reviewed_mode: FlowStepReviewMode | None = None,
    existing: bool = False,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
) -> StepSpec:
    return _text_step(
        ref,
        output_type=OutputType.JSON,
        output_mode=output_mode,
        existing_step_ref=ref if existing else None,
        reviewed_mode=reviewed_mode,
    )


def _spec(*steps: StepSpec) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(flow_name="Reviewed result", steps=list(steps))


def _kinds_and_refs(
    mismatches: tuple[CheckpointIntentMismatch, ...],
) -> set[tuple[str, str | None]]:
    return {(mismatch.kind, mismatch.step_ref) for mismatch in mismatches}


def _apply_and_critic_create_mismatches(
    spec: FlowDraftSpecCore, intents: list[CheckpointIntent]
) -> tuple[tuple[CheckpointIntentMismatch, ...], tuple[CheckpointIntentMismatch, ...]]:
    return (
        checkpoint_intent_mismatches(spec, intents),
        checkpoint_intent_mismatches(spec, intents, enforce_unrequested_reviews=False),
    )


def test_structured_checkpoint_binds_to_the_reviewed_earlier_result() -> None:
    """A later decision step does not displace the comparison under review."""

    spec = _spec(
        _json_step("comparison", reviewed_mode=FlowStepReviewMode.EDIT),
        _json_step("decision"),
        _text_step("letter", output_mode=OutputMode.COMPOSE_TEXT),
    )

    for mismatches in _apply_and_critic_create_mismatches(
        spec, [_set_structured_intent()]
    ):
        assert mismatches == ()


def test_structured_set_without_one_reviewed_result_is_unbound() -> None:
    unreviewed = _spec(_json_step("comparison"), _json_step("decision"))
    both_reviewed = _spec(
        _json_step("comparison", reviewed_mode=FlowStepReviewMode.EDIT),
        _json_step("decision", reviewed_mode=FlowStepReviewMode.EDIT),
    )

    for spec in (unreviewed, both_reviewed):
        for mismatches in _apply_and_critic_create_mismatches(
            spec, [_set_structured_intent()]
        ):
            unbound = {
                ref
                for kind, ref in _kinds_and_refs(mismatches)
                if kind == "producer_unbound"
            }
            assert unbound == {"comparison", "decision"}


def test_structured_set_on_the_only_json_step_still_needs_its_review() -> None:
    mismatches = checkpoint_intent_mismatches(
        _spec(_json_step("only"), _text_step("letter")),
        [_set_structured_intent()],
    )

    assert _kinds_and_refs(mismatches) == {("producer_unbound", "only")}
    no_json = checkpoint_intent_mismatches(
        _spec(_text_step("letter")), [_set_structured_intent()]
    )
    assert [mismatch.kind for mismatch in no_json] == ["producer_missing"]


def test_speaker_mapping_is_the_transcript_never_the_structured_result() -> None:
    def audio_spec(*, analysis_mode: FlowStepReviewMode | None) -> FlowDraftSpecCore:
        return _spec(
            _text_step("transcribe", output_mode=OutputMode.TRANSCRIBE_ONLY),
            _json_step(
                "speakers",
                output_mode=OutputMode.SPEAKER_MAPPING,
                reviewed_mode=FlowStepReviewMode.EDIT,
            ),
            _json_step("analysis", reviewed_mode=analysis_mode),
        )

    intent = _set_structured_intent()
    assert (
        checkpoint_intent_mismatches(
            audio_spec(analysis_mode=FlowStepReviewMode.EDIT),
            [intent],
            enforce_unrequested_reviews=False,
        )
        == ()
    )
    unbound = checkpoint_intent_mismatches(
        audio_spec(analysis_mode=None),
        [intent],
        enforce_unrequested_reviews=False,
    )
    assert _kinds_and_refs(unbound) == {("producer_unbound", "analysis")}


def test_projection_keeps_the_declared_result_and_never_picks_one() -> None:
    intent = _set_structured_intent()
    declared = _spec(
        _json_step("comparison", reviewed_mode=FlowStepReviewMode.EDIT),
        _json_step("decision"),
    )

    projected = project_checkpoint_intents(declared, [intent])
    assert [step.review_policy for step in projected.steps] == [
        FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT),
        None,
    ]
    assert checkpoint_intent_mismatches(projected, [intent]) == ()
    # Undeclared, even a single JSON step is assembly's to infer, not the
    # projection's.
    single = _spec(_json_step("only"), _text_step("letter"))
    assert project_checkpoint_intents(single, [intent]).steps[0].review_policy is None


def _saved_baseline(
    *,
    comparison: FlowStepReviewMode | None,
    decision: FlowStepReviewMode | None,
) -> FlowDraftSpecCore:
    return _spec(
        _json_step("comparison", reviewed_mode=comparison, existing=True),
        _json_step("decision", reviewed_mode=decision, existing=True),
        _text_step("letter", existing_step_ref="letter"),
    )


def test_edit_set_and_clear_act_on_the_saved_reviewed_result() -> None:
    """The saved review on an earlier step is the one set or clear changes."""

    baseline = _saved_baseline(comparison=FlowStepReviewMode.VIEW, decision=None)

    cleared = _saved_baseline(comparison=None, decision=None)
    assert (
        checkpoint_intent_mismatches(
            cleared, [_clear_structured_intent()], baseline_spec=baseline
        )
        == ()
    )
    kept = _saved_baseline(comparison=FlowStepReviewMode.VIEW, decision=None)
    assert _kinds_and_refs(
        checkpoint_intent_mismatches(
            kept, [_clear_structured_intent()], baseline_spec=baseline
        )
    ) == {("unexpected_review", "comparison")}

    made_editable = _saved_baseline(comparison=FlowStepReviewMode.EDIT, decision=None)
    assert (
        checkpoint_intent_mismatches(
            made_editable, [_set_structured_intent()], baseline_spec=baseline
        )
        == ()
    )
    second_review = _saved_baseline(
        comparison=FlowStepReviewMode.VIEW, decision=FlowStepReviewMode.EDIT
    )
    assert "producer_unbound" in {
        mismatch.kind
        for mismatch in checkpoint_intent_mismatches(
            second_review, [_set_structured_intent()], baseline_spec=baseline
        )
    }
    # Moving the saved review to another step was not requested.
    moved = _saved_baseline(comparison=None, decision=FlowStepReviewMode.EDIT)
    assert _kinds_and_refs(
        checkpoint_intent_mismatches(
            moved, [_set_structured_intent()], baseline_spec=baseline
        )
    ) == {("review_missing", "comparison")}


def test_several_saved_structured_reviews_are_kept_and_never_released() -> None:
    baseline = _saved_baseline(
        comparison=FlowStepReviewMode.VIEW, decision=FlowStepReviewMode.EDIT
    )

    # Edits that request no structured-result change keep every saved review.
    assert checkpoint_intent_mismatches(baseline, [], baseline_spec=baseline) == ()
    report_only = checkpoint_intent_mismatches(
        baseline, [_report_intent()], baseline_spec=baseline
    )
    assert not {
        mismatch.step_ref
        for mismatch in report_only
        if mismatch.step_ref in {"comparison", "decision"}
    }

    # The request path refuses such an edit first; the predicate itself
    # releases neither saved review, so removing one is never authorized.
    for intent in (_set_structured_intent(), _clear_structured_intent()):
        one_removed = _saved_baseline(comparison=None, decision=FlowStepReviewMode.EDIT)
        assert ("review_missing", "comparison") in _kinds_and_refs(
            checkpoint_intent_mismatches(one_removed, [intent], baseline_spec=baseline)
        )


def test_structured_intent_verdict_is_the_same_at_critic_and_apply() -> None:
    """The edit critic (with baseline) and edit apply (approved spec only)
    judge a structured-result intent by one predicate."""

    baseline = _saved_baseline(comparison=FlowStepReviewMode.VIEW, decision=None)
    cases = [
        (_clear_structured_intent(), _saved_baseline(comparison=None, decision=None)),
        (
            _clear_structured_intent(),
            _saved_baseline(comparison=FlowStepReviewMode.VIEW, decision=None),
        ),
        (
            _clear_structured_intent(),
            _saved_baseline(
                comparison=FlowStepReviewMode.VIEW, decision=FlowStepReviewMode.VIEW
            ),
        ),
        (
            _set_structured_intent(),
            _saved_baseline(comparison=FlowStepReviewMode.EDIT, decision=None),
        ),
        (
            _set_structured_intent(),
            _saved_baseline(
                comparison=FlowStepReviewMode.EDIT, decision=FlowStepReviewMode.EDIT
            ),
        ),
        (
            _set_structured_intent(),
            _saved_baseline(comparison=FlowStepReviewMode.VIEW, decision=None),
        ),
    ]

    def intent_verdict(
        mismatches: tuple[CheckpointIntentMismatch, ...],
    ) -> set[tuple[str, str | None]]:
        return {
            (mismatch.kind, mismatch.step_ref)
            for mismatch in mismatches
            if mismatch.producer_kind == "structured_result"
        }

    verdicts = []
    for intent, candidate in cases:
        critic = intent_verdict(
            checkpoint_intent_mismatches(candidate, [intent], baseline_spec=baseline)
        )
        apply = intent_verdict(
            checkpoint_intent_mismatches(
                candidate, [intent], enforce_unrequested_reviews=False
            )
        )
        assert critic == apply
        verdicts.append(bool(apply))
    assert verdicts == [False, True, True, False, True, True]

    # Only the critic reads the saved Flow, so only it sees a review moved off
    # the saved step; apply then re-checks the spec the critic approved.
    moved = _saved_baseline(comparison=None, decision=FlowStepReviewMode.EDIT)
    assert checkpoint_intent_mismatches(
        moved, [_set_structured_intent()], baseline_spec=baseline
    )
    assert (
        checkpoint_intent_mismatches(
            moved, [_set_structured_intent()], enforce_unrequested_reviews=False
        )
        == ()
    )

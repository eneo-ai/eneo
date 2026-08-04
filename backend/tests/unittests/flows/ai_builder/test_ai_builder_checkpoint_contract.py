"""Producer-resolution behavior of the canonical checkpoint predicate."""

from eneo.flows.ai_builder.ai_builder_checkpoint_contract import (
    checkpoint_intent_mismatches,
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
        producer_kind="structured_result",
        operation="clear",
        mode=None,
        confidence="high",
        evidence=["quote:user_message:1:Remove the JSON approval."],
    )


def _set_structured_intent() -> CheckpointIntent:
    return CheckpointIntent(
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


def test_set_relocation_releases_the_former_baseline_producer() -> None:
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

    def proposed(*, old_reviewed: bool, new_reviewed: bool) -> FlowDraftSpecCore:
        return FlowDraftSpecCore(
            flow_name="Relocated producer",
            steps=[
                _text_step(
                    "existing-1",
                    output_type=OutputType.JSON,
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

    clean = checkpoint_intent_mismatches(
        proposed(old_reviewed=False, new_reviewed=True),
        [_set_structured_intent()],
        baseline_spec=baseline,
    )
    assert clean == ()

    duplicate = checkpoint_intent_mismatches(
        proposed(old_reviewed=True, new_reviewed=True),
        [_set_structured_intent()],
        baseline_spec=baseline,
    )
    assert {mismatch.kind for mismatch in duplicate} == {"unexpected_review"}


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

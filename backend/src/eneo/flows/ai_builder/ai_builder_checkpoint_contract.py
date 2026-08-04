"""Canonical requested-versus-compiled checkpoint predicate.

Producer resolution contract: each ``CheckpointProducerKind`` names the
TERMINAL eligible producer of that kind in the compiled spec — the last JSON
step for ``structured_result`` and the last referenced body-writer (else last
compose/pass-through text step) for ``report_text``. ``transcript`` requires
exactly one backend-inserted transcription step; any other transcript topology
is a planning/architecture contradiction, not a repairable plan defect.

Create compilation projects intents onto those producers and strips every
model-authored review policy first, so typed intents are the only checkpoint
owner on create.

Edit contract: the existing Flow's step review policies are the preserved
baseline, and typed ``set``/``clear`` intents are the only authorized changes.
An intent overrides the baseline checkpoint of its producer kind on BOTH
sides — the baseline producer's old expectation is released (so a producer
that changes type, moves, or disappears does not pin its stale review) and
the candidate producer carries the requested mode (``set``) or no review
(``clear``). Every other step must keep exactly its baseline review. The
baseline is the canonical Flow authoring snapshot
(``current_flow_authoring_spec``), which reconstructs document body-writer
identity, so baseline and candidate producer resolution share one owner.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from eneo.flows.ai_builder.planning_state import (
    CheckpointIntent,
    CheckpointProducerKind,
)
from eneo.flows.application.flow_authoring_snapshot import (
    current_flow_authoring_spec,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy

if TYPE_CHECKING:
    from eneo.flows.domain.flow import FlowStep

CheckpointMismatchKind = Literal[
    "producer_missing",
    "review_missing",
    "review_mode_mismatch",
    "template_fill_review_forbidden",
    "unexpected_review",
]


@dataclass(frozen=True, slots=True)
class CheckpointIntentMismatch:
    kind: CheckpointMismatchKind
    producer_kind: CheckpointProducerKind | None
    step_ref: str | None
    expected_mode: FlowStepReviewMode | None
    actual_mode: FlowStepReviewMode | None


def project_checkpoint_intents(
    spec: FlowDraftSpecCore,
    checkpoint_intents: Sequence[CheckpointIntent],
) -> FlowDraftSpecCore:
    """Compile typed checkpoint intent onto the actual Flow-step producers."""

    expected_by_step_ref = _expected_checkpoints_by_step_ref(
        spec,
        checkpoint_intents,
    )
    projected_steps: list[StepSpec] = []
    changed = False
    for step in spec.steps:
        expected = expected_by_step_ref.get(step.plan_step_ref)
        review_policy = (
            FlowStepReviewPolicy(mode=expected.mode)
            if expected is not None and expected.mode is not None
            else None
        )
        if step.review_policy == review_policy:
            projected_steps.append(step)
            continue
        projected_steps.append(step.model_copy(update={"review_policy": review_policy}))
        changed = True
    if not changed:
        return spec
    return spec.model_copy(update={"steps": projected_steps})


def checkpoint_intent_mismatches(
    spec: FlowDraftSpecCore,
    checkpoint_intents: Sequence[CheckpointIntent],
    *,
    baseline_spec: FlowDraftSpecCore | None = None,
    enforce_unrequested_reviews: bool = True,
) -> tuple[CheckpointIntentMismatch, ...]:
    """Return exact requested-versus-compiled checkpoint differences.

    Create lane (no baseline): the intent snapshot is the complete contract —
    every ``set`` intent must land on its producer and no other step may carry
    a review.

    Edit lane with ``baseline_spec`` (the existing Flow's canonical authoring
    snapshot, body-writer identity included): a step's expected mode is the
    ``set``/``clear`` intent on its resolved producer, else its preserved
    baseline mode, else none. Each intent also releases its producer kind's
    BASELINE checkpoint, so an explicit change survives a producer that was
    retyped, relocated, or removed by the same edit. This enforces all four
    edit cases: unchanged-preserved, set-applied, clear-removed, and
    unsolicited change rejected.

    Edit apply passes ``enforce_unrequested_reviews=False`` without a
    baseline: requested intents are re-checked against the approved spec, and
    non-requested reviews are the critic-approved preserved state.
    """

    mismatches: list[CheckpointIntentMismatch] = []
    baseline_modes: dict[str, FlowStepReviewMode] = {}
    if baseline_spec is not None:
        baseline_modes = {
            (step.existing_step_ref or step.plan_step_ref): step.review_policy.mode
            for step in baseline_spec.steps
            if step.review_policy is not None
            and step.output_mode != OutputMode.TEMPLATE_FILL
        }

    expected_by_step_ref: dict[str, CheckpointIntent] = {}
    for intent in checkpoint_intents:
        if baseline_spec is not None:
            baseline_producer = _checkpoint_producer_step(
                baseline_spec,
                intent.producer_kind,
            )
            if baseline_producer is not None:
                baseline_modes.pop(
                    baseline_producer.existing_step_ref
                    or baseline_producer.plan_step_ref,
                    None,
                )
        producer = _checkpoint_producer_step(spec, intent.producer_kind)
        if producer is None:
            if intent.operation == "set":
                mismatches.append(
                    CheckpointIntentMismatch(
                        kind="producer_missing",
                        producer_kind=intent.producer_kind,
                        step_ref=None,
                        expected_mode=intent.mode,
                        actual_mode=None,
                    )
                )
            # A clear intent without a candidate producer has nothing left to
            # remove; its baseline expectation was already released above.
            continue
        expected_by_step_ref[producer.plan_step_ref] = intent

    for step in spec.steps:
        intent = expected_by_step_ref.get(step.plan_step_ref)
        actual_mode = (
            step.review_policy.mode if step.review_policy is not None else None
        )
        if step.output_mode == OutputMode.TEMPLATE_FILL and actual_mode is not None:
            mismatches.append(
                CheckpointIntentMismatch(
                    kind="template_fill_review_forbidden",
                    producer_kind=None,
                    step_ref=step.plan_step_ref,
                    expected_mode=None,
                    actual_mode=actual_mode,
                )
            )
            continue
        if intent is not None:
            expected_mode = intent.mode
            producer_kind: CheckpointProducerKind | None = intent.producer_kind
        elif (
            step.existing_step_ref is not None
            and step.existing_step_ref in baseline_modes
        ):
            expected_mode = baseline_modes[step.existing_step_ref]
            producer_kind = None
        else:
            expected_mode = None
            producer_kind = None
            if (
                actual_mode is not None
                and baseline_spec is None
                and not enforce_unrequested_reviews
            ):
                continue
        if actual_mode == expected_mode:
            continue
        if expected_mode is None:
            mismatches.append(
                CheckpointIntentMismatch(
                    kind="unexpected_review",
                    producer_kind=producer_kind,
                    step_ref=step.plan_step_ref,
                    expected_mode=None,
                    actual_mode=actual_mode,
                )
            )
        elif actual_mode is None:
            mismatches.append(
                CheckpointIntentMismatch(
                    kind="review_missing",
                    producer_kind=producer_kind,
                    step_ref=step.plan_step_ref,
                    expected_mode=expected_mode,
                    actual_mode=None,
                )
            )
        else:
            mismatches.append(
                CheckpointIntentMismatch(
                    kind="review_mode_mismatch",
                    producer_kind=producer_kind,
                    step_ref=step.plan_step_ref,
                    expected_mode=expected_mode,
                    actual_mode=actual_mode,
                )
            )
    return tuple(mismatches)


def baseline_spec_from_flow_steps(
    steps: Sequence["FlowStep"],
) -> FlowDraftSpecCore:
    """The existing Flow's canonical snapshot as the edit lane's baseline."""

    return current_flow_authoring_spec(
        current_steps=list(steps),
        flow_name="baseline",
        flow_description=None,
        assistant_snapshots=None,
    )


def _expected_checkpoints_by_step_ref(
    spec: FlowDraftSpecCore,
    checkpoint_intents: Sequence[CheckpointIntent],
) -> dict[str, CheckpointIntent]:
    expected: dict[str, CheckpointIntent] = {}
    for intent in checkpoint_intents:
        if intent.operation != "set":
            continue
        producer = _checkpoint_producer_step(spec, intent.producer_kind)
        if producer is not None:
            expected[producer.plan_step_ref] = intent
    return expected


def _checkpoint_producer_step(
    spec: FlowDraftSpecCore,
    producer_kind: CheckpointProducerKind,
) -> StepSpec | None:
    if producer_kind == "transcript":
        producers = [
            step
            for step in spec.steps
            if step.output_mode == OutputMode.TRANSCRIBE_ONLY
        ]
        return producers[0] if len(producers) == 1 else None
    if producer_kind == "structured_result":
        return next(
            (
                step
                for step in reversed(spec.steps)
                if step.output_type == OutputType.JSON
            ),
            None,
        )

    body_writer_refs = set(spec.document_body_writer_step_refs or ())
    if body_writer_refs:
        return next(
            (
                step
                for step in reversed(spec.steps)
                if step.plan_step_ref in body_writer_refs
                and step.output_type == OutputType.TEXT
            ),
            None,
        )
    return next(
        (
            step
            for step in reversed(spec.steps)
            if step.output_type == OutputType.TEXT
            and step.output_mode
            in {
                OutputMode.PASS_THROUGH,
                OutputMode.COMPOSE_TEXT,
            }
        ),
        None,
    )

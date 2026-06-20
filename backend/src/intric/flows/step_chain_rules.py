from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, Sequence

from intric.flows.domain.flow_step_validation import FlowGraphIssueCode


class StepChainShape(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def input_source(self) -> str: ...

    @property
    def input_type(self) -> str: ...

    @property
    def output_type(self) -> str: ...


@dataclass(frozen=True)
class StepChainViolation:
    step_order: int
    message: str
    code: FlowGraphIssueCode


COMPATIBLE_TYPE_COERCIONS = {
    ("text", "text"),
    ("text", "json"),
    ("text", "any"),
    ("json", "text"),
    ("json", "json"),
    ("json", "any"),
    ("pdf", "text"),
    ("pdf", "any"),
    ("docx", "text"),
    ("docx", "any"),
}


def find_first_step_chain_violation(
    steps: Sequence[StepChainShape],
) -> StepChainViolation | None:
    return next(iter_step_chain_violations(steps), None)


def iter_step_chain_violations(
    steps: Sequence[StepChainShape],
) -> Iterator[StepChainViolation]:
    if not steps:
        return

    sorted_steps = sorted(steps, key=lambda item: item.step_order)
    steps_by_order = {item.step_order: item for item in sorted_steps}
    flow_input_steps = [
        step for step in sorted_steps if step.input_source == "flow_input"
    ]

    if len(flow_input_steps) > 1:
        extra_step = flow_input_steps[1]
        yield StepChainViolation(
            step_order=extra_step.step_order,
            message="Only one step may use input_source 'flow_input'.",
            code=FlowGraphIssueCode.TYPED_IO_MULTIPLE_FLOW_INPUT_STEPS,
        )
        first_global_yielded = True
    else:
        first_global_yielded = False

    if (
        not first_global_yielded
        and flow_input_steps
        and flow_input_steps[0].step_order != 1
    ):
        flow_input_step = flow_input_steps[0]
        yield StepChainViolation(
            step_order=flow_input_step.step_order,
            message="input_source 'flow_input' must be step 1 if present.",
            code=FlowGraphIssueCode.TYPED_IO_FLOW_INPUT_POSITION_INVALID,
        )
        first_global_yielded = True

    for step in sorted_steps:
        if not first_global_yielded:
            violation = _first_global_step_chain_violation(step)
            if violation is not None:
                yield violation
                first_global_yielded = True

        if step.input_source == "previous_step" and step.step_order > 1:
            previous = steps_by_order.get(step.step_order - 1)
            if previous is None:
                if not first_global_yielded:
                    yield StepChainViolation(
                        step_order=step.step_order,
                        message=(
                            f"Step {step.step_order}: input_source 'previous_step' requires step "
                            f"{step.step_order - 1} to exist."
                        ),
                        code=FlowGraphIssueCode.TYPED_IO_MISSING_PREVIOUS_STEP,
                    )
                    first_global_yielded = True
                continue
            if (previous.output_type, step.input_type) not in COMPATIBLE_TYPE_COERCIONS:
                yield StepChainViolation(
                    step_order=step.step_order,
                    message=(
                        f"Step {step.step_order}: incompatible type chain — previous step output_type "
                        f"'{previous.output_type}' cannot feed input_type '{step.input_type}'."
                    ),
                    code=FlowGraphIssueCode.TYPED_IO_INCOMPATIBLE_TYPE_CHAIN,
                )


def _first_global_step_chain_violation(
    step: StepChainShape,
) -> StepChainViolation | None:
    if step.step_order == 1 and step.input_source in {
        "previous_step",
        "all_previous_steps",
    }:
        return StepChainViolation(
            step_order=step.step_order,
            message="Step 1 cannot use previous_step/all_previous_steps input source. Use flow_input.",
            code=FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_POSITION,
        )
    if step.input_type == "document" and step.input_source != "flow_input":
        return StepChainViolation(
            step_order=step.step_order,
            message=(
                f"Step {step.step_order}: input_type 'document' is only supported with input_source "
                f"'flow_input'."
            ),
            code=FlowGraphIssueCode.TYPED_IO_DOCUMENT_SOURCE_UNSUPPORTED,
        )
    if step.input_type == "audio" and step.input_source != "flow_input":
        return StepChainViolation(
            step_order=step.step_order,
            message=(
                f"Step {step.step_order}: input_type 'audio' is only supported with input_source "
                f"'flow_input'."
            ),
            code=FlowGraphIssueCode.TYPED_IO_AUDIO_SOURCE_UNSUPPORTED,
        )
    if step.input_type == "file" and step.input_source != "flow_input":
        return StepChainViolation(
            step_order=step.step_order,
            message=(
                f"Step {step.step_order}: input_type 'file' is only supported with input_source "
                f"'flow_input'."
            ),
            code=FlowGraphIssueCode.TYPED_IO_FILE_SOURCE_UNSUPPORTED,
        )
    if step.input_type == "json" and step.input_source == "all_previous_steps":
        return StepChainViolation(
            step_order=step.step_order,
            message=(
                f"Step {step.step_order}: input_type 'json' is incompatible with input_source "
                f"'all_previous_steps' (concatenated text is not valid JSON)."
            ),
            code=FlowGraphIssueCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION,
        )
    return None

"""Which steps of a flow are its run's deliverables.

One rule over the facts every kind of step holds, so publishing (a draft's
``FlowStep``) and the run contract (a published ``RuntimeStep``) cannot choose
differently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eneo.flows.enums import FlowOutputMode, FlowOutputType, step_can_be_deliverable


@dataclass(frozen=True, slots=True)
class StepDeliverableFacts:
    """What the rule reads of one step."""

    output_type: FlowOutputType | str
    output_mode: FlowOutputMode | str
    # The author marked the step as a deliverable.
    marked: bool
    # The step sends the run's finished result once the run has completed.
    sends_run_result: bool = False


def deliverable_positions(steps: Sequence[StepDeliverableFacts]) -> list[int]:
    """The positions in ``steps``, which are in step order, of the steps a
    run delivers: each marked step and the last step, when its text or
    document can be delivered. A last step that sends the run's result holds
    nothing of its own, so the step before it stands in its place."""
    last = len(steps) - 1
    if last >= 0 and steps[last].sends_run_result:
        last -= 1
    return [
        position
        for position, step in enumerate(steps)
        if (step.marked or position == last)
        and step_can_be_deliverable(
            output_type=step.output_type, output_mode=step.output_mode
        )
    ]

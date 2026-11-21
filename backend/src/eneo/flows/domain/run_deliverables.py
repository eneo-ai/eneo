"""Which steps of a flow are its run's deliverables.

One rule over the facts every kind of step holds, so publishing (a draft's
``FlowStep``) and the run contract (a published ``RuntimeStep``) cannot choose
differently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eneo.flows.enums import FlowOutputMode, FlowOutputType, step_delivers_artifact


@dataclass(frozen=True, slots=True)
class StepDeliverableFacts:
    """What the rule reads of one step."""

    output_type: FlowOutputType | str
    output_mode: FlowOutputMode | str
    # The author marked the step as a deliverable.
    marked: bool


def deliverable_positions(steps: Sequence[StepDeliverableFacts]) -> list[int]:
    """The positions in ``steps``, which are in step order, of the steps a
    run delivers: each marked step and the last step, when it delivers a
    document."""
    last = len(steps) - 1
    return [
        position
        for position, step in enumerate(steps)
        if (step.marked or position == last)
        and step_delivers_artifact(
            output_type=step.output_type, output_mode=step.output_mode
        )
    ]

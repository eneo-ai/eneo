from __future__ import annotations

from dataclasses import dataclass

from intric.flows.step_chain_rules import find_first_step_chain_violation


@dataclass(frozen=True)
class _Step:
    step_order: int
    input_source: str = "flow_input"
    input_type: str = "text"
    output_type: str = "text"


def test_rejects_missing_previous_step_for_previous_step_source() -> None:
    violation = find_first_step_chain_violation(
        [
            _Step(step_order=1, input_source="flow_input"),
            _Step(step_order=3, input_source="previous_step", input_type="text"),
        ]
    )

    assert violation is not None
    assert violation.code == "typed_io_missing_previous_step"


from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.step_chain_rules import find_first_step_chain_violation


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


def test_accepts_docx_to_text_previous_step_chain() -> None:
    violation = find_first_step_chain_violation(
        [
            _Step(step_order=1, output_type="docx"),
            _Step(step_order=2, input_source="previous_step", input_type="text"),
        ]
    )

    assert violation is None


def test_accepts_text_to_json_previous_step_chain() -> None:
    violation = find_first_step_chain_violation(
        [
            _Step(step_order=1, output_type="text"),
            _Step(step_order=2, input_source="previous_step", input_type="json"),
        ]
    )

    assert violation is None


def test_rejects_incompatible_previous_step_chain() -> None:
    violation = find_first_step_chain_violation(
        [
            _Step(step_order=1, output_type="docx"),
            _Step(step_order=2, input_source="previous_step", input_type="json"),
        ]
    )

    assert violation is not None
    assert violation.code == "typed_io_incompatible_type_chain"


def test_rejects_unknown_previous_step_output_type() -> None:
    violation = find_first_step_chain_violation(
        [
            _Step(step_order=1, output_type="spreadsheet"),
            _Step(step_order=2, input_source="previous_step", input_type="text"),
        ]
    )

    assert violation is not None
    assert violation.code == "typed_io_incompatible_type_chain"


def test_rejects_unknown_previous_step_input_type() -> None:
    violation = find_first_step_chain_violation(
        [
            _Step(step_order=1, output_type="text"),
            _Step(step_order=2, input_source="previous_step", input_type="spreadsheet"),
        ]
    )

    assert violation is not None
    assert violation.code == "typed_io_incompatible_type_chain"

from __future__ import annotations

from eneo.flows.flow_variable_definitions import PRIMARY_FLOW_INPUT_KEYS
from eneo.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
    consumes_runtime_input,
    referenced_form_fields,
)


def test_consumes_runtime_input_only_for_real_template_expression() -> None:
    refs = analyze_template(
        "Literal step_input.text marker only",
        step_refs={},
        form_field_names=set(),
    )

    assert consumes_runtime_input(refs) is False


def test_consumes_runtime_input_for_step_input_expression() -> None:
    refs = analyze_template(
        "Underlag: {{ step_input.text }}",
        step_refs={},
        form_field_names=set(),
    )

    assert consumes_runtime_input(refs) is True
    assert refs[0].kind is TemplateReferenceKind.RUNTIME


def test_flow_input_path_counts_as_declared_form_field_reference() -> None:
    refs = analyze_template(
        (
            "Case: {{ flow_input.case_id }}, raw input {{ flow_input.text }}, "
            "and complete input {{ flow_input }}"
        ),
        step_refs={},
        form_field_names={"case_id"},
    )

    assert refs[0].kind is TemplateReferenceKind.RUNTIME
    assert refs[0].head == "flow_input"
    assert refs[0].form_field_name == "case_id"
    assert refs[1].kind is TemplateReferenceKind.RUNTIME
    assert refs[2].kind is TemplateReferenceKind.RUNTIME
    assert all(reference.path_error_code is None for reference in refs)
    assert referenced_form_fields(refs) == {"case_id"}


def test_marks_unknown_flow_input_key_as_invalid_runtime_reference() -> None:
    refs = analyze_template(
        "Unknown: {{ flow_input.case_identifier }}",
        step_refs={},
        form_field_names={"case_id"},
    )

    assert refs[0].kind is TemplateReferenceKind.RUNTIME
    assert refs[0].path_error_code == "unknown_flow_input_key"
    assert refs[0].path_error_context == {
        "known_keys": tuple(sorted({*PRIMARY_FLOW_INPUT_KEYS, "case_id"}))
    }


def test_marks_scalar_runtime_tail_as_invalid() -> None:
    refs = analyze_template(
        "Today: {{ datum.year }}",
        step_refs={},
        form_field_names=set(),
    )

    assert refs[0].path_error_code == "runtime_scalar_nested_access"


def test_marks_unknown_step_input_key_as_invalid() -> None:
    refs = analyze_template(
        "Unknown: {{ step_input.nonexistent }}",
        step_refs={},
        form_field_names=set(),
    )

    assert refs[0].path_error_code == "unknown_step_input_key"


def test_validates_sequence_indexes_for_step_input_file_ids() -> None:
    refs = analyze_template(
        "{{ step_input.file_ids.first }} and {{ step_input.file_ids.0 }}",
        step_refs={},
        form_field_names=set(),
    )

    assert refs[0].path_error_code == "runtime_sequence_non_numeric_index"
    assert refs[1].path_error_code is None

from __future__ import annotations

from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
    consumes_runtime_input,
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


def test_validates_sequence_indexes_for_runtime_variables() -> None:
    refs = analyze_template(
        "{{ indata_filer.first }} and {{ indata_filer.0 }}",
        step_refs={},
        form_field_names=set(),
    )

    assert refs[0].path_error_code == "runtime_sequence_non_numeric_index"
    assert refs[1].path_error_code is None

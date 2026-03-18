from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from intric.flows.flow_variable_definitions import (
    RESERVED_RUNTIME_VARIABLES,
    STEP_INPUT_KEY_SHAPES,
    VariableShape,
    runtime_variable_shape,
    step_input_key_shape,
)
from intric.flows.variable_resolver import iter_template_expressions


class TemplateReferenceKind(str, Enum):
    STEP = "step"
    FORM_FIELD = "form_field"
    RUNTIME = "runtime"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TemplateReference:
    expression: str
    head: str
    tail: str
    kind: TemplateReferenceKind
    step_ref: str | None = None
    step_order: int | None = None
    structured_path: tuple[str, ...] | None = None
    path_error_code: str | None = None
    path_error_context: dict[str, object] | None = None


def analyze_template(
    template: str,
    *,
    step_refs: dict[str, int],
    form_field_names: set[str],
) -> list[TemplateReference]:
    references: list[TemplateReference] = []
    for expression in iter_template_expressions(template):
        references.append(
            _analyze_expression(
                expression=expression,
                step_refs=step_refs,
                form_field_names=form_field_names,
            )
        )
    return references


def consumes_runtime_input(references: list[TemplateReference]) -> bool:
    return any(
        reference.head == "step_input"
        and bool(reference.tail)
        and reference.path_error_code is None
        for reference in references
    )


def referenced_step_refs(references: list[TemplateReference]) -> set[str]:
    return {
        reference.step_ref or reference.head
        for reference in references
        if reference.kind is TemplateReferenceKind.STEP
    }


def referenced_form_fields(references: list[TemplateReference]) -> set[str]:
    return {
        reference.head
        for reference in references
        if reference.kind is TemplateReferenceKind.FORM_FIELD
    }


def _analyze_expression(
    *,
    expression: str,
    step_refs: dict[str, int],
    form_field_names: set[str],
) -> TemplateReference:
    if "." in expression:
        raw_head, raw_tail = expression.split(".", maxsplit=1)
    else:
        raw_head, raw_tail = expression, ""
    head = raw_head.strip()
    tail = raw_tail.strip()

    if head in step_refs:
        return _build_step_reference(
            expression=expression,
            head=head,
            tail=tail,
            step_ref=head,
            step_order=step_refs[head],
        )
    if head in RESERVED_RUNTIME_VARIABLES:
        return _build_runtime_reference(
            expression=expression,
            head=head,
            tail=tail,
        )
    if head.startswith("step_"):
        step_order = _runtime_step_order(head)
        if step_order is not None:
            return _build_step_reference(
                expression=expression,
                head=head,
                tail=tail,
                step_ref=head,
                step_order=step_order,
            )
        return TemplateReference(
            expression=expression,
            head=head,
            tail=tail,
            kind=TemplateReferenceKind.STEP,
            path_error_code="invalid_step_reference_format",
        )
    if head in form_field_names:
        return TemplateReference(
            expression=expression,
            head=head,
            tail=tail,
            kind=TemplateReferenceKind.FORM_FIELD,
        )
    return TemplateReference(
        expression=expression,
        head=head,
        tail=tail,
        kind=TemplateReferenceKind.UNKNOWN,
    )


def _build_step_reference(
    *,
    expression: str,
    head: str,
    tail: str,
    step_ref: str,
    step_order: int,
) -> TemplateReference:
    structured_path: tuple[str, ...] | None = None
    if tail.startswith("output.structured."):
        structured_path = tuple(
            part for part in tail.removeprefix("output.structured.").split(".") if part
        )
    return TemplateReference(
        expression=expression,
        head=head,
        tail=tail,
        kind=TemplateReferenceKind.STEP,
        step_ref=step_ref,
        step_order=step_order,
        structured_path=structured_path,
    )


def _build_runtime_reference(
    *,
    expression: str,
    head: str,
    tail: str,
) -> TemplateReference:
    path_error_code: str | None = None
    path_error_context: dict[str, object] | None = None
    root_shape = runtime_variable_shape(head)
    if head == "step_input":
        path_error_code, path_error_context = _validate_step_input_path(tail)
    elif root_shape is VariableShape.SCALAR and tail:
        path_error_code = "runtime_scalar_nested_access"
        path_error_context = {"shape": root_shape.value}
    elif root_shape is VariableShape.SEQUENCE and tail:
        path_error_code, path_error_context = _validate_sequence_tail(tail)

    return TemplateReference(
        expression=expression,
        head=head,
        tail=tail,
        kind=TemplateReferenceKind.RUNTIME,
        path_error_code=path_error_code,
        path_error_context=path_error_context,
    )


def _validate_step_input_path(tail: str) -> tuple[str | None, dict[str, object] | None]:
    if not tail:
        return "step_input_key_required", None
    segments = [part for part in tail.split(".") if part]
    key = segments[0]
    key_shape = step_input_key_shape(key)
    if key_shape is None:
        return (
            "unknown_step_input_key",
            {"known_keys": tuple(STEP_INPUT_KEY_SHAPES.keys())},
        )
    remainder = segments[1:]
    if not remainder:
        return None, None
    if key_shape is VariableShape.SCALAR:
        return "runtime_scalar_nested_access", {"shape": key_shape.value}
    if key_shape is VariableShape.SEQUENCE:
        return _validate_sequence_segments(remainder)
    return None, None


def _validate_sequence_tail(tail: str) -> tuple[str | None, dict[str, object] | None]:
    segments = [part for part in tail.split(".") if part]
    return _validate_sequence_segments(segments)


def _validate_sequence_segments(
    segments: list[str],
) -> tuple[str | None, dict[str, object] | None]:
    if not segments:
        return None, None
    first = segments[0]
    if not first.isdigit():
        return "runtime_sequence_non_numeric_index", None
    if len(segments) > 1:
        return "runtime_scalar_nested_access", {"shape": VariableShape.SCALAR.value}
    return None, None


def _runtime_step_order(head: str) -> int | None:
    raw_index = head.removeprefix("step_")
    if raw_index.isdigit():
        return int(raw_index)
    return None

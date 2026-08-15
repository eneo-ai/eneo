"""Strict admission for proposal ``output_fields``.

The propose/edit tool contract requires an array of complete field objects
with a closed type enum, and ``StructuredFieldDraft`` is the canonical
typed form of that contract. Admission delegates to it: a payload is either
preserved losslessly or the whole list is rejected with repairable feedback
naming the first decisive error. Nothing is invented (no ``field_N``
names), downgraded (no unknown-type or over-depth coercion to string), or
partially retained — silent lossy coercion is what turned a valid live
proposal into an unwinnable repair loop.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft

_REJECTION_SUFFIX = (
    "No output_fields were accepted. "
    "Resend the complete output_fields list using the declared tool shape."
)


class StructuredFieldAdmissionError(ValueError):
    """One decisive, model-repairable admission failure."""

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"{path}: {detail} {_REJECTION_SUFFIX}")


def normalize_structured_field_list(
    value: Any,
    *,
    path: str = "output_fields",
) -> list[dict[str, Any]] | None:
    """Admit a complete field list losslessly or reject it whole."""

    if value is None:
        return None
    if not isinstance(value, list):
        raise StructuredFieldAdmissionError(
            path,
            "must be an array of field objects.",
        )
    items = cast(list[Any], value)
    if not items:
        # An explicit empty list is a statement ("no structured fields"),
        # not lost content.
        return None
    return [
        _admit_structured_field_item(item, path=f"{path}[{index}]")
        for index, item in enumerate(items)
    ]


def _admit_structured_field_item(value: Any, *, path: str) -> dict[str, Any]:
    if isinstance(value, StructuredFieldDraft):
        draft = value
    elif isinstance(value, dict):
        raw_item = cast(dict[str, Any], value)
        try:
            draft = StructuredFieldDraft.model_validate(raw_item)
        except ValidationError as error:
            raise StructuredFieldAdmissionError(
                _admission_error_path(path, error),
                _admission_error_detail(error),
            ) from error
    else:
        raise StructuredFieldAdmissionError(
            path,
            "must be a field object with name, field_type, and description.",
        )
    return draft.model_dump()


def _admission_error_path(path: str, error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(
        str(part) for part in first.get("loc", ()) if not isinstance(part, int)
    )
    return f"{path}.{location}" if location else path


def _admission_error_detail(error: ValidationError) -> str:
    first = error.errors()[0]
    message = str(first.get("msg", "is invalid"))
    return f"{message.removeprefix('Value error, ').rstrip('.')}."


__all__ = [
    "StructuredFieldAdmissionError",
    "normalize_structured_field_list",
]

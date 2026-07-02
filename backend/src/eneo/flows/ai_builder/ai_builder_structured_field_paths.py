from __future__ import annotations

from typing import Sequence, cast

from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft


def missing_draft_field_path(
    fields: Sequence[StructuredFieldDraft],
    field_path: str,
) -> str | None:
    """Return the first missing segment of a draft field path, or None if valid.

    A path that ends on an array field is accepted: the runtime resolver
    returns the whole list and stringifies it. A path that traverses past
    an array without a numeric index (e.g. ``risker.rubrik``) is rejected,
    matching the runtime template resolver's required-index branch.
    """

    current_fields: Sequence[StructuredFieldDraft] = fields
    current_field: StructuredFieldDraft | None = None
    traversed: list[str] = []
    expecting_index = False

    for segment in field_path.split("."):
        traversed.append(segment)
        if expecting_index:
            if not segment.isdigit():
                return ".".join(traversed)
            if current_field is None:
                return ".".join(traversed)
            item_fields = cast(
                list[StructuredFieldDraft] | None,
                current_field.item_fields,
            )
            if item_fields is None:
                return ".".join(traversed)
            current_fields = item_fields
            expecting_index = False
            continue

        current_field = _find_field(current_fields, segment)
        if current_field is None:
            return ".".join(traversed)

        if current_field.field_type == "array":
            expecting_index = True
        else:
            nested_fields = cast(
                list[StructuredFieldDraft] | None,
                current_field.fields,
            )
            if nested_fields is not None:
                current_fields = nested_fields
            else:
                current_fields = []

    return None


def _find_field(
    fields: Sequence[StructuredFieldDraft],
    name: str,
) -> StructuredFieldDraft | None:
    for field in fields:
        if field.name == name:
            return field
    return None

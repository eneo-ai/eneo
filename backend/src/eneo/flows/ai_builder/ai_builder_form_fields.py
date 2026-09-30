from __future__ import annotations

from typing import Any, cast

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_spec import FormFieldSpec, authoring_form_field
from eneo.flows.flow_metadata import form_fields_in_display_order


def extract_form_fields_from_metadata(
    metadata_json: dict[str, Any] | None,
) -> list[FormFieldSpec] | None:
    if not isinstance(metadata_json, dict):
        return None
    form_schema = metadata_json.get("form_schema")
    if not isinstance(form_schema, dict):
        return None
    raw_fields = cast(dict[str, Any], form_schema).get("fields")
    if not isinstance(raw_fields, list):
        return None
    saved: list[FlowPersistedJsonObject] = []
    saved_index: dict[int, int] = {}
    for index, field in enumerate(cast(list[object], raw_fields)):
        if isinstance(field, dict):
            entry = cast(FlowPersistedJsonObject, field)
            saved.append(entry)
            saved_index[id(entry)] = index
    fields = [
        spec
        for field in form_fields_in_display_order(saved)
        if (spec := authoring_form_field(field, index=saved_index[id(field)]))
        is not None
    ]
    return fields or None

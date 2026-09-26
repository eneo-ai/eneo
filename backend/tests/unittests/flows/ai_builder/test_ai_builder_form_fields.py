from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_edit_compiler import build_form_field_changes
from eneo.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from eneo.flows.flow_authoring_spec import FormFieldSpec


def test_the_builder_reads_saved_fields_as_the_editor_shows_them() -> None:
    fields = extract_form_fields_from_metadata(
        {
            "form_schema": {
                "fields": [
                    {"name": "second", "type": "text", "label": "Second", "order": 2},
                    {"name": "first", "type": "text", "label": None, "order": 1},
                ]
            }
        }
    )

    assert fields is not None
    assert [(field.name, field.label) for field in fields] == [
        ("first", "first"),
        ("second", "Second"),
    ]


def _field(name: str) -> FormFieldSpec:
    return FormFieldSpec(name=name, type="text", label=name.title())


def test_a_moved_field_is_a_change_the_preview_shows() -> None:
    changes = build_form_field_changes(
        [_field("a"), _field("b"), _field("c")],
        [_field("b"), _field("a"), _field("c")],
    )

    assert [(c.kind, c.field_name, c.details) for c in changes] == [
        ("modified", "b", "moved"),
        ("modified", "a", "moved"),
    ]


def test_a_field_that_moved_and_changed_shows_both() -> None:
    relabelled = FormFieldSpec(name="a", type="text", label="Ärende")

    changes = build_form_field_changes(
        [_field("a"), _field("b")], [_field("b"), relabelled]
    )

    assert [(c.kind, c.field_name, c.details) for c in changes] == [
        ("modified", "b", "moved"),
        ("modified", "a", None),
        ("modified", "a", "moved"),
    ]

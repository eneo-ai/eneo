"""Which saved form field types an authoring edit stores as saved."""

from __future__ import annotations

import pytest

from eneo.flows.application.flow_service import _with_saved_form_fields
from eneo.flows.flow_metadata import normalize_flow_metadata_for_write

_SAVED = {
    "form_schema": {
        "fields": [
            {
                "name": "epost",
                "type": "email",
                "label": "E-post",
                "required": True,
                "order": 1,
            },
            {"name": "namn", "type": "string", "label": "Namn", "order": 2},
            {"name": "info", "type": "textarea", "label": "Info", "order": 3},
        ]
    }
}


def _written(*fields: dict[str, object]) -> dict[str, object]:
    # The authoring write numbers the fields in the order it states them.
    numbered = [{**field, "order": place} for place, field in enumerate(fields, 1)]
    metadata = normalize_flow_metadata_for_write({"form_schema": {"fields": numbered}})
    assert metadata is not None
    return metadata


def _stored(written: dict[str, object]) -> list[tuple[str, str, object]]:
    result = _with_saved_form_fields(written, _SAVED)
    assert result is not None
    return [
        (f["name"], f["type"], f.get("label")) for f in result["form_schema"]["fields"]
    ]


_EPOST = {"name": "epost", "type": "text", "label": "E-post", "required": True}
_NAMN = {"name": "namn", "type": "text", "label": "Namn"}
_INFO = {"name": "info", "type": "text", "label": "Info"}


def test_a_form_that_reads_as_saved_is_stored_exactly_as_saved() -> None:
    result = _with_saved_form_fields(_written(_EPOST, _NAMN, _INFO), _SAVED)

    assert result is not None
    assert result["form_schema"] == _SAVED["form_schema"]


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param(
            [{**_EPOST, "label": "Din e-post"}, _NAMN, _INFO],
            [
                ("epost", "email", "Din e-post"),
                ("namn", "string", "Namn"),
                ("info", "textarea", "Info"),
            ],
            id="label",
        ),
        pytest.param(
            [_EPOST, {**_NAMN, "required": True}, _INFO],
            [
                ("epost", "email", "E-post"),
                ("namn", "string", "Namn"),
                ("info", "textarea", "Info"),
            ],
            id="required",
        ),
        pytest.param(
            [_INFO, _NAMN, _EPOST],
            [
                ("info", "textarea", "Info"),
                ("namn", "string", "Namn"),
                ("epost", "email", "E-post"),
            ],
            id="reorder",
        ),
        pytest.param(
            [_EPOST, {**_NAMN, "type": "number"}, _INFO],
            [
                ("epost", "email", "E-post"),
                ("namn", "number", "Namn"),
                ("info", "textarea", "Info"),
            ],
            id="a type change writes the new type",
        ),
        pytest.param(
            [_EPOST, {"name": "ny", "type": "text", "label": "Ny"}],
            [("epost", "email", "E-post"), ("ny", "text", "Ny")],
            id="a new field is written as given",
        ),
    ],
)
def test_a_field_keeps_its_saved_type_while_the_edit_leaves_the_type_it_reads(
    fields: list[dict[str, object]], expected: list[tuple[str, str, object]]
) -> None:
    assert _stored(_written(*fields)) == expected

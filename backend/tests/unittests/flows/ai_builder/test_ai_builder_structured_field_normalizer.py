from __future__ import annotations

import logging

from eneo.flows.ai_builder.ai_builder_structured_field_normalizer import (
    normalize_structured_field_list,
)

_NORMALIZER_LOGGER = "eneo.flows.ai_builder.ai_builder_structured_field_normalizer"


def test_empty_field_list_is_not_logged_as_dropped(caplog) -> None:
    # An explicit empty list means "no structured fields" — logging it as a
    # drop misattributes compile failures during incident analysis.
    with caplog.at_level(logging.INFO, logger=_NORMALIZER_LOGGER):
        assert normalize_structured_field_list([]) is None
    assert "ai_builder_structured_field_list_dropped" not in caplog.text


def test_array_field_with_empty_item_fields_is_retained_without_drop_log(
    caplog,
) -> None:
    # The 2026-08-05 incident log shape: valid array fields whose optional
    # item_fields were empty emitted three "dropped" events while every array
    # was in fact retained.
    fields = [
        {"name": "beslut", "field_type": "array", "item_fields": []},
        {"name": "atgarder", "field_type": "array", "item_fields": []},
        {"name": "oppna_fragor", "field_type": "array", "item_fields": []},
    ]

    with caplog.at_level(logging.INFO, logger=_NORMALIZER_LOGGER):
        normalized = normalize_structured_field_list(fields)

    assert normalized is not None
    assert [field["name"] for field in normalized] == [
        "beslut",
        "atgarder",
        "oppna_fragor",
    ]
    assert "ai_builder_structured_field_list_dropped" not in caplog.text

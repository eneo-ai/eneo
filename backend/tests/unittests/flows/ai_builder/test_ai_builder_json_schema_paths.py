from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    missing_structured_output_path,
    schema_leaf_property_names,
    schema_property_names,
    top_level_schema_property_names,
)


def test_missing_structured_output_path_accepts_numeric_array_indexes() -> None:
    contract = {
        "type": "object",
        "properties": {
            "risker": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rubrik": {"type": "string"},
                    },
                },
            }
        },
    }

    assert missing_structured_output_path(contract, "risker.0.rubrik") is None


def test_missing_structured_output_path_reports_first_missing_segment() -> None:
    contract = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
        },
    }

    assert missing_structured_output_path(contract, "details.title") == "details"


def test_missing_structured_output_path_rejects_array_field_without_index_when_strict() -> (
    None
):
    contract = {
        "type": "object",
        "properties": {
            "risker": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rubrik": {"type": "string"},
                    },
                },
            }
        },
    }

    assert (
        missing_structured_output_path(
            contract,
            "risker.rubrik",
            require_array_index=True,
        )
        == "risker.rubrik"
    )


def test_missing_structured_output_path_accepts_composite_schema_properties() -> None:
    contract = {
        "allOf": [
            {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
            {
                "type": "object",
                "properties": {"risk": {"type": "string"}},
            },
        ]
    }

    assert missing_structured_output_path(contract, "risk") is None


def test_schema_property_names_includes_composite_and_child_properties() -> None:
    schema = {
        "allOf": [
            {"type": "object", "properties": {"summary": {"type": "string"}}},
            {
                "type": "object",
                "properties": {
                    "risker": {
                        "type": "object",
                        "properties": {"rubrik": {"type": "string"}},
                    }
                },
            },
        ]
    }

    assert schema_property_names(schema) == {"summary", "risker", "rubrik"}


def test_top_level_schema_property_names_preserves_declaration_order() -> None:
    schema = {
        "type": "object",
        "properties": {
            "meeting_context": {"type": "string"},
            "participants": {"type": "array"},
        },
    }

    assert top_level_schema_property_names(schema) == [
        "meeting_context",
        "participants",
    ]


def test_top_level_schema_property_names_ignores_composite_and_nested_properties() -> (
    None
):
    schema = {
        "allOf": [
            {"type": "object", "properties": {"summary": {"type": "string"}}},
        ],
        "properties": {
            "risker": {
                "type": "object",
                "properties": {"rubrik": {"type": "string"}},
            }
        },
    }

    assert top_level_schema_property_names(schema) == ["risker"]


def test_schema_leaf_property_names_descends_objects_and_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {
            "dokument": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "titel": {"type": "string"},
                        "datum": {"type": "string"},
                    },
                },
            },
            "sammanfattning": {"type": "string"},
        },
    }

    assert schema_leaf_property_names(schema) == [
        "titel",
        "datum",
        "sammanfattning",
    ]

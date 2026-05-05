from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from intric.flows.ai_builder.ai_builder_structured_field_paths import (
    missing_draft_field_path,
    missing_structured_output_path,
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


def test_missing_draft_field_path_requires_array_index() -> None:
    fields = [
        StructuredFieldDraft(
            name="risker",
            field_type="array",
            description="Risker",
            item_fields=[
                StructuredFieldDraft(
                    name="rubrik",
                    field_type="string",
                    description="Rubrik",
                )
            ],
        )
    ]

    assert missing_draft_field_path(fields, "risker.0.rubrik") is None
    assert missing_draft_field_path(fields, "risker.rubrik") == "risker.rubrik"
    assert missing_draft_field_path(fields, "risker") is None

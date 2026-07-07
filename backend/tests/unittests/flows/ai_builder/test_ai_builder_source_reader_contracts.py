from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_new_step_compiler import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
    StructuredFieldType,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    complete_structured_source_reader_fields,
)


def _field(
    name: str,
    field_type: StructuredFieldType = "string",
    *,
    description: str = "Beskrivning.",
    item_fields: list[StructuredFieldDraft] | None = None,
) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type=field_type,
        description=description,
        item_fields=item_fields,
    )


def test_source_reader_completion_does_not_nest_existing_array_container() -> None:
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "documents",
                "array",
                item_fields=[_field("title", description="Dokumenttitel.")],
            ),
        ),
        required_fields=(
            SourceCaptureField(name="documents"),
            SourceCaptureField(name="summary"),
            SourceCaptureField(name="sammanfattning"),
        ),
    )

    documents_field = completed[0]
    assert documents_field.name == "documents"
    assert [field.name for field in documents_field.item_fields or []] == [
        "title",
        "summary",
    ]


def test_source_reader_completion_treats_swedish_summary_as_existing_summary() -> None:
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "documents",
                "array",
                item_fields=[
                    _field("title", description="Dokumenttitel."),
                    _field("sammanfattning", description="Kort sammanfattning."),
                ],
            ),
        ),
        required_fields=(SourceCaptureField(name="summary"),),
    )

    documents_field = completed[0]
    assert [field.name for field in documents_field.item_fields or []] == [
        "title",
        "sammanfattning",
    ]

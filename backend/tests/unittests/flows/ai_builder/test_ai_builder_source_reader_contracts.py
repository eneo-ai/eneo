from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
    StructuredFieldType,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
    complete_structured_source_reader_fields,
    structured_fields_have_document_items,
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
        "source_label",
        "title",
        "summary",
    ]


def test_source_reader_completion_canonicalizes_source_item_fields() -> None:
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "documents",
                "array",
                item_fields=[
                    _field("title", description="Dokumenttitel."),
                    _field("date", description="Datum eller år."),
                    _field("author", description="Författare eller avsändare."),
                    _field("sammanfattning", description="Kort sammanfattning."),
                    _field("summary", description="Duplicerad sammanfattning."),
                    _field("documents", description="Felaktigt nästlad container."),
                ],
            ),
        ),
        required_fields=(SourceCaptureField(name="summary"),),
    )

    documents_field = completed[0]
    assert [field.name for field in documents_field.item_fields or []] == [
        "source_label",
        "title",
        "date_or_year",
        "author_or_sender",
        "summary",
    ]


def test_source_reader_completion_canonicalizes_obligation_variants() -> None:
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "documents",
                "array",
                item_fields=[
                    _field("topic_summary"),
                    _field("source_summary"),
                    _field("key_requirements"),
                    _field("sensitive_parts"),
                    _field("confidential_sections"),
                ],
            ),
        ),
        required_fields=(),
    )

    documents_field = completed[0]
    assert [field.name for field in documents_field.item_fields or []] == [
        "source_label",
        "summary",
        "requirements",
        "confidentiality",
    ]


def test_source_reader_completion_materializes_bare_document_array_items() -> None:
    completed = complete_structured_source_reader_fields(
        (_field("documents", "array"),),
        required_fields=(
            SourceCaptureField(name="summary"),
            SourceCaptureField(name="date_or_year"),
        ),
    )

    documents_field = completed[0]
    assert documents_field.name == "documents"
    assert [field.name for field in documents_field.item_fields or []] == [
        "source_label",
        "summary",
        "date_or_year",
    ]
    assert structured_fields_have_document_items(completed)


def test_source_reader_completion_canonicalizes_localized_document_array() -> None:
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "dokument",
                "array",
                item_fields=[
                    _field("titel", description="Dokumenttitel."),
                    _field("dokumenttyp", description="Typ av dokument."),
                    _field("kategori", description="Dokumentkategori."),
                    _field("slutsatser", description="Dokumentets slutsatser."),
                ],
            ),
        ),
        required_fields=(),
    )

    documents_field = completed[0]
    assert documents_field.name == "documents"
    assert [field.name for field in documents_field.item_fields or []] == [
        "source_label",
        "title",
        "document_type",
        "category",
        "conclusions",
    ]
    assert structured_fields_have_document_items(completed)


def test_source_reader_completion_does_not_tag_non_source_document_arrays() -> None:
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "referenced_documents",
                "array",
                item_fields=[_field("title", description="Refererad titel.")],
            ),
        ),
        required_fields=(),
    )

    referenced_documents_field = completed[0]
    assert referenced_documents_field.name == "referenced_documents"
    assert [field.name for field in referenced_documents_field.item_fields or []] == [
        "title"
    ]
    assert not structured_fields_have_document_items(completed)

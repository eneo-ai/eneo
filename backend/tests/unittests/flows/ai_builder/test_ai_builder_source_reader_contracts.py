from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
    StructuredFieldType,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
    allocate_injected_source_field_name,
    complete_structured_source_reader_fields,
    source_contract_shadow_form_field_names,
    structured_fields_have_document_items,
)
from eneo.flows.flow_authoring_spec import FormFieldSpec


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


def test_source_contract_collision_uses_exact_folded_identity_only() -> None:
    form_field = FormFieldSpec(
        name="case_id",
        type="text",
        label="Case report identifier",
        required=True,
    )

    assert source_contract_shadow_form_field_names(
        output_fields_by_step=((_field("case_id"),),),
        form_fields=(form_field,),
    ) == ("case_id",)
    assert (
        source_contract_shadow_form_field_names(
            output_fields_by_step=((_field("source_case_id"),),),
            form_fields=(form_field,),
        )
        == ()
    )
    differently_named_field = FormFieldSpec(
        name="runtime_case_reference",
        type="text",
        label="Case id",
        required=True,
    )
    assert (
        source_contract_shadow_form_field_names(
            output_fields_by_step=((_field("case_id"),),),
            form_fields=(differently_named_field,),
        )
        == ()
    )


def test_source_reader_completion_renames_only_injected_confirmed_collision() -> None:
    authored = _field("title")

    completed = complete_structured_source_reader_fields(
        (authored,),
        required_fields=(SourceCaptureField(name="case_id"),),
        reserved_field_names=frozenset({"case_id"}),
    )

    assert completed[0] == authored
    assert [field.name for field in completed] == ["title", "source_case_id"]


def test_injected_source_field_allocator_avoids_reserved_and_occupied_names() -> None:
    assert (
        allocate_injected_source_field_name(
            "case_id",
            reserved_field_names=frozenset({"CASE-ID"}),
            occupied_field_names=frozenset({"source_case_id"}),
        )
        == "source_source_case_id"
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
        ),
    )

    documents_field = completed[0]
    assert documents_field.name == "documents"
    assert [field.name for field in documents_field.item_fields or []] == [
        "source_label",
        "title",
        "summary",
    ]


def test_source_reader_completion_preserves_names_and_dedupes_by_identity() -> None:
    # Identity is folded, wording is the author's: names survive verbatim,
    # duplicate identities collapse, and a required capture field is
    # satisfied by any synonym instead of appended as a shadow.
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "documents",
                "array",
                item_fields=[
                    _field("title", description="Dokumenttitel."),
                    _field("date", description="Datum eller år."),
                    _field("author", description="Författare eller avsändare."),
                    _field("brief_summary", description="Kort sammanfattning."),
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
        "date",
        "author",
        "brief_summary",
    ]


def test_source_reader_completion_accepts_declared_source_identity_field() -> None:
    completed = complete_structured_source_reader_fields(
        (
            _field(
                "documents",
                "array",
                item_fields=[
                    _field("author_or_source"),
                    _field("source"),
                ],
            ),
        ),
        required_fields=(),
    )

    documents_field = completed[0]
    assert [field.name for field in documents_field.item_fields or []] == [
        "source",
        "author_or_source",
    ]


def test_source_reader_completion_dedupes_obligation_variants_by_identity() -> None:
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
        "topic_summary",
        "key_requirements",
        "sensitive_parts",
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


def test_source_reader_completion_preserves_localized_document_array_items() -> None:
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
        "titel",
        "dokumenttyp",
        "kategori",
        "slutsatser",
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

from __future__ import annotations

from dataclasses import replace

from eneo.flows.ai_builder.ai_builder_assembly.document_report.diagnostics import (
    raise_document_report_review_mode_conflict as _raise_document_report_review_mode_conflict,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.topology import (
    COMPOSE_OVERALL_OVERVIEW_KEY,
    COMPOSE_REPORT_TITLE_KEY,
    COMPOSE_SECTION_BODY_KEY,
    COMPOSE_SECTION_TITLE_KEY,
    COMPOSE_SOURCE_LABEL_KEY,
)
from eneo.flows.ai_builder.ai_builder_assembly.plan import PlannedStep
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
    structured_field_draft_names,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    structured_field_names_satisfy_result_field,
)


def _merge_report_writer_semantics(
    planned_step: PlannedStep,
    *,
    semantic_step: PlannedStep,
    preserve_review_mode: bool = True,
) -> PlannedStep:
    if (
        preserve_review_mode
        and planned_step.review_mode is not None
        and semantic_step.review_mode is not None
    ):
        _raise_document_report_review_mode_conflict(
            planned_step=planned_step,
            semantic_step=semantic_step,
        )
    instructions = planned_step.instructions
    if semantic_step.instructions not in instructions:
        instructions = f"{semantic_step.instructions}\n\n{instructions}"
    return replace(
        planned_step,
        instructions=instructions,
        form_field_refs=tuple(
            dict.fromkeys(
                (*planned_step.form_field_refs, *semantic_step.form_field_refs)
            )
        ),
        model_ref=semantic_step.model_ref or planned_step.model_ref,
        knowledge_refs=tuple(
            dict.fromkeys((*planned_step.knowledge_refs, *semantic_step.knowledge_refs))
        ),
        citations_requested=(
            planned_step.citations_requested or semantic_step.citations_requested
        ),
        review_mode=(
            semantic_step.review_mode
            if preserve_review_mode and semantic_step.review_mode is not None
            else planned_step.review_mode
        ),
    )


def _complete_source_section_fields_for_compose(
    planned_step: PlannedStep,
    *,
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    requested_section_fields: tuple[StructuredFieldDraft, ...],
    include_runtime_file_id: bool,
    ui_language: str | None,
) -> PlannedStep:
    if len(planned_step.output_fields) != 1:
        return planned_step
    array_field = planned_step.output_fields[0]
    if array_field.field_type != "array":
        return planned_step
    item_fields = [
        field
        for field in array_field.item_fields or ()
        if include_runtime_file_id or field.name != "source_file_id"
    ]
    canonical_fields = (
        _section_title_field(ui_language),
        _section_body_field(ui_language),
        _source_label_field(
            ui_language,
            runtime_owned=include_runtime_file_id,
        ),
        *(
            (_runtime_source_file_id_field(ui_language),)
            if include_runtime_file_id
            else ()
        ),
        *requested_section_fields,
    )
    for field in canonical_fields:
        item_fields = _set_canonical_structured_field(item_fields, field)
    item_fields = _merge_result_contract_fields(
        item_fields,
        result_contract_output_fields,
    )
    completed_array_field = array_field.model_copy(update={"item_fields": item_fields})
    return replace(planned_step, output_fields=(completed_array_field,))


def _set_canonical_structured_field(
    fields: list[StructuredFieldDraft],
    field: StructuredFieldDraft,
) -> list[StructuredFieldDraft]:
    for index, existing in enumerate(fields):
        if existing.name != field.name:
            continue
        updated_fields = list(fields)
        updated_fields[index] = field
        return updated_fields
    return [*fields, field]


def _merge_result_contract_fields(
    fields: list[StructuredFieldDraft],
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
) -> list[StructuredFieldDraft]:
    """Add required result fields unless an equivalent field already exists.

    Exact-name matches are upserted like layout fields; a Swedish or compound
    field that already covers the role must not gain a canonical duplicate.
    """

    merged_fields = list(fields)
    for required_field in result_contract_output_fields:
        if any(existing.name == required_field.name for existing in merged_fields):
            merged_fields = _set_canonical_structured_field(
                merged_fields,
                required_field,
            )
            continue
        if structured_field_names_satisfy_result_field(
            structured_field_draft_names(merged_fields),
            required_field.name,
        ):
            continue
        merged_fields.append(required_field)
    return merged_fields


def _section_title_field(ui_language: str | None) -> StructuredFieldDraft:
    description = (
        "Human-readable section heading from the document title or topic, not the uploaded filename."
        if ui_language == "en"
        else "Mänsklig avsnittsrubrik från dokumentets titel eller ämne, inte uppladdat filnamn."
    )
    return StructuredFieldDraft(
        name=COMPOSE_SECTION_TITLE_KEY,
        field_type="string",
        description=description,
    )


def _section_body_field(ui_language: str | None) -> StructuredFieldDraft:
    description = (
        "Finished source-specific report section body."
        if ui_language == "en"
        else "Färdig källspecifik rapporttext för avsnittet."
    )
    return StructuredFieldDraft(
        name=COMPOSE_SECTION_BODY_KEY,
        field_type="string",
        description=description,
    )


def _source_label_field(
    ui_language: str | None,
    *,
    runtime_owned: bool,
) -> StructuredFieldDraft:
    if runtime_owned:
        description = (
            "Runtime-owned uploaded source label. The runtime fills this field."
            if ui_language == "en"
            else "Runtimeägd källetikett för uppladdad fil. Runtime fyller fältet."
        )
    else:
        description = (
            "Source label copied from the matching input document item."
            if ui_language == "en"
            else "Källetikett kopierad från motsvarande dokumentpost i underlaget."
        )
    return StructuredFieldDraft(
        name=COMPOSE_SOURCE_LABEL_KEY,
        field_type="string",
        description=description,
    )


def _runtime_source_file_id_field(ui_language: str | None) -> StructuredFieldDraft:
    description = (
        "Runtime-owned uploaded source file id. The runtime fills this field."
        if ui_language == "en"
        else "Runtimeägt fil-id för uppladdad källa. Runtime fyller fältet."
    )
    return StructuredFieldDraft(
        name="source_file_id",
        field_type="string",
        description=description,
    )


def _report_overview_fields(
    existing_fields: tuple[StructuredFieldDraft, ...],
    *,
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    requested_section_fields: tuple[StructuredFieldDraft, ...],
    ui_language: str | None,
) -> tuple[StructuredFieldDraft, ...]:
    if ui_language == "en":
        report_fields = (
            StructuredFieldDraft(
                name=COMPOSE_REPORT_TITLE_KEY,
                field_type="string",
                description="Final report title.",
            ),
            StructuredFieldDraft(
                name=COMPOSE_OVERALL_OVERVIEW_KEY,
                field_type="string",
                description="Synthesized overview or conclusion across all sources.",
            ),
        )
    else:
        report_fields = (
            StructuredFieldDraft(
                name=COMPOSE_REPORT_TITLE_KEY,
                field_type="string",
                description="Slutrapportens titel.",
            ),
            StructuredFieldDraft(
                name=COMPOSE_OVERALL_OVERVIEW_KEY,
                field_type="string",
                description="Samlad översikt eller slutsats över alla källor.",
            ),
        )
    completed_fields = [
        field
        for field in existing_fields
        if field.name
        not in {"overview", COMPOSE_REPORT_TITLE_KEY, COMPOSE_OVERALL_OVERVIEW_KEY}
    ]
    for report_field in (*report_fields, *requested_section_fields):
        completed_fields = _set_canonical_structured_field(
            completed_fields,
            report_field,
        )
    completed_fields = _merge_result_contract_fields(
        completed_fields,
        result_contract_output_fields,
    )
    return tuple(completed_fields)


complete_source_section_fields_for_compose = _complete_source_section_fields_for_compose
merge_report_writer_semantics = _merge_report_writer_semantics
report_overview_fields = _report_overview_fields
section_body_field = _section_body_field
section_title_field = _section_title_field

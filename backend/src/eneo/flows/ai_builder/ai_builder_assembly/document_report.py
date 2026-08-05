from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import NoReturn, assert_never, cast

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    DocumentReportSectionSource,
    PlannedStep,
    derive_underlag_channel,
    planned_step_is_source_reader,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    missing_structured_output_path,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import make_plan_step_ref
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
    structured_field_draft_names,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSectionContract,
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import SemanticStepIntent
from eneo.flows.ai_builder.ai_builder_result_contract import (
    structured_field_names_satisfy_result_field,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
    complete_structured_source_reader_fields,
    structured_fields_have_document_items,
)
from eneo.flows.ai_builder.planning_state import ReportDisposition
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_variable_definitions import form_field_reference_expression
from eneo.flows.input_binding_contract_rules import (
    SourceRefBinding,
    item_template_field_names,
    source_ref_bindings,
)

logger = logging.getLogger(__name__)

COMPOSE_SECTION_TITLE_KEY = "section_title"
COMPOSE_SECTION_BODY_KEY = "section_body"
COMPOSE_SOURCE_LABEL_KEY = "source_label"
COMPOSE_REPORT_TITLE_KEY = "report_title"
COMPOSE_OVERALL_OVERVIEW_KEY = "overall_overview"
DOCUMENT_REPORT_COMPOSE_TOPOLOGY_MISSING_FEEDBACK = (
    "Document report flows with a committed report disposition must end with "
    "a deterministic compose_text body writer before the renderer."
)


def admit_document_report_semantic_shape(
    steps: Sequence[SemanticStepIntent],
    *,
    runtime_input_type: InputType,
    final_semantic_output_type: OutputType,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    report_disposition: ReportDisposition | None,
    ui_language: str | None,
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if (
        not semantic_steps
        or runtime_input_type not in {InputType.DOCUMENT, InputType.FILE}
        or final_semantic_output_type != OutputType.TEXT
    ):
        return semantic_steps

    if len(semantic_steps) == 1:
        semantic_step = semantic_steps[0]
        source_fields = tuple(semantic_step.output_fields or ())
        if not source_fields:
            source_fields = _structured_fields_from_source_capture_fields(
                source_reader_required_fields
            )
        if not source_fields:
            if report_disposition is None:
                return semantic_steps
            source_fields = (_default_document_report_source_field(ui_language),)
        source_fields = complete_structured_source_reader_fields(
            source_fields,
            required_fields=(),
        )
        if report_disposition is not None:
            source_fields = _admitted_document_report_source_fields(
                source_fields,
                ui_language=ui_language,
            )
        reader_step = semantic_step.model_copy(
            update={
                "name": _source_report_reader_name(ui_language),
                "instructions": _source_report_reader_instructions(ui_language),
                "output_type": OutputType.JSON,
                "output_fields": list(source_fields),
                "uses_form_fields": [],
            }
        )
        writer_step = semantic_step.model_copy(
            update={
                "name": _source_report_writer_name(ui_language),
                "instructions": append_terminal_helper_output_fields(
                    semantic_step.instructions,
                    source_fields,
                    ui_language=ui_language,
                ),
                "output_type": OutputType.TEXT,
                "output_fields": None,
            }
        )
        return (reader_step, writer_step)

    if report_disposition is None:
        return semantic_steps
    reader_step = semantic_steps[0]
    source_fields = complete_structured_source_reader_fields(
        tuple(reader_step.output_fields or ())
        or (_default_document_report_source_field(ui_language),),
        required_fields=(),
    )
    admitted_reader = reader_step.model_copy(
        update={
            "output_type": OutputType.JSON,
            "output_fields": list(
                _admitted_document_report_source_fields(
                    source_fields,
                    ui_language=ui_language,
                )
            ),
        }
    )
    return (admitted_reader, *semantic_steps[1:])


def _admitted_document_report_source_fields(
    source_fields: tuple[StructuredFieldDraft, ...],
    *,
    ui_language: str | None,
) -> tuple[StructuredFieldDraft, ...]:
    if structured_fields_have_document_items(source_fields):
        return source_fields
    return (
        _document_report_source_array_field(source_fields, ui_language=ui_language),
    )


def _document_report_source_array_field(
    source_fields: tuple[StructuredFieldDraft, ...],
    *,
    ui_language: str | None,
) -> StructuredFieldDraft:
    description = (
        "Source-grounded report material for the current document."
        if ui_language == "en"
        else "Källgrundat rapportunderlag för det aktuella dokumentet."
    )
    return StructuredFieldDraft(
        name="documents",
        field_type="array",
        description=description,
        item_fields=list(source_fields),
    )


def _default_document_report_source_field(
    ui_language: str | None,
) -> StructuredFieldDraft:
    description = (
        "Source-grounded material needed to write the requested report."
        if ui_language == "en"
        else "Källgrundat underlag som behövs för att skriva den begärda rapporten."
    )
    return StructuredFieldDraft(
        name="source_material",
        field_type="string",
        description=description,
    )


def _structured_fields_from_source_capture_fields(
    fields: tuple[SourceCaptureField, ...],
) -> tuple[StructuredFieldDraft, ...]:
    return tuple(
        StructuredFieldDraft(
            name=field.name,
            field_type="string",
            description=field.description or f"Source-derived value for {field.name}.",
        )
        for field in fields
    )


def _source_report_reader_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Extract source fields"
    return "Extrahera källfält"


def _source_report_writer_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Write report"
    return "Skriv rapport"


def _source_report_reader_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Extract the source-derived fields needed before writing the report."
    return "Extrahera de källbaserade fält som behövs innan rapporten skrivs."


def append_terminal_helper_output_fields(
    instructions: str,
    output_fields: Sequence[StructuredFieldDraft],
    *,
    ui_language: str | None,
) -> str:
    field_names = ", ".join(field.name for field in output_fields if field.name)
    if not field_names:
        return instructions
    if ui_language == "en":
        field_instruction = "Ensure the report body covers these fields: "
    else:
        field_instruction = "Säkerställ att rapporttexten täcker dessa fält: "
    return f"{instructions}\n\n{field_instruction}{field_names}."


def lower_document_report_topology(
    planned_steps: tuple[PlannedStep, ...],
    *,
    report_disposition: ReportDisposition | None,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    semantic_step_count: int,
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    requested_output_section_contracts: tuple[RequestedOutputSectionContract, ...],
    ui_language: str | None,
) -> tuple[tuple[PlannedStep, ...], DocumentReportSectionSource | None]:
    if report_disposition is None:
        return planned_steps, None

    def fail_closed() -> NoReturn:
        _raise_document_report_compose_topology_missing(
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
            pattern_ids=pattern_ids,
            chain_steps=chain_steps,
            semantic_step_count=semantic_step_count,
        )

    if (
        runtime_input_type not in {InputType.DOCUMENT, InputType.FILE}
        or final_output_type not in {OutputType.PDF, OutputType.DOCX}
        or len(planned_steps) < 3
        or planned_steps[-1].role != "renderer"
        or planned_steps[-2].role != "body_writer"
    ):
        fail_closed()

    renderer_step = planned_steps[-1]
    body_writer_step = planned_steps[-2]
    if body_writer_step.citations_requested or any(
        step.citations_requested for step in planned_steps[:-2]
    ):
        _raise_document_report_citations_unsupported(
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            report_disposition=report_disposition,
        )
    content_steps = list(planned_steps[:-2])
    reader_index = _document_report_reader_index(tuple(content_steps))
    if reader_index is None:
        fail_closed()
    reader_is_mapped = (
        content_steps[reader_index].runtime_input_execution_mode == "per_source"
    )
    if not reader_is_mapped:
        content_steps[reader_index] = replace(
            content_steps[reader_index],
            instructions=_append_single_call_reader_instruction(
                content_steps[reader_index].instructions,
                ui_language=ui_language,
            ),
        )

    match report_disposition:
        case "per_source_sections" | "both":
            section_index = _source_section_single_array_index(
                tuple(content_steps),
                after_index=reader_index,
            )
            if section_index is None:
                section_semantic_step: PlannedStep | None = None
                replaced_index = reader_index + 1
                if replaced_index < len(
                    content_steps
                ) and _step_outputs_weak_section_text(content_steps[replaced_index]):
                    section_semantic_step = content_steps.pop(replaced_index)
                    logger.info(
                        "ai_builder_document_report_weak_section_writer_replaced",
                        extra={"replaced_step_name": section_semantic_step.name},
                    )
                section_step = _document_report_section_writer(
                    reader_step=content_steps[reader_index],
                    model_ref=(
                        section_semantic_step.model_ref
                        if section_semantic_step is not None
                        else body_writer_step.model_ref
                    ),
                    ui_language=ui_language,
                )
                if section_semantic_step is not None:
                    section_step = _merge_report_writer_semantics(
                        section_step,
                        semantic_step=section_semantic_step,
                    )
                content_steps.insert(reader_index + 1, section_step)
                section_index = reader_index + 1
                logger.info(
                    "ai_builder_document_report_section_writer_inserted",
                    extra={"reader_step_name": content_steps[reader_index].name},
                )

            if reader_is_mapped:
                content_steps = list(
                    _apply_previous_document_item_map_execution(
                        tuple(content_steps),
                        ui_language=ui_language,
                    )
                )
                if not content_steps[section_index].previous_item_map_enabled:
                    fail_closed()
            section_field_name = _single_output_array_field_name(
                content_steps[section_index].output_fields
            )
            if section_field_name is None:
                fail_closed()
            if not reader_is_mapped:
                content_steps[section_index] = replace(
                    content_steps[section_index],
                    instructions=_append_single_call_section_instruction(
                        content_steps[section_index].instructions,
                        section_field_name=section_field_name,
                        ui_language=ui_language,
                    ),
                )
            content_steps[section_index] = _complete_source_section_fields_for_compose(
                content_steps[section_index],
                result_contract_output_fields=(
                    result_contract_output_fields
                    if report_disposition == "per_source_sections"
                    else ()
                ),
                requested_section_fields=(
                    _requested_section_fields(
                        requested_output_section_contracts,
                        ui_language,
                    )
                    if report_disposition == "per_source_sections"
                    else ()
                ),
                include_runtime_file_id=reader_is_mapped,
                ui_language=ui_language,
            )
            if report_disposition == "per_source_sections":
                content_steps, remaining_report_semantics = (
                    _without_report_text_semantics_after(
                        content_steps,
                        after_index=section_index,
                    )
                )
                for semantic_step in remaining_report_semantics:
                    content_steps[section_index] = _merge_report_writer_semantics(
                        content_steps[section_index],
                        semantic_step=semantic_step,
                    )
                content_steps[section_index] = _merge_report_writer_semantics(
                    content_steps[section_index],
                    semantic_step=body_writer_step,
                    preserve_review_mode=False,
                )
        case "synthesized_overview":
            section_index = reader_index
            section_field_name = None
        case _ as unreachable:
            assert_never(unreachable)

    match report_disposition:
        case "synthesized_overview" | "both":
            content_steps, overview_semantics = _without_report_text_semantics_after(
                content_steps,
                after_index=section_index,
            )
            overview_index = _overview_writer_index(
                planned_steps=tuple(content_steps),
                after_index=section_index,
                before_index=len(content_steps),
            )
            if overview_index is None:
                previous_step = content_steps[-1]
                if previous_step.output_type != OutputType.JSON:
                    fail_closed()
                content_steps.append(
                    _document_report_overview_writer(
                        previous_step=previous_step,
                        ui_language=ui_language,
                    )
                )
                overview_index = len(content_steps) - 1
                logger.info(
                    "ai_builder_document_report_overview_writer_inserted",
                    extra={"previous_step_name": previous_step.name},
                )
            for semantic_step in overview_semantics:
                content_steps[overview_index] = _merge_report_writer_semantics(
                    content_steps[overview_index],
                    semantic_step=semantic_step,
                )
                logger.info(
                    "ai_builder_document_report_text_writer_converted_to_overview",
                    extra={"step_name": semantic_step.name},
                )
            content_steps[overview_index] = replace(
                content_steps[overview_index],
                output_fields=_report_overview_fields(
                    content_steps[overview_index].output_fields,
                    result_contract_output_fields=result_contract_output_fields,
                    requested_section_fields=_requested_section_fields(
                        requested_output_section_contracts,
                        ui_language,
                    ),
                    ui_language=ui_language,
                ),
            )
            content_steps[overview_index] = _merge_report_writer_semantics(
                content_steps[overview_index],
                semantic_step=body_writer_step,
                preserve_review_mode=False,
            )
        case "per_source_sections":
            pass
        case _ as unreachable:
            assert_never(unreachable)

    lowered_steps = (
        *content_steps,
        _document_report_compose_step(
            body_writer_step=body_writer_step,
            ui_language=ui_language,
        ),
        renderer_step,
    )
    section_source = (
        DocumentReportSectionSource(
            producer_ref=make_plan_step_ref(section_index),
            field_name=section_field_name,
        )
        if section_field_name is not None
        else None
    )
    return lowered_steps, section_source


def _document_report_section_writer(
    *,
    reader_step: PlannedStep,
    model_ref: str | None,
    ui_language: str | None,
) -> PlannedStep:
    return PlannedStep(
        role="transform",
        name=_document_report_section_writer_name(ui_language),
        instructions=_document_report_section_writer_instructions(ui_language),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        output_mode=OutputMode.PASS_THROUGH,
        underlag_channel=derive_underlag_channel(
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.JSON,
            previous_step=reader_step,
            previous_field_refs=(),
        ),
        output_fields=(_document_report_section_array_field(ui_language),),
        model_ref=model_ref,
    )


def _merge_report_writer_semantics(
    planned_step: PlannedStep,
    *,
    semantic_step: PlannedStep,
    preserve_review_mode: bool = True,
) -> PlannedStep:
    if (
        planned_step.model_ref is not None
        and semantic_step.model_ref is not None
        and planned_step.model_ref != semantic_step.model_ref
    ):
        _raise_document_report_model_ref_conflict(
            planned_step=planned_step,
            semantic_step=semantic_step,
        )
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


def _document_report_reader_index(
    planned_steps: tuple[PlannedStep, ...],
) -> int | None:
    for index, planned_step in enumerate(planned_steps):
        if planned_step_is_source_reader(
            planned_step
        ) and structured_fields_have_document_items(planned_step.output_fields):
            return index
    return None


def _source_section_single_array_index(
    planned_steps: tuple[PlannedStep, ...],
    *,
    after_index: int = -1,
) -> int | None:
    for index, planned_step in enumerate(planned_steps):
        if index <= after_index:
            continue
        if _step_outputs_source_section_array(planned_step):
            return index
    return None


def _step_outputs_source_section_array(planned_step: PlannedStep) -> bool:
    if len(planned_step.output_fields) != 1:
        return False
    field = planned_step.output_fields[0]
    if field.field_type != "array":
        return False
    item_field_names = {item.name for item in field.item_fields or ()}
    return {COMPOSE_SECTION_TITLE_KEY, COMPOSE_SECTION_BODY_KEY}.issubset(
        item_field_names
    )


def _step_outputs_weak_section_text(planned_step: PlannedStep) -> bool:
    if planned_step.input_source != InputSource.PREVIOUS_STEP:
        return False
    if planned_step.output_type == OutputType.TEXT:
        return True
    if planned_step.input_type != InputType.JSON:
        return False
    if (
        planned_step.output_type != OutputType.JSON
        or len(planned_step.output_fields) != 1
    ):
        return False
    field = planned_step.output_fields[0]
    if field.field_type == "string":
        return _is_section_text_field_name(field.name)
    if field.field_type != "array":
        return False
    return any(
        item.field_type == "string" and _is_section_text_field_name(item.name)
        for item in field.item_fields or ()
    )


def _is_section_text_field_name(name: str) -> bool:
    return name in {"section_text", COMPOSE_SECTION_BODY_KEY}


def _step_outputs_report_text(planned_step: PlannedStep) -> bool:
    return (
        planned_step.input_source == InputSource.PREVIOUS_STEP
        and planned_step.output_type == OutputType.TEXT
    )


def _without_report_text_semantics_after(
    planned_steps: list[PlannedStep],
    *,
    after_index: int,
) -> tuple[list[PlannedStep], tuple[PlannedStep, ...]]:
    retained_steps = planned_steps[: after_index + 1]
    report_semantics: list[PlannedStep] = []
    for planned_step in planned_steps[after_index + 1 :]:
        if _step_outputs_report_text(planned_step):
            report_semantics.append(planned_step)
        else:
            retained_steps.append(planned_step)
    return retained_steps, tuple(report_semantics)


def _document_report_section_writer_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Build source sections"
    return "Bygg källavsnitt"


def _document_report_section_writer_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return (
            "Write one finished report section for the current document item. "
            "Use the document title or topic as section_title, not the uploaded "
            "filename. Put the full source-specific prose in section_body."
        )
    return (
        "Skriv ett färdigt rapportavsnitt för den aktuella dokumentposten. "
        "Använd dokumentets titel eller ämne som section_title, inte det "
        "uppladdade filnamnet. Lägg hela den källspecifika rapporttexten i "
        "section_body."
    )


def _document_report_section_array_field(
    ui_language: str | None,
) -> StructuredFieldDraft:
    description = (
        "One finished report section per source document."
        if ui_language == "en"
        else "Ett färdigt rapportavsnitt per källdokument."
    )
    return StructuredFieldDraft(
        name="source_sections",
        field_type="array",
        description=description,
        item_fields=[
            _section_title_field(ui_language),
            _section_body_field(ui_language),
        ],
    )


def _apply_previous_document_item_map_execution(
    planned_steps: tuple[PlannedStep, ...],
    *,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    updated_steps: list[PlannedStep] = []
    changed = False
    for planned_step in planned_steps:
        previous_step = updated_steps[-1] if updated_steps else None
        output_array = _single_output_array_field_name(planned_step.output_fields)
        if (
            previous_step is None
            or not planned_step_is_source_reader(previous_step)
            or previous_step.runtime_input_execution_mode != "per_source"
            or planned_step.input_source != InputSource.PREVIOUS_STEP
            or planned_step.input_type != InputType.JSON
            or planned_step.output_type != OutputType.JSON
            or output_array is None
        ):
            updated_steps.append(planned_step)
            continue
        annotated_step = replace(
            planned_step,
            instructions=_append_previous_document_item_map_instruction(
                planned_step.instructions,
                output_array=output_array,
                ui_language=ui_language,
            ),
            previous_item_map_enabled=True,
        )
        updated_steps.append(annotated_step)
        changed = changed or annotated_step != planned_step
    return tuple(updated_steps) if changed else planned_steps


def _single_output_array_field_name(
    output_fields: tuple[StructuredFieldDraft, ...],
) -> str | None:
    if len(output_fields) != 1:
        return None
    field = output_fields[0]
    if field.field_type != "array":
        return None
    return field.name


def _append_previous_document_item_map_instruction(
    instructions: str,
    *,
    output_array: str,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        addition = (
            "This step runs once per documents[] item from the previous reader. "
            f"Use only the current document item and return {output_array} with "
            "one item."
        )
    else:
        addition = (
            "Det här steget körs en gång per documents[]-post från föregående "
            f"läsare. Använd bara den aktuella dokumentposten och returnera "
            f"{output_array} med en post."
        )
    if addition in instructions:
        return instructions
    return f"{instructions}\n\n{addition}"


def _append_single_call_section_instruction(
    instructions: str,
    *,
    section_field_name: str,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        addition = (
            f"Write exactly one {section_field_name} item for each documents item. "
            "Keep the same order and copy its source_label into the matching section."
        )
    else:
        addition = (
            f"Skriv exakt en {section_field_name}-post för varje documents-post. "
            "Behåll samma ordning och kopiera source_label till motsvarande avsnitt."
        )
    if addition in instructions:
        return instructions
    return f"{instructions}\n\n{addition}"


def _append_single_call_reader_instruction(
    instructions: str,
    *,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        addition = (
            "Return one documents item per supplied source and set its "
            "source_label from that source's header or filename."
        )
    else:
        addition = (
            "Returnera en documents-post per angiven källa och sätt source_label "
            "från källans rubrik eller filnamn."
        )
    if addition in instructions:
        return instructions
    return f"{instructions}\n\n{addition}"


def _document_report_overview_writer(
    *,
    previous_step: PlannedStep,
    ui_language: str | None,
) -> PlannedStep:
    return PlannedStep(
        role="transform",
        name=_document_report_overview_writer_name(ui_language),
        instructions=_document_report_overview_writer_instructions(ui_language),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        output_mode=OutputMode.PASS_THROUGH,
        underlag_channel=derive_underlag_channel(
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.JSON,
            previous_step=previous_step,
            previous_field_refs=(),
        ),
        output_fields=_report_overview_fields(
            (),
            result_contract_output_fields=(),
            requested_section_fields=(),
            ui_language=ui_language,
        ),
    )


def _document_report_overview_writer_name(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Write overview"
    return "Skriv översikt"


def _document_report_overview_writer_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return (
            "Write a concise report title and synthesized overview across the "
            "completed source sections. Use only the supplied section content."
        )
    return (
        "Skriv en koncis rapporttitel och samlad översikt över de färdiga "
        "källavsnitten. Använd endast det tillhandahållna avsnittsinnehållet."
    )


def _document_report_compose_step(
    *,
    body_writer_step: PlannedStep,
    ui_language: str | None,
) -> PlannedStep:
    return PlannedStep(
        role="body_writer",
        name=body_writer_step.name,
        instructions=_compose_step_instructions(ui_language),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        output_type=OutputType.TEXT,
        output_mode=OutputMode.COMPOSE_TEXT,
        underlag_channel="whole_object",
        form_field_refs=body_writer_step.form_field_refs,
        review_mode=body_writer_step.review_mode,
    )


def _raise_document_report_compose_topology_missing(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    semantic_step_count: int,
) -> NoReturn:
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=DOCUMENT_REPORT_COMPOSE_TOPOLOGY_MISSING_FEEDBACK,
        log_context={
            "failure_code": "assembly_document_report_compose_topology_missing",
            "reason": "document_report_compose_topology_missing",
            "runtime_input_type": runtime_input_type.value,
            "final_output_type": final_output_type.value,
            "final_output_mode": (
                final_output_mode.value if final_output_mode is not None else None
            ),
            "pattern_ids": ",".join(pattern_ids),
            "chain_steps": ",".join(chain_steps),
            "semantic_step_count": semantic_step_count,
        },
    )


def _raise_document_report_citations_unsupported(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    report_disposition: ReportDisposition,
) -> NoReturn:
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=(
            "The requested citation sidecar cannot be preserved when the report "
            "is lowered through structured sections and deterministic composition. "
            "Use a structured-text result or remove the citation requirement."
        ),
        log_context={
            "failure_code": "assembly_document_report_citations_unsupported",
            "reason": "document_report_citations_unsupported",
            "runtime_input_type": runtime_input_type.value,
            "final_output_type": final_output_type.value,
            "report_disposition": report_disposition,
        },
    )


def _raise_document_report_model_ref_conflict(
    *,
    planned_step: PlannedStep,
    semantic_step: PlannedStep,
) -> NoReturn:
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=(
            "Report steps that lower into one semantic producer must use the same "
            "model selection."
        ),
        log_context={
            "failure_code": "assembly_document_report_model_ref_conflict",
            "reason": "document_report_model_ref_conflict",
            "planned_step_name": planned_step.name,
            "semantic_step_name": semantic_step.name,
        },
    )


def _raise_document_report_review_mode_conflict(
    *,
    planned_step: PlannedStep,
    semantic_step: PlannedStep,
) -> NoReturn:
    planned_review_mode = planned_step.review_mode
    semantic_review_mode = semantic_step.review_mode
    assert planned_review_mode is not None
    assert semantic_review_mode is not None
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=(
            "Multiple human-review checkpoints cannot be lowered into one report "
            "producer without losing a requested pause."
        ),
        log_context={
            "failure_code": "assembly_document_report_review_mode_conflict",
            "reason": "document_report_review_mode_conflict",
            "planned_step_name": planned_step.name,
            "semantic_step_name": semantic_step.name,
            "planned_review_mode": planned_review_mode.value,
            "semantic_review_mode": semantic_review_mode.value,
        },
    )


def _overview_writer_index(
    *,
    planned_steps: tuple[PlannedStep, ...],
    after_index: int,
    before_index: int,
) -> int | None:
    for index in range(before_index - 1, after_index, -1):
        planned_step = planned_steps[index]
        if (
            planned_step.output_type == OutputType.JSON
            and not planned_step.previous_item_map_enabled
            and planned_step.output_fields
        ):
            return index
    return None


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


def requested_output_section_contracts(
    requested: RequestedOutputSections,
) -> tuple[RequestedOutputSectionContract, ...]:
    if not requested.high_confidence:
        return ()
    return tuple(
        RequestedOutputSectionContract(
            original_label=original_label,
            derived_key=f"requested_section_{index}",
        )
        for index, original_label in enumerate(requested.sections, start=1)
    )


def _requested_section_fields(
    contracts: tuple[RequestedOutputSectionContract, ...],
    ui_language: str | None,
) -> tuple[StructuredFieldDraft, ...]:
    fields: list[StructuredFieldDraft] = []
    for contract in contracts:
        description = (
            f"Finished report section: {contract.original_label}."
            if ui_language == "en"
            else f"Färdigt rapportavsnitt: {contract.original_label}."
        )
        fields.append(
            StructuredFieldDraft(
                name=contract.derived_key,
                field_type="string",
                description=description,
            )
        )
    return tuple(fields)


def _compose_step_instructions(ui_language: str | None) -> str:
    if ui_language == "en":
        return "Assemble the final report deterministically from completed sections."
    return "Sätt ihop slutrapporten deterministiskt från färdiga avsnitt."


def bind_document_report_compose_inputs(
    *,
    step: StepSpec,
    prior_steps: list[StepSpec],
    form_field_refs: tuple[str, ...],
    requested_output_section_contracts: tuple[RequestedOutputSectionContract, ...],
    document_report_section_source: DocumentReportSectionSource | None,
    ui_language: str | None,
) -> StepSpec:
    prior_steps_by_ref = {prior.plan_step_ref: prior for prior in prior_steps}
    section_step = (
        prior_steps_by_ref.get(document_report_section_source.producer_ref)
        if document_report_section_source is not None
        else None
    )
    section_array = (
        document_report_section_source.field_name
        if document_report_section_source is not None
        else None
    )
    if document_report_section_source is not None and (
        section_step is None
        or section_array not in _schema_properties(section_step.output_contract)
    ):
        raise ValueError(
            "Compiler-lowered report section source is missing from the plan."
        )
    overview_step = _find_compose_overview_source(prior_steps)
    if (section_step is None or section_array is None) and overview_step is None:
        return step

    section_label_by_key = {
        contract.derived_key: contract.original_label
        for contract in requested_output_section_contracts
    }
    source_refs: list[dict[str, object]] = []
    if section_step is not None and section_array is not None:
        section_schema = _schema_properties(section_step.output_contract).get(
            section_array
        )
        source_refs.append(
            SourceRefBinding(
                step_ref=section_step.plan_step_ref,
                output="structured",
                field_path=(section_array,),
                item_template=_compose_section_item_template(
                    ui_language,
                    item_properties=_array_item_properties(section_schema),
                    section_label_by_key=section_label_by_key,
                ),
            ).binding_payload()
        )
        section_step_index = prior_steps.index(section_step)
        for producer in prior_steps[section_step_index + 1 :]:
            if producer is overview_step or producer.output_type != OutputType.JSON:
                continue
            for field_name, field_schema in _schema_properties(
                producer.output_contract
            ).items():
                source_refs.append(
                    _compose_additional_field_ref(
                        step_ref=producer.plan_step_ref,
                        field_name=field_name,
                        field_schema=field_schema,
                        label=None,
                    ).binding_payload()
                )
    question_parts = [
        _compose_report_title_question(
            overview_step=overview_step,
            ui_language=ui_language,
        )
    ]
    if form_field_refs:
        question_parts.append(
            "\n".join(
                f"{field_name}: {form_field_reference_expression(field_name)}"
                for field_name in form_field_refs
            )
        )
    if overview_step is not None:
        source_refs.append(
            SourceRefBinding(
                step_ref=overview_step.plan_step_ref,
                output="structured",
                field_path=(COMPOSE_OVERALL_OVERVIEW_KEY,),
                label=_compose_overview_label(ui_language),
            ).binding_payload()
        )
        for field_name, field_schema in _schema_properties(
            overview_step.output_contract
        ).items():
            if field_name in {
                COMPOSE_REPORT_TITLE_KEY,
                COMPOSE_OVERALL_OVERVIEW_KEY,
            }:
                continue
            source_refs.append(
                _compose_additional_field_ref(
                    step_ref=overview_step.plan_step_ref,
                    field_name=field_name,
                    field_schema=field_schema,
                    label=section_label_by_key.get(field_name),
                ).binding_payload()
            )
    retained_producer_index = (
        prior_steps.index(section_step)
        if section_step is not None
        else prior_steps.index(overview_step)
        if overview_step is not None
        else None
    )
    referenced_step_refs = {
        ref.step_ref for ref in source_ref_bindings({"source_refs": source_refs})
    }
    if retained_producer_index is None or any(
        producer.plan_step_ref not in referenced_step_refs
        for producer in prior_steps[retained_producer_index:]
        if producer.output_type == OutputType.JSON
        and producer.output_contract is not None
    ):
        raise ValueError(
            "Compiler-lowered report compose omitted a retained structured producer."
        )
    return step.model_copy(
        update={
            "input_bindings": {
                "question": "\n\n".join(question_parts),
                "source_refs": source_refs,
            },
            "input_contract": None,
        }
    )


def is_bound_document_report_compose_topology(
    spec: FlowDraftSpecCore,
    step: StepSpec,
) -> bool:
    if (
        step.input_source != InputSource.PREVIOUS_STEP
        or step.input_type != InputType.TEXT
        or step.output_type != OutputType.TEXT
        or step.output_mode != OutputMode.COMPOSE_TEXT
        or step.plan_step_ref not in (spec.document_body_writer_step_refs or ())
    ):
        return False
    step_index = next(
        (index for index, candidate in enumerate(spec.steps) if candidate is step),
        None,
    )
    if step_index is None or step_index + 2 != len(spec.steps):
        return False
    renderer = spec.steps[step_index + 1]
    if (
        renderer.input_source != InputSource.PREVIOUS_STEP
        or renderer.input_type != InputType.TEXT
        or renderer.output_mode != OutputMode.RENDER_VERBATIM
        or renderer.output_type not in {OutputType.DOCX, OutputType.PDF}
    ):
        return False
    prior_steps = spec.steps[:step_index]
    if (
        not prior_steps
        or prior_steps[0].input_source != InputSource.FLOW_INPUT
        or prior_steps[0].input_type not in {InputType.DOCUMENT, InputType.FILE}
        or prior_steps[0].output_type != OutputType.JSON
        or any(
            prior.input_source != InputSource.PREVIOUS_STEP
            or prior.input_type != InputType.JSON
            or prior.output_type != OutputType.JSON
            for prior in prior_steps[1:]
        )
    ):
        return False
    prior_steps_by_ref = {prior.plan_step_ref: prior for prior in prior_steps}
    refs = source_ref_bindings(step.input_bindings)
    if not refs or any(
        ref.output != "structured"
        or not ref.field_path
        or (producer := prior_steps_by_ref.get(ref.step_ref)) is None
        or producer.output_contract is None
        or missing_structured_output_path(
            producer.output_contract,
            ".".join(ref.field_path),
        )
        is not None
        for ref in refs
    ):
        return False

    section_source = _bound_document_report_section_source(refs)
    canonical_producer_indexes: list[int] = []
    if section_source is not None:
        section_producer = prior_steps_by_ref.get(section_source.producer_ref)
        if section_producer is None or section_producer.output_contract is None:
            return False
        section_ref = refs[0]
        section_schema = _schema_properties(section_producer.output_contract).get(
            section_source.field_name
        )
        section_fields = {
            COMPOSE_SECTION_TITLE_KEY,
            COMPOSE_SECTION_BODY_KEY,
            COMPOSE_SOURCE_LABEL_KEY,
        }
        if (
            section_schema is None
            or section_ref.item_template is None
            or not section_fields.issubset(_array_item_properties(section_schema))
            or not section_fields.issubset(
                item_template_field_names(section_ref.item_template)
            )
        ):
            return False
        canonical_producer_indexes.append(prior_steps.index(section_producer))
    for ref in refs:
        producer = prior_steps_by_ref[ref.step_ref]
        assert producer.output_contract is not None
        producer_fields = _schema_properties(producer.output_contract)
        if (
            ref.field_path == (COMPOSE_OVERALL_OVERVIEW_KEY,)
            and ref.item_template is None
            and {COMPOSE_REPORT_TITLE_KEY, COMPOSE_OVERALL_OVERVIEW_KEY}.issubset(
                producer_fields
            )
        ):
            canonical_producer_indexes.append(prior_steps.index(producer))
    if not canonical_producer_indexes:
        return False
    referenced_step_refs = {ref.step_ref for ref in refs}
    return all(
        producer.plan_step_ref in referenced_step_refs
        for producer in prior_steps[min(canonical_producer_indexes) :]
        if producer.output_type == OutputType.JSON
        and producer.output_contract is not None
    )


def document_report_compose_covers_requested_sections(
    composer: StepSpec,
    requested: RequestedOutputSections,
) -> bool:
    contracts = requested_output_section_contracts(requested)
    refs = source_ref_bindings(composer.input_bindings)
    section_source = _bound_document_report_section_source(refs)
    overview_producer_ref = next(
        (
            ref.step_ref
            for ref in refs
            if ref.field_path == (COMPOSE_OVERALL_OVERVIEW_KEY,)
            and ref.item_template is None
        ),
        None,
    )
    return bool(contracts) and all(
        any(
            (
                overview_producer_ref is not None
                and ref.step_ref == overview_producer_ref
                and ref.field_path == (contract.derived_key,)
                and ref.label == contract.original_label
            )
            or (
                section_source is not None
                and ref.step_ref == section_source.producer_ref
                and ref.field_path == (section_source.field_name,)
                and ref.item_template is not None
                and (
                    f"{_item_template_literal(contract.original_label)}: "
                    f"{{{contract.derived_key}}}" in ref.item_template.splitlines()
                )
            )
            for ref in refs
        )
        for contract in contracts
    )


def _bound_document_report_section_source(
    refs: tuple[SourceRefBinding, ...],
) -> DocumentReportSectionSource | None:
    if not refs or refs[0].item_template is None or len(refs[0].field_path) != 1:
        return None
    return DocumentReportSectionSource(
        producer_ref=refs[0].step_ref,
        field_name=refs[0].field_path[0],
    )


def _find_compose_overview_source(prior_steps: list[StepSpec]) -> StepSpec | None:
    for prior_step in reversed(prior_steps):
        properties = _schema_properties(prior_step.output_contract)
        if {COMPOSE_REPORT_TITLE_KEY, COMPOSE_OVERALL_OVERVIEW_KEY}.issubset(
            properties
        ):
            return prior_step
    return None


def _schema_properties(schema: object) -> dict[str, object]:
    if not isinstance(schema, Mapping):
        return {}
    typed_schema = cast(Mapping[str, object], schema)
    raw_properties = typed_schema.get("properties")
    if not isinstance(raw_properties, Mapping):
        return {}
    properties = cast(Mapping[object, object], raw_properties)
    return {
        key: value
        for key, value in properties.items()
        if isinstance(key, str) and isinstance(value, Mapping)
    }


def _array_item_properties(schema: object) -> dict[str, object]:
    if not isinstance(schema, Mapping):
        return {}
    typed_schema = cast(Mapping[str, object], schema)
    raw_type = typed_schema.get("type")
    if raw_type != "array":
        return {}
    return _schema_properties(typed_schema.get("items"))


def _compose_report_title_question(
    *,
    overview_step: StepSpec | None,
    ui_language: str | None,
) -> str:
    if overview_step is not None:
        return f"# {{{{ {overview_step.plan_step_ref}.output.structured.{COMPOSE_REPORT_TITLE_KEY} }}}}"
    return "# Source report" if ui_language == "en" else "# Rapport per källa"


def _compose_section_item_template(
    ui_language: str | None,
    *,
    item_properties: Mapping[str, object],
    section_label_by_key: Mapping[str, str],
) -> str:
    source_label = "Source" if ui_language == "en" else "Källa"
    template = (
        f"## {{{COMPOSE_SECTION_TITLE_KEY}}}\n\n"
        f"{{{COMPOSE_SECTION_BODY_KEY}}}\n\n"
        f"{source_label}: {{{COMPOSE_SOURCE_LABEL_KEY}}}"
    )
    reserved_fields = {
        COMPOSE_SECTION_TITLE_KEY,
        COMPOSE_SECTION_BODY_KEY,
        COMPOSE_SOURCE_LABEL_KEY,
        "source_file_id",
    }
    additional_fields = [
        f"{_item_template_literal(section_label_by_key.get(field_name, _humanized_field_name(field_name)))}: "
        f"{{{field_name}}}"
        for field_name in item_properties
        if field_name not in reserved_fields
    ]
    if not additional_fields:
        return template
    return f"{template}\n\n" + "\n\n".join(additional_fields)


def _item_template_literal(value: str) -> str:
    return value.replace("{", "&#123;").replace("}", "&#125;")


def _compose_overview_label(ui_language: str | None) -> str:
    return "Overall overview" if ui_language == "en" else "Samlad översikt"


def _compose_field_label(field_name: str) -> str:
    return _humanized_field_name(field_name)


def _compose_additional_field_ref(
    *,
    step_ref: str,
    field_name: str,
    field_schema: object,
    label: str | None,
) -> SourceRefBinding:
    item_properties = _array_item_properties(field_schema)
    return SourceRefBinding(
        step_ref=step_ref,
        output="structured",
        field_path=(field_name,),
        label=label or _compose_field_label(field_name),
        item_template=(
            _compose_object_item_template(item_properties) if item_properties else None
        ),
    )


def _compose_object_item_template(
    item_properties: Mapping[str, object],
) -> str:
    return "\n".join(
        f"{_humanized_field_name(field_name)}: {{{field_name}}}"
        for field_name in item_properties
    )


def _humanized_field_name(field_name: str) -> str:
    return field_name.replace("_", " ").strip().capitalize()

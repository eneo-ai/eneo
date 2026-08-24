from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import NoReturn, assert_never

from eneo.flows.ai_builder.ai_builder_assembly.document_report.diagnostics import (
    append_combined_model_selection_diagnostics as _append_combined_model_selection_diagnostics,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.diagnostics import (
    raise_document_report_compose_topology_missing as _raise_document_report_compose_topology_missing,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.merge import (
    complete_source_section_fields_for_compose as _complete_source_section_fields_for_compose,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.merge import (
    merge_report_writer_semantics as _merge_report_writer_semantics,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.merge import (
    report_overview_fields as _report_overview_fields,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.merge import (
    section_body_field as _section_body_field,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.merge import (
    section_title_field as _section_title_field,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report.topology import (
    COMPOSE_SECTION_BODY_KEY,
    COMPOSE_SECTION_TITLE_KEY,
)
from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    DocumentReportSectionSource,
    PlannedStep,
    derive_underlag_channel,
    planned_step_is_source_reader,
)
from eneo.flows.ai_builder.ai_builder_domain_models import LintWarning
from eneo.flows.ai_builder.ai_builder_field_identity import (
    fold_result_field_name,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import make_plan_step_ref
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSectionContract,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import SemanticStepIntent
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
    allocate_injected_source_field_name,
    complete_structured_source_reader_fields,
    structured_fields_have_document_items,
)
from eneo.flows.ai_builder.planning_state import ReportDisposition
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.main.logging import get_logger

logger = get_logger(__name__)


def admit_document_report_semantic_shape(
    steps: Sequence[SemanticStepIntent],
    semantic_origin_eligibility: Sequence[bool],
    *,
    runtime_input_type: InputType,
    final_semantic_output_type: OutputType,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    report_disposition: ReportDisposition | None,
    per_source_runtime: bool,
    ui_language: str | None,
    reserved_source_output_field_names: frozenset[str] = frozenset(),
) -> tuple[tuple[SemanticStepIntent, ...], tuple[bool, ...]]:
    semantic_steps = tuple(steps)
    eligibility = tuple(semantic_origin_eligibility)
    if len(semantic_steps) != len(eligibility):
        raise ValueError("Semantic origin eligibility must align with semantic steps.")
    if (
        not semantic_steps
        or runtime_input_type
        not in {
            InputType.DOCUMENT,
            InputType.FILE,
            InputType.JSON,
        }
        or final_semantic_output_type != OutputType.TEXT
    ):
        return semantic_steps, eligibility

    if per_source_runtime and report_disposition is None:
        reader_step = semantic_steps[0]
        # The authored reader fields are the model's typed record of which
        # source facts downstream steps need. They are wrapped into the
        # per-source ``documents[]`` items by the admission helper below, never
        # replaced: substituting a generic material field here discarded typed
        # facts like reported times while the injected instructions still told
        # the model to preserve them.
        reader_fields = tuple(reader_step.output_fields or ())
        reader_fields = complete_structured_source_reader_fields(
            reader_fields,
            required_fields=source_reader_required_fields,
            reserved_field_names=reserved_source_output_field_names,
        )
        admitted_reader = reader_step.model_copy(
            update={
                "name": _source_report_reader_name(ui_language),
                "instructions": _per_source_report_reader_instructions(
                    reader_step.instructions,
                    ui_language=ui_language,
                ),
                "output_type": OutputType.JSON,
                "output_fields": list(
                    _admitted_document_report_source_fields(
                        reader_fields,
                        ui_language=ui_language,
                        reserved_field_names=reserved_source_output_field_names,
                    )
                ),
            }
        )
        if len(semantic_steps) == 1:
            writer_step = reader_step.model_copy(
                update={
                    "name": _source_report_writer_name(ui_language),
                    "instructions": reader_step.instructions,
                    "output_type": OutputType.TEXT,
                    "output_fields": None,
                }
            )
            return (admitted_reader, writer_step), (
                eligibility[0],
                eligibility[0],
            )
        return (admitted_reader, *semantic_steps[1:]), eligibility

    if len(semantic_steps) == 1:
        semantic_step = semantic_steps[0]
        source_fields = tuple(semantic_step.output_fields or ())
        if not source_fields:
            source_fields = complete_structured_source_reader_fields(
                (),
                required_fields=source_reader_required_fields,
                reserved_field_names=reserved_source_output_field_names,
            )
        if not source_fields:
            if report_disposition is None:
                return semantic_steps, eligibility
            source_fields = (
                _default_document_report_source_field(
                    ui_language,
                    reserved_field_names=reserved_source_output_field_names,
                ),
            )
        source_fields = complete_structured_source_reader_fields(
            source_fields,
            required_fields=(),
            reserved_field_names=reserved_source_output_field_names,
        )
        if report_disposition is not None:
            source_fields = _admitted_document_report_source_fields(
                source_fields,
                ui_language=ui_language,
                reserved_field_names=reserved_source_output_field_names,
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
        return (reader_step, writer_step), (False, eligibility[0])

    if report_disposition is None:
        return semantic_steps, eligibility
    reader_step = semantic_steps[0]
    source_fields = complete_structured_source_reader_fields(
        tuple(reader_step.output_fields or ())
        or (
            _default_document_report_source_field(
                ui_language,
                reserved_field_names=reserved_source_output_field_names,
            ),
        ),
        required_fields=(),
        reserved_field_names=reserved_source_output_field_names,
    )
    admitted_reader = reader_step.model_copy(
        update={
            "output_type": OutputType.JSON,
            "output_fields": list(
                _admitted_document_report_source_fields(
                    source_fields,
                    ui_language=ui_language,
                    reserved_field_names=reserved_source_output_field_names,
                )
            ),
        }
    )
    return (admitted_reader, *semantic_steps[1:]), eligibility


def _admitted_document_report_source_fields(
    source_fields: tuple[StructuredFieldDraft, ...],
    *,
    ui_language: str | None,
    reserved_field_names: frozenset[str],
) -> tuple[StructuredFieldDraft, ...]:
    # Wrap first, then complete: the fallback material capture must be a
    # SIBLING of the authored fields inside each document item. Completing
    # before wrapping nested it inside a sole authored array, so a document
    # whose array was empty could represent no material at all.
    if not structured_fields_have_document_items(source_fields):
        source_fields = (
            _document_report_source_array_field(source_fields, ui_language=ui_language),
        )
    return tuple(
        field.model_copy(
            update={
                "item_fields": list(
                    _with_document_material_capture(
                        tuple(field.item_fields or ()),
                        ui_language=ui_language,
                        reserved_field_names=reserved_field_names,
                    )
                )
            }
        )
        if structured_fields_have_document_items((field,))
        else field
        for field in source_fields
    )


def _with_document_material_capture(
    item_fields: tuple[StructuredFieldDraft, ...],
    *,
    ui_language: str | None,
    reserved_field_names: frozenset[str],
) -> tuple[StructuredFieldDraft, ...]:
    material = fold_result_field_name("source_material")
    if any(fold_result_field_name(field.name) == material for field in item_fields):
        return item_fields
    description = (
        "Exact source facts needed downstream, including identifiers, "
        "dates, times, numbers, claims, missing values, and uncertainty."
        if ui_language == "en"
        else "Exakta källuppgifter som behövs senare, inklusive "
        "identifierare, datum, tider, tal, påståenden, saknade värden "
        "och osäkerheter."
    )
    return (
        *item_fields,
        StructuredFieldDraft(
            name=allocate_injected_source_field_name(
                "source_material",
                reserved_field_names=reserved_field_names
                | frozenset(field.name for field in item_fields),
            ),
            field_type="string",
            description=description,
        ),
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
    *,
    reserved_field_names: frozenset[str],
) -> StructuredFieldDraft:
    description = (
        "Source-grounded material needed to write the requested report."
        if ui_language == "en"
        else "Källgrundat underlag som behövs för att skriva den begärda rapporten."
    )
    return StructuredFieldDraft(
        name=allocate_injected_source_field_name(
            "source_material",
            reserved_field_names=reserved_field_names,
        ),
        field_type="string",
        description=description,
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


def _per_source_report_reader_instructions(
    authored_instructions: str,
    *,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        contract = (
            "Read only the current source. Preserve all source-grounded facts "
            "needed for downstream analysis, including exact identifiers, dates, "
            "times, numbers, claims, missing values, and uncertainty. Do not infer "
            "across sources or assume that the current source has a particular "
            "format. Apply the proposed extraction requirement below only where "
            "the current source supports it."
        )
    else:
        contract = (
            "Läs endast den aktuella källan. Bevara alla källgrundade uppgifter som "
            "behövs för efterföljande analys, inklusive exakta identifierare, datum, "
            "tider, tal, påståenden, saknade värden och osäkerheter. Dra inga "
            "slutsatser mellan källor och anta inte att den aktuella källan har ett "
            "visst format. Tillämpa det föreslagna extraktionskravet nedan endast "
            "där den aktuella källan stöder det."
        )
    return f"{contract}\n\n{authored_instructions}"


def _multi_source_downstream_instructions(
    authored_instructions: str,
    *,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        contract = (
            "The preceding material is the complete normalized source set. Use "
            "every relevant documents item, preserve each source label, keep "
            "conflicting values separate, and do not let this step's name limit "
            "which sources are considered."
        )
    else:
        contract = (
            "Det föregående materialet är den fullständiga normaliserade "
            "källuppsättningen. Använd varje relevant documents-post, bevara varje "
            "källmärkning, håll motstridiga värden åtskilda och låt inte stegets "
            "namn begränsa vilka källor som beaktas."
        )
    if contract in authored_instructions:
        return authored_instructions
    return f"{authored_instructions}\n\n{contract}"


def apply_multi_source_reader_consumer_contract(
    steps: Sequence[SemanticStepIntent],
    *,
    ui_language: str | None,
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if len(semantic_steps) < 2 or not structured_fields_have_document_items(
        tuple(semantic_steps[0].output_fields or ())
    ):
        return semantic_steps
    consumer = semantic_steps[1]
    return (
        semantic_steps[0],
        consumer.model_copy(
            update={
                "instructions": _multi_source_downstream_instructions(
                    consumer.instructions,
                    ui_language=ui_language,
                )
            }
        ),
        *semantic_steps[2:],
    )


def append_terminal_helper_output_fields(
    instructions: str,
    output_fields: Sequence[StructuredFieldDraft],
    *,
    ui_language: str | None,
) -> str:
    # Naming raw field keys here invited JSON envelopes: a live writer
    # answered `{"document_body": ...}` and the renderer printed the braces
    # verbatim. Fold the fields' MEANING (descriptions), and demand prose.
    field_meanings = "; ".join(
        (field.description.strip() or field.name).rstrip(".")
        for field in output_fields
        if field.name
    )
    if not field_meanings:
        return instructions
    if ui_language == "en":
        field_instruction = (
            "Write the result as readable prose with headings — never as "
            "JSON or named fields. The text must cover: "
        )
    else:
        field_instruction = (
            "Skriv resultatet som löpande läsbar text med rubriker — aldrig "
            "som JSON eller namngivna fält. Texten ska täcka: "
        )
    return f"{instructions}\n\n{field_instruction}{field_meanings}."


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
    field_diagnostics: list[LintWarning] | None = None,
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

    combined_producer_model_refs: list[str] = []
    renderer_step = planned_steps[-1]
    body_writer_step = planned_steps[-2]
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
                distinct_model_refs = {
                    model_ref
                    for model_ref in (
                        content_steps[section_index].model_ref,
                        *(step.model_ref for step in remaining_report_semantics),
                        body_writer_step.model_ref,
                    )
                    if model_ref is not None
                }
                for semantic_step in remaining_report_semantics:
                    content_steps[section_index] = _merge_report_writer_semantics(
                        content_steps[section_index],
                        semantic_step=semantic_step,
                    )
                content_steps[section_index] = _merge_report_writer_semantics(
                    content_steps[section_index],
                    semantic_step=body_writer_step,
                )
                if len(distinct_model_refs) > 1:
                    model_ref = content_steps[section_index].model_ref
                    assert model_ref is not None
                    combined_producer_model_refs.append(model_ref)
        case "synthesized_overview":
            section_index = reader_index
            section_field_name = None
        case _ as unreachable:
            assert_never(unreachable)

    match report_disposition:
        case "synthesized_overview" | "both":
            overview_original_steps = tuple(content_steps[section_index + 1 :])
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
            overview_step = content_steps[overview_index]
            collapsed_model_refs = tuple(
                step.model_ref
                for step in overview_original_steps
                if _step_outputs_report_text(step) or step is overview_step
            ) + (body_writer_step.model_ref,)
            terminal_model_ref = next(
                (
                    model_ref
                    for model_ref in reversed(collapsed_model_refs)
                    if model_ref is not None
                ),
                None,
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
            )
            content_steps[overview_index] = replace(
                content_steps[overview_index],
                model_ref=terminal_model_ref,
            )
            if (
                len(
                    {
                        model_ref
                        for model_ref in collapsed_model_refs
                        if model_ref is not None
                    }
                )
                > 1
            ):
                assert terminal_model_ref is not None
                combined_producer_model_refs.append(terminal_model_ref)
        case "per_source_sections":
            pass
        case _ as unreachable:
            assert_never(unreachable)

    _append_combined_model_selection_diagnostics(
        combined_producer_model_refs,
        field_diagnostics=field_diagnostics,
        ui_language=ui_language,
    )

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

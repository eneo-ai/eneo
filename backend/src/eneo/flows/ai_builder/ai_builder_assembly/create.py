from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, assert_never

from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    architecture_hints_are_supported,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_assembly.document_report import (
    DOCUMENT_REPORT_COMPOSE_TOPOLOGY_MISSING_FEEDBACK,
    admit_document_report_semantic_shape,
    append_terminal_helper_output_fields,
    lower_document_report_topology,
    requested_output_section_contracts,
)
from eneo.flows.ai_builder.ai_builder_assembly.fixed_steps import (
    fixed_audio_transcription_step,
    render_verbatim_step,
    template_fill_step,
    template_variable_reader_step,
)
from eneo.flows.ai_builder.ai_builder_assembly.lower import lower_assembly_plan
from eneo.flows.ai_builder.ai_builder_assembly.plan import (
    SOURCE_READER_INPUT_TYPES,
    FlowAssemblyPlan,
    PlannedStep,
    PlannedStepRole,
    derive_underlag_channel,
    planned_step_is_source_reader,
)
from eneo.flows.ai_builder.ai_builder_domain_models import LintWarning
from eneo.flows.ai_builder.ai_builder_field_identity import fold_result_field_name
from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    FlowInputFieldProvenance,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
    structured_field_draft_names,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    ResultOutputFieldRole,
    structured_field_names_satisfy_result_field,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
    add_runtime_source_file_id_field,
    complete_structured_source_reader_fields,
    log_dropped_source_contract_shadow_fields,
    source_capture_fields_from_terminal_schema,
    source_contract_shadow_form_field_names,
    source_reader_leaf_field_name,
    structured_fields_have_document_items,
    structured_fields_have_source_leaf,
)
from eneo.flows.ai_builder.planning_state import (
    AggregationIntent,
    ConfirmedRuntimeMetadataField,
    ReportDisposition,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.json_types import JsonObject
from eneo.main.logging import get_logger

logger = get_logger(__name__)

_DOCUMENT_OUTPUT_TYPES = frozenset({OutputType.PDF, OutputType.DOCX})
_SOURCE_INPUT_TYPES = frozenset(
    {
        InputType.AUDIO,
        InputType.DOCUMENT,
        InputType.FILE,
        InputType.JSON,
        InputType.TEXT,
    }
)
_FILE_INPUT_TYPES = frozenset({InputType.DOCUMENT, InputType.FILE})
CreateAssemblyRejectionReason = Literal[
    "aggregate_requires_text_or_document_output",
    "all_previous_step_cannot_use_explicit_refs",
    "compare_json_requires_structured_producers",
    "confirmed_runtime_input_source_output_collision",
    "audio_requires_linear",
    "docx_template_form_fields_mismatch",
    "docx_template_shape_unsupported",
    "document_report_compose_topology_missing",
    "empty_steps",
    "explicit_refs_not_supported",
    "form_field_no_legal_target",
    "form_field_placement_mismatch",
    "form_field_required_semantic_target_missing",
    "invalid_template_fill_mode",
    "plan_invariant_failed",
    "pure_audio_transcription_requires_no_reader_fields",
    "pure_audio_transcription_shape_unsupported",
    "section_writer_structured_source_ambiguous",
    "source_file_first_step_requires_json",
    "step_output_type_mismatch",
    "terminal_schema_requires_json_terminal",
    "unsupported_aggregation_intent",
    "unsupported_architecture_hints",
    "unsupported_final_output_type",
    "unsupported_output_mode",
    "unsupported_runtime_input_type",
    "unsupported_runtime_output_tuple",
]

_REJECTION_FEEDBACK: dict[CreateAssemblyRejectionReason, str] = {
    "aggregate_requires_text_or_document_output": (
        "Aggregate and compare create flows must end in text or a document artifact; "
        "remove the JSON terminal shape or make the flow linear."
    ),
    "all_previous_step_cannot_use_explicit_refs": (
        "The fan-in step must combine prior outputs as a whole. Remove explicit "
        "form-field or previous-output refs from that semantic step."
    ),
    "compare_json_requires_structured_producers": (
        "A compare flow delivering JSON needs every earlier semantic step to "
        "declare structured output_fields so the terminal can consume them "
        "through typed references."
    ),
    "confirmed_runtime_input_source_output_collision": (
        "A confirmed runtime input field has the same identity as a source output "
        "field. Keep the runtime input field and rename the source output field."
    ),
    "audio_requires_linear": "Audio create flows must be linear.",
    "docx_template_form_fields_mismatch": (
        "A DOCX template-fill semantic step may only reference declared "
        "runtime form fields."
    ),
    "docx_template_shape_unsupported": (
        "DOCX template-fill flows require a linear chain of JSON or text "
        "semantic steps. End with either a JSON step whose string "
        "output_fields carry the folded placeholder names, or a text-writing "
        "step for the template variables."
    ),
    "document_report_compose_topology_missing": (
        DOCUMENT_REPORT_COMPOSE_TOPOLOGY_MISSING_FEEDBACK
    ),
    "empty_steps": "The proposal must contain at least one semantic step.",
    "explicit_refs_not_supported": (
        "Create-mode semantic steps must not author uses_previous_fields or "
        "uses_previous_outputs. Describe the data needed in instructions and "
        "output_fields instead."
    ),
    "form_field_no_legal_target": (
        "A runtime form field has no legal target in the assembled flow topology."
    ),
    "form_field_placement_mismatch": (
        "Every runtime form field must be referenced by at least one semantic "
        "step, and every referenced field must be declared."
    ),
    "form_field_required_semantic_target_missing": (
        "A runtime form field's purpose requires a semantic target that does not "
        "exist in the assembled flow topology."
    ),
    "invalid_template_fill_mode": (
        "template_fill output mode is only valid for DOCX template-fill flows."
    ),
    "plan_invariant_failed": "The assembled flow violated a construction invariant.",
    "pure_audio_transcription_requires_no_reader_fields": (
        "Pure audio transcription must not request structured source-reader fields."
    ),
    "pure_audio_transcription_shape_unsupported": (
        "Pure audio transcription requires one plain text semantic step and no "
        "runtime form fields."
    ),
    "section_writer_structured_source_ambiguous": (
        "Consolidate the required facts into one structured preparation step, "
        "or use one supported terminal aggregate before adding section writers."
    ),
    "source_file_first_step_requires_json": (
        "For document and file inputs, the first semantic step must extract JSON "
        "before text-writing steps consume it."
    ),
    "step_output_type_mismatch": (
        "A semantic step's output_type or output_fields conflicts with the confirmed "
        "terminal output shape."
    ),
    "terminal_schema_requires_json_terminal": (
        "A terminal output schema can only be used by a linear JSON terminal flow."
    ),
    "unsupported_aggregation_intent": (
        "Create assembly supports only linear, aggregate, and compare intents."
    ),
    "unsupported_architecture_hints": (
        "The confirmed architecture pattern is not supported by create assembly."
    ),
    "unsupported_final_output_type": (
        "Create assembly supports text, JSON, PDF, and DOCX terminal outputs."
    ),
    "unsupported_output_mode": (
        "Create assembly supports pass-through output mode for semantic model steps."
    ),
    "unsupported_runtime_input_type": (
        "Create assembly supports text, JSON, audio, document, and file inputs."
    ),
    "unsupported_runtime_output_tuple": (
        "Create assembly does not support JSON input with text output."
    ),
}


@dataclass(frozen=True, slots=True)
class CreateAssemblyRejection:
    reason: CreateAssemblyRejectionReason
    step_index: int | None = None
    detail: str | None = None
    field_names: tuple[str, ...] = ()

    @property
    def failure_code(self) -> str:
        if self.reason in {
            "confirmed_runtime_input_source_output_collision",
            "section_writer_structured_source_ambiguous",
        }:
            return self.reason
        return f"assembly_{self.reason}"

    @property
    def feedback(self) -> str:
        feedback = self.detail or _REJECTION_FEEDBACK[self.reason]
        if self.step_index is None:
            return feedback
        return f"Step {self.step_index}: {feedback}"


def _reject(
    reason: CreateAssemblyRejectionReason,
    *,
    step_index: int | None = None,
    detail: str | None = None,
    field_names: tuple[str, ...] = (),
) -> CreateAssemblyRejection:
    return CreateAssemblyRejection(
        reason=reason,
        step_index=step_index,
        detail=detail,
        field_names=field_names,
    )


def try_compile_create_intent_with_assembly(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    is_pure_audio_transcription: bool,
    form_fields: Sequence[FormFieldSpec],
    runtime_input_fields: Sequence[ConfirmedRuntimeMetadataField],
    template_form_field_names: tuple[str, ...],
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    aggregation_intent: AggregationIntent,
    terminal_output_schema: JsonObject | None,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    result_contract_required_roles: tuple[ResultOutputFieldRole, ...],
    requested_output_sections: RequestedOutputSections,
    report_disposition: ReportDisposition | None,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
    terminal_obligation_instructions: str | None = None,
    field_provenance: dict[str, FlowInputFieldProvenance] | None = None,
    field_diagnostics: list[LintWarning] | None = None,
) -> FlowDraftSpecCore | CreateAssemblyRejection:
    try:
        plan = _assemble_create_intent(
            intent,
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
            is_pure_audio_transcription=is_pure_audio_transcription,
            form_fields=form_fields,
            runtime_input_fields=runtime_input_fields,
            template_form_field_names=template_form_field_names,
            pattern_ids=pattern_ids,
            chain_steps=chain_steps,
            aggregation_intent=aggregation_intent,
            terminal_output_schema=terminal_output_schema,
            source_reader_required_fields=source_reader_required_fields,
            result_contract_output_fields=result_contract_output_fields,
            result_contract_required_roles=result_contract_required_roles,
            requested_output_sections=requested_output_sections,
            report_disposition=report_disposition,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
            terminal_obligation_instructions=terminal_obligation_instructions,
            field_provenance=field_provenance,
            field_diagnostics=field_diagnostics,
        )
        if isinstance(plan, CreateAssemblyRejection):
            return plan
        return lower_assembly_plan(plan, field_diagnostics=field_diagnostics)
    except ValueError as error:
        return _reject("plan_invariant_failed", detail=str(error))


def _assemble_create_intent(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    is_pure_audio_transcription: bool,
    form_fields: Sequence[FormFieldSpec],
    runtime_input_fields: Sequence[ConfirmedRuntimeMetadataField],
    template_form_field_names: tuple[str, ...],
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    aggregation_intent: AggregationIntent,
    terminal_output_schema: JsonObject | None,
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    result_contract_required_roles: tuple[ResultOutputFieldRole, ...],
    requested_output_sections: RequestedOutputSections,
    report_disposition: ReportDisposition | None,
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
    terminal_obligation_instructions: str | None = None,
    field_provenance: dict[str, FlowInputFieldProvenance] | None = None,
    field_diagnostics: list[LintWarning] | None = None,
) -> FlowAssemblyPlan | CreateAssemblyRejection:
    if runtime_input_type == InputType.JSON and final_output_type == OutputType.TEXT:
        return _reject("unsupported_runtime_output_tuple")
    if not architecture_hints_are_supported(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
    ):
        return _reject("unsupported_architecture_hints")
    if aggregation_intent not in {"linear", "aggregate", "compare"}:
        return _reject("unsupported_aggregation_intent")
    if not intent.steps:
        return _reject("empty_steps")
    if runtime_input_type not in _SOURCE_INPUT_TYPES:
        return _reject("unsupported_runtime_input_type")
    provider_collision_names = _provider_source_output_collision_names(
        intent=intent,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        runtime_input_fields=runtime_input_fields,
    )
    if provider_collision_names:
        return _reject(
            "confirmed_runtime_input_source_output_collision",
            detail=(
                "Rename the source output field(s) that duplicate confirmed "
                "runtime input: " + ", ".join(provider_collision_names) + "."
            ),
            field_names=provider_collision_names,
        )
    if runtime_input_type == InputType.AUDIO and aggregation_intent != "linear":
        return _reject("audio_requires_linear")
    document_artifact_requested = final_output_type in _DOCUMENT_OUTPUT_TYPES
    if (
        final_output_type
        not in {OutputType.TEXT, OutputType.JSON} | _DOCUMENT_OUTPUT_TYPES
    ):
        return _reject("unsupported_final_output_type")
    template_fill_requested = (
        final_output_type == OutputType.DOCX
        and final_output_mode == OutputMode.TEMPLATE_FILL
    )
    if final_output_mode == OutputMode.TEMPLATE_FILL and not template_fill_requested:
        return _reject("invalid_template_fill_mode")
    if terminal_output_schema is not None and (
        document_artifact_requested or final_output_type != OutputType.JSON
    ):
        return _reject("terminal_schema_requires_json_terminal")
    if aggregation_intent == "aggregate" and (
        terminal_output_schema is not None or final_output_type == OutputType.JSON
    ):
        # DECIDED product direction (B9(e2)): compare flows may deliver
        # JSON through typed structured fan-in; aggregate stays text or
        # document.
        return _reject("aggregate_requires_text_or_document_output")
    if template_fill_requested:
        return _assemble_docx_template_fill(
            intent,
            runtime_input_type=runtime_input_type,
            form_fields=form_fields,
            runtime_input_fields=runtime_input_fields,
            template_form_field_names=template_form_field_names,
            source_reader_required_fields=source_reader_required_fields,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            aggregation_intent=aggregation_intent,
            ui_language=ui_language,
            field_provenance=field_provenance,
            field_diagnostics=field_diagnostics,
        )
    if is_pure_audio_transcription:
        if source_reader_required_fields:
            return _reject("pure_audio_transcription_requires_no_reader_fields")
        return _assemble_pure_audio_transcription(
            intent,
            form_fields=form_fields,
            runtime_input_fields=runtime_input_fields,
            template_form_field_names=template_form_field_names,
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
    semantic_output_mode = OutputMode.PASS_THROUGH
    if (
        not document_artifact_requested
        and (final_output_mode or OutputMode.PASS_THROUGH) != OutputMode.PASS_THROUGH
    ):
        return _reject("unsupported_output_mode")

    terminal_semantic_output_type = _terminal_semantic_output_type(final_output_type)
    planned_steps: list[PlannedStep] = []
    semantic_steps = _semantic_steps_without_terminal_document_render_helper(
        intent.steps,
        final_output_type=final_output_type,
        document_artifact_requested=document_artifact_requested,
        ui_language=ui_language,
    )
    semantic_origin_eligibility = (True,) * len(semantic_steps)
    semantic_steps, semantic_origin_eligibility = admit_document_report_semantic_shape(
        semantic_steps,
        semantic_origin_eligibility,
        runtime_input_type=runtime_input_type,
        final_semantic_output_type=terminal_semantic_output_type,
        source_reader_required_fields=source_reader_required_fields,
        report_disposition=report_disposition,
        ui_language=ui_language,
        reserved_source_output_field_names=frozenset(
            record.value.variable_name for record in runtime_input_fields
        ),
    )
    semantic_steps = _semantic_steps_with_terminal_obligation(
        semantic_steps,
        terminal_obligation_instructions=terminal_obligation_instructions,
    )
    semantic_steps = _semantic_steps_with_terminal_text_fields_folded(
        semantic_steps,
        final_semantic_output_type=terminal_semantic_output_type,
        ui_language=ui_language,
    )
    followup_step_index: int | None = None
    if report_disposition is None:
        semantic_steps, followup_step_index = (
            _semantic_steps_with_result_contract_fields(
                semantic_steps,
                runtime_input_type=runtime_input_type,
                final_semantic_output_type=terminal_semantic_output_type,
                result_contract_output_fields=result_contract_output_fields,
                result_contract_required_roles=result_contract_required_roles,
                terminal_output_schema=terminal_output_schema,
                ui_language=ui_language,
            )
        )
        if followup_step_index is not None:
            semantic_origin_eligibility = (
                *semantic_origin_eligibility[:followup_step_index],
                False,
                *semantic_origin_eligibility[followup_step_index:],
            )
    previous_output_type: OutputType | None = None
    has_source_prefix = False
    if runtime_input_type == InputType.AUDIO:
        transcription_step = fixed_audio_transcription_step(
            runtime_required=runtime_required,
            runtime_max_files=runtime_max_files,
            ui_language=ui_language,
        )
        planned_steps.append(transcription_step)
        previous_output_type = OutputType.TEXT
        has_source_prefix = True
    for index, semantic_step in enumerate(semantic_steps):
        is_terminal_semantic_step = index == len(semantic_steps) - 1
        if semantic_step.uses_previous_fields or semantic_step.uses_previous_outputs:
            return _reject("explicit_refs_not_supported", step_index=index + 1)
        step_output_type = _linear_step_output_type(
            output_type=semantic_step.output_type,
            output_fields=semantic_step.output_fields,
            final_output_type=terminal_semantic_output_type,
            is_terminal=is_terminal_semantic_step,
        )
        if step_output_type is None:
            return _reject("step_output_type_mismatch", step_index=index + 1)
        if (
            index == 0
            and runtime_input_type in _FILE_INPUT_TYPES
            and step_output_type != OutputType.JSON
        ):
            return _reject(
                "source_file_first_step_requires_json",
                step_index=index + 1,
            )
        aggregate_terminal_previous_refs = _aggregate_terminal_previous_structured_refs(
            planned_steps=tuple(planned_steps),
            aggregation_intent=aggregation_intent,
            is_terminal_semantic_step=is_terminal_semantic_step,
        )
        if (
            is_terminal_semantic_step
            and aggregation_intent == "compare"
            and step_output_type == OutputType.JSON
            and len(planned_steps) >= 2
            and not aggregate_terminal_previous_refs
        ):
            # Silent fan-in would hide which producer failed to declare its
            # contract; a compare JSON terminal must consume typed refs.
            return _reject(
                "compare_json_requires_structured_producers",
                step_index=index + 1,
            )
        input_source = _linear_step_input_source(
            step_index=index,
            semantic_step_count=len(semantic_steps),
            aggregation_intent=aggregation_intent,
            has_source_prefix=has_source_prefix,
            prior_step_count=len(planned_steps),
            aggregate_terminal_uses_source_refs=bool(aggregate_terminal_previous_refs),
        )
        if input_source == InputSource.ALL_PREVIOUS_STEPS and (
            semantic_step.uses_previous_fields or semantic_step.uses_previous_outputs
        ):
            return _reject(
                "all_previous_step_cannot_use_explicit_refs",
                step_index=index + 1,
            )
        input_type = _linear_step_input_type(
            input_source=input_source,
            runtime_input_type=runtime_input_type,
            previous_output_type=previous_output_type,
            output_type=step_output_type,
        )
        previous_planned_step = (
            planned_steps[-1] if input_source == InputSource.PREVIOUS_STEP else None
        )
        previous_field_refs = (
            aggregate_terminal_previous_refs
            or _derived_terminal_text_previous_field_refs(
                planned_steps=tuple(planned_steps),
                input_source=input_source,
                input_type=input_type,
                output_type=step_output_type,
                is_terminal_semantic_step=is_terminal_semantic_step,
            )
        )
        # Explicit refs replace implicit input, so a terminal writer after an
        # inserted follow-up extraction step must name BOTH sources — the
        # extraction object alone would erase the narrative it summarizes.
        previous_output_refs: tuple[PreviousOutputRef, ...] = ()
        if (
            is_terminal_semantic_step
            and followup_step_index is not None
            and input_source == InputSource.PREVIOUS_STEP
            and not previous_field_refs
        ):
            # The inserted extraction step is always the immediately
            # preceding planned step here, so its one-based ref is simply
            # the current planned-step count.
            extraction_from_step = len(planned_steps)
            previous_output_refs = tuple(
                PreviousOutputRef(
                    from_step=from_step,
                    label=planned_steps[from_step - 1].name,
                )
                for from_step in (extraction_from_step - 1, extraction_from_step)
            )
        planned_step = PlannedStep(
            role=_linear_step_role(
                output_type=step_output_type,
                is_terminal=is_terminal_semantic_step,
                document_artifact_requested=document_artifact_requested,
            ),
            name=semantic_step.name,
            instructions=semantic_step.instructions,
            input_source=input_source,
            input_type=input_type,
            output_type=step_output_type,
            output_mode=semantic_output_mode,
            underlag_channel=derive_underlag_channel(
                input_source=input_source,
                input_type=input_type,
                previous_step=previous_planned_step,
                previous_field_refs=previous_field_refs,
            ),
            runtime_required=(
                index == 0
                and runtime_input_type in _FILE_INPUT_TYPES
                and runtime_required
            ),
            runtime_max_files=(
                runtime_max_files
                if index == 0 and runtime_input_type in _FILE_INPUT_TYPES
                else None
            ),
            semantic_origin_eligible=semantic_origin_eligibility[index],
            previous_field_refs=previous_field_refs,
            previous_output_refs=previous_output_refs,
            output_fields=tuple(semantic_step.output_fields or ()),
            model_ref=semantic_step.model_ref,
            knowledge_refs=tuple(semantic_step.knowledge_refs),
            citations_requested=semantic_step.citations_requested,
        )
        planned_steps.append(planned_step)
        previous_output_type = step_output_type

    if document_artifact_requested:
        renderer_step = render_verbatim_step(
            output_type=final_output_type,
            ui_language=ui_language,
        )
        planned_steps.append(renderer_step)
    completed_steps = _apply_per_source_reader_execution(
        tuple(planned_steps),
        ui_language=ui_language,
    )
    completed_steps = _complete_planned_source_reader_contracts(
        completed_steps,
        terminal_output_schema=terminal_output_schema,
        required_fields=source_reader_required_fields,
        reserved_field_names=frozenset(
            record.value.variable_name for record in runtime_input_fields
        ),
    )
    section_contracts = (
        requested_output_section_contracts(requested_output_sections)
        if report_disposition is not None
        else ()
    )
    completed_steps, document_report_section_source = lower_document_report_topology(
        completed_steps,
        report_disposition=report_disposition,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
        semantic_step_count=len(semantic_steps),
        result_contract_output_fields=result_contract_output_fields,
        requested_output_section_contracts=section_contracts,
        ui_language=ui_language,
        field_diagnostics=field_diagnostics,
    )
    section_writer_material = _resolve_section_writer_structured_sources(
        completed_steps
    )
    if isinstance(section_writer_material, CreateAssemblyRejection):
        return section_writer_material
    completed_steps = section_writer_material
    completed_steps, admitted_form_fields = (
        _drop_planned_source_contract_shadow_form_fields(
            planned_steps=completed_steps,
            form_fields=tuple(form_fields),
            field_provenance=field_provenance or {},
            field_diagnostics=field_diagnostics,
        )
    )
    placement = _place_runtime_form_fields(
        planned_steps=completed_steps,
        form_fields=admitted_form_fields,
        runtime_input_fields=runtime_input_fields,
        template_form_field_names=template_form_field_names,
    )
    if isinstance(placement, CreateAssemblyRejection):
        return placement
    completed_steps = placement
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=admitted_form_fields,
        steps=completed_steps,
        terminal_output_schema=terminal_output_schema,
        source_reader_required_fields=source_reader_required_fields,
        aggregation_intent=aggregation_intent,
        ui_language=ui_language,
        requested_output_section_contracts=section_contracts,
        document_report_section_source=document_report_section_source,
    )


def _semantic_steps_with_terminal_obligation(
    steps: tuple[SemanticStepIntent, ...],
    *,
    terminal_obligation_instructions: str | None,
) -> tuple[SemanticStepIntent, ...]:
    """Attach a server-owned obligation to the retained content producer.

    Runs after terminal-helper normalization so the sentence can never land on
    a render helper the assembly is about to drop.
    """
    if not terminal_obligation_instructions or not steps:
        return steps
    terminal = steps[-1]
    if terminal_obligation_instructions in terminal.instructions:
        return steps
    updated = terminal.model_copy(
        update={
            "instructions": (
                f"{terminal.instructions.rstrip()}\n\n"
                f"{terminal_obligation_instructions}"
            )
        }
    )
    return (*steps[:-1], updated)


def _provider_source_output_collision_names(
    *,
    intent: CreateFlowIntent,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    runtime_input_fields: Sequence[ConfirmedRuntimeMetadataField],
) -> tuple[str, ...]:
    """Return exact confirmed-field collisions in provider-authored source output.

    Only the first semantic step can read the primary source directly in create
    assembly. This check runs before server-owned reader completion, preserving
    the provenance needed to make the failure model-repairable.
    """

    if (
        runtime_input_type not in SOURCE_READER_INPUT_TYPES
        or not intent.steps
        or (
            runtime_input_type is InputType.TEXT
            and len(intent.steps) == 1
            and final_output_mode is not OutputMode.TEMPLATE_FILL
            and _terminal_step_output_fields_fold_to_text(
                intent.steps[0],
                final_semantic_output_type=_terminal_semantic_output_type(
                    final_output_type
                ),
            )
        )
    ):
        return ()
    first_step_fields = tuple(intent.steps[0].output_fields or ())
    if not first_step_fields:
        return ()
    source_identities = {
        fold_result_field_name(name)
        for name in structured_field_draft_names(first_step_fields)
    }
    return tuple(
        dict.fromkeys(
            record.value.variable_name
            for record in runtime_input_fields
            if fold_result_field_name(record.value.variable_name) in source_identities
        )
    )


def _semantic_steps_without_terminal_document_render_helper(
    steps: Sequence[SemanticStepIntent],
    *,
    final_output_type: OutputType,
    document_artifact_requested: bool,
    ui_language: str | None,
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if (
        not document_artifact_requested
        or final_output_type not in _DOCUMENT_OUTPUT_TYPES
        or len(semantic_steps) < 2
    ):
        return semantic_steps

    previous_step = semantic_steps[-2]
    helper_candidate = semantic_steps[-1]
    previous_output_type = _linear_step_output_type(
        output_type=previous_step.output_type,
        output_fields=previous_step.output_fields,
        final_output_type=OutputType.TEXT,
        is_terminal=False,
    )
    if previous_output_type != OutputType.TEXT:
        return semantic_steps
    if helper_candidate.output_type not in {None, OutputType.TEXT, final_output_type}:
        return semantic_steps
    if not _looks_like_terminal_document_render_helper(
        helper_candidate,
        final_output_type=final_output_type,
    ):
        return semantic_steps

    retained_steps = semantic_steps[:-1]
    if helper_candidate.output_fields:
        retained_steps = (
            *semantic_steps[:-2],
            previous_step.model_copy(
                update={
                    "instructions": append_terminal_helper_output_fields(
                        previous_step.instructions,
                        helper_candidate.output_fields,
                        ui_language=ui_language,
                    )
                }
            ),
        )

    logger.info(
        "ai_builder_terminal_document_render_helper_dropped",
        extra={
            "step_name": helper_candidate.name,
            "final_output_type": final_output_type.value,
        },
    )
    return retained_steps


def _semantic_steps_with_terminal_text_fields_folded(
    steps: Sequence[SemanticStepIntent],
    *,
    final_semantic_output_type: OutputType,
    ui_language: str | None,
) -> tuple[SemanticStepIntent, ...]:
    semantic_steps = tuple(steps)
    if not semantic_steps:
        return semantic_steps

    terminal_step = semantic_steps[-1]
    if not _terminal_step_output_fields_fold_to_text(
        terminal_step,
        final_semantic_output_type=final_semantic_output_type,
    ):
        return semantic_steps
    assert terminal_step.output_fields is not None

    folded_terminal_step = terminal_step.model_copy(
        update={
            "instructions": append_terminal_helper_output_fields(
                terminal_step.instructions,
                terminal_step.output_fields,
                ui_language=ui_language,
            ),
            "output_type": OutputType.TEXT,
            "output_fields": None,
        }
    )
    return (*semantic_steps[:-1], folded_terminal_step)


def _terminal_semantic_output_type(final_output_type: OutputType) -> OutputType:
    if final_output_type in _DOCUMENT_OUTPUT_TYPES:
        return OutputType.TEXT
    return final_output_type


def _terminal_step_output_fields_fold_to_text(
    terminal_step: SemanticStepIntent,
    *,
    final_semantic_output_type: OutputType,
) -> bool:
    return bool(
        final_semantic_output_type is OutputType.TEXT
        and terminal_step.output_fields
        and terminal_step.output_type in {None, OutputType.TEXT, OutputType.JSON}
    )


def _semantic_steps_with_result_contract_fields(
    steps: Sequence[SemanticStepIntent],
    *,
    runtime_input_type: InputType,
    final_semantic_output_type: OutputType,
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    result_contract_required_roles: tuple[ResultOutputFieldRole, ...],
    terminal_output_schema: JsonObject | None,
    ui_language: str | None,
) -> tuple[tuple[SemanticStepIntent, ...], int | None]:
    semantic_steps = tuple(steps)
    if not result_contract_output_fields or not semantic_steps:
        return semantic_steps, None

    terminal_step = semantic_steps[-1]
    terminal_output_type = _linear_step_output_type(
        output_type=terminal_step.output_type,
        output_fields=terminal_step.output_fields,
        final_output_type=final_semantic_output_type,
        is_terminal=True,
    )

    if final_semantic_output_type == OutputType.JSON:
        # A user-owned exact schema wins: never append canonical siblings.
        if terminal_output_schema is not None:
            return semantic_steps, None
        if terminal_output_type != OutputType.JSON:
            return semantic_steps, None
        completed_fields = _complete_result_contract_output_fields(
            tuple(terminal_step.output_fields or ()),
            required_fields=result_contract_output_fields,
        )
        if completed_fields == tuple(terminal_step.output_fields or ()):
            return semantic_steps, None
        return (
            *semantic_steps[:-1],
            terminal_step.model_copy(
                update={
                    "output_type": OutputType.JSON,
                    "output_fields": list(completed_fields),
                }
            ),
        ), None

    if final_semantic_output_type != OutputType.TEXT:
        return semantic_steps, None
    if terminal_output_type != OutputType.TEXT:
        return semantic_steps, None

    for index in range(len(semantic_steps) - 2, -1, -1):
        if index == 0 and runtime_input_type in _FILE_INPUT_TYPES:
            continue
        candidate = semantic_steps[index]
        candidate_output_type = _linear_step_output_type(
            output_type=candidate.output_type,
            output_fields=candidate.output_fields,
            final_output_type=final_semantic_output_type,
            is_terminal=False,
        )
        if candidate_output_type != OutputType.JSON:
            continue
        completed_fields = _complete_result_contract_output_fields(
            tuple(candidate.output_fields or ()),
            required_fields=result_contract_output_fields,
        )
        if completed_fields == tuple(candidate.output_fields or ()):
            return semantic_steps, None
        updated_steps = list(semantic_steps)
        updated_steps[index] = candidate.model_copy(
            update={
                "output_type": OutputType.JSON,
                "output_fields": list(completed_fields),
            }
        )
        return tuple(updated_steps), None

    # No structured producer exists for the required follow-up roles, and
    # terminal text fields are folded away before this point — without a
    # compiler-owned extraction step the critic would demand a contract no
    # model repair can produce. The extraction step needs a preceding planned
    # step to read (an earlier semantic step or the fixed audio
    # transcription), so single-step flows over other inputs keep the model
    # repair path instead.
    if not result_contract_required_roles:
        return semantic_steps, None
    insert_at = len(semantic_steps) - 1
    if insert_at == 0 and runtime_input_type != InputType.AUDIO:
        return semantic_steps, None
    logger.info(
        "ai_builder_result_contract_followup_step_inserted",
        extra={"terminal_step_name": terminal_step.name},
    )
    return (
        *semantic_steps[:insert_at],
        _result_contract_followup_step(
            result_contract_output_fields,
            ui_language=ui_language,
        ),
        *semantic_steps[insert_at:],
    ), insert_at


def _result_contract_followup_step(
    result_contract_output_fields: tuple[StructuredFieldDraft, ...],
    *,
    ui_language: str | None,
) -> SemanticStepIntent:
    swedish = ui_language is None or ui_language.casefold().startswith("sv")
    return SemanticStepIntent(
        name="Uppföljningspunkter" if swedish else "Follow-up extraction",
        instructions=(
            "Identifiera uppföljningsfälten ur föregående material. "
            "Markera saknade värden som ospecificerade."
            if swedish
            else (
                "Identify the follow-up fields from the preceding material. "
                "Mark missing values as unspecified."
            )
        ),
        output_type=OutputType.JSON,
        output_fields=list(result_contract_output_fields),
    )


def _complete_result_contract_output_fields(
    fields: tuple[StructuredFieldDraft, ...],
    *,
    required_fields: tuple[StructuredFieldDraft, ...],
) -> tuple[StructuredFieldDraft, ...]:
    declared_names = structured_field_draft_names(fields)
    completed_fields = list(fields)
    for required_field in required_fields:
        if structured_field_names_satisfy_result_field(
            declared_names,
            required_field.name,
        ):
            continue
        completed_fields.append(required_field)
    return tuple(completed_fields)


def _looks_like_terminal_document_render_helper(
    step: SemanticStepIntent,
    *,
    final_output_type: OutputType,
) -> bool:
    if step.knowledge_refs or step.citations_requested:
        return False
    return _mentions_output_artifact_type(
        f"{step.name} {step.instructions}",
        final_output_type=final_output_type,
    )


def _mentions_output_artifact_type(
    text: str,
    *,
    final_output_type: OutputType,
) -> bool:
    artifact_type = re.escape(final_output_type.value)
    return (
        re.search(rf"(?<![a-z0-9]){artifact_type}(?![a-z0-9])", text.casefold())
        is not None
    )


def _assemble_docx_template_fill(
    intent: CreateFlowIntent,
    *,
    runtime_input_type: InputType,
    form_fields: Sequence[FormFieldSpec],
    runtime_input_fields: Sequence[ConfirmedRuntimeMetadataField],
    template_form_field_names: tuple[str, ...],
    source_reader_required_fields: tuple[SourceCaptureField, ...],
    runtime_required: bool,
    runtime_max_files: int | None,
    aggregation_intent: AggregationIntent,
    ui_language: str | None,
    field_provenance: dict[str, FlowInputFieldProvenance] | None,
    field_diagnostics: list[LintWarning] | None,
) -> FlowAssemblyPlan | CreateAssemblyRejection:
    # Aggregate and compare intents describe the preparation work (reading
    # several sources, cross-checking them); the fixed chain already reads
    # every file through its per-source reader, so any aggregation intent
    # assembles to the same linear template topology.
    if runtime_input_type not in _FILE_INPUT_TYPES:
        return _reject("docx_template_shape_unsupported")
    reader_step = template_variable_reader_step(
        runtime_input_type=runtime_input_type,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )
    semantic_steps: list[PlannedStep] = []
    previous_step = reader_step
    for index, semantic_step in enumerate(intent.steps):
        is_terminal_semantic_step = index == len(intent.steps) - 1
        step_index = index + 1
        if semantic_step.uses_previous_fields or semantic_step.uses_previous_outputs:
            return _reject(
                "docx_template_shape_unsupported",
                step_index=step_index,
            )
        if is_terminal_semantic_step:
            if semantic_step.output_fields:
                # Prepared-fields terminal: the template contract binds each
                # placeholder to a declared string field by folded name, so
                # the chain may end in the JSON step that prepares them.
                if semantic_step.output_type not in {None, OutputType.JSON}:
                    return _reject(
                        "docx_template_shape_unsupported",
                        step_index=step_index,
                    )
                step_output_type = OutputType.JSON
                step_input_type = _linear_step_input_type(
                    input_source=InputSource.PREVIOUS_STEP,
                    runtime_input_type=runtime_input_type,
                    previous_output_type=previous_step.output_type,
                    output_type=step_output_type,
                )
            else:
                if semantic_step.output_type not in {None, OutputType.TEXT}:
                    return _reject(
                        "docx_template_shape_unsupported",
                        step_index=step_index,
                    )
                step_output_type = OutputType.TEXT
                step_input_type = (
                    InputType.TEXT
                    if previous_step.output_type == OutputType.TEXT
                    else InputType.JSON
                )
        else:
            step_output_type = _linear_step_output_type(
                output_type=semantic_step.output_type,
                output_fields=semantic_step.output_fields,
                final_output_type=OutputType.TEXT,
                is_terminal=False,
            )
            if (
                step_output_type is None
                or step_output_type not in {OutputType.JSON, OutputType.TEXT}
                or (
                    step_output_type == OutputType.JSON
                    and not semantic_step.output_fields
                )
            ):
                return _reject(
                    "docx_template_shape_unsupported",
                    step_index=step_index,
                )
            step_input_type = _linear_step_input_type(
                input_source=InputSource.PREVIOUS_STEP,
                runtime_input_type=runtime_input_type,
                previous_output_type=previous_step.output_type,
                output_type=step_output_type,
            )
        planned_step = PlannedStep(
            role="transform",
            name=semantic_step.name,
            instructions=semantic_step.instructions,
            input_source=InputSource.PREVIOUS_STEP,
            input_type=step_input_type,
            output_type=step_output_type,
            output_mode=OutputMode.PASS_THROUGH,
            underlag_channel=derive_underlag_channel(
                input_source=InputSource.PREVIOUS_STEP,
                input_type=step_input_type,
                previous_step=previous_step,
                previous_field_refs=(),
            ),
            semantic_origin_eligible=True,
            output_fields=tuple(semantic_step.output_fields or ()),
            model_ref=semantic_step.model_ref,
            knowledge_refs=tuple(semantic_step.knowledge_refs),
            citations_requested=semantic_step.citations_requested,
        )
        semantic_steps.append(planned_step)
        previous_step = planned_step

    fixed_template_fill_step = template_fill_step(ui_language=ui_language)
    fixed_template_fill_step = replace(
        fixed_template_fill_step,
        underlag_channel=derive_underlag_channel(
            input_source=fixed_template_fill_step.input_source,
            input_type=fixed_template_fill_step.input_type,
            previous_step=previous_step,
            previous_field_refs=(),
        ),
    )
    planned_steps = (reader_step, *semantic_steps, fixed_template_fill_step)
    completed_steps = _apply_per_source_reader_execution(
        planned_steps,
        ui_language=ui_language,
    )
    completed_steps = _complete_planned_source_reader_contracts(
        completed_steps,
        terminal_output_schema=None,
        required_fields=source_reader_required_fields,
        reserved_field_names=frozenset(
            record.value.variable_name for record in runtime_input_fields
        ),
    )
    completed_steps, admitted_form_fields = (
        _drop_planned_source_contract_shadow_form_fields(
            planned_steps=completed_steps,
            form_fields=tuple(form_fields),
            field_provenance=field_provenance or {},
            field_diagnostics=field_diagnostics,
        )
    )
    placement = _place_runtime_form_fields(
        planned_steps=completed_steps,
        form_fields=admitted_form_fields,
        runtime_input_fields=runtime_input_fields,
        template_form_field_names=template_form_field_names,
    )
    if isinstance(placement, CreateAssemblyRejection):
        return placement
    completed_steps = placement
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=admitted_form_fields,
        steps=completed_steps,
        terminal_output_schema=None,
        source_reader_required_fields=source_reader_required_fields,
        aggregation_intent="linear",
        ui_language=ui_language,
    )


def _derived_terminal_text_previous_field_refs(
    *,
    planned_steps: tuple[PlannedStep, ...],
    input_source: InputSource,
    input_type: InputType,
    output_type: OutputType,
    is_terminal_semantic_step: bool,
) -> tuple[PreviousFieldRef, ...]:
    if (
        not is_terminal_semantic_step
        or input_source != InputSource.PREVIOUS_STEP
        or input_type != InputType.TEXT
        or output_type != OutputType.TEXT
    ):
        return ()
    json_steps = tuple(
        (index, step)
        for index, step in enumerate(planned_steps, start=1)
        if step.output_type == OutputType.JSON and step.output_fields
    )
    if len(json_steps) < 2:
        return ()
    return tuple(
        PreviousFieldRef(from_step=from_step, field_path=field.name)
        for from_step, step in json_steps
        for field in step.output_fields
    )


def _resolve_section_writer_structured_sources(
    planned_steps: tuple[PlannedStep, ...],
) -> tuple[PlannedStep, ...] | CreateAssemblyRejection:
    terminal_content_index = next(
        (
            index
            for index in range(len(planned_steps) - 1, -1, -1)
            if planned_steps[index].role not in {"renderer", "template_fill"}
        ),
        None,
    )
    structured_producer_indexes: list[int] = []
    writer_indexes_by_producer: dict[int, list[int]] = {}
    for index, step in enumerate(planned_steps):
        if step.output_type == OutputType.JSON and step.output_fields:
            structured_producer_indexes.append(index)
            continue
        if not (
            step.role in {"transform", "body_writer"}
            and step.input_source == InputSource.PREVIOUS_STEP
            and step.input_type == InputType.TEXT
            and step.output_type == OutputType.TEXT
            and step.output_mode == OutputMode.PASS_THROUGH
        ):
            continue
        if len(structured_producer_indexes) > 1 and index != terminal_content_index:
            return _reject(
                "section_writer_structured_source_ambiguous",
                step_index=index + 1,
            )
        if len(structured_producer_indexes) != 1:
            continue
        producer_index = structured_producer_indexes[0]
        writer_indexes_by_producer.setdefault(producer_index, []).append(index)

    updated_steps = list(planned_steps)
    for producer_index, writer_indexes in writer_indexes_by_producer.items():
        if len(writer_indexes) < 2:
            continue
        producer = planned_steps[producer_index]
        previous_field_refs = tuple(
            PreviousFieldRef(
                from_step=producer_index + 1,
                field_path=field.name,
            )
            for field in producer.output_fields
        )
        for writer_index in writer_indexes:
            writer = updated_steps[writer_index]
            updated_steps[writer_index] = replace(
                writer,
                previous_field_refs=previous_field_refs,
                underlag_channel=derive_underlag_channel(
                    input_source=writer.input_source,
                    input_type=writer.input_type,
                    previous_step=planned_steps[writer_index - 1],
                    previous_field_refs=previous_field_refs,
                ),
            )
    return tuple(updated_steps)


def _aggregate_terminal_previous_structured_refs(
    *,
    planned_steps: tuple[PlannedStep, ...],
    aggregation_intent: AggregationIntent,
    is_terminal_semantic_step: bool,
) -> tuple[PreviousFieldRef, ...]:
    if (
        aggregation_intent not in {"aggregate", "compare"}
        or not is_terminal_semantic_step
        or len(planned_steps) < 2
    ):
        return ()
    if any(
        step.output_type != OutputType.JSON or not step.output_fields
        for step in planned_steps
    ):
        return ()
    refs = tuple(
        PreviousFieldRef(from_step=index, field_path=field.name)
        for index, step in enumerate(planned_steps, start=1)
        for field in step.output_fields
    )
    # A later analysis step commonly refines a field first emitted by its
    # source reader. The structured projection has one root namespace, so the
    # later producer is the canonical value for a repeated identity; retaining
    # both would make an otherwise valid compare plan impossible to lower.
    seen: set[str] = set()
    surviving_reversed: list[PreviousFieldRef] = []
    for ref in reversed(refs):
        identity = fold_result_field_name(ref.field_path)
        if identity in seen:
            continue
        seen.add(identity)
        surviving_reversed.append(ref)
    return tuple(reversed(surviving_reversed))


def _assemble_pure_audio_transcription(
    intent: CreateFlowIntent,
    *,
    form_fields: Sequence[FormFieldSpec],
    runtime_input_fields: Sequence[ConfirmedRuntimeMetadataField],
    template_form_field_names: tuple[str, ...],
    runtime_required: bool,
    runtime_max_files: int | None,
    ui_language: str | None,
) -> FlowAssemblyPlan | CreateAssemblyRejection:
    if len(intent.steps) != 1:
        return _reject("pure_audio_transcription_shape_unsupported")
    semantic_step = intent.steps[0]
    if (
        semantic_step.output_fields
        or semantic_step.uses_previous_fields
        or semantic_step.uses_previous_outputs
        or semantic_step.output_type not in {None, OutputType.TEXT}
    ):
        return _reject(
            "pure_audio_transcription_shape_unsupported",
            step_index=1,
        )
    planned_step = fixed_audio_transcription_step(
        name=semantic_step.name,
        instructions=semantic_step.instructions,
        runtime_required=runtime_required,
        runtime_max_files=runtime_max_files,
        ui_language=ui_language,
    )
    placement = _place_runtime_form_fields(
        planned_steps=(planned_step,),
        form_fields=tuple(form_fields),
        runtime_input_fields=runtime_input_fields,
        template_form_field_names=template_form_field_names,
    )
    if isinstance(placement, CreateAssemblyRejection):
        return placement
    return FlowAssemblyPlan(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description or "",
        form_fields=tuple(form_fields),
        steps=placement,
        terminal_output_schema=None,
        source_reader_required_fields=(),
        aggregation_intent="linear",
        ui_language=ui_language,
    )


def _place_runtime_form_fields(
    *,
    planned_steps: tuple[PlannedStep, ...],
    form_fields: tuple[FormFieldSpec, ...],
    runtime_input_fields: Sequence[ConfirmedRuntimeMetadataField],
    template_form_field_names: tuple[str, ...],
) -> tuple[PlannedStep, ...] | CreateAssemblyRejection:
    """Place server-owned runtime fields on the completed create topology."""

    declared_names = {field.name for field in form_fields}
    runtime_fields_by_name = {
        record.value.variable_name: record for record in runtime_input_fields
    }
    template_names = set(template_form_field_names) & declared_names
    semantic_target_indexes = tuple(
        index
        for index, step in enumerate(planned_steps)
        if step.semantic_origin_eligible
        and step.input_source != InputSource.ALL_PREVIOUS_STEPS
    )
    template_target_index = next(
        (
            index
            for index, step in enumerate(planned_steps)
            if step.role == "template_fill"
        ),
        None,
    )
    field_names_by_step: list[list[str]] = [[] for _ in planned_steps]
    for field in form_fields:
        name = field.name
        record = runtime_fields_by_name.get(name)
        has_template_target = (
            name in template_names and template_target_index is not None
        )
        semantic_indexes: tuple[int, ...] = ()
        if record is not None:
            match record.purpose:
                case "interpret_input":
                    if not semantic_target_indexes:
                        return _reject(
                            "form_field_required_semantic_target_missing",
                            detail=(
                                f"Runtime form field {name!r} requires an input "
                                "interpretation target, but none exists."
                            ),
                        )
                    semantic_indexes = semantic_target_indexes[:1]
                case "shape_result":
                    if not has_template_target:
                        if not semantic_target_indexes:
                            return _reject(
                                "form_field_required_semantic_target_missing",
                                detail=(
                                    f"Runtime form field {name!r} requires a result "
                                    "shaping target, but none exists."
                                ),
                            )
                        semantic_indexes = semantic_target_indexes[-1:]
                case "whole_flow":
                    if not semantic_target_indexes:
                        return _reject(
                            "form_field_required_semantic_target_missing",
                            detail=(
                                f"Runtime form field {name!r} requires semantic "
                                "targets, but none exist."
                            ),
                        )
                    semantic_indexes = semantic_target_indexes
                case _ as unsupported_purpose:
                    assert_never(unsupported_purpose)
        elif not has_template_target:
            return _reject(
                "form_field_no_legal_target",
                detail=f"Runtime form field {name!r} has no legal target.",
            )

        target_indexes = tuple(
            dict.fromkeys(
                (
                    *semantic_indexes,
                    *(
                        (template_target_index,)
                        if has_template_target and template_target_index is not None
                        else ()
                    ),
                )
            )
        )
        if not target_indexes:
            return _reject(
                "form_field_no_legal_target",
                detail=f"Runtime form field {name!r} has no legal target.",
            )
        for target_index in target_indexes:
            field_names_by_step[target_index].append(name)

    return tuple(
        replace(
            step,
            form_field_refs=tuple(dict.fromkeys(field_names_by_step[index])),
        )
        for index, step in enumerate(planned_steps)
    )


def _linear_step_output_type(
    *,
    output_type: OutputType | None,
    output_fields: Sequence[StructuredFieldDraft] | None,
    final_output_type: OutputType,
    is_terminal: bool,
) -> OutputType | None:
    step_output_type = output_type
    if step_output_type is None:
        if output_fields:
            step_output_type = OutputType.JSON
        elif is_terminal:
            step_output_type = final_output_type
        else:
            step_output_type = OutputType.TEXT
    if output_fields and step_output_type != OutputType.JSON:
        return None
    if is_terminal and step_output_type != final_output_type:
        return None
    return step_output_type


def _linear_step_input_type(
    *,
    input_source: InputSource,
    runtime_input_type: InputType,
    previous_output_type: OutputType | None,
    output_type: OutputType,
) -> InputType:
    if input_source == InputSource.FLOW_INPUT:
        return runtime_input_type
    if input_source == InputSource.ALL_PREVIOUS_STEPS:
        return InputType.TEXT
    if previous_output_type == OutputType.JSON:
        if output_type == OutputType.TEXT:
            return InputType.TEXT
        return InputType.JSON
    return InputType.TEXT


def _linear_step_role(
    *,
    output_type: OutputType,
    is_terminal: bool,
    document_artifact_requested: bool,
) -> PlannedStepRole:
    if is_terminal and document_artifact_requested:
        return "body_writer"
    if output_type == OutputType.JSON:
        return "reader"
    return "transform"


def _linear_step_input_source(
    *,
    step_index: int,
    semantic_step_count: int,
    aggregation_intent: str,
    has_source_prefix: bool,
    prior_step_count: int,
    aggregate_terminal_uses_source_refs: bool,
) -> InputSource:
    if step_index == 0 and not has_source_prefix:
        return InputSource.FLOW_INPUT
    if (
        aggregation_intent in {"aggregate", "compare"}
        and step_index == semantic_step_count - 1
        and prior_step_count > 1
    ):
        if aggregate_terminal_uses_source_refs:
            return InputSource.PREVIOUS_STEP
        return InputSource.ALL_PREVIOUS_STEPS
    return InputSource.PREVIOUS_STEP


def _complete_planned_source_reader_contracts(
    planned_steps: tuple[PlannedStep, ...],
    *,
    terminal_output_schema: JsonObject | None,
    required_fields: tuple[SourceCaptureField, ...],
    reserved_field_names: frozenset[str],
) -> tuple[PlannedStep, ...]:
    source_reader_indexes = tuple(
        index
        for index, planned_step in enumerate(planned_steps)
        if planned_step_is_source_reader(planned_step)
    )
    if not source_reader_indexes:
        return planned_steps

    fields_by_index: dict[int, list[SourceCaptureField]] = {}
    terminal_fields = (
        source_capture_fields_from_terminal_schema(terminal_output_schema)
        if terminal_output_schema is not None
        else ()
    )
    global_fields = (*required_fields, *terminal_fields)
    missing_global_fields = [
        field
        for field in global_fields
        if not any(
            structured_fields_have_source_leaf(
                planned_steps[index].output_fields,
                field.name,
            )
            for index in source_reader_indexes
        )
    ]
    if missing_global_fields:
        if len(source_reader_indexes) != 1:
            raise ValueError(
                "FlowAssemblyPlan source-reader field completion requires "
                "exactly one source reader when global fields are missing."
            )
        fields_by_index.setdefault(source_reader_indexes[0], []).extend(
            missing_global_fields
        )

    source_reader_index_set = set(source_reader_indexes)
    for planned_step in planned_steps:
        for ref in planned_step.previous_field_refs:
            source_index = ref.from_step - 1
            if source_index not in source_reader_index_set:
                continue
            field_name = source_reader_leaf_field_name(ref.field_path)
            if not field_name or structured_fields_have_source_leaf(
                planned_steps[source_index].output_fields,
                field_name,
            ):
                continue
            fields_by_index.setdefault(source_index, []).append(
                SourceCaptureField(name=field_name, description=ref.label)
            )

    updated_steps = list(planned_steps)
    renamed_roots_by_step: dict[int, dict[str, str]] = {}
    for index in source_reader_indexes:
        fields = fields_by_index.get(index, [])
        planned_step = planned_steps[index]
        completed_fields = complete_structured_source_reader_fields(
            planned_step.output_fields,
            required_fields=tuple(fields),
            runtime_input_execution_mode=(planned_step.runtime_input_execution_mode),
            reserved_field_names=reserved_field_names,
        )
        if completed_fields == planned_step.output_fields:
            continue
        updated_steps[index] = replace(planned_step, output_fields=completed_fields)
        renamed_roots = _canonical_source_reader_root_renames(
            before=planned_step.output_fields,
            after=completed_fields,
        )
        if renamed_roots:
            renamed_roots_by_step[index + 1] = renamed_roots
        logger.info(
            "ai_builder_source_reader_contract_completed",
            extra={
                "step_index": index + 1,
                "field_names": [field.name for field in fields],
            },
        )
    if renamed_roots_by_step:
        updated_steps = [
            _rewrite_source_reader_refs(
                step,
                renamed_roots_by_step=renamed_roots_by_step,
            )
            for step in updated_steps
        ]
    return tuple(updated_steps)


def _canonical_source_reader_root_renames(
    *,
    before: tuple[StructuredFieldDraft, ...],
    after: tuple[StructuredFieldDraft, ...],
) -> dict[str, str]:
    if not any(field.name == "documents" for field in after):
        return {}
    return {
        fold_result_field_name(field.name): "documents"
        for field in before
        if field.name != "documents" and structured_fields_have_document_items((field,))
    }


def _rewrite_source_reader_refs(
    step: PlannedStep,
    *,
    renamed_roots_by_step: dict[int, dict[str, str]],
) -> PlannedStep:
    rewritten: list[PreviousFieldRef] = []
    changed = False
    for ref in step.previous_field_refs:
        renamed_roots = renamed_roots_by_step.get(ref.from_step)
        path_parts = ref.field_path.split(".", 1)
        canonical_root = (
            renamed_roots.get(fold_result_field_name(path_parts[0]))
            if renamed_roots is not None
            else None
        )
        if canonical_root is None:
            rewritten.append(ref)
            continue
        canonical_path = (
            canonical_root
            if len(path_parts) == 1
            else f"{canonical_root}.{path_parts[1]}"
        )
        rewritten.append(ref.model_copy(update={"field_path": canonical_path}))
        changed = True
    if not changed:
        return step
    return replace(step, previous_field_refs=tuple(rewritten))


def _apply_per_source_reader_execution(
    planned_steps: tuple[PlannedStep, ...],
    *,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    updated_steps: list[PlannedStep] = []
    changed = False
    for planned_step in planned_steps:
        if not (
            planned_step_is_source_reader(planned_step)
            and len(planned_step.output_fields) == 1
            and structured_fields_have_document_items(planned_step.output_fields)
            and planned_step.input_type in _FILE_INPUT_TYPES
            and planned_step.runtime_max_files is not None
            and planned_step.runtime_max_files != 1
        ):
            updated_steps.append(planned_step)
            continue
        annotated_step = replace(
            planned_step,
            instructions=_append_per_source_reader_instruction(
                planned_step.instructions,
                ui_language=ui_language,
            ),
            output_fields=add_runtime_source_file_id_field(planned_step.output_fields),
            runtime_input_execution_mode="per_source",
        )
        updated_steps.append(annotated_step)
        changed = changed or annotated_step != planned_step
    if not changed:
        return planned_steps
    return tuple(updated_steps)


def _append_per_source_reader_instruction(
    instructions: str,
    *,
    ui_language: str | None,
) -> str:
    if ui_language == "en":
        addition = (
            "This document reader runs once per uploaded source. Extract facts "
            "only from the current source document and return documents with one "
            "document object."
        )
    else:
        addition = (
            "Den här dokumentläsaren körs en gång per uppladdad källa. Extrahera "
            "bara fakta från det aktuella källdokumentet och returnera documents "
            "med ett dokumentobjekt."
        )
    if addition in instructions:
        return instructions
    return f"{instructions}\n\n{addition}"


def _drop_planned_source_contract_shadow_form_fields(
    *,
    planned_steps: tuple[PlannedStep, ...],
    form_fields: tuple[FormFieldSpec, ...],
    field_provenance: dict[str, FlowInputFieldProvenance],
    field_diagnostics: list[LintWarning] | None,
) -> tuple[tuple[PlannedStep, ...], tuple[FormFieldSpec, ...]]:
    dropped_names = set(
        source_contract_shadow_form_field_names(
            output_fields_by_step=tuple(
                planned_step.output_fields
                for planned_step in planned_steps
                if planned_step_is_source_reader(planned_step)
            ),
            form_fields=form_fields,
        )
    )
    if not dropped_names:
        return planned_steps, form_fields
    confirmed_names = sorted(
        name for name in dropped_names if field_provenance.get(name) == "user_confirmed"
    )
    if confirmed_names:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail=(
                "Confirmed runtime fields conflict with fields extracted from the "
                "source contract. Rename or remove the incompatible fields."
            ),
            log_context={
                "failure_code": "confirmed_form_field_incompatible",
                "field_names": ",".join(confirmed_names),
            },
        )
    if field_diagnostics is not None:
        for name in sorted(dropped_names):
            provenance = field_provenance.get(name, "model_proposed")
            field_diagnostics.append(
                LintWarning(
                    code="source_contract_shadow_form_field_dropped",
                    message=(
                        f"Runtime field '{name}' was removed because the source "
                        "reader already produces that field."
                    ),
                    field_name=name,
                    field_provenance=provenance,
                )
            )
    log_dropped_source_contract_shadow_fields(field_names=sorted(dropped_names))
    return (
        tuple(
            _without_planned_form_field_refs(
                planned_step,
                dropped_names=dropped_names,
            )
            for planned_step in planned_steps
        ),
        tuple(field for field in form_fields if field.name not in dropped_names),
    )


def _without_planned_form_field_refs(
    planned_step: PlannedStep,
    *,
    dropped_names: set[str],
) -> PlannedStep:
    if not planned_step.form_field_refs:
        return planned_step
    form_field_refs = tuple(
        field_name
        for field_name in planned_step.form_field_refs
        if field_name not in dropped_names
    )
    if form_field_refs == planned_step.form_field_refs:
        return planned_step
    return replace(planned_step, form_field_refs=form_field_refs)

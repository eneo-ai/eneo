"""Create-mode compile pipeline. Owns semantic intent -> spec."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from eneo.flows.ai_builder.ai_builder_aggregation_intent import (
    derive_aggregation_intent_from_slots,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
    flow_input_type_from_primary_runtime_input_value,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_assembly import (
    CreateAssemblyRejection,
    try_compile_create_intent_with_assembly,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    FlowInputFieldIntent,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    derive_result_contract,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
    RuntimeMetadataState,
    extract_runtime_input_field_hints,
    normalize_runtime_metadata_state,
    runtime_metadata_allows_input_fields,
    runtime_metadata_disables_declared_input_fields,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from eneo.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommit,
    ArchitectureCommitDraft,
    PlanningState,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_variable_definitions import can_expose_form_field_bare_alias
from eneo.json_types import JsonObject

logger = logging.getLogger(__name__)
_COMPARISON_FAN_IN_PATTERN_IDS = frozenset({"comparison"})
ArchitectureEnvelope = ArchitectureCommit | ArchitectureCommitDraft


@dataclass(frozen=True, slots=True)
class CreateCompileContext:
    """Server-owned create-mode architecture envelope.

    The LLM-facing intent is semantic. Core architecture facts already
    resolved by discovery must not be re-decided by the model when it
    proposes a plan.
    """

    runtime_input_type: InputType | None = None
    runtime_required: bool = True
    runtime_max_files: int | None = None
    final_output_type: OutputType | None = None
    final_output_mode: OutputMode | None = None
    pattern_ids: tuple[str, ...] = ()
    pattern_chain_steps: tuple[str, ...] = ()
    ui_language: str | None = None
    runtime_metadata_state: RuntimeMetadataState | None = None
    runtime_metadata_disables_declared_input_fields: bool = False
    runtime_input_field_hints: tuple[RuntimeInputFieldHint, ...] = ()
    template_placeholder_field_hints: tuple[RuntimeInputFieldHint, ...] = ()
    aggregation_intent: AggregationIntent = "linear"
    terminal_output_schema: JsonObject | None = None
    source_reader_required_fields: tuple[SourceCaptureField, ...] = ()
    result_contract_output_fields: tuple[StructuredFieldDraft, ...] = ()
    report_disposition: str | None = None

    def __post_init__(self) -> None:
        if self.runtime_input_type is InputType.ANY:
            raise ValueError("CreateCompileContext.runtime_input_type cannot be ANY")
        if self.runtime_max_files is not None and self.runtime_max_files < 1:
            raise ValueError("runtime_max_files must be at least 1 when provided")


def compile_create_intent_to_spec(
    intent: CreateFlowIntent,
    *,
    context: CreateCompileContext | None = None,
) -> FlowDraftSpecCore:
    runtime_input_type = (
        context.runtime_input_type
        if context is not None and context.runtime_input_type is not None
        else InputType.TEXT
    )
    final_output_type = (
        context.final_output_type
        if context is not None and context.final_output_type is not None
        else OutputType.TEXT
    )
    (
        form_fields,
        dropped_primary_input_field_names,
        dropped_form_field_ref_names,
    ) = _compile_form_fields(
        intent_fields=intent.input_fields,
        context=context,
        runtime_input_type=runtime_input_type,
    )
    intent_with_admitted_form_refs = _intent_without_form_field_refs(
        intent,
        field_names=dropped_form_field_ref_names,
    )
    referenced_hint_names = {
        field_name
        for semantic_step in intent_with_admitted_form_refs.steps
        for field_name in semantic_step.uses_form_fields
    }
    known_field_order = [field.name for field in form_fields]
    known_field_names = set(known_field_order)
    server_owned_field_names = _server_owned_runtime_field_names(
        context=context,
        known_field_names=known_field_names,
    )
    server_owned_fields_requiring_placement = [
        field_name
        for field_name in known_field_order
        if field_name in server_owned_field_names
        and field_name not in referenced_hint_names
    ]
    intent_with_server_owned_field_placement = (
        _intent_with_server_owned_form_field_placement(
            intent_with_admitted_form_refs,
            field_names=server_owned_fields_requiring_placement,
        )
    )
    _raise_for_unplaced_create_form_fields(
        intent_with_server_owned_field_placement,
        field_order=known_field_order,
    )

    final_output_mode = context.final_output_mode if context is not None else None
    pattern_ids = context.pattern_ids if context is not None else ()
    chain_steps = context.pattern_chain_steps if context is not None else ()
    aggregation_intent = context.aggregation_intent if context is not None else "linear"
    assembly_spec = try_compile_create_intent_with_assembly(
        intent_with_server_owned_field_placement,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        form_fields=form_fields,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
        aggregation_intent=aggregation_intent,
        terminal_output_schema=context.terminal_output_schema if context else None,
        source_reader_required_fields=(
            context.source_reader_required_fields if context is not None else ()
        ),
        result_contract_output_fields=(
            context.result_contract_output_fields if context is not None else ()
        ),
        report_disposition=context.report_disposition if context is not None else None,
        runtime_required=context.runtime_required if context is not None else True,
        runtime_max_files=context.runtime_max_files if context is not None else None,
        ui_language=context.ui_language if context is not None else None,
    )
    if isinstance(assembly_spec, CreateAssemblyRejection):
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail=assembly_spec.feedback,
            log_context={
                "failure_code": assembly_spec.failure_code,
                "reason": assembly_spec.reason,
                "step_index": assembly_spec.step_index,
                "runtime_input_type": runtime_input_type.value,
                "final_output_type": final_output_type.value,
                "final_output_mode": (
                    final_output_mode.value if final_output_mode is not None else None
                ),
                "pattern_ids": ",".join(pattern_ids),
                "chain_steps": ",".join(chain_steps),
                "semantic_step_count": len(
                    intent_with_server_owned_field_placement.steps
                ),
            },
        )
    else:
        _log_dropped_primary_input_shadow_fields(
            field_names=dropped_primary_input_field_names,
            runtime_input_type=runtime_input_type,
        )
        return assembly_spec


def _raise_for_unplaced_create_form_fields(
    intent: CreateFlowIntent,
    *,
    field_order: list[str],
) -> None:
    if not field_order:
        return
    placed_field_names = {
        field_name
        for semantic_step in intent.steps
        for field_name in semantic_step.uses_form_fields
    }
    unplaced_field_names = [
        field_name for field_name in field_order if field_name not in placed_field_names
    ]
    if not unplaced_field_names:
        return
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail="Create-flow input fields must be referenced by at least one step.",
        log_context={
            "failure_code": "unplaced_form_fields",
            "reason": "unplaced_form_fields",
            "field_names": ",".join(unplaced_field_names),
        },
    )


def _intent_with_server_owned_form_field_placement(
    intent: CreateFlowIntent,
    *,
    field_names: list[str],
) -> CreateFlowIntent:
    if not field_names or not intent.steps:
        return intent

    final_step = intent.steps[-1]
    uses_form_fields = [
        *final_step.uses_form_fields,
        *(
            field_name
            for field_name in field_names
            if field_name not in final_step.uses_form_fields
        ),
    ]
    return intent.model_copy(
        update={
            "steps": [
                *intent.steps[:-1],
                final_step.model_copy(update={"uses_form_fields": uses_form_fields}),
            ]
        }
    )


def _intent_without_form_field_refs(
    intent: CreateFlowIntent,
    *,
    field_names: set[str],
) -> CreateFlowIntent:
    if not field_names:
        return intent

    steps: list[SemanticStepIntent] = []
    changed = False
    for step in intent.steps:
        uses_form_fields = [
            field_name
            for field_name in step.uses_form_fields
            if field_name not in field_names
        ]
        if uses_form_fields == step.uses_form_fields:
            steps.append(step)
            continue
        steps.append(step.model_copy(update={"uses_form_fields": uses_form_fields}))
        changed = True
    if not changed:
        return intent
    return intent.model_copy(update={"steps": steps})


def create_compile_context_from_planning_state(
    planning_state: PlanningState | None,
    *,
    ui_language: str | None = None,
    runtime_input_hint_text: str | None = None,
) -> CreateCompileContext | None:
    runtime_metadata_state = _runtime_metadata_state_from_planning_state(planning_state)
    metadata_disables_declared_input_fields = (
        _runtime_metadata_disables_declared_input_fields_from_planning_state(
            planning_state
        )
    )
    runtime_input_field_hints = _runtime_input_field_hints_from_source(
        runtime_metadata_state=runtime_metadata_state,
        runtime_input_hint_text=runtime_input_hint_text,
    )
    template_placeholder_field_hints = (
        _template_placeholder_field_hints_from_planning_state(planning_state)
    )
    if planning_state is None:
        if (
            ui_language is None
            and not runtime_input_field_hints
            and not template_placeholder_field_hints
        ):
            return None
        return CreateCompileContext(
            ui_language=ui_language,
            runtime_metadata_state=runtime_metadata_state,
            runtime_metadata_disables_declared_input_fields=(
                metadata_disables_declared_input_fields
            ),
            runtime_input_field_hints=runtime_input_field_hints,
            template_placeholder_field_hints=template_placeholder_field_hints,
        )
    architecture = _architecture_envelope_from_planning_state(planning_state)
    runtime_input_type = _runtime_input_type_from_architecture(
        architecture
    ) or _runtime_input_type_from_planning_state(planning_state)
    final_output_type = _final_output_type_from_architecture(
        architecture
    ) or _final_output_type_from_planning_state(planning_state)
    return CreateCompileContext(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=_final_output_mode_from_architecture(architecture),
        pattern_ids=_pattern_ids_from_architecture(architecture),
        pattern_chain_steps=_pattern_chain_steps_from_architecture(architecture),
        ui_language=ui_language,
        runtime_metadata_state=runtime_metadata_state,
        runtime_metadata_disables_declared_input_fields=(
            metadata_disables_declared_input_fields
        ),
        runtime_input_field_hints=runtime_input_field_hints,
        template_placeholder_field_hints=template_placeholder_field_hints,
        aggregation_intent=_aggregation_intent_for_compile_context(
            planning_state,
            architecture,
        ),
        terminal_output_schema=_terminal_output_schema_from_planning_state(
            planning_state,
            final_output_type=final_output_type,
        ),
        source_reader_required_fields=_source_reader_required_fields_from_planning_state(
            planning_state,
            ui_language=ui_language,
        ),
        result_contract_output_fields=(
            _result_contract_output_fields_from_planning_state(
                planning_state,
                ui_language=ui_language,
            )
        ),
        report_disposition=_report_disposition_from_planning_state(planning_state),
    )


def _report_disposition_from_planning_state(
    planning_state: PlanningState,
) -> str | None:
    slot = planning_state.resolved_slots.get("report_disposition")
    return slot.value if slot is not None else None


def _source_reader_required_fields_from_planning_state(
    planning_state: PlanningState,
    *,
    ui_language: str | None,
) -> tuple[SourceCaptureField, ...]:
    contract = derive_result_contract(planning_state)
    if contract is None:
        return ()
    if (
        contract.post_processing_goal != "summarize_or_overview"
        and "summary" not in contract.secondary_obligations
    ):
        return ()
    return (
        SourceCaptureField(
            name="summary",
            description=_summary_source_reader_field_description(ui_language),
        ),
    )


def _summary_source_reader_field_description(ui_language: str | None) -> str:
    if ui_language is None or ui_language.casefold().startswith("sv"):
        return "Kort sammanfattning grundad i källmaterialet."
    return "Concise summary grounded in the source material."


def _result_contract_output_fields_from_planning_state(
    planning_state: PlanningState,
    *,
    ui_language: str | None,
) -> tuple[StructuredFieldDraft, ...]:
    contract = derive_result_contract(planning_state)
    if contract is None:
        return ()

    field_names: list[str] = []
    if contract.post_processing_goal == "compare_or_validate":
        field_names.append("matches")
    if "missing_information_policy" in contract.secondary_obligations:
        field_names.extend(("missing_information", "uncertainty"))
    if "recommendations" in contract.secondary_obligations:
        field_names.append("recommended_action")
    if "risks" in contract.secondary_obligations:
        field_names.append("risks")
    if "deviations" in contract.secondary_obligations:
        field_names.append("deviations")
    if "open_questions" in contract.secondary_obligations:
        field_names.append("open_questions")

    return tuple(
        StructuredFieldDraft(
            name=name,
            field_type="string",
            description=_result_contract_output_field_description(
                name,
                ui_language=ui_language,
            ),
        )
        for name in dict.fromkeys(field_names)
    )


def _result_contract_output_field_description(
    field_name: str,
    *,
    ui_language: str | None,
) -> str:
    swedish = ui_language is None or ui_language.casefold().startswith("sv")
    if field_name == "missing_information":
        return (
            "Saknade uppgifter eller krav som inte kan verifieras i underlaget."
            if swedish
            else "Missing information or requirements that cannot be verified from the source material."
        )
    if field_name == "matches":
        return (
            "Krav eller kontrollpunkter som uppfylls enligt jämförelsen."
            if swedish
            else "Requirements or control points that are satisfied by the comparison."
        )
    if field_name == "uncertainty":
        return (
            "Osäkra punkter där underlaget inte räcker för en säker bedömning."
            if swedish
            else "Uncertain points where the source material is insufficient for a confident assessment."
        )
    if field_name == "recommended_action":
        return (
            "Rekommenderad nästa åtgärd grundad i jämförelsen eller granskningen."
            if swedish
            else "Recommended next action grounded in the comparison or review."
        )
    if field_name == "risks":
        return (
            "Risker som är grundade i underlaget eller i de angivna reglerna."
            if swedish
            else "Risks grounded in the source material or provided rules."
        )
    if field_name == "deviations":
        return (
            "Avvikelser mot angivet referensmaterial, regler eller checklista."
            if swedish
            else "Deviations from the provided reference material, rules, or checklist."
        )
    if field_name == "open_questions":
        return (
            "Öppna frågor som behöver besvaras innan slutsatsen är komplett."
            if swedish
            else "Open questions that must be answered before the conclusion is complete."
        )
    raise ValueError(f"Unsupported result contract output field: {field_name}")


def _runtime_metadata_state_from_planning_state(
    planning_state: PlanningState | None,
) -> RuntimeMetadataState | None:
    if planning_state is None:
        return None
    slot = planning_state.resolved_slots.get("runtime_metadata_fields")
    return normalize_runtime_metadata_state(slot.value if slot is not None else None)


def _runtime_metadata_disables_declared_input_fields_from_planning_state(
    planning_state: PlanningState | None,
) -> bool:
    if planning_state is None:
        return False
    slot = planning_state.resolved_slots.get("runtime_metadata_fields")
    if slot is None:
        return False
    return runtime_metadata_disables_declared_input_fields(
        state=normalize_runtime_metadata_state(slot.value),
        source=slot.source,
        confidence=slot.confidence,
    )


def _runtime_input_field_hints_from_source(
    *,
    runtime_metadata_state: RuntimeMetadataState | None,
    runtime_input_hint_text: str | None,
) -> tuple[RuntimeInputFieldHint, ...]:
    if runtime_input_hint_text is None:
        return ()
    source_text = runtime_input_hint_text.strip()
    if not source_text:
        return ()
    if not runtime_metadata_allows_input_fields(runtime_metadata_state):
        return ()
    return extract_runtime_input_field_hints(source_text)


def _template_placeholder_field_hints_from_planning_state(
    planning_state: PlanningState | None,
) -> tuple[RuntimeInputFieldHint, ...]:
    if planning_state is None:
        return ()
    evidence = planning_state.output_schema_evidence
    if evidence is None or evidence.source != "template_placeholders":
        return ()
    raw_properties = evidence.json_schema.get("properties")
    if not isinstance(raw_properties, Mapping):
        return ()

    raw_required = evidence.json_schema.get("required")
    required_names: set[str] = (
        {item for item in raw_required if isinstance(item, str)}
        if isinstance(raw_required, list)
        else set()
    )
    hints: list[RuntimeInputFieldHint] = []
    seen: set[str] = set()
    for raw_placeholder in raw_properties:
        field_name = _template_placeholder_form_field_name(raw_placeholder)
        if field_name is None or field_name in seen:
            continue
        hints.append(
            RuntimeInputFieldHint(
                variable_name=field_name,
                label=field_name,
                required=(
                    raw_placeholder in required_names or field_name in required_names
                ),
            )
        )
        seen.add(field_name)
    return tuple(hints)


def _template_placeholder_form_field_name(placeholder: str) -> str | None:
    candidate = " ".join(placeholder.strip().split())
    if not candidate:
        return None

    candidate_casefold = candidate.casefold()
    for prefix in ("flow_input.", "flow.input."):
        if not candidate_casefold.startswith(prefix):
            continue
        candidate = candidate[len(prefix) :].strip()
        break

    if not can_expose_form_field_bare_alias(candidate):
        return None
    return candidate


def _runtime_input_type_from_planning_state(state: PlanningState) -> InputType | None:
    slot = state.resolved_slots.get("primary_runtime_input")
    if slot is None:
        return None
    flow_input_type = flow_input_type_from_primary_runtime_input_value(slot.value)
    if flow_input_type is None:
        return None
    return InputType(flow_input_type.value)


def _architecture_envelope_from_planning_state(
    state: PlanningState,
) -> ArchitectureEnvelope | None:
    return state.architecture_commit or derive_architecture_commit_draft(state)


def _runtime_input_type_from_architecture(
    architecture: ArchitectureEnvelope | None,
) -> InputType | None:
    if architecture is None or not architecture.tuples_chain:
        return None
    try:
        runtime_input_type = InputType(architecture.tuples_chain[0].input_type)
    except ValueError:
        return None
    if runtime_input_type is InputType.ANY:
        # ANY is a capability envelope, not a concrete compile input type.
        return None
    return runtime_input_type


def _final_output_type_from_planning_state(state: PlanningState) -> OutputType | None:
    slot = state.resolved_slots.get("terminal_output")
    if slot is None:
        return None
    return {
        "docx": OutputType.DOCX,
        "docx_document": OutputType.DOCX,
        "json": OutputType.JSON,
        "pdf": OutputType.PDF,
        "pdf_document": OutputType.PDF,
        "structured_json": OutputType.JSON,
        "structured_text": OutputType.TEXT,
        "text": OutputType.TEXT,
    }.get(slot.value)


def _terminal_output_schema_from_planning_state(
    state: PlanningState,
    *,
    final_output_type: OutputType | None,
) -> JsonObject | None:
    evidence = state.output_schema_evidence
    if evidence is None:
        return None
    if evidence.source != "freeform_text":
        return None
    if final_output_type != OutputType.JSON:
        slot = state.resolved_slots.get("terminal_output")
        raise AIBuilderArchitectureError(
            public_code="architecture_critic_invariant_failed",
            detail=(
                "output_schema_evidence requires a JSON terminal output before "
                "create-mode compilation"
            ),
            log_context={
                "final_output_type": (
                    final_output_type.value if final_output_type is not None else None
                ),
                "terminal_output_slot": slot.value if slot is not None else None,
                "terminal_output_source": slot.source if slot is not None else None,
            },
        )
    return evidence.json_schema


def _final_output_type_from_architecture(
    architecture: ArchitectureEnvelope | None,
) -> OutputType | None:
    if architecture is None or not architecture.tuples_chain:
        return None
    try:
        return OutputType(architecture.tuples_chain[-1].output_type)
    except ValueError:
        return None


def _final_output_mode_from_architecture(
    architecture: ArchitectureEnvelope | None,
) -> OutputMode | None:
    if architecture is None or not architecture.tuples_chain:
        return None
    try:
        return OutputMode(architecture.tuples_chain[-1].output_mode)
    except ValueError:
        return None


def _pattern_chain_steps_from_architecture(
    architecture: ArchitectureEnvelope | None,
) -> tuple[str, ...]:
    if architecture is None:
        return ()
    chain_steps: list[str] = []
    seen: set[str] = set()
    for pattern_id in architecture.chosen_patterns:
        pattern = PATTERN_REGISTRY.get(pattern_id)
        if pattern is not None and pattern.chain_steps:
            for chain_step in pattern.chain_steps:
                if chain_step in seen:
                    continue
                chain_steps.append(chain_step)
                seen.add(chain_step)
    return tuple(chain_steps)


def _pattern_ids_from_architecture(
    architecture: ArchitectureEnvelope | None,
) -> tuple[str, ...]:
    if architecture is None:
        return ()
    return tuple(architecture.chosen_patterns)


def _aggregation_intent_for_compile_context(
    state: PlanningState,
    architecture: ArchitectureEnvelope | None,
) -> AggregationIntent:
    """Return the server-owned aggregate/compare policy for dataflow.

    The model may describe comparison or synthesis semantically, but it should
    not have to know when Eneo Flow should use `all_previous_steps`.
    """

    runtime_input_type = _runtime_input_type_from_architecture(
        architecture
    ) or _runtime_input_type_from_planning_state(state)
    if architecture is not None:
        if architecture.aggregation_intent != "linear":
            return architecture.aggregation_intent
        if _COMPARISON_FAN_IN_PATTERN_IDS & set(architecture.chosen_patterns):
            return "compare"

    return derive_aggregation_intent_from_slots(
        state,
        document_material_input=runtime_input_type
        in (
            InputType.DOCUMENT,
            InputType.FILE,
        ),
    )


def _compile_form_fields(
    *,
    intent_fields: list[FlowInputFieldIntent],
    context: CreateCompileContext | None,
    runtime_input_type: InputType | None,
) -> tuple[list[FormFieldSpec], list[str], set[str]]:
    runtime_metadata_state = (
        context.runtime_metadata_state if context is not None else None
    )
    runtime_input_field_hints = (
        context.runtime_input_field_hints if context is not None else ()
    )
    template_placeholder_field_hints = (
        context.template_placeholder_field_hints if context is not None else ()
    )
    metadata_disables_declared_input_fields = (
        context.runtime_metadata_disables_declared_input_fields
        if context is not None
        else False
    )
    active_intent_fields = intent_fields
    dropped_form_field_ref_names: set[str] = set()
    if runtime_metadata_state is not None and not runtime_metadata_allows_input_fields(
        runtime_metadata_state
    ):
        _log_dropped_runtime_metadata_input_fields(
            field_names=[
                *(
                    field.variable_name
                    for field in intent_fields
                    if metadata_disables_declared_input_fields
                ),
                *(hint.variable_name for hint in runtime_input_field_hints),
            ],
            runtime_metadata_state=runtime_metadata_state,
        )
        dropped_ref_names = {
            *(field.variable_name for field in intent_fields),
            *(hint.variable_name for hint in runtime_input_field_hints),
        }
        runtime_input_field_hints = ()
        if metadata_disables_declared_input_fields:
            active_intent_fields = []
            dropped_form_field_ref_names.update(dropped_ref_names)

    fields: list[FormFieldSpec] = []
    dropped_primary_input_field_names: list[str] = []
    metadata_hint_names = {hint.variable_name for hint in runtime_input_field_hints}
    template_hint_names = {
        hint.variable_name for hint in template_placeholder_field_hints
    }
    for field in active_intent_fields:
        if (
            metadata_hint_names
            and field.variable_name not in metadata_hint_names
            and field.variable_name not in template_hint_names
        ):
            dropped_form_field_ref_names.add(field.variable_name)
            continue
        if is_primary_runtime_input_shadow_field(
            variable_name=field.variable_name,
            field_type=field.field_type,
            runtime_input_type=runtime_input_type,
        ):
            dropped_primary_input_field_names.append(field.variable_name)
            dropped_form_field_ref_names.add(field.variable_name)
            continue
        fields.append(_compile_input_field(field))

    seen = {field.name for field in fields}
    for hint in (*runtime_input_field_hints, *template_placeholder_field_hints):
        if is_primary_runtime_input_shadow_field(
            variable_name=hint.variable_name,
            field_type=hint.field_type,
            runtime_input_type=runtime_input_type,
        ):
            dropped_primary_input_field_names.append(hint.variable_name)
            dropped_form_field_ref_names.add(hint.variable_name)
            continue
        if hint.variable_name in seen:
            continue
        fields.append(
            FormFieldSpec(
                name=hint.variable_name,
                label=hint.label,
                type=hint.field_type,
                required=hint.required,
                options=list(hint.options) or None,
            )
        )
        seen.add(hint.variable_name)
    return fields, dropped_primary_input_field_names, dropped_form_field_ref_names


def _server_owned_runtime_field_names(
    *,
    context: CreateCompileContext | None,
    known_field_names: set[str],
) -> set[str]:
    if context is None:
        return set()
    return {
        hint.variable_name
        for hint in (
            *context.runtime_input_field_hints,
            *context.template_placeholder_field_hints,
        )
        if hint.variable_name in known_field_names
    }


def _log_dropped_runtime_metadata_input_fields(
    *,
    field_names: list[str],
    runtime_metadata_state: RuntimeMetadataState,
) -> None:
    unique_names = sorted(set(field_names))
    if not unique_names:
        return
    logger.info(
        "ai_builder_runtime_metadata_input_fields_dropped",
        extra={
            "field_names": unique_names,
            "runtime_metadata_state": runtime_metadata_state,
        },
    )


def _log_dropped_primary_input_shadow_fields(
    *,
    field_names: list[str],
    runtime_input_type: InputType,
) -> None:
    unique_names = sorted(set(field_names))
    if not unique_names:
        return
    logger.info(
        "ai_builder_primary_input_shadow_fields_dropped",
        extra={
            "field_names": unique_names,
            "runtime_input_type": runtime_input_type.value,
        },
    )


def _compile_input_field(field: FlowInputFieldIntent) -> FormFieldSpec:
    return FormFieldSpec(
        name=field.variable_name,
        label=field.label,
        type=field.field_type,
        required=field.required,
        options=list(field.options) or None,
    )

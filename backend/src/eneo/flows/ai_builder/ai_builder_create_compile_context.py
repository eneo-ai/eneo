"""Prepared create compile context derived from committed planning state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    ResultOutputFieldRole,
    derive_result_contract,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    NO_EXTRA_RUNTIME_METADATA,
    RuntimeInputFieldHint,
    RuntimeMetadataState,
    normalize_runtime_metadata_state,
    runtime_metadata_disables_declared_input_fields,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.pattern_registry import pattern_chain_steps
from eneo.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommit,
    CheckpointIntent,
    PlanningState,
    ReportDisposition,
)
from eneo.flows.flow_authoring_spec import InputType, OutputMode, OutputType
from eneo.flows.flow_variable_definitions import template_placeholder_form_field_name
from eneo.json_types import JsonObject


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
    selected_template_count: int | None = None
    selected_template_placeholders: tuple[str, ...] | None = None
    aggregation_intent: AggregationIntent = "linear"
    flow_input_schema: JsonObject | None = None
    terminal_output_schema: JsonObject | None = None
    source_reader_required_fields: tuple[SourceCaptureField, ...] = ()
    result_contract_output_fields: tuple[StructuredFieldDraft, ...] = ()
    result_contract_required_roles: tuple[ResultOutputFieldRole, ...] = ()
    requested_output_sections: RequestedOutputSections = EMPTY_REQUESTED_OUTPUT_SECTIONS
    report_disposition: ReportDisposition | None = None
    checkpoint_intents: tuple[CheckpointIntent, ...] | None = None

    def __post_init__(self) -> None:
        if self.runtime_input_type is InputType.ANY:
            raise ValueError("CreateCompileContext.runtime_input_type cannot be ANY")
        if (
            self.flow_input_schema is not None
            and self.runtime_input_type is not InputType.JSON
        ):
            raise ValueError(
                "CreateCompileContext.flow_input_schema requires JSON runtime input"
            )
        if self.runtime_max_files is not None and self.runtime_max_files < 1:
            raise ValueError("runtime_max_files must be at least 1 when provided")
        if (
            self.runtime_metadata_disables_declared_input_fields
            and self.runtime_metadata_state != NO_EXTRA_RUNTIME_METADATA
        ):
            raise ValueError(
                "CreateCompileContext can disable declared input fields only "
                "for an explicit no-extra-metadata decision"
            )

    @property
    def admitted_runtime_input_field_hints(
        self,
    ) -> tuple[RuntimeInputFieldHint, ...]:
        if self.runtime_metadata_disables_declared_input_fields:
            return ()
        return self.runtime_input_field_hints

    @property
    def admitted_form_field_hints(self) -> tuple[RuntimeInputFieldHint, ...]:
        hints: list[RuntimeInputFieldHint] = []
        seen: set[str] = set()
        for hint in (
            *self.admitted_runtime_input_field_hints,
            *self.template_placeholder_field_hints,
        ):
            if hint.variable_name in seen:
                continue
            if is_primary_runtime_input_shadow_field(
                variable_name=hint.variable_name,
                field_type=hint.field_type,
                runtime_input_type=self.runtime_input_type,
            ):
                continue
            hints.append(hint)
            seen.add(hint.variable_name)
        return tuple(hints)

    @property
    def confirmed_runtime_field_contract_closed(self) -> bool:
        return any(
            hint.provenance == "user_confirmed"
            for hint in self.admitted_runtime_input_field_hints
        )

    @property
    def incompatible_confirmed_form_field_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                hint.variable_name
                for hint in (
                    *self.admitted_runtime_input_field_hints,
                    *self.template_placeholder_field_hints,
                )
                if hint.provenance == "user_confirmed"
                and is_primary_runtime_input_shadow_field(
                    variable_name=hint.variable_name,
                    field_type=hint.field_type,
                    runtime_input_type=self.runtime_input_type,
                )
            )
        )


def create_compile_context_from_planning_state(
    planning_state: PlanningState | None,
    *,
    ui_language: str | None = None,
    requested_output_sections: RequestedOutputSections = (
        EMPTY_REQUESTED_OUTPUT_SECTIONS
    ),
) -> CreateCompileContext | None:
    runtime_metadata_state = _runtime_metadata_state_from_planning_state(planning_state)
    metadata_disables_declared_input_fields = (
        _runtime_metadata_disables_declared_input_fields_from_planning_state(
            planning_state
        )
    )
    runtime_input_field_hints = _runtime_input_field_hints_from_planning_state(
        planning_state
    )
    template_placeholder_field_hints = (
        _template_placeholder_field_hints_from_planning_state(planning_state)
    )
    selected_template_roles = (
        []
        if planning_state is None
        else [role for role in planning_state.file_roles if role.role == "template"]
    )
    if planning_state is None:
        if (
            ui_language is None
            and not runtime_input_field_hints
            and not template_placeholder_field_hints
            and not requested_output_sections.sections
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
            selected_template_count=None,
            requested_output_sections=requested_output_sections,
        )
    architecture = planning_state.architecture_commit
    runtime_input_type = _runtime_input_type_from_architecture(architecture)
    final_output_type = _final_output_type_from_architecture(architecture)
    return CreateCompileContext(
        runtime_input_type=runtime_input_type,
        runtime_max_files=planning_state.mapped_file_limit.accepted_value,
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
        selected_template_count=len(selected_template_roles),
        selected_template_placeholders=(
            tuple(selected_template_roles[0].template_placeholders)
            if len(selected_template_roles) == 1
            and selected_template_roles[0].template_placeholders is not None
            else None
        ),
        aggregation_intent=_aggregation_intent_for_compile_context(
            architecture,
        ),
        flow_input_schema=_flow_input_schema_from_planning_state(
            planning_state,
            runtime_input_type=runtime_input_type,
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
        result_contract_required_roles=_result_contract_required_roles_from_planning_state(
            planning_state
        ),
        requested_output_sections=requested_output_sections,
        report_disposition=(
            architecture.report_disposition if architecture is not None else None
        ),
        checkpoint_intents=tuple(planning_state.checkpoint_intents),
    )


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


def _result_contract_required_roles_from_planning_state(
    planning_state: PlanningState,
) -> tuple[ResultOutputFieldRole, ...]:
    contract = derive_result_contract(planning_state)
    if contract is None:
        return ()
    return contract.required_output_field_roles


def _result_contract_output_fields_from_planning_state(
    planning_state: PlanningState,
    *,
    ui_language: str | None,
) -> tuple[StructuredFieldDraft, ...]:
    contract = derive_result_contract(planning_state)
    if contract is None:
        return ()

    field_names = [
        requirement.canonical_name for requirement in contract.required_output_fields
    ]
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
    if field_name == "decisions":
        return (
            "Beslut som framgår av underlaget."
            if swedish
            else "Decisions stated in the source material."
        )
    if field_name == "actions":
        return (
            "Åtgärder eller nästa steg som framgår av underlaget."
            if swedish
            else "Actions or next steps stated in the source material."
        )
    if field_name == "owners":
        return (
            "Ansvariga för åtgärderna, eller ospecificerat när uppgiften saknas."
            if swedish
            else "Owners for the actions, or unspecified when absent."
        )
    if field_name == "deadlines":
        return (
            "Tidsfrister för åtgärderna, eller ospecificerat när uppgiften saknas."
            if swedish
            else "Deadlines for the actions, or unspecified when absent."
        )
    raise ValueError(f"Unsupported result contract output field: {field_name}")


def _runtime_metadata_state_from_planning_state(
    planning_state: PlanningState | None,
) -> RuntimeMetadataState | None:
    if planning_state is None:
        return None
    slot = planning_state.resolved_slots.get("runtime_metadata_fields")
    return normalize_runtime_metadata_state(
        slot.value if slot is not None and slot.is_commit_grade else None
    )


def _runtime_metadata_disables_declared_input_fields_from_planning_state(
    planning_state: PlanningState | None,
) -> bool:
    if planning_state is None:
        return False
    slot = planning_state.resolved_slots.get("runtime_metadata_fields")
    if slot is None or not slot.is_commit_grade:
        return False
    return runtime_metadata_disables_declared_input_fields(
        state=normalize_runtime_metadata_state(slot.value),
        source=slot.source,
        confidence=slot.confidence,
    )


def _runtime_input_field_hints_from_planning_state(
    planning_state: PlanningState | None,
) -> tuple[RuntimeInputFieldHint, ...]:
    if planning_state is None:
        return ()
    return tuple(
        RuntimeInputFieldHint(
            variable_name=field.variable_name,
            label=field.label,
            field_type=field.field_type,
            required=field.required,
            options=tuple(field.options),
            provenance=field.provenance,
        )
        for field in planning_state.input_fields
    )


def _template_placeholder_field_hints_from_planning_state(
    planning_state: PlanningState | None,
) -> tuple[RuntimeInputFieldHint, ...]:
    if planning_state is None:
        return ()
    selected_templates = [
        role for role in planning_state.file_roles if role.role == "template"
    ]
    raw_placeholders: tuple[str, ...]
    if len(selected_templates) == 1:
        if selected_templates[0].template_placeholders is None:
            return ()
        raw_placeholders = tuple(selected_templates[0].template_placeholders)
    else:
        evidence = planning_state.output_schema_evidence
        if evidence is None or evidence.source != "template_placeholders":
            return ()
        raw_properties = evidence.json_schema.get("properties")
        if not isinstance(raw_properties, Mapping):
            return ()
        raw_placeholders = tuple(str(name) for name in raw_properties)
    hints: list[RuntimeInputFieldHint] = []
    seen: set[str] = set()
    for raw_placeholder in raw_placeholders:
        field_name = template_placeholder_form_field_name(raw_placeholder)
        if field_name is None or field_name in seen:
            continue
        hints.append(
            RuntimeInputFieldHint(
                variable_name=field_name,
                label=field_name,
                required=True,
                provenance="template_derived",
            )
        )
        seen.add(field_name)
    return tuple(hints)


def _runtime_input_type_from_architecture(
    architecture: ArchitectureCommit | None,
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


def _terminal_output_schema_from_planning_state(
    state: PlanningState,
    *,
    final_output_type: OutputType | None,
) -> JsonObject | None:
    evidence = state.output_schema_evidence
    if evidence is None:
        return None
    if evidence.source != "declared_schema":
        # Inferred examples are hints: the proposal owns types and nesting.
        # Pinning them verbatim would overwrite the model's typed fields.
        return None
    if final_output_type != OutputType.JSON:
        return None
    return evidence.json_schema


def _flow_input_schema_from_planning_state(
    state: PlanningState,
    *,
    runtime_input_type: InputType | None,
) -> JsonObject | None:
    evidence = state.input_schema_evidence
    if evidence is None or runtime_input_type is not InputType.JSON:
        return None
    return evidence.json_schema


def _final_output_type_from_architecture(
    architecture: ArchitectureCommit | None,
) -> OutputType | None:
    if architecture is None or not architecture.tuples_chain:
        return None
    try:
        return OutputType(architecture.tuples_chain[-1].output_type)
    except ValueError:
        return None


def _final_output_mode_from_architecture(
    architecture: ArchitectureCommit | None,
) -> OutputMode | None:
    if architecture is None or not architecture.tuples_chain:
        return None
    try:
        return OutputMode(architecture.tuples_chain[-1].output_mode)
    except ValueError:
        return None


def _pattern_chain_steps_from_architecture(
    architecture: ArchitectureCommit | None,
) -> tuple[str, ...]:
    if architecture is None:
        return ()
    return pattern_chain_steps(architecture.chosen_patterns)


def _pattern_ids_from_architecture(
    architecture: ArchitectureCommit | None,
) -> tuple[str, ...]:
    if architecture is None:
        return ()
    return tuple(architecture.chosen_patterns)


def _aggregation_intent_for_compile_context(
    architecture: ArchitectureCommit | None,
) -> AggregationIntent:
    """Return the server-owned aggregate/compare policy for dataflow.

    The model may describe comparison or synthesis semantically, but it should
    not have to know when Eneo Flow should use `all_previous_steps`.
    """

    return architecture.aggregation_intent if architecture is not None else "linear"

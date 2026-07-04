from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    RuntimeInputFieldHintSource,
    compile_create_intent_to_spec,
    compile_create_steps_to_spec,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_create_dataflow import (
    auto_bind_targeted_underlag_for_text_composer as _auto_bind_targeted_underlag_for_text_composer,
)
from eneo.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_step_mechanics,
)
from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_form_field_type_values,
    builder_output_type_values,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    _CREATE_INTENT_STEP_BACKEND_OWNED_KEYS,
    MAX_PROPOSAL_STEPS,
    ProposalIntentArgumentError,
    attach_selected_mcp_refs_to_explicit_intent_steps,
    build_create_flow_tool_schema,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
    canonicalize_flow_spec_resources,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    DETAILED_CASE_METADATA,
    NO_EXTRA_RUNTIME_METADATA,
    RuntimeInputFieldHint,
    extract_runtime_input_field_hints,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.pattern_registry import (
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    PATTERN_REGISTRY,
    STRUCTURED_EXTRACTION_STEP,
    TERMINAL_ARTIFACT_STEP,
)
from eneo.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommitDraft,
    OutputSchemaEvidence,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.output_processing import validate_against_contract
from eneo.main.exceptions import TypedIOValidationException
from tests.unittests.flows.ai_builder.ai_builder_intent_diagnostic_payloads import (
    self_correction_intent_with_step_assumptions_payload,
)
from tests.unittests.flows.ai_builder.authoring_command_assertions import (
    assert_create_spec_prepares_through_authoring_command,
)

PROPOSAL_INTENT_LOGGER = "eneo.flows.ai_builder.ai_builder_proposal_intent"
CREATE_COMPILER_LOGGER = "eneo.flows.ai_builder.ai_builder_create_compiler"


def _normalize_create_steps(
    *,
    flow_name: str,
    steps: list[NewStepDraft],
    form_fields: list[FormFieldSpec] | None = None,
    flow_description: str | None = None,
    aggregation_intent: AggregationIntent = "linear",
) -> list[NewStepDraft]:
    return normalize_create_step_mechanics(
        steps=steps,
        form_fields=form_fields or [],
        flow_name=flow_name,
        flow_description=flow_description,
        aggregation_intent=aggregation_intent,
    )


def _compile_create_steps(
    *,
    flow_name: str = "Test flow",
    flow_description: str | None = None,
    form_fields: list[FormFieldSpec] | None = None,
    steps: list[NewStepDraft],
    document_body_writer_step_indexes: tuple[int, ...] = (),
    aggregation_intent: AggregationIntent = "linear",
    terminal_output_schema: dict[str, object] | None = None,
) -> FlowDraftSpecCore:
    return compile_create_steps_to_spec(
        flow_name=flow_name,
        flow_description=flow_description,
        form_fields=form_fields,
        steps=steps,
        document_body_writer_step_indexes=document_body_writer_step_indexes,
        aggregation_intent=aggregation_intent,
        terminal_output_schema=terminal_output_schema,
    )


def auto_bind_targeted_underlag_for_text_composer(
    steps: list[NewStepDraft],
    *,
    flow_name: str = "Auto-bind test",
    flow_description: str | None = None,
    aggregation_intent: AggregationIntent,
) -> list[NewStepDraft]:
    return _auto_bind_targeted_underlag_for_text_composer(
        steps=steps,
        flow_name=flow_name,
        flow_description=flow_description,
        aggregation_intent=aggregation_intent,
    )


def _model_resource(
    local_id: str,
    name: str,
    *,
    provider: str = "test",
) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": provider,
    }


def _kb_resource(
    local_id: str,
    name: str,
    *,
    description: str = "",
) -> AIBuilderAvailableKnowledgeBaseResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "description": description,
    }


def _catalog_with_mcps(
    mcps: list[dict[str, object]],
) -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=mcps,
    )


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[],
    )


def _canonicalize_create_spec(
    spec: FlowDraftSpecCore,
    *,
    catalog: AIBuilderResourceCatalog,
) -> FlowDraftSpecCore:
    canonicalized, issues = canonicalize_flow_spec_resources(spec, catalog=catalog)
    assert issues == []
    return canonicalized


def _field(
    name: str,
    field_type: str,
    *,
    description: str = "Beskrivning",
    required: bool = True,
    fields: list[StructuredFieldDraft] | None = None,
    item_fields: list[StructuredFieldDraft] | None = None,
) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type=field_type,
        description=description,
        required=required,
        fields=fields,
        item_fields=item_fields,
    )


def _committed_architecture_state(
    *,
    input_type: str,
    output_type: str,
    output_mode: str,
    chosen_patterns: list[str],
    required_capabilities: list[str],
    aggregation_intent: AggregationIntent = "linear",
) -> PlanningState:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type=input_type,
                    output_type=output_type,
                    output_mode=output_mode,
                )
            ],
            chosen_patterns=chosen_patterns,
            required_capabilities=required_capabilities,
            aggregation_intent=aggregation_intent,
        )
    )
    return state


def _output_schema_evidence(schema: dict[str, object]) -> OutputSchemaEvidence:
    return OutputSchemaEvidence(
        json_schema=schema,
        source="freeform_text",
        confidence="high",
        evidence=["message:msg_schema", "fenced_json_schema"],
    )


def _structured_field_snapshot(
    name: str,
    field_type: str,
    description: str,
    *,
    required: bool = True,
    fields: list[dict[str, object]] | None = None,
    item_fields: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "field_type": field_type,
        "description": description,
        "required": required,
        "fields": fields,
        "item_fields": item_fields,
    }


def _form_field_snapshot(
    name: str,
    label: str,
    field_type: str,
    *,
    required: bool,
) -> dict[str, object]:
    return {
        "name": name,
        "label": label,
        "type": field_type,
        "required": required,
        "options": None,
    }


def _create_step_snapshot(
    *,
    name: str,
    instructions: str,
    input_source: str,
    input_type: str,
    output_type: str,
    runtime_required: bool = False,
    document_delivery_mode: str = "not_applicable",
    uses_form_fields: list[str] | None = None,
    review_mode: str | None = None,
    output_fields: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "instructions": instructions,
        "input_source": input_source,
        "input_type": input_type,
        "output_type": output_type,
        "model_ref": None,
        "knowledge_refs": [],
        "mcp_server_refs": [],
        "mcp_tool_refs": [],
        "runtime_required": runtime_required,
        "runtime_max_files": None,
        "uses_form_fields": uses_form_fields or [],
        "uses_previous_fields": [],
        "uses_previous_outputs": [],
        "document_delivery_mode": document_delivery_mode,
        "citations_requested": False,
        "review_mode": review_mode,
        "output_fields": output_fields,
    }


def test_new_step_draft_rejects_nested_assistant_spec() -> None:
    with pytest.raises(ValidationError) as exc_info:
        NewStepDraft.model_validate(
            {
                "name": "Extract",
                "instructions": "Extract source facts.",
                "assistant_spec": {"instructions": "Nested instructions."},
            }
        )

    assert "assistant_spec" in str(exc_info.value)


def _create_spec_snapshot(
    *,
    flow_name: str,
    steps: list[dict[str, object]],
    flow_description: str | None = None,
    form_fields: list[dict[str, object]] | None = None,
    document_body_writer_step_indexes: tuple[int, ...] = (),
) -> dict[str, object]:
    return _compile_create_steps(
        flow_name=flow_name,
        flow_description=flow_description,
        form_fields=[
            FormFieldSpec.model_validate(field) for field in form_fields or []
        ],
        steps=[NewStepDraft.model_validate(step) for step in steps],
        document_body_writer_step_indexes=document_body_writer_step_indexes,
    ).model_dump(mode="json")


def _source_facts_fields_snapshot() -> list[dict[str, object]]:
    return [
        _structured_field_snapshot(
            "source_facts",
            "array",
            "Important source facts extracted from the input material.",
            item_fields=[
                _structured_field_snapshot(
                    "fact",
                    "string",
                    "A concise source fact.",
                ),
                _structured_field_snapshot(
                    "source_note",
                    "string",
                    "Where the fact came from or why it matters.",
                    required=False,
                ),
            ],
        ),
        _structured_field_snapshot(
            "uncertainties",
            "array",
            "Missing, ambiguous, or uncertain information.",
            required=False,
            item_fields=[
                _structured_field_snapshot(
                    "issue",
                    "string",
                    "A missing or uncertain point.",
                )
            ],
        ),
    ]


def test_compile_context_carries_output_schema_for_terminal_json_only() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    json_state = _committed_architecture_state(
        input_type="text",
        output_type="json",
        output_mode="pass_through",
        chosen_patterns=["text_to_json"],
        required_capabilities=["input_text", "output_mode_pass_through"],
    )
    json_state.output_schema_evidence = _output_schema_evidence(schema)
    text_state = _committed_architecture_state(
        input_type="text",
        output_type="text",
        output_mode="pass_through",
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_text", "output_mode_pass_through"],
    )
    text_state.output_schema_evidence = _output_schema_evidence(schema)

    json_context = create_compile_context_from_planning_state(json_state)
    text_context = create_compile_context_from_planning_state(text_state)

    assert json_context is not None
    assert json_context.terminal_output_schema == schema
    assert text_context is not None
    assert text_context.terminal_output_schema is None


def test_compile_create_intent_applies_exact_terminal_output_schema_evidence() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["approved", "rejected"],
                "description": "Final status.",
            },
            "created_at": {"type": "string", "format": "date-time"},
        },
        "required": ["status"],
        "additionalProperties": True,
    }
    state = _committed_architecture_state(
        input_type="text",
        output_type="json",
        output_mode="pass_through",
        chosen_patterns=["text_to_json"],
        required_capabilities=["input_text", "output_mode_pass_through"],
    )
    state.output_schema_evidence = _output_schema_evidence(schema)
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured status",
            "plan_rationale": "Return the requested status object.",
            "steps": [
                {
                    "name": "Return status",
                    "instructions": "Return the status.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "model_supplied_stale_field",
                            "field_type": "string",
                            "description": "Wrong field.",
                        }
                    ],
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    terminal_step = compiled.steps[-1]

    assert terminal_step.output_contract == schema
    assert "model_supplied_stale_field" not in terminal_step.assistant_spec.instructions
    validate_against_contract(
        {"status": "approved", "created_at": "2026-07-04T12:00:00Z", "extra": "ok"},
        terminal_step.output_contract,
        label="terminal output",
    )
    with pytest.raises(TypedIOValidationException):
        validate_against_contract(
            {"status": "pending"},
            terminal_step.output_contract,
            label="terminal output",
        )


def test_compile_create_steps_applies_schema_only_to_terminal_json_step() -> None:
    terminal_schema: dict[str, object] = {
        "type": "object",
        "properties": {"final_status": {"type": "string", "enum": ["done"]}},
        "required": ["final_status"],
        "additionalProperties": False,
    }
    compiled = _compile_create_steps(
        steps=[
            NewStepDraft(
                name="Extract facts",
                instructions="Extract facts.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                output_fields=[_field("facts", "string")],
            ),
            NewStepDraft(
                name="Normalize final",
                instructions="Create the final status object.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
                output_fields=[_field("stale_final_field", "string")],
            ),
        ],
        terminal_output_schema=terminal_schema,
    )

    first_step, terminal_step = compiled.steps
    assert first_step.output_contract is not None
    assert set(first_step.output_contract["properties"]) == {"facts"}
    assert terminal_step.input_contract == first_step.output_contract
    assert terminal_step.output_contract == terminal_schema
    assert "stale_final_field" not in terminal_step.assistant_spec.instructions


@dataclass(frozen=True, slots=True)
class _CreateCompilerArchetypeCase:
    pattern_id: str
    steps: tuple[NewStepDraft, ...]
    expected_output_modes: tuple[str, ...]
    form_fields: tuple[FormFieldSpec, ...] = ()
    expected_mcp_server_refs_by_step: tuple[tuple[str, ...], ...] | None = None
    expected_mcp_tool_refs_by_step: tuple[tuple[str, ...], ...] | None = None


def _case(
    *,
    pattern_id: str,
    steps: tuple[NewStepDraft, ...],
    expected_output_modes: tuple[str, ...],
    form_fields: tuple[FormFieldSpec, ...] = (),
    expected_mcp_server_refs_by_step: tuple[tuple[str, ...], ...] | None = None,
    expected_mcp_tool_refs_by_step: tuple[tuple[str, ...], ...] | None = None,
) -> _CreateCompilerArchetypeCase:
    return _CreateCompilerArchetypeCase(
        pattern_id=pattern_id,
        steps=steps,
        form_fields=form_fields,
        expected_output_modes=expected_output_modes,
        expected_mcp_server_refs_by_step=expected_mcp_server_refs_by_step,
        expected_mcp_tool_refs_by_step=expected_mcp_tool_refs_by_step,
    )


_CREATE_COMPILER_ARCHETYPE_CASES: tuple[_CreateCompilerArchetypeCase, ...] = (
    _case(
        pattern_id="summarize_text",
        steps=(
            NewStepDraft(
                name="Sammanfatta texten",
                instructions="Skriv en kort sammanfattning av texten.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="extract_structured_fields",
        steps=(
            NewStepDraft(
                name="Extrahera fält",
                instructions="Extrahera namn och datum från texten.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                output_fields=(
                    _field("customer_name", "string", description="Kundens namn."),
                    _field("issued_at", "string", description="Utfärdandedatum."),
                ),
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="json_to_structured_payload",
        steps=(
            NewStepDraft(
                name="Transformera JSON",
                instructions="Normalisera inkommande JSON till det önskade schemat.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
                output_fields=(
                    _field("customer_name", "string", description="Kundens namn."),
                    _field("risk_flags", "array", description="Identifierade risker."),
                ),
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="json_to_text_summary",
        steps=(
            NewStepDraft(
                name="Sammanfatta JSON",
                instructions="Skriv en läsbar sammanfattning av JSON-payloaden.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="json_to_artifact_report",
        steps=(
            NewStepDraft(
                name="Skapa JSON-baserad rapport",
                instructions="Skapa en DOCX-rapport från inkommande JSON.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="document_to_structured_report",
        steps=(
            NewStepDraft(
                name="Rapport från dokument",
                instructions="Sammanfatta dokumentet som en strukturerad rapport.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.TEXT,
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="document_to_docx_template",
        steps=(
            NewStepDraft(
                name="Läs in dokument",
                instructions="Läs in dokumentet och extrahera nyckelvärden.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=(
                    _field("reference_id", "string", description="Referensnummer."),
                ),
            ),
            NewStepDraft(
                name="Skriv brödtext",
                instructions="Förbered den text som ska fyllas i mallen.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Fyll DOCX-mall",
                instructions="Fyll i DOCX-mallen med brödtexten.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.DOCX,
                document_delivery_mode="template_fill",
            ),
        ),
        expected_output_modes=("pass_through", "pass_through", "template_fill"),
    ),
    _case(
        pattern_id="document_to_pdf_report",
        steps=(
            NewStepDraft(
                name="PDF-rapport",
                instructions="Producera en strukturerad PDF-rapport.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.PDF,
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="audio_transcription",
        steps=(
            NewStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera inspelningen till text.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
            ),
        ),
        expected_output_modes=("transcribe_only",),
    ),
    _case(
        pattern_id="audio_to_artifact_report",
        steps=(
            NewStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera inspelningen till text.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Skapa PDF-rapport",
                instructions="Skapa en PDF-rapport från transkriptionen.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.PDF,
            ),
        ),
        expected_output_modes=("transcribe_only", "pass_through"),
    ),
    _case(
        pattern_id="text_to_artifact_report",
        steps=(
            NewStepDraft(
                name="Skapa DOCX-rapport",
                instructions="Skapa en DOCX-rapport från textunderlaget.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.DOCX,
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="multi_step_quality_chain",
        steps=(
            NewStepDraft(
                name="Extrahera struktur",
                instructions="Extrahera strukturerade fält från dokumentet.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=(
                    _field("topic", "string", description="Huvudämnet i dokumentet."),
                ),
            ),
            NewStepDraft(
                name="Skriv utkast",
                instructions="Skapa ett första utkast baserat på extraktionen.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Granska kvalitet",
                instructions="Granska utkastet och föreslå förbättringar.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Slutresultat",
                instructions="Producera den slutgiltiga texten.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ),
        expected_output_modes=(
            "pass_through",
            "pass_through",
            "pass_through",
            "pass_through",
        ),
    ),
    _case(
        pattern_id="comparison",
        steps=(
            NewStepDraft(
                name="Jämför dokument",
                instructions="Jämför dokumentet mot de angivna referenserna.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.TEXT,
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="sectioned_form_intake",
        steps=(
            NewStepDraft(
                name="Fånga sektioner",
                instructions="Ta in rubriktext för varje angiven sektion.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
                uses_form_fields=("bakgrund", "analys"),
            ),
            NewStepDraft(
                name="Komponera resultat",
                instructions="Sammanställ sektionerna till ett slutresultat.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ),
        form_fields=(
            FormFieldSpec(
                name="bakgrund",
                label="Bakgrund",
                type="text",
                required=True,
            ),
            FormFieldSpec(
                name="analys",
                label="Analys",
                type="text",
                required=True,
            ),
        ),
        expected_output_modes=("pass_through", "pass_through"),
    ),
    _case(
        pattern_id="form_field_runtime_inputs",
        steps=(
            NewStepDraft(
                name="Generera svar",
                instructions="Svara med utgångspunkt från formulärfälten.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
                uses_form_fields=("reference_id", "owning_unit"),
            ),
        ),
        form_fields=(
            FormFieldSpec(
                name="reference_id",
                label="Referens-ID",
                type="text",
                required=True,
            ),
            FormFieldSpec(
                name="owning_unit",
                label="Ansvarig enhet",
                type="text",
            ),
        ),
        expected_output_modes=("pass_through",),
    ),
    _case(
        pattern_id="mcp_tool_step",
        steps=(
            NewStepDraft(
                name="Hämta lagerstatus",
                instructions="Använd lagerverktyget för att hämta aktuell produktdata.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
                mcp_server_refs=("mcp_server.inventory-api",),
                mcp_tool_refs=("mcp_tool.inventory-lookup",),
            ),
        ),
        expected_output_modes=("pass_through",),
        expected_mcp_server_refs_by_step=(("mcp_server.inventory-api",),),
        expected_mcp_tool_refs_by_step=(("mcp_tool.inventory-lookup",),),
    ),
    _case(
        pattern_id="source_parallel_extractions_to_final_text",
        steps=(
            NewStepDraft(
                name="Extrahera produktdata",
                instructions="Plocka ut produktrelaterade fält ur underlaget.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            NewStepDraft(
                name="Extrahera kunddata",
                instructions="Plocka ut kundrelaterade fält ur samma underlag.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
            ),
            NewStepDraft(
                name="Skriv sammanfattning",
                instructions="Sammanfatta produkten och kundprofilen.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ),
        expected_output_modes=("pass_through", "pass_through", "pass_through"),
    ),
)


def _compile_archetype_case(case: _CreateCompilerArchetypeCase) -> FlowDraftSpecCore:
    return _compile_create_steps(
        flow_name=f"{case.pattern_id} flow",
        flow_description=f"Create compiler fixture for {case.pattern_id}.",
        form_fields=list(case.form_fields),
        steps=list(case.steps),
    )


def test_every_positive_pattern_has_create_compiler_fixture() -> None:
    positive_registry_ids = {
        pattern.id
        for pattern in PATTERN_REGISTRY.values()
        if pattern.polarity == "positive"
    }
    covered_ids = {case.pattern_id for case in _CREATE_COMPILER_ARCHETYPE_CASES}
    missing = positive_registry_ids - covered_ids
    assert not missing, (
        "Every positive PATTERN_REGISTRY entry must have a create-compiler "
        f"fixture; missing: {sorted(missing)}"
    )
    unknown = covered_ids - positive_registry_ids
    assert not unknown, (
        "Create-compiler archetype fixtures reference patterns absent from the "
        f"registry: {sorted(unknown)}"
    )


@pytest.mark.parametrize(
    "case",
    _CREATE_COMPILER_ARCHETYPE_CASES,
    ids=[case.pattern_id for case in _CREATE_COMPILER_ARCHETYPE_CASES],
)
def test_positive_pattern_fixture_compiles_through_create_compiler(
    case: _CreateCompilerArchetypeCase,
) -> None:
    compiled = _compile_archetype_case(case)

    assert len(compiled.steps) == len(case.steps)
    assert tuple(step.output_mode.value for step in compiled.steps) == (
        case.expected_output_modes
    )
    if case.expected_mcp_server_refs_by_step is not None:
        assert (
            tuple(tuple(step.assistant_spec.mcp_server_refs) for step in compiled.steps)
            == case.expected_mcp_server_refs_by_step
        )
    if case.expected_mcp_tool_refs_by_step is not None:
        assert (
            tuple(tuple(step.assistant_spec.mcp_tool_refs) for step in compiled.steps)
            == case.expected_mcp_tool_refs_by_step
        )


def test_compile_create_steps_to_spec_generates_runtime_input_contracts_and_form_fields() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Dokumentanalys",
        flow_description="Analyserar dokumentpaket.",
        form_fields=[
            FormFieldSpec(
                name="referensnummer",
                label="Referensnummer",
                type="text",
                required=True,
            ),
            FormFieldSpec(
                name="ansvarig_enhet",
                label="Ansvarig enhet",
                type="select",
                required=True,
                options=["Avdelning A", "Avdelning B"],
            ),
        ],
        steps=[
            NewStepDraft(
                name="Extrahera strukturerad data",
                instructions="Extrahera viktiga datapunkter.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_required=True,
                runtime_max_files=5,
                uses_form_fields=["referensnummer", "ansvarig_enhet"],
                output_fields=[
                    _field(
                        "risker",
                        "array",
                        description="Identifierade risker.",
                        item_fields=[
                            _field("titel", "string", description="Riskens namn."),
                            _field("nivå", "string", description="Risknivå."),
                        ],
                    ),
                    _field(
                        "konsekvenser",
                        "array",
                        description="Identifierade effekter.",
                        item_fields=[
                            _field(
                                "sammanfattning",
                                "string",
                                description="Kort summering.",
                            ),
                        ],
                    ),
                ],
            ),
            NewStepDraft(
                name="Grounded sammanfattning",
                instructions="Skriv en grounded sammanfattning med källhänvisningar.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
                citations_requested=True,
                knowledge_refs=["kb-risk"],
            ),
        ],
    )

    assert compiled.flow_name == "Dokumentanalys"
    assert [step.plan_step_ref for step in compiled.steps] == ["step_a", "step_b"]
    assert compiled.form_fields is not None
    assert compiled.form_fields[0].name == "referensnummer"
    assert compiled.form_fields[1].options == ["Avdelning A", "Avdelning B"]

    first_step = compiled.steps[0]
    assert first_step.input_config is not None
    runtime_input = first_step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 5
    assert runtime_input["input_format"] == "document"
    assert first_step.input_bindings == {
        "question": "{{ step_input.text }}\n\nreferensnummer: {{ flow_input.referensnummer }}\nansvarig_enhet: {{ flow_input.ansvarig_enhet }}"
    }
    assert "Required JSON fields:" in first_step.assistant_spec.instructions
    assert "risker" in first_step.assistant_spec.instructions
    assert "konsekvenser" in first_step.assistant_spec.instructions
    assert (
        "Allowed fields for items of risker: titel, nivå. Do not emit other fields."
    ) in first_step.assistant_spec.instructions
    assert (
        "Allowed fields for items of konsekvenser: sammanfattning. Do not emit "
        "other fields."
    ) in first_step.assistant_spec.instructions
    assert first_step.output_contract is not None
    assert first_step.output_contract["properties"]["risker"]["type"] == "array"
    assert (
        first_step.output_contract["properties"]["risker"]["items"]["properties"][
            "titel"
        ]["type"]
        == "string"
    )

    second_step = compiled.steps[1]
    assert second_step.input_bindings is None
    assert second_step.input_contract == first_step.output_contract
    assert second_step.output_config == {"citation_mode": "inline_inref_sidecar"}

    validation = validate_spec(compiled)
    assert validation.valid
    assert not any(
        warning.code == "contract_instruction_mismatch"
        for warning in validation.warnings
    )


def test_compile_create_steps_to_spec_uses_previous_fields_to_generate_field_level_bindings() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Dokumentanalys",
        form_fields=[
            FormFieldSpec(
                name="referensnummer",
                label="Referensnummer",
                type="text",
                required=True,
            )
        ],
        steps=[
            NewStepDraft(
                name="Extrahera risker",
                instructions="Extrahera risker och rekommendationer.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_required=True,
                output_fields=[
                    _field(
                        "sammanfattning", "string", description="Kort sammanfattning."
                    ),
                    _field(
                        "risker",
                        "array",
                        description="Identifierade risker.",
                        item_fields=[
                            _field("rubrik", "string", description="Riskrubrik.")
                        ],
                    ),
                ],
            ),
            NewStepDraft(
                name="Skriv slutrapport",
                instructions="Skriv slutrapport med specifika datapunkter.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
                uses_form_fields=["referensnummer"],
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "sammanfattning",
                        "label": "Sammanfattning",
                    },
                    {
                        "from_step": 1,
                        "field_path": "risker.0.rubrik",
                        "label": "Första riskrubrik",
                    },
                ],
            ),
        ],
    )

    second_step = compiled.steps[1]
    assert second_step.input_bindings is not None
    assert second_step.input_bindings["question"] == (
        "Sammanfattning: {{ step_a.output.structured.sammanfattning }}\n\n"
        "Första riskrubrik: {{ step_a.output.structured.risker.0.rubrik }}\n\n"
        "referensnummer: {{ flow_input.referensnummer }}"
    )


def test_compile_create_steps_to_spec_keeps_previous_json_when_field_ref_is_non_adjacent() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Protokoll",
        steps=[
            NewStepDraft(
                name="Strukturera transkription",
                instructions="Strukturera transkriptionen.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field(
                        "transcription_text",
                        "string",
                        description="Full transkription.",
                    )
                ],
            ),
            NewStepDraft(
                name="Identifiera metadata",
                instructions="Identifiera metadata.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[
                    _field("meeting_title", "string", description="Titel."),
                ],
            ),
            NewStepDraft(
                name="Skapa protokoll",
                instructions="Skapa protokoll från metadata och transkription.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "transcription_text",
                        "label": "Transkription",
                    }
                ],
            ),
        ],
    )

    third_step = compiled.steps[2]
    assert third_step.input_bindings is not None
    assert third_step.input_bindings["question"] == (
        "{{ step_b.output.structured }}\n\n"
        "Transkription: {{ step_a.output.structured.transcription_text }}"
    )


def test_compile_create_steps_to_spec_keeps_previous_json_when_output_ref_is_non_adjacent() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Protokoll",
        steps=[
            NewStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera ljud.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_required=True,
            ),
            NewStepDraft(
                name="Identifiera metadata",
                instructions="Identifiera metadata.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field("meeting_title", "string", description="Titel."),
                ],
            ),
            NewStepDraft(
                name="Skapa protokoll",
                instructions="Skapa protokoll från metadata och källtext.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_outputs=[
                    {
                        "from_step": 1,
                        "label": "Source material",
                    }
                ],
            ),
        ],
    )

    third_step = compiled.steps[2]
    assert third_step.input_bindings is not None
    assert third_step.input_bindings["question"] == (
        "Titel.: {{ step_b.output.structured.meeting_title }}\n\n"
        "Source material: {{ step_a.output.text }}"
    )


def test_compile_create_steps_to_spec_all_previous_owns_source_over_previous_field_refs() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Samlad analys",
        steps=[
            NewStepDraft(
                name="Extrahera fakta",
                instructions="Extrahera fakta.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field(
                        "sammanfattning", "string", description="Kort sammanfattning."
                    )
                ],
            ),
            NewStepDraft(
                name="Bedöm fakta",
                instructions="Bedöm fakta.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
            NewStepDraft(
                name="Jämför allt",
                instructions="Jämför allt tidigare arbete.",
                input_source="all_previous_steps",
                input_type="text",
                output_type="text",
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "sammanfattning",
                        "label": "Sammanfattning",
                    }
                ],
            ),
        ],
    )

    validation = validate_spec(compiled)

    third_step = compiled.steps[2]
    assert third_step.input_bindings is None
    assert "Beakta särskilt följande strukturerade fält" in (
        third_step.assistant_spec.instructions
    )
    assert "- Sammanfattning (steg 1: sammanfattning)" in (
        third_step.assistant_spec.instructions
    )
    assert validation.valid


def test_compile_create_steps_to_spec_derives_transcribe_only_for_audio_upload() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Transkribera ljud",
        steps=[
            NewStepDraft(
                name="Transkribera",
                instructions="Transkribera ljudfilen ordagrant.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                model_ref="model.gpt-5-4-nano",
                runtime_required=True,
            )
        ],
    )

    step = compiled.steps[0]
    assert step.output_mode.value == "transcribe_only"
    assert step.assistant_spec.model_ref is None
    assert step.input_bindings == {"question": "{{ step_input.text }}"}
    assert step.input_config is not None
    assert step.input_config["runtime_input"]["input_format"] == "audio"


def test_compile_create_steps_to_spec_sets_review_policy_from_review_mode() -> None:
    compiled = _compile_create_steps(
        flow_name="Granska transkribering",
        steps=[
            NewStepDraft(
                name="Transkribera",
                instructions="Transkribera ljudfilen.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_required=True,
                review_mode="view",
            )
        ],
    )

    assert compiled.steps[0].review_policy is not None
    assert compiled.steps[0].review_policy.mode is FlowStepReviewMode.VIEW


def test_outline_flow_schema_exposes_review_mode_on_steps() -> None:
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME, resource_catalog=_empty_catalog()
    )
    parameters = cast(dict[str, object], schema["function"])["parameters"]
    properties = cast(dict[str, object], parameters)["properties"]
    steps = cast(dict[str, object], cast(dict[str, object], properties)["steps"])
    items = cast(dict[str, object], steps["items"])
    step_properties = cast(dict[str, object], items["properties"])
    review_mode = cast(dict[str, object], step_properties["review_mode"])

    assert review_mode["enum"] == ["view", "edit", None]


def test_parse_create_flow_intent_arguments_accepts_review_mode() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Granska text",
            "plan_rationale": "Användaren ska granska resultatet innan nästa steg.",
            "steps": [
                {
                    "name": "Bearbeta text",
                    "instructions": "Bearbeta texten.",
                    "review_mode": "edit",
                }
            ],
        }
    )

    assert outline.steps[0].review_mode is FlowStepReviewMode.EDIT


def test_parse_create_flow_intent_arguments_strips_input_field_type_before_validation() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Fältflöde",
            "plan_rationale": "Behöver ett runtime-fält.",
            "input_fields": [
                {
                    "variable_name": "case_id",
                    "label": "Case ID",
                    "field_type": " text ",
                    "required": True,
                }
            ],
            "steps": [{"name": "Skriv", "instructions": "Skriv med fältet."}],
        }
    )

    assert outline.input_fields[0].field_type == "text"


def test_parse_create_flow_intent_arguments_rejects_flow_layer_field_type_coercion() -> (
    None
):
    with pytest.raises(ProposalIntentArgumentError, match="field_type"):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Fältflöde",
                "plan_rationale": "AI Builder ska vara strikt här.",
                "input_fields": [
                    {
                        "variable_name": "message",
                        "label": "Message",
                        "field_type": "textarea",
                        "required": True,
                    }
                ],
                "steps": [{"name": "Skriv", "instructions": "Skriv med fältet."}],
            }
        )


def test_parse_create_flow_intent_arguments_rejects_invalid_review_mode() -> None:
    with pytest.raises(ProposalIntentArgumentError, match="review_mode"):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Felaktig granskning",
                "plan_rationale": "Ogiltigt granskningsläge ska stoppas.",
                "steps": [
                    {
                        "name": "Bearbeta text",
                        "instructions": "Bearbeta texten.",
                        "review_mode": "approve",
                    }
                ],
            }
        )


def test_parse_create_flow_intent_arguments_preserves_declared_previous_refs() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Deklarerat dataflöde",
            "plan_rationale": "Återanvänd tydliga tidigare resultat.",
            "steps": [
                {
                    "name": "Extrahera ärende",
                    "instructions": "Extrahera ärende-id.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Ärende-id.",
                        }
                    ],
                },
                {
                    "name": "Skriv utkast",
                    "instructions": "Skriv ett första utkast.",
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten från ärende-id och källtext.",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "case_id",
                            "label": "Ärende-id",
                        }
                    ],
                    "uses_previous_outputs": [{"from_step": 2, "label": "Utkast"}],
                },
            ],
        }
    )

    final_step = outline.steps[2]
    assert [
        (ref.from_step, ref.field_path, ref.label)
        for ref in final_step.uses_previous_fields
    ] == [(1, "case_id", "Ärende-id")]
    assert [(ref.from_step, ref.label) for ref in final_step.uses_previous_outputs] == [
        (2, "Utkast")
    ]


def test_compile_create_intent_threads_declared_previous_refs() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Deklarerat dataflöde",
            "plan_rationale": "Återanvänd tydliga tidigare resultat.",
            "steps": [
                {
                    "name": "Extrahera ärende",
                    "instructions": "Extrahera ärende-id.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Ärende-id.",
                        }
                    ],
                },
                {
                    "name": "Skriv utkast",
                    "instructions": "Skriv ett första utkast.",
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten från ärende-id och källtext.",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "case_id",
                            "label": "Ärende-id",
                        }
                    ],
                    "uses_previous_outputs": [{"from_step": 2, "label": "Utkast"}],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(outline)
    question = compiled.steps[2].input_bindings["question"]

    assert "Ärende-id: {{ step_a.output.structured.case_id }}" in question
    assert "Utkast: {{ step_b.output.text }}" in question


def test_compile_create_intent_remaps_declared_refs_across_backend_prefix() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Ljud till rapport",
            "plan_rationale": "Transkribera ljud och skriv rapport.",
            "steps": [
                {
                    "name": "Extrahera ärende",
                    "instructions": "Extrahera ärende-id från transkriptionen.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Ärende-id.",
                        }
                    ],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten från ärende-id.",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "case_id",
                            "label": "Ärende-id",
                        }
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.PDF,
            ui_language="sv",
        ),
    )
    body_step = compiled.steps[2]

    assert compiled.steps[0].output_type == OutputType.TEXT
    assert compiled.steps[1].output_type == OutputType.JSON
    assert body_step.input_bindings is not None
    assert (
        "Ärende-id: {{ step_b.output.structured.case_id }}"
        in body_step.input_bindings["question"]
    )
    assert (
        "step_a.output.structured.case_id" not in body_step.input_bindings["question"]
    )


def test_compile_create_intent_drops_invalid_declared_previous_field_refs() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Tolerera felaktiga deklarerade refs",
            "plan_rationale": "Felaktiga modellrefs ska inte krascha skapandet.",
            "steps": [
                {
                    "name": "Extrahera ärende",
                    "instructions": "Extrahera ärende-id.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Ärende-id.",
                        }
                    ],
                },
                {
                    "name": "Skriv utkast",
                    "instructions": "Skriv ett första utkast.",
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten från giltigt underlag.",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "missing",
                            "label": "Saknat fält",
                        },
                        {
                            "from_step": 2,
                            "field_path": "case_id",
                            "label": "Textsteg kan inte ha strukturfält",
                        },
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(outline)
    question = (compiled.steps[2].input_bindings or {}).get("question", "")

    assert "Saknat fält" not in question
    assert "Textsteg kan inte ha strukturfält" not in question


def test_compile_create_intent_clears_declared_refs_after_leading_fold() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Foldad referens",
            "plan_rationale": "Undvik felkoppling efter fold.",
            "steps": [
                {
                    "name": "Ta emot material",
                    "instructions": "Använd användarens text som material.",
                    "output_type": "text",
                },
                {
                    "name": "Extrahera första ärende",
                    "instructions": "Extrahera ärende-id från materialet.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Första ärende-id.",
                        }
                    ],
                },
                {
                    "name": "Extrahera kontrollärende",
                    "instructions": "Extrahera ett kontroll-id från materialet.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Kontrollärende-id.",
                        }
                    ],
                },
                {
                    "name": "Skriv sammanställning",
                    "instructions": "Skriv sammanställningen från rätt ärende-id.",
                    "uses_previous_fields": [
                        {
                            "from_step": 2,
                            "field_path": "case_id",
                            "label": "Rätt ärende-id",
                        }
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(outline)
    question = (compiled.steps[2].input_bindings or {}).get("question", "")

    assert [step.name for step in compiled.steps] == [
        "Extrahera första ärende",
        "Extrahera kontrollärende",
        "Skriv sammanställning",
    ]
    assert "Rätt ärende-id" not in question
    assert "Första ärende-id.: {{ step_a.output.structured.case_id }}" in question
    assert "Kontrollärende-id.: {{ step_b.output.structured.case_id }}" in question


def test_compile_outline_flow_sets_review_policy_from_review_mode() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Granska text",
            "plan_rationale": "Användaren ska kunna ändra resultatet.",
            "steps": [
                {
                    "name": "Bearbeta text",
                    "instructions": "Bearbeta texten.",
                    "review_mode": "edit",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(outline)

    assert compiled.steps[0].review_policy is not None
    assert compiled.steps[0].review_policy.mode is FlowStepReviewMode.EDIT


def test_compile_outline_parity_plain_text_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Text summary",
            "plan_rationale": "Summarize supplied text.",
            "steps": [
                {
                    "name": "Summarize text",
                    "instructions": "Write a concise summary.",
                }
            ],
        }
    )

    spec = compile_create_intent_to_spec(outline)

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Text summary",
        steps=[
            _create_step_snapshot(
                name="Summarize text",
                instructions="Write a concise summary.",
                input_source="flow_input",
                input_type="text",
                output_type="text",
            )
        ],
    )


def test_compile_outline_parity_audio_review_mode_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Meeting minutes",
            "plan_rationale": "Transcribe meeting audio and produce a PDF report.",
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "instructions": "Transkribera ljud till text.",
                    "review_mode": "edit",
                },
                {
                    "name": "Skapa rapport",
                    "instructions": "Skriv en rapport från transkriptionen.",
                    "output_type": "pdf",
                },
            ],
        }
    )
    state = _committed_architecture_state(
        input_type="audio",
        output_type="pdf",
        output_mode="pass_through",
        chosen_patterns=["audio_to_artifact_report"],
        required_capabilities=["input_audio", "output_mode_pass_through"],
    )

    spec = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Meeting minutes",
        steps=[
            _create_step_snapshot(
                name="Transcribe audio",
                instructions=(
                    "Transcribe the uploaded audio into text before downstream "
                    "analysis or artifact generation."
                ),
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_required=True,
                review_mode="edit",
            ),
            _create_step_snapshot(
                name="Skapa rapport",
                instructions="Skriv en rapport från transkriptionen.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
            ),
            _create_step_snapshot(
                name="Create PDF",
                instructions=(
                    "Create the final output from the previous structured work. "
                    "Preserve the user's requested scope, ordering, and constraints."
                ),
                input_source="previous_step",
                input_type="text",
                output_type="pdf",
                document_delivery_mode="generated",
            ),
        ],
    )


def test_compile_outline_parity_docx_template_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from source material.",
            "steps": [
                {
                    "name": "Prepare report content",
                    "instructions": "Prepare content for the template.",
                }
            ],
        }
    )
    state = _committed_architecture_state(
        input_type="document",
        output_type="docx",
        output_mode="template_fill",
        chosen_patterns=["document_to_docx_template"],
        required_capabilities=["input_document", "output_mode_template_fill"],
    )

    spec = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Template report",
        steps=[
            _create_step_snapshot(
                name="Extract template variables",
                instructions=(
                    "Extract the stable fields and source facts needed before "
                    "filling the DOCX template."
                ),
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_required=True,
                output_fields=_source_facts_fields_snapshot(),
            ),
            _create_step_snapshot(
                name="Prepare report content",
                instructions="Prepare content for the template.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
            _create_step_snapshot(
                name="Fill DOCX template",
                instructions=(
                    "Fill the DOCX template from the prepared content. Preserve "
                    "the user's requested scope and terminology."
                ),
                input_source="previous_step",
                input_type="text",
                output_type="docx",
                document_delivery_mode="template_fill",
            ),
        ],
    )


def test_compile_outline_parity_json_intermediate_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Customer report",
            "plan_rationale": "Extract structured facts and write a report.",
            "steps": [
                {
                    "name": "Extract facts",
                    "instructions": "Extract customer facts.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "customer_name",
                            "field_type": "string",
                            "description": "Customer name.",
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write a short customer report.",
                    "output_type": "text",
                },
            ],
        }
    )
    state = _committed_architecture_state(
        input_type="text",
        output_type="text",
        output_mode="pass_through",
        chosen_patterns=[],
        required_capabilities=["input_text", "output_mode_pass_through"],
    )

    spec = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Customer report",
        steps=[
            _create_step_snapshot(
                name="Extract facts",
                instructions="Extract customer facts.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[
                    _structured_field_snapshot(
                        "customer_name",
                        "string",
                        "Customer name.",
                    )
                ],
            ),
            _create_step_snapshot(
                name="Write report",
                instructions="Write a short customer report.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
        ],
    )


def test_compile_outline_parity_form_field_chain_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audience report",
            "plan_rationale": "Use requested form fields.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": True,
                },
                {
                    "variable_name": "tone",
                    "label": "Tone",
                    "field_type": "text",
                    "required": False,
                },
            ],
            "steps": [
                {
                    "name": "Draft section",
                    "instructions": "Draft for audience.",
                    "uses_form_fields": ["audience"],
                },
                {
                    "name": "Finalize",
                    "instructions": "Finalize the text.",
                    "uses_form_fields": ["tone"],
                },
            ],
        }
    )
    state = _committed_architecture_state(
        input_type="text",
        output_type="text",
        output_mode="pass_through",
        chosen_patterns=["sectioned_form_intake"],
        required_capabilities=["input_text", "output_mode_pass_through"],
    )

    spec = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Audience report",
        form_fields=[
            _form_field_snapshot("audience", "Audience", "text", required=True),
            _form_field_snapshot("tone", "Tone", "text", required=False),
        ],
        steps=[
            _create_step_snapshot(
                name="Draft section",
                instructions="Draft for audience.",
                input_source="flow_input",
                input_type="text",
                output_type="text",
                uses_form_fields=["audience"],
            ),
            _create_step_snapshot(
                name="Finalize",
                instructions="Finalize the text.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_form_fields=["tone"],
            ),
        ],
    )


def test_compile_outline_parity_single_step_field_attachment_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Single field report",
            "plan_rationale": "One step uses all fields implicitly.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": True,
                },
                {
                    "variable_name": "deadline",
                    "label": "Deadline",
                    "field_type": "date",
                    "required": False,
                },
            ],
            "steps": [
                {
                    "name": "Write report",
                    "instructions": "Write report using the provided fields.",
                }
            ],
        }
    )

    spec = compile_create_intent_to_spec(outline)

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Single field report",
        form_fields=[
            _form_field_snapshot("audience", "Audience", "text", required=True),
            _form_field_snapshot("deadline", "Deadline", "date", required=False),
        ],
        steps=[
            _create_step_snapshot(
                name="Write report",
                instructions="Write report using the provided fields.",
                input_source="flow_input",
                input_type="text",
                output_type="text",
                uses_form_fields=["audience", "deadline"],
            )
        ],
    )


def test_compile_outline_parity_aggregate_context_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Aggregate documents",
            "plan_rationale": "Aggregate multiple documents into a PDF.",
            "steps": [
                {
                    "name": "Extract themes",
                    "instructions": "Extract themes from the material.",
                },
                {
                    "name": "Synthesize",
                    "instructions": "Synthesize all themes.",
                    "output_type": "text",
                },
            ],
        }
    )
    state = _committed_architecture_state(
        input_type="document",
        output_type="pdf",
        output_mode="pass_through",
        chosen_patterns=["multi_step_quality_chain"],
        required_capabilities=["input_document", "output_mode_pass_through"],
        aggregation_intent="aggregate",
    )

    spec = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Aggregate documents",
        steps=[
            _create_step_snapshot(
                name="Extract structured foundation",
                instructions=(
                    "Extract source facts, key points, and uncertainties needed "
                    "for the downstream analysis."
                ),
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_required=True,
                output_fields=_source_facts_fields_snapshot(),
            ),
            _create_step_snapshot(
                name="Extract themes",
                instructions="Extract themes from the material.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
            _create_step_snapshot(
                name="Synthesize",
                instructions="Synthesize all themes.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
            ),
            _create_step_snapshot(
                name="Review and finalize",
                instructions=(
                    "Review the analysis for missing information, uncertainty, "
                    "and quality issues, then write the revised final version "
                    "for the final output."
                ),
                input_source="all_previous_steps",
                input_type="text",
                output_type="text",
            ),
            _create_step_snapshot(
                name="Create PDF",
                instructions=(
                    "Create the final output from the previous structured work. "
                    "Preserve the user's requested scope, ordering, and constraints."
                ),
                input_source="all_previous_steps",
                input_type="text",
                output_type="pdf",
                document_delivery_mode="generated",
            ),
        ],
        document_body_writer_step_indexes=(3,),
    )


def test_compile_outline_parity_leading_zero_contract_fold_snapshot() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Fold text hop",
            "plan_rationale": "Avoid zero-contract first step.",
            "steps": [
                {
                    "name": "Receive text",
                    "instructions": "Read the user text.",
                },
                {
                    "name": "Create PDF",
                    "instructions": "Create a PDF report.",
                    "output_type": "pdf",
                },
            ],
        }
    )

    spec = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(final_output_type=OutputType.PDF),
    )

    assert spec.model_dump(mode="json") == _create_spec_snapshot(
        flow_name="Fold text hop",
        steps=[
            _create_step_snapshot(
                name="Create PDF",
                instructions="Read the user text.\n\nCreate a PDF report.",
                input_source="flow_input",
                input_type="text",
                output_type="text",
            ),
            _create_step_snapshot(
                name="Create PDF",
                instructions=(
                    "Create the final output from the previous structured work. "
                    "Preserve the user's requested scope, ordering, and constraints."
                ),
                input_source="previous_step",
                input_type="text",
                output_type="pdf",
                document_delivery_mode="generated",
            ),
        ],
    )


def test_compile_create_steps_to_spec_derives_template_fill_for_docx_templates() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Mallstyrd rapport",
        steps=[
            NewStepDraft(
                name="Generera rapport",
                instructions="Fyll DOCX-mallen med det strukturerade innehållet.",
                input_source="flow_input",
                input_type="text",
                output_type="docx",
                document_delivery_mode="template_fill",
            )
        ],
    )

    assert compiled.steps[0].output_mode.value == "template_fill"


def test_normalize_create_step_mechanics_strips_template_fill_from_non_docx() -> None:
    steps = [
        NewStepDraft(
            name="PDF-steg",
            instructions="Generera PDF med mall.",
            input_source="flow_input",
            input_type="text",
            output_type="pdf",
            document_delivery_mode="template_fill",
        )
    ]
    normalized = _normalize_create_steps(
        flow_name="Ogiltig mall",
        steps=steps,
    )
    compiled = _compile_create_steps(flow_name="Ogiltig mall", steps=normalized)
    validation = validate_spec(compiled)

    assert normalized[0].document_delivery_mode == "generated"
    assert compiled.steps[0].output_mode == OutputMode.PASS_THROUGH
    assert validation.valid


def test_normalize_create_step_mechanics_strips_template_fill_from_text_output() -> (
    None
):
    steps = [
        NewStepDraft(
            name="Textsteg",
            instructions="Skriv en text.",
            input_source="flow_input",
            input_type="text",
            output_type="text",
            document_delivery_mode="template_fill",
        )
    ]
    normalized = _normalize_create_steps(
        flow_name="Ogiltig textmall",
        steps=steps,
    )
    compiled = _compile_create_steps(flow_name="Ogiltig textmall", steps=normalized)
    validation = validate_spec(compiled)

    assert normalized[0].document_delivery_mode == "not_applicable"
    assert compiled.steps[0].output_mode == OutputMode.PASS_THROUGH
    assert validation.valid


def test_compile_create_steps_to_spec_empty_steps_surfaces_canonical_empty_steps_error() -> (
    None
):
    compiled = _compile_create_steps(
        flow_name="Tomt flöde",
        steps=[],
    )
    validation = validate_spec(compiled)

    assert compiled.steps == []
    assert not validation.valid
    assert [error.code for error in validation.errors] == ["empty_steps"]


def test_normalize_create_step_mechanics_rejects_non_json_previous_field_source() -> (
    None
):
    steps = [
        NewStepDraft(
            name="Skriv text",
            instructions="Skriv text.",
            input_source="flow_input",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Sammanfatta",
            instructions="Sammanfatta.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
            uses_previous_fields=[{"from_step": 1, "field_path": "titel"}],
        ),
    ]

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _normalize_create_steps(
            flow_name="Ogiltig fältkälla",
            steps=steps,
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "previous_field_source_not_json"


def test_compile_create_steps_to_spec_derives_file_flow_input_runtime_config() -> None:
    steps = [
        NewStepDraft(
            name="Analysera dokument",
            instructions="Analysera dokumentet.",
            input_source="flow_input",
            input_type="document",
            output_type="json",
            output_fields=[_field("sammanfattning", "string")],
        )
    ]
    normalized = _normalize_create_steps(flow_name="Ogiltig filindata", steps=steps)
    compiled = _compile_create_steps(flow_name="Ogiltig filindata", steps=normalized)
    validation = validate_spec(compiled)
    runtime_input = compiled.steps[0].input_config["runtime_input"]

    assert runtime_input["enabled"] is True
    assert runtime_input["input_format"] == "document"
    assert runtime_input["required"] is False
    assert validation.valid


def test_structured_field_depth_above_three_is_rejected() -> None:
    with pytest.raises(ValueError, match="nesting depth"):
        NewStepDraft(
            name="Extrahera",
            instructions="Extrahera struktur.",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[
                _field(
                    "nivå_ett",
                    "object",
                    fields=[
                        _field(
                            "nivå_två",
                            "object",
                            fields=[
                                _field(
                                    "nivå_tre",
                                    "object",
                                    fields=[
                                        _field("nivå_fyra", "string"),
                                    ],
                                ),
                            ],
                        )
                    ],
                )
            ],
        )


def test_outline_flow_schema_exposes_declared_previous_refs_and_hides_mechanics() -> (
    None
):
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME, resource_catalog=_empty_catalog()
    )
    assert schema["function"]["name"] == PROPOSE_FLOW_TOOL_NAME
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]
    leaked_backend_keys = sorted(
        set(step_props) & _CREATE_INTENT_STEP_BACKEND_OWNED_KEYS
    )

    assert leaked_backend_keys == []
    assert "uses_form_fields" in step_props
    assert "uses_previous_fields" in step_props
    assert "uses_previous_outputs" in step_props


def test_outline_flow_schema_uses_flow_derived_enums() -> None:
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME, resource_catalog=_empty_catalog()
    )
    parameters = schema["function"]["parameters"]
    properties = parameters["properties"]
    step_props = properties["steps"]["items"]["properties"]

    assert parameters["required"] == ["flow_name", "plan_rationale", "steps"]
    assert "runtime_input" not in properties
    assert "final_output_type" not in properties
    assert properties["steps"]["maxItems"] == MAX_PROPOSAL_STEPS
    assert step_props["output_type"]["enum"] == [
        *builder_output_type_values(),
        None,
    ]


def test_outline_flow_schema_keeps_mcp_refs_free_form_for_small_catalog() -> None:
    catalog = _catalog_with_mcps(
        [
            {
                "ref": "server-1",
                "name": "Case system",
                "tools": [{"ref": "tool-1", "name": "lookup_case"}],
            }
        ]
    )
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        resource_catalog=catalog,
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_selected_mcp_server_is_attached_to_explicit_outline_step_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger=PROPOSAL_INTENT_LOGGER,
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Separera MCP-hämtning från slutlig strukturering.",
            "steps": [
                {
                    "name": "Hämta aktuell tid med Time MCP",
                    "instructions": "Använd Time MCP för att hämta aktuell tid.",
                    "output_type": "json",
                },
                {
                    "name": "Skapa strukturerat svar",
                    "instructions": "Formatera resultatet som JSON.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_intent_steps(
        outline,
        selected_server_refs={"mcp_server.time-mcp"},
        catalog=catalog,
    )
    spec = _canonicalize_create_spec(
        compile_create_intent_to_spec(updated),
        catalog=catalog,
    )

    assert spec.steps[0].assistant_spec.mcp_server_refs == ["mcp_server.time-mcp"]
    assert spec.steps[0].assistant_spec.mcp_tool_refs == [
        "mcp_tool.time-mcp-get-current-time"
    ]
    assert spec.steps[1].assistant_spec.mcp_server_refs == []
    assert spec.steps[1].assistant_spec.mcp_tool_refs == []
    record = next(
        (
            record
            for record in caplog.records
            if record.message
            == "ai_builder_selected_mcp_refs_attached_to_semantic_steps"
        ),
        None,
    )
    assert record is not None
    assert record.patched_step_count == 1
    assert record.patched_steps == [
        {
            "step_name": "Hämta aktuell tid med Time MCP",
            "mcp_server_refs": ["mcp_server.time-mcp"],
            "mcp_tool_refs": [],
        }
    ]
    assert record.selected_mcp_server_refs == ["mcp_server.time-mcp"]


def test_selected_mcp_attachment_prefers_explicit_tool_aliases() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [
                    {"id": "current-time", "name": "get_current_time"},
                    {"id": "convert-time", "name": "convert_time"},
                ],
            }
        ],
    )
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Använd bara relevant MCP-verktyg.",
            "steps": [
                {
                    "name": "Hämta tid med Time MCP",
                    "instructions": "Använd get_current_time för angiven tidszon.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_intent_steps(
        outline,
        selected_server_refs={"mcp_server.time-mcp"},
        catalog=catalog,
    )
    spec = _canonicalize_create_spec(
        compile_create_intent_to_spec(updated),
        catalog=catalog,
    )

    assert spec.steps[0].assistant_spec.mcp_server_refs == ["mcp_server.time-mcp"]
    assert spec.steps[0].assistant_spec.mcp_tool_refs == [
        "mcp_tool.time-mcp-get-current-time"
    ]


def test_selected_mcp_attachment_uses_explicit_tool_alias_without_server_name() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [
                    {"id": "current-time", "name": "get_current_time"},
                    {"id": "convert-time", "name": "convert_time"},
                ],
            }
        ],
    )
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Verktygsnamnet räcker när användaren redan valt servern.",
            "steps": [
                {
                    "name": "Hämta aktuell tid",
                    "instructions": "Använd get_current_time för angiven tidszon.",
                    "output_type": "json",
                },
                {
                    "name": "Konvertera tiden",
                    "instructions": "Använd convert_time till Europe/Stockholm.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_intent_steps(
        outline,
        selected_server_refs={"mcp_server.time-mcp"},
        catalog=catalog,
    )
    spec = _canonicalize_create_spec(
        compile_create_intent_to_spec(updated),
        catalog=catalog,
    )

    assert spec.steps[0].assistant_spec.mcp_server_refs == ["mcp_server.time-mcp"]
    assert spec.steps[0].assistant_spec.mcp_tool_refs == [
        "mcp_tool.time-mcp-get-current-time"
    ]
    assert spec.steps[1].assistant_spec.mcp_server_refs == ["mcp_server.time-mcp"]
    assert spec.steps[1].assistant_spec.mcp_tool_refs == [
        "mcp_tool.time-mcp-convert-time"
    ]


def test_selected_mcp_attachment_skips_knowledge_steps() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[_kb_resource("kb-1", "Policy")],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Policy och tid",
            "plan_rationale": "Knowledge och MCP får inte blandas på samma steg.",
            "steps": [
                {
                    "name": "Grounda i policy",
                    "instructions": "Använd get_current_time endast som exempeltext här.",
                    "output_type": "text",
                    "knowledge_refs": ["kb-1"],
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_intent_steps(
        outline,
        selected_server_refs={"time-server"},
        catalog=catalog,
    )

    assert updated.steps[0].knowledge_refs == ["kb-1"]
    assert updated.steps[0].mcp_server_refs == []
    assert updated.steps[0].mcp_tool_refs == []


def test_selected_mcp_attachment_does_not_infer_from_domain_words() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Domänord räcker inte för MCP-koppling.",
            "steps": [
                {
                    "name": "Hämta aktuell tid",
                    "instructions": "Hämta aktuell tid för användarens tidszon.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_intent_steps(
        outline,
        selected_server_refs={"time-server"},
        catalog=catalog,
    )

    assert updated.steps[0].mcp_server_refs == []
    assert updated.steps[0].mcp_tool_refs == []


def test_outline_flow_schema_exposes_model_and_knowledge_refs_for_small_catalog() -> (
    None
):
    catalog = build_ai_builder_resource_catalog(
        available_models=[_model_resource("model-1", "gpt-5.4-nano")],
        available_kbs=[_kb_resource("kb-1", "Risk KB")],
    )
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        resource_catalog=catalog,
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert step_props["model_ref"]["enum"] == ["model.gpt-5-4-nano", None]
    assert step_props["knowledge_refs"]["items"]["enum"] == ["knowledge.risk-kb"]


def test_outline_flow_schema_form_field_enum_matches_builder_values() -> None:
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME, resource_catalog=_empty_catalog()
    )
    parameters = cast(dict[str, object], schema["function"])["parameters"]
    properties = cast(dict[str, object], parameters)["properties"]
    input_fields = cast(dict[str, object], properties["input_fields"])
    input_field_items = cast(dict[str, object], input_fields["items"])
    input_field_properties = cast(dict[str, object], input_field_items["properties"])
    field_type = cast(dict[str, object], input_field_properties["field_type"])

    assert field_type["enum"] == builder_form_field_type_values()


def test_outline_flow_schema_keeps_mcp_refs_free_form_for_malformed_catalog() -> None:
    catalog = _catalog_with_mcps(
        [
            {"ref": "", "tools": [{"ref": "ignored-tool"}]},
            {
                "ref": "server-1",
                "tools": [{"ref": ""}, {"ref": "tool-1", "name": "lookup_case"}],
            },
        ]
    )
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        resource_catalog=catalog,
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_outline_flow_schema_omits_mcp_ref_enums_for_large_catalog() -> None:
    catalog = _catalog_with_mcps(
        [
            {
                "ref": f"server-{index}",
                "tools": [{"ref": f"tool-{index}", "name": "lookup"}],
            }
            for index in range(16)
        ]
    )
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        resource_catalog=catalog,
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_outline_flow_schema_keeps_mcp_refs_free_form_when_tool_catalog_is_large() -> (
    None
):
    catalog = _catalog_with_mcps(
        [
            {
                "ref": "server-1",
                "tools": [
                    {"ref": f"tool-{index}", "name": "lookup"} for index in range(31)
                ],
            }
        ]
    )
    schema = build_create_flow_tool_schema(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        resource_catalog=catalog,
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_parse_outline_flow_allows_server_owned_core_shape_defaults() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Minimal outline",
            "plan_rationale": "Let the backend apply the committed architecture.",
            "steps": [
                {
                    "name": "Do the work",
                    "instructions": "Follow the user's confirmed requirements.",
                }
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)

    assert draft.steps[0].input_type is InputType.TEXT
    assert draft.steps[0].input_config is None


def test_parse_outline_flow_rejects_model_supplied_runtime_input() -> None:
    with pytest.raises(ProposalIntentArgumentError, match="runtime_input"):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Minimal outline",
                "plan_rationale": "Runtime input is server-owned.",
                "runtime_input": {"input_type": "document", "required": True},
                "steps": [
                    {
                        "name": "Do the work",
                        "instructions": "Follow the user's confirmed requirements.",
                    }
                ],
            }
        )


def test_outline_compile_context_rejects_invalid_runtime_input_constraints() -> None:
    with pytest.raises(ValueError, match="runtime_max_files"):
        CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            runtime_max_files=0,
        )

    with pytest.raises(ValueError, match="runtime_input_type"):
        CreateCompileContext(runtime_input_type=InputType.ANY)


def test_parse_outline_flow_ignores_model_supplied_final_output_type() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Minimal outline",
            "plan_rationale": "Let the backend apply the committed architecture.",
            "final_output_type": "docx",
            "steps": [
                {
                    "name": "Do the work",
                    "instructions": "Follow the user's confirmed requirements.",
                }
            ],
        }
    )

    assert not hasattr(outline, "final_output_type")
    default_draft = compile_create_intent_to_spec(outline)
    context_draft = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(final_output_type=OutputType.PDF),
    )

    assert default_draft.steps[-1].output_type == OutputType.TEXT
    assert context_draft.steps[-1].output_type == OutputType.PDF


def test_parse_outline_flow_accepts_create_resource_refs() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Kunskapsflöde",
            "plan_rationale": "Använder rätt modell och kunskapsbas.",
            "steps": [
                {
                    "name": "Analysera policy",
                    "instructions": "Svara med stöd av policyunderlaget.",
                    "model_ref": " model-1 ",
                    "knowledge_refs": [" kb-1 ", "kb-1", ""],
                }
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)

    assert draft.steps[0].assistant_spec.model_ref == "model-1"
    assert draft.steps[0].assistant_spec.knowledge_refs == ["kb-1"]


def test_parse_outline_flow_rejects_knowledge_and_mcp_on_same_step() -> None:
    with pytest.raises(
        ProposalIntentArgumentError, match="knowledge_refs with MCP refs"
    ):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Ogiltigt",
                "plan_rationale": "Blandar två externa resurslägen.",
                "steps": [
                    {
                        "name": "Analysera",
                        "instructions": "Analysera med allt.",
                        "knowledge_refs": ["kb-1"],
                        "mcp_tool_refs": ["tool-1"],
                    }
                ],
            }
        )


def test_parse_outline_flow_errors_are_safe_and_field_level() -> None:
    with pytest.raises(ProposalIntentArgumentError) as exc_info:
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Broken outline",
                "plan_rationale": "Contains a malformed step.",
                "steps": [
                    {
                        "name": "Extract",
                        "instructions": "Secret case note that should not appear in logs.",
                        "unexpected_mechanic": "Secret low-level binding detail.",
                    }
                ],
            }
        )

    message = str(exc_info.value)
    assert "steps.0.unexpected_mechanic" in message
    assert "Secret case note" not in message
    assert "Secret low-level binding detail" not in message
    assert "input_value" not in message


def test_parse_outline_flow_ignores_stale_backend_owned_step_mechanics() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Stale mechanics outline",
            "plan_rationale": "Stale models may emit low-level mechanics.",
            "steps": [
                {
                    "name": "Do the work",
                    "instructions": "Follow the user's confirmed requirements.",
                    "input_strategy": "all_prior_work",
                    "input_source": "all_previous_steps",
                    "input_type": "json",
                    "input_bindings": {"question": "{{ step_a.output.text }}"},
                    "output_contract": {"type": "object"},
                }
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)

    assert draft.steps[0].input_source.value == "flow_input"
    assert draft.steps[0].input_type.value == "text"


def test_parse_outline_flow_rejects_step_local_assumptions_from_diagnostic_payload() -> (
    None
):
    with pytest.raises(ProposalIntentArgumentError) as exc_info:
        parse_create_flow_intent_arguments(
            self_correction_intent_with_step_assumptions_payload()
        )

    message = str(exc_info.value)
    assert "steps.1.assumptions" in message
    assert "extra_forbidden" in message
    assert "Det går att avgöra" not in message


def test_parse_outline_flow_rejects_step_local_input_fields() -> None:
    with pytest.raises(ProposalIntentArgumentError) as exc_info:
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Felplacerade fält",
                "plan_rationale": "Input fields ska vara root-level.",
                "steps": [
                    {
                        "name": "Bearbeta",
                        "instructions": "Bearbeta med extra körningsfält.",
                        "input_fields": [
                            {
                                "variable_name": "case_id",
                                "label": "Case ID",
                                "field_type": "text",
                                "required": True,
                            }
                        ],
                    }
                ],
            }
        )

    message = str(exc_info.value)
    assert "steps.0.input_fields" in message
    assert "Case ID" not in message


def test_parse_outline_flow_ignores_step_only_fields_at_root() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Root noise outline",
            "plan_rationale": "Weak models may place step-only fields at root.",
            "uses_form_fields": ["audience"],
            "citations_requested": True,
            "model_ref": "model-default",
            "knowledge_refs": ["kb-ref"],
            "mcp_server_refs": ["server-ref"],
            "mcp_tool_refs": ["tool-ref"],
            "output_type": "json",
            "review_mode": "edit",
            "steps": [
                {
                    "name": "Do the work",
                    "instructions": "Follow the user's confirmed requirements.",
                }
            ],
        }
    )

    assert outline.flow_name == "Root noise outline"
    assert len(outline.steps) == 1


def test_parse_outline_flow_rejects_orphan_field_specs_in_steps() -> None:
    with pytest.raises(ProposalIntentArgumentError) as exc_info:
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Orphan field outline",
                "plan_rationale": "Field specs in steps[] are malformed steps.",
                "steps": [
                    {
                        "name": "Extract facts",
                        "instructions": "Extract structured facts.",
                        "output_type": "json",
                        "output_fields": [
                            {
                                "name": "facts",
                                "field_type": "array",
                                "description": "Extracted facts.",
                                "item_fields": [
                                    {
                                        "name": "fact",
                                        "field_type": "string",
                                        "description": "Fact text.",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "name": "extraction_notes",
                        "field_type": "array",
                        "description": "Notes about extraction quality.",
                        "item_fields": [
                            {
                                "name": "note",
                                "field_type": "string",
                                "description": "A quality note.",
                            }
                        ],
                    },
                ],
            }
        )

    message = str(exc_info.value)
    assert "steps.1.instructions" in message
    assert "missing" in message
    assert "Notes about extraction quality" not in message


def test_outline_flow_truncates_over_deep_structured_fields_before_draft_validation() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Nested outline",
            "plan_rationale": "Weak models may over-nest JSON fields.",
            "steps": [
                {
                    "name": "Extract",
                    "instructions": "Extract nested facts.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "level_one",
                            "field_type": "object",
                            "fields": [
                                {
                                    "name": "level_two",
                                    "field_type": "object",
                                    "fields": [
                                        {
                                            "name": "level_three",
                                            "field_type": "object",
                                            "fields": [
                                                {
                                                    "name": "level_four",
                                                    "field_type": "string",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)

    output_contract = draft.steps[0].output_contract
    assert output_contract is not None
    level_one = output_contract["properties"]["level_one"]
    level_two = level_one["properties"]["level_two"]
    level_three = level_two["properties"]["level_three"]
    assert level_three["type"] == "string"
    assert "properties" not in level_three


def test_parse_outline_flow_allows_advanced_step_counts_above_old_limit() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Advanced workflow",
            "plan_rationale": "The requested process has many meaningful phases.",
            "steps": [
                {
                    "name": f"Phase {index}",
                    "instructions": f"Perform semantic phase {index}.",
                }
                for index in range(1, 21)
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    assert len(outline.steps) == 20
    assert len(draft.steps) == 20
    assert [step.name for step in compiled.steps] == [
        f"Phase {index}" for index in range(1, 21)
    ]
    assert validation.valid


def test_parse_outline_flow_allows_advanced_step_counts_above_old_soft_cap() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Very advanced workflow",
            "plan_rationale": "Some valid enterprise processes need many phases.",
            "steps": [
                {
                    "name": f"Phase {index}",
                    "instructions": f"Perform semantic phase {index}.",
                }
                for index in range(1, 81)
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)

    assert len(outline.steps) == 80
    assert len(draft.steps) == 80


def test_parse_outline_flow_normalizes_malformed_array_item_fields() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured extraction",
            "plan_rationale": "Weak models may emit one field object instead of a list.",
            "steps": [
                {
                    "name": "Extract rows",
                    "instructions": "Extract row summaries.",
                    "output_fields": [
                        {
                            "name": "rows",
                            "field_type": "array",
                            "description": "Extracted rows.",
                            "item_fields": {
                                "name": "summary",
                                "type": "text",
                                "description": "Row summary.",
                            },
                        }
                    ],
                }
            ],
        }
    )

    field = (
        outline.steps[0].output_fields[0] if outline.steps[0].output_fields else None
    )

    assert field is not None
    assert field.field_type == "array"
    assert field.item_fields is not None
    assert [item.name for item in field.item_fields] == ["summary"]
    assert field.item_fields[0].field_type == "string"


def test_parse_outline_flow_normalizes_json_schema_like_output_fields() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Schema-like extraction",
            "plan_rationale": "Weak models often emit JSON Schema-like properties.",
            "steps": [
                {
                    "name": "Extract fields",
                    "instructions": "Extract structured fields.",
                    "output_fields": {
                        "properties": {
                            "case_id": {
                                "type": "string",
                                "description": "Case identifier.",
                            },
                            "scores": {
                                "type": "array",
                                "description": "Score rows.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "value": {"type": "number"},
                                    },
                                },
                            },
                        }
                    },
                }
            ],
        }
    )

    fields = outline.steps[0].output_fields

    assert fields is not None
    assert [field.name for field in fields] == ["case_id", "scores"]
    assert fields[0].field_type == "string"
    assert fields[1].field_type == "array"
    assert fields[1].item_fields is not None
    assert [field.name for field in fields[1].item_fields] == ["label", "value"]


def test_compile_outline_flow_derives_runtime_input_fields_and_final_docx() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case report",
            "flow_description": "Analyzes uploaded source material.",
            "plan_rationale": "Extract structure first, then create the report.",
            "input_fields": [
                {
                    "variable_name": "case_id",
                    "label": "Case ID",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Extract facts",
                    "instructions": "Extract the key facts and open questions.",
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "array",
                            "description": "Key facts.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Fact summary.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Quality check",
                    "instructions": "Check for missing information and uncertainty.",
                    "output_type": "text",
                    "uses_form_fields": ["case_id"],
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.DOCX,
            runtime_required=True,
            runtime_max_files=5,
        ),
    )
    compiled = draft

    assert [step.name for step in draft.steps] == [
        "Extract facts",
        "Quality check",
        "Create DOCX",
    ]
    assert draft.steps[0].input_source.value == "flow_input"
    assert draft.steps[0].input_type.value == "document"
    assert compiled.steps[0].input_config is not None
    runtime_input = compiled.steps[0].input_config["runtime_input"]
    assert runtime_input["input_format"] == "document"
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 5
    assert draft.steps[0].output_type.value == "json"
    assert draft.steps[1].input_source.value == "previous_step"
    assert draft.steps[1].input_type.value == "text"
    assert draft.steps[2].output_type.value == "docx"
    assert draft.steps[2].output_mode == OutputMode.PASS_THROUGH

    assert compiled.form_fields is not None
    assert compiled.form_fields[0].name == "case_id"
    assert compiled.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}\n\ncase_id: {{ flow_input.case_id }}"
    }
    assert compiled.steps[2].input_bindings is None
    validation = validate_spec(compiled)
    assert validation.valid
    assert_create_spec_prepares_through_authoring_command(compiled)


def test_compile_outline_flow_drops_server_derived_hints_when_planner_did_not_reference_them() -> (
    None
):
    """Server-derived runtime field hints are suggestions for fields the
    user mentioned in free text. They are only added to `form_fields`
    when the planner actually references them via `uses_form_fields`
    on at least one step. Hints the planner ignored are dropped so they
    do not surface as orphan UI controls or trigger the semantic critic
    spuriously — the planner asked for a flow with no input fields and
    that is what they get.
    """
    from eneo.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Review report",
            "plan_rationale": "Review source material and produce a report.",
            "steps": [
                {
                    "name": "Review",
                    "instructions": "Review the source material.",
                }
            ],
        }
    )
    context = CreateCompileContext(
        runtime_input_field_hints=(
            RuntimeInputFieldHint(variable_name="audience", label="Audience"),
            RuntimeInputFieldHint(variable_name="detail_level", label="Detail level"),
        ),
    )

    draft = compile_create_intent_to_spec(outline, context=context)
    compiled = draft
    validation = validate_spec(compiled)

    assert [field.name for field in (draft.form_fields or [])] == []
    assert compiled.form_fields is None or compiled.form_fields == []
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_keeps_hint_when_planner_referenced_it_via_uses_form_fields() -> (
    None
):
    """A server-derived hint completes the declaration when the planner
    referenced its variable name via `uses_form_fields` even without
    declaring an explicit `input_fields` entry. The compiler then wires
    the field into the step's underlag automatically — the planner
    needs only to mention the name once.
    """
    from eneo.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Review report",
            "plan_rationale": "Review source material for the chosen audience.",
            "steps": [
                {
                    "name": "Review",
                    "instructions": "Review the source material for the chosen audience.",
                    "uses_form_fields": ["audience"],
                }
            ],
        }
    )
    context = CreateCompileContext(
        runtime_input_field_hints=(
            RuntimeInputFieldHint(variable_name="audience", label="Audience"),
            RuntimeInputFieldHint(variable_name="detail_level", label="Detail level"),
        ),
    )

    draft = compile_create_intent_to_spec(outline, context=context)
    compiled = draft
    validation = validate_spec(compiled)

    assert [field.name for field in (draft.form_fields or [])] == ["audience"]
    assert compiled.form_fields is not None
    assert [field.name for field in (compiled.form_fields or [])] == ["audience"]
    assert compiled.form_fields[0].options is None
    first_question = compiled.steps[0].input_bindings or {}
    assert "{{ flow_input.audience }}" in str(first_question.get("question") or "")
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_includes_only_referenced_runtime_hints() -> None:
    from eneo.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Review report",
            "plan_rationale": "Review source material for the chosen audience.",
            "steps": [
                {
                    "name": "Extract report facts",
                    "instructions": "Extract facts for the selected report type.",
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "array",
                            "description": "Relevant report facts.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "fact",
                                    "field_type": "string",
                                    "description": "A fact.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                    "uses_form_fields": ["report_type"],
                },
                {
                    "name": "Review for audience",
                    "instructions": "Review the extracted facts for the chosen audience.",
                    "uses_form_fields": ["audience"],
                },
            ],
        }
    )
    context = CreateCompileContext(
        runtime_input_field_hints=(
            RuntimeInputFieldHint(variable_name="audience", label="Audience"),
            RuntimeInputFieldHint(variable_name="report_type", label="Report type"),
            RuntimeInputFieldHint(variable_name="detail_level", label="Detail level"),
        ),
    )

    draft = compile_create_intent_to_spec(outline, context=context)
    compiled = draft
    validation = validate_spec(compiled)

    assert [field.name for field in (draft.form_fields or [])] == [
        "audience",
        "report_type",
    ]
    assert compiled.form_fields is not None
    assert [field.name for field in (compiled.form_fields or [])] == [
        "audience",
        "report_type",
    ]
    first_question = str((compiled.steps[0].input_bindings or {}).get("question") or "")
    second_question = str(
        (compiled.steps[1].input_bindings or {}).get("question") or ""
    )
    assert "{{ flow_input.report_type }}" in first_question
    assert "{{ flow_input.audience }}" in second_question
    assert find_unused_form_fields(compiled) == []
    assert validation.valid


def test_compile_outline_flow_drops_extracted_metadata_hints_when_planner_did_not_wire_them() -> (
    None
):
    prompt = (
        "Jag vill ha ett flöde för utvecklingssamtal där användaren kommer "
        "att ange namn, personnummer, yrke, roll och nuvarande lön och sedan "
        "ladda upp ljud från samtalet."
    )
    field_hints = extract_runtime_input_field_hints(prompt)
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Utvecklingssamtal",
            "plan_rationale": "Transkribera samtal och skapa en strukturerad bedömning.",
            "steps": [
                {
                    "name": "Transkribera samtal",
                    "instructions": "Transkribera ljudet från utvecklingssamtalet.",
                    "output_type": "text",
                },
                {
                    "name": "Analysera samtal",
                    "instructions": (
                        "Analysera transkriptionen och använd metadatafält vid "
                        "bedömningen."
                    ),
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "salary_increase_percent",
                            "field_type": "number",
                            "description": "Bedömd lönehöjning i procent.",
                            "required": True,
                        }
                    ],
                },
            ],
        }
    )
    context = CreateCompileContext(
        runtime_input_type=InputType.AUDIO,
        runtime_input_field_hints=field_hints,
    )

    draft = compile_create_intent_to_spec(outline, context=context)
    compiled = draft
    validation = validate_spec(compiled)

    from eneo.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    # The planner declared no `input_fields` and did not list any hint name
    # in `uses_form_fields`, so the server-derived hints stay out of
    # form_fields entirely. The flow validates without orphan UI controls.
    assert [field.name for field in (draft.form_fields or [])] == []
    assert compiled.form_fields is None or compiled.form_fields == []
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_overlap_planner_declared_field_and_hint_with_same_name() -> (
    None
):
    """When the planner declares an `input_fields` entry whose name
    matches a server-derived hint, the planner-declared label/options/etc
    win and the field appears exactly once in form_fields. The hint
    completes nothing because the declaration is already there.
    """
    from eneo.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Overlap audience",
            "plan_rationale": "Use audience for tone.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience explicit",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Write",
                    "instructions": "Write for the audience.",
                    "uses_form_fields": ["audience"],
                }
            ],
        }
    )
    context = CreateCompileContext(
        runtime_input_field_hints=(
            RuntimeInputFieldHint(
                variable_name="audience", label="Audience hint label"
            ),
        ),
    )

    draft = compile_create_intent_to_spec(outline, context=context)
    compiled = draft
    validation = validate_spec(compiled)

    # Field appears once and keeps the planner-declared label.
    assert [field.name for field in (draft.form_fields or [])] == ["audience"]
    assert draft.form_fields[0].label == "Audience explicit"
    assert compiled.form_fields is not None
    assert [field.name for field in (compiled.form_fields or [])] == ["audience"]
    first_question = str((compiled.steps[0].input_bindings or {}).get("question") or "")
    assert first_question.count("{{ flow_input.audience }}") == 1
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_orphan_uses_form_fields_reference_is_dropped_silently() -> (
    None
):
    """When a step lists a name in `uses_form_fields` that exists in
    NEITHER `outline.input_fields` NOR any server-derived hint, the
    reference is silently dropped. The compiled spec is valid (no
    orphan template variable, no exception).
    """
    from eneo.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Orphan reference",
            "plan_rationale": "Reference a name that does not exist.",
            "steps": [
                {
                    "name": "Write",
                    "instructions": "Write something useful.",
                    "uses_form_fields": ["missing_field"],
                }
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    # The orphan reference does not pull a field into form_fields and
    # does not poison the step's bindings with `{{ missing_field }}`.
    assert [field.name for field in (draft.form_fields or [])] == []
    first_question = str((compiled.steps[0].input_bindings or {}).get("question") or "")
    assert "{{ missing_field }}" not in first_question
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_drops_field_that_shadows_primary_text_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Customer reply",
            "plan_rationale": "Classify the request before drafting an answer.",
            "input_fields": [
                {
                    "variable_name": "text",
                    "label": "Text",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "instructions": "Classify the incoming customer request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "instructions": "Draft a concise reply based on the classification.",
                    "output_type": "text",
                    "uses_form_fields": ["text"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        ),
    }

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(
            outline,
            context=create_compile_context_from_planning_state(state),
        )
    compiled = draft
    validation = validate_spec(compiled)

    shadow_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_primary_input_shadow_fields_dropped"
    ]
    assert shadow_records
    assert getattr(shadow_records[0], "field_names") == ["text"]
    assert getattr(shadow_records[0], "runtime_input_type") == "text"
    assert draft.form_fields is None
    assert draft.steps[1].input_type.value == "json"
    assert compiled.form_fields is None
    assert compiled.steps[1].input_bindings is None
    assert validation.valid


def test_compile_outline_flow_keeps_secondary_text_metadata_for_text_input() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audience aware reply",
            "plan_rationale": "Classify the request and adapt the response.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "instructions": "Classify the incoming customer request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "instructions": "Draft a concise reply for the selected audience.",
                    "output_type": "text",
                    "uses_form_fields": ["audience"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [field.name for field in (draft.form_fields or [])] == ["audience"]
    assert compiled.form_fields is not None
    assert compiled.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}\n\naudience: {{ flow_input.audience }}"
    }
    assert validation.valid


def test_compile_outline_flow_keeps_declared_runtime_fields_for_policy_default_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audience aware reply",
            "plan_rationale": "Classify the request and adapt the response.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "instructions": "Classify the incoming customer request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "instructions": "Draft a concise reply for the selected audience.",
                    "output_type": "text",
                    "uses_form_fields": ["audience"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        ),
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=NO_EXTRA_RUNTIME_METADATA,
            source="policy_default",
            confidence="medium",
        ),
    }

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(
            outline,
            context=create_compile_context_from_planning_state(state),
        )
    validation = validate_spec(draft)

    assert [
        record
        for record in caplog.records
        if record.message == "ai_builder_runtime_metadata_input_fields_dropped"
    ] == []
    assert [field.name for field in (draft.form_fields or [])] == ["audience"]
    assert draft.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}\n\naudience: {{ flow_input.audience }}"
    }
    assert validation.valid


def test_compile_outline_flow_drops_runtime_fields_for_explicit_no_metadata_decision(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Kommunstyrelsemöte till DOCX",
            "plan_rationale": "Transkribera och strukturera mötet innan DOCX skapas.",
            "input_fields": [
                {
                    "variable_name": "language",
                    "label": "Språk",
                    "field_type": "text",
                    "required": False,
                },
                {
                    "variable_name": "output_style",
                    "label": "Dokumentstil",
                    "field_type": "text",
                    "required": False,
                },
                {
                    "variable_name": "include_timestamps",
                    "label": "Inkludera tidsstämplar",
                    "field_type": "text",
                    "required": False,
                },
            ],
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "instructions": "Transkribera den uppladdade ljudfilen.",
                    "output_type": "text",
                    "uses_form_fields": ["language"],
                },
                {
                    "name": "Identifiera rubriker",
                    "instructions": "Dela in mötet i kommunstyrelserubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "object",
                            "description": "Rubrikindelat mötesinnehåll.",
                            "required": True,
                        }
                    ],
                    "uses_form_fields": ["output_style"],
                },
                {
                    "name": "Skriv dokumenttext",
                    "instructions": "Skriv slutlig dokumenttext.",
                    "output_type": "text",
                    "uses_form_fields": ["include_timestamps"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="docx_document",
            source="structured_answer",
            confidence="high",
        ),
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=NO_EXTRA_RUNTIME_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(
            outline,
            context=create_compile_context_from_planning_state(state),
        )
    compiled = draft
    validation = validate_spec(compiled)

    metadata_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_runtime_metadata_input_fields_dropped"
    ]
    assert metadata_records
    assert getattr(metadata_records[0], "field_names") == [
        "include_timestamps",
        "language",
        "output_style",
    ]
    assert getattr(metadata_records[0], "runtime_metadata_state") == (
        NO_EXTRA_RUNTIME_METADATA
    )
    assert draft.form_fields is None
    assert compiled.form_fields is None
    question_bindings = [
        step.input_bindings["question"]
        for step in compiled.steps
        if step.input_bindings is not None
    ]
    assert not any("{{ language }}" in binding for binding in question_bindings)
    assert not any(
        "{{ flow_input.language }}" in binding for binding in question_bindings
    )
    assert not any("{{ output_style }}" in binding for binding in question_bindings)
    assert not any(
        "{{ flow_input.output_style }}" in binding for binding in question_bindings
    )
    assert not any(
        "{{ include_timestamps }}" in binding for binding in question_bindings
    )
    assert not any(
        "{{ flow_input.include_timestamps }}" in binding
        for binding in question_bindings
    )
    assert validation.valid


def test_compile_outline_flow_keeps_runtime_fields_when_metadata_is_detailed() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audience aware reply",
            "plan_rationale": "Classify the request and adapt the response.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "instructions": "Classify the incoming customer request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "instructions": "Draft a concise reply for the selected audience.",
                    "output_type": "text",
                    "uses_form_fields": ["audience"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        ),
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [field.name for field in (draft.form_fields or [])] == ["audience"]
    assert compiled.form_fields is not None
    assert "{{ flow_input.audience }}" in str(
        (compiled.steps[1].input_bindings or {}).get("question") or ""
    )
    assert validation.valid


def test_compile_outline_flow_folds_leading_zero_contract_text_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Customer reply",
            "plan_rationale": "Classify first, then draft the reply.",
            "steps": [
                {
                    "name": "Receive question",
                    "instructions": "Use the customer question as the source material.",
                    "output_type": "text",
                },
                {
                    "name": "Classify request",
                    "instructions": "Classify the incoming request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "instructions": "Draft a concise customer reply.",
                    "output_type": "text",
                },
            ],
        }
    )

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    folded_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_create_intent_zero_contract_steps_folded"
    ]
    assert folded_records
    assert getattr(folded_records[0], "folded_step_names") == ["Receive question"]
    assert getattr(folded_records[0], "target_step_name") == "Classify request"
    assert [step.name for step in draft.steps] == ["Classify request", "Draft reply"]
    assert (
        draft.steps[0].assistant_spec.instructions
        == "Use the customer question as the source material.\n\n"
        "Classify the incoming request.\n\n"
        "Required JSON fields:\n"
        "- category: Request category."
    )
    assert draft.steps[0].input_source.value == "flow_input"
    assert draft.steps[0].input_type.value == "text"
    assert draft.steps[0].output_type.value == "json"
    assert compiled.steps[0].input_bindings == {"question": "{{ indata_text }}"}
    assert compiled.steps[1].input_type.value == "json"
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_output_contract() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured intake",
            "plan_rationale": "Extract structured fields before writing.",
            "steps": [
                {
                    "name": "Extract intake",
                    "instructions": "Extract the source fields.",
                    "output_type": "text",
                    "output_fields": [
                        {
                            "name": "topic",
                            "field_type": "string",
                            "description": "Main topic.",
                        }
                    ],
                },
                {
                    "name": "Write answer",
                    "instructions": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == ["Extract intake", "Write answer"]
    assert draft.steps[0].output_contract is not None
    assert compiled.steps[1].input_contract == compiled.steps[0].output_contract
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_form_field_usage() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audience reply",
            "plan_rationale": "Use runtime audience metadata while drafting.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Prepare audience context",
                    "instructions": "Prepare context for the selected audience.",
                    "output_type": "text",
                    "uses_form_fields": ["audience"],
                },
                {
                    "name": "Write answer",
                    "instructions": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Prepare audience context",
        "Write answer",
    ]
    assert compiled.steps[0].input_bindings == {
        "question": "{{ indata_text }}\n\naudience: {{ flow_input.audience }}"
    }
    assert validation.valid


def test_compile_outline_flow_preserves_file_runtime_leading_step() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document summary",
            "plan_rationale": "Prepare uploaded documents before summarizing.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Read the uploaded documents.",
                    "output_type": "text",
                },
                {
                    "name": "Summarize",
                    "instructions": "Summarize the document material.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(runtime_input_type=InputType.DOCUMENT),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == ["Read documents", "Summarize"]
    assert compiled.steps[0].input_config["runtime_input"]["input_format"] == "document"
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_model_ref() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Specialized first pass",
            "plan_rationale": "Use a selected model for the first pass.",
            "steps": [
                {
                    "name": "Specialized reading",
                    "instructions": "Read the source text with the selected model.",
                    "output_type": "text",
                    "model_ref": "model-specialist",
                },
                {
                    "name": "Write answer",
                    "instructions": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Specialized reading",
        "Write answer",
    ]
    assert draft.steps[0].assistant_spec.model_ref == "model-specialist"
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_knowledge_refs() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Policy grounded reply",
            "plan_rationale": "Ground the first pass in a selected knowledge base.",
            "steps": [
                {
                    "name": "Ground in policy",
                    "instructions": "Read the source text against the policy base.",
                    "output_type": "text",
                    "knowledge_refs": ["kb-policy"],
                },
                {
                    "name": "Write answer",
                    "instructions": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == ["Ground in policy", "Write answer"]
    assert draft.steps[0].assistant_spec.knowledge_refs == ["kb-policy"]
    assert validation.valid


def test_compile_outline_flow_folds_before_final_artifact_append() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "DOCX report",
            "plan_rationale": "Prepare source text and generate a report.",
            "steps": [
                {
                    "name": "Receive text",
                    "instructions": "Use the submitted text as report source.",
                    "output_type": "text",
                },
                {
                    "name": "Draft report content",
                    "instructions": "Draft the report body.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(final_output_type=OutputType.DOCX),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Draft report content",
        "Create DOCX",
    ]
    assert draft.steps[0].assistant_spec.instructions == (
        "Use the submitted text as report source.\n\nDraft the report body."
    )
    assert draft.steps[-1].output_type.value == "docx"
    assert compiled.steps[-1].output_type.value == "docx"
    assert validation.valid


def test_runtime_input_field_hints_parse_generic_field_declarations() -> None:
    hints = extract_runtime_input_field_hints(
        "Use input fields for audience and detail level at runtime, then build a report."
    )

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("audience", "audience"),
        ("detail_level", "detail level"),
    ]

    swedish_hints = extract_runtime_input_field_hints(
        "Använd inmatningsfält för målgrupp och rapportnivå vid körning, och skapa rapport."
    )

    assert [(hint.variable_name, hint.label) for hint in swedish_hints] == [
        ("malgrupp", "målgrupp"),
        ("rapportniva", "rapportnivå"),
    ]


def test_outline_compile_context_extracts_runtime_hints_when_state_allows_source() -> (
    None
):
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }

    context = create_compile_context_from_planning_state(
        state,
        runtime_input_hint_source=RuntimeInputFieldHintSource(
            aggregated_conversation_text=(
                "Använd inmatningsfält för målgrupp och rapportnivå vid körning."
            )
        ),
    )

    assert context is not None
    assert [
        (hint.variable_name, hint.label) for hint in context.runtime_input_field_hints
    ] == [
        ("malgrupp", "målgrupp"),
        ("rapportniva", "rapportnivå"),
    ]


def test_outline_compile_context_suppresses_runtime_hints_when_state_forbids_source() -> (
    None
):
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=NO_EXTRA_RUNTIME_METADATA,
            source="policy_default",
            confidence="medium",
        ),
    }

    context = create_compile_context_from_planning_state(
        state,
        runtime_input_hint_source=RuntimeInputFieldHintSource(
            aggregated_conversation_text=(
                "Använd inmatningsfält för målgrupp och rapportnivå vid körning."
            )
        ),
    )

    assert context is not None
    assert context.runtime_input_field_hints == ()


def test_outline_compile_context_does_not_extract_runtime_hints_without_source() -> (
    None
):
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_field_hints == ()


def test_outline_compile_context_keeps_hints_empty_when_state_and_source_absent() -> (
    None
):
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=NO_EXTRA_RUNTIME_METADATA,
            source="policy_default",
            confidence="medium",
        ),
    }

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_field_hints == ()


def test_outline_compile_context_does_not_extract_runtime_hints_from_empty_source() -> (
    None
):
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }

    context = create_compile_context_from_planning_state(
        state,
        runtime_input_hint_source=RuntimeInputFieldHintSource(
            aggregated_conversation_text=""
        ),
    )

    assert context is not None
    assert context.runtime_input_field_hints == ()


def test_outline_compile_context_treats_architecture_any_input_as_no_override() -> None:
    state = _committed_architecture_state(
        input_type="any",
        output_type="text",
        output_mode="pass_through",
        chosen_patterns=[],
        required_capabilities=[],
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_type is None


def test_compile_outline_flow_uses_server_architecture_context_for_core_shape() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio report",
            "plan_rationale": "Transcribe and summarize.",
            "steps": [
                {
                    "name": "Transcribe",
                    "instructions": "Transcribe the uploaded audio.",
                    "output_type": "text",
                },
                {
                    "name": "Summarize",
                    "instructions": "Summarize the transcript for the reader.",
                    "output_type": "text",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.output_type.value for step in draft.steps] == [
        "text",
        "text",
        "pdf",
    ]
    assert draft.steps[0].input_type.value == "audio"
    assert draft.steps[2].output_mode == OutputMode.PASS_THROUGH
    assert compiled.steps[0].input_config["runtime_input"]["input_format"] == "audio"
    assert compiled.steps[2].output_type.value == "pdf"
    assert validation.valid


def test_compile_outline_flow_inserts_audio_transcription_for_single_artifact_step() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio PDF report",
            "plan_rationale": "Create a report from uploaded audio.",
            "steps": [
                {
                    "name": "Create report",
                    "instructions": "Summarize the recording and create the final PDF.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Create report",
        "Create PDF",
    ]
    assert draft.steps[0].input_type.value == "audio"
    assert draft.steps[0].output_type.value == "text"
    assert draft.steps[1].input_source.value == "previous_step"
    assert draft.steps[1].input_type.value == "text"
    assert draft.steps[1].output_type.value == "text"
    assert draft.steps[2].output_type.value == "pdf"
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert compiled.steps[2].output_type.value == "pdf"
    assert validation.valid
    assert_create_spec_prepares_through_authoring_command(compiled)


def test_compile_outline_flow_moves_review_to_backend_audio_transcription() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio PDF report",
            "plan_rationale": "Review the transcript before creating the report.",
            "steps": [
                {
                    "name": "Transcribe audio",
                    "instructions": "Transcribe the uploaded audio to text.",
                    "review_mode": "edit",
                },
                {
                    "name": "Create report",
                    "instructions": "Summarize the reviewed transcript and create the final PDF.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Create report",
        "Create PDF",
    ]
    assert draft.steps[0].review_policy is not None
    assert draft.steps[0].review_policy.mode is FlowStepReviewMode.EDIT
    assert draft.steps[1].review_policy is None
    assert compiled.steps[0].review_policy is not None
    assert compiled.steps[0].review_policy.mode is FlowStepReviewMode.EDIT
    assert compiled.steps[1].review_policy is None
    assert validation.valid


def test_compile_outline_flow_does_not_leak_review_to_backend_audio_transcription() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio PDF report",
            "plan_rationale": "Review the analysis before creating the report.",
            "steps": [
                {
                    "name": "Analyze transcript",
                    "instructions": "Analyze the transcript.",
                    "review_mode": "edit",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Analyze transcript",
        "Create PDF",
    ]
    assert draft.steps[0].review_policy is None
    assert draft.steps[1].review_policy is not None
    assert draft.steps[1].review_policy.mode is FlowStepReviewMode.EDIT
    assert compiled.steps[0].review_policy is None
    assert compiled.steps[1].review_policy is not None
    assert compiled.steps[1].review_policy.mode is FlowStepReviewMode.EDIT
    assert validation.valid


def test_compile_outline_flow_drops_redundant_leading_audio_transcription_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "instructions": "Transkribera den uppladdade ljudinspelningen till text.",
                    "model_ref": "default_small_model",
                },
                {
                    "name": "Strukturera innehållet",
                    "instructions": "Dela transkriptionen i tydliga rubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "array",
                            "description": "Rubrikindelat innehåll.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "heading",
                                    "field_type": "string",
                                    "description": "Rubrik.",
                                    "required": True,
                                },
                                {
                                    "name": "body",
                                    "field_type": "string",
                                    "description": "Avsnittets text.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Skriv dokumenttext",
                    "instructions": "Skriv ett sammanhängande dokument från rubrikerna.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(
            outline,
            context=create_compile_context_from_planning_state(state),
        )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Strukturera innehållet",
        "Skriv dokumenttext",
        "Create DOCX",
    ]
    drop_records = [
        record
        for record in caplog.records
        if record.message
        == "ai_builder_redundant_audio_transcription_semantic_step_dropped"
    ]
    assert drop_records
    assert getattr(drop_records[0], "step_name") == "Transkribera ljud"
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert validation.valid


def test_compile_outline_flow_drops_task_only_audio_to_text_transcription_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Förbered textunderlag",
                    "instructions": "Transkribera uppladdade ljudinspelningar till text.",
                },
                {
                    "name": "Strukturera innehållet",
                    "instructions": "Dela transkriptionen i tydliga rubriker.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(
            outline,
            context=create_compile_context_from_planning_state(state),
        )

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Strukturera innehållet",
        "Create DOCX",
    ]
    assert any(
        record.message
        == "ai_builder_redundant_audio_transcription_semantic_step_dropped"
        and getattr(record, "step_name") == "Förbered textunderlag"
        for record in caplog.records
    )


def test_compile_outline_flow_rewrites_structured_audio_transcription_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Transkribera mötesljud",
                    "instructions": "Transkribera uppladdade ljudinspelningar till text.",
                    "output_fields": [
                        {
                            "name": "transcript",
                            "field_type": "string",
                            "description": "Sammanställd transkription.",
                            "required": True,
                        },
                        {
                            "name": "segments",
                            "field_type": "array",
                            "description": "Segmenterad transkription.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "text",
                                    "field_type": "string",
                                    "description": "Segmenttext.",
                                    "required": True,
                                }
                            ],
                        },
                    ],
                },
                {
                    "name": "Extrahera beslut",
                    "instructions": "Identifiera beslut och åtgärder från transkriptionen.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(
            outline,
            context=create_compile_context_from_planning_state(state),
        )
    compiled = draft
    validation = validate_spec(compiled)

    assert draft.steps[1].name == "Strukturera transkription"
    assert "redan transkriberade texten" in draft.steps[1].assistant_spec.instructions
    assert "Transkribera mötesljud" not in [step.name for step in draft.steps]
    rewrite_records = [
        record
        for record in caplog.records
        if record.message
        == "ai_builder_redundant_audio_transcription_semantic_step_rewritten"
    ]
    assert rewrite_records
    assert validation.valid


def test_compile_outline_flow_audio_to_docx_uses_skeleton_terminal_artifact() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Summarize recording",
                    "instructions": "Summarize the transcribed audio.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Summarize recording",
        "Create DOCX",
    ]
    assert [step.input_type.value for step in draft.steps] == [
        "audio",
        "text",
        "text",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "text",
        "text",
        "docx",
    ]
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert compiled.steps[-1].output_type.value == "docx"
    assert validation.valid


def test_compile_outline_audio_docx_keeps_document_body_step_text_when_fields_requested() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Generera DOCX-dokument",
                    "instructions": "Skapa dokumentets rubriker och textinnehåll.",
                    "output_fields": [
                        {
                            "name": "docx_title",
                            "field_type": "string",
                            "description": "Titel som används i dokumentet.",
                            "required": True,
                        },
                        {
                            "name": "document_sections_count",
                            "field_type": "number",
                            "description": "Antal rubriksektioner som inkluderades.",
                            "required": True,
                        },
                    ],
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Generera DOCX-dokument",
        "Create DOCX",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "text",
        "text",
        "docx",
    ]
    assert compiled.steps[1].output_contract is None
    assert compiled.steps[-1].input_type.value == "text"
    assert compiled.steps[-1].input_bindings is None
    assert validation.valid


def test_compile_outline_audio_pdf_defaults_contract_for_untyped_json_extraction() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_plan_quality_critic import (
        build_conversation_aware_quality_feedback,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio PDF report",
            "plan_rationale": "Extract key information and produce a PDF.",
            "steps": [
                {
                    "name": "Extrahera nyckeluppgifter",
                    "instructions": "Extrahera nyckeluppgifter från transkriptionen.",
                    "output_type": "json",
                },
                {
                    "name": "Skapa PDF-innehåll",
                    "instructions": "Skriv PDF-innehåll från de extraherade uppgifterna.",
                    "output_type": "pdf",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)
    feedback = build_conversation_aware_quality_feedback(
        [
            {
                "role": "user",
                "content": (
                    "Transkribera ljud, extrahera nyckeluppgifter och skapa en PDF."
                ),
            }
        ],
        compiled,
    )

    extraction_step = draft.steps[1]
    assert extraction_step.output_type == OutputType.JSON
    assert extraction_step.output_contract is not None
    assert set(extraction_step.output_contract["properties"]) == {
        "source_facts",
        "uncertainties",
    }
    assert validation.valid
    assert feedback is None


@pytest.mark.parametrize("final_output_type", ["docx", "pdf"])
def test_compile_outline_audio_artifact_final_body_step_fans_in_prior_structured_work(
    final_output_type: str,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio artifact report",
            "plan_rationale": "Create a document report from uploaded audio.",
            "steps": [
                {
                    "name": "Identifiera och segmentera innehåll per rubrik",
                    "instructions": "Dela in mötet i rubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "object",
                            "description": "Rubrikindelat innehåll.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "introduction",
                                    "field_type": "string",
                                    "description": "Introduktion.",
                                    "required": True,
                                },
                                {
                                    "name": "conclusions",
                                    "field_type": "string",
                                    "description": "Slutsatser.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Skapa sammanfattning av allt ovan",
                    "instructions": "Sammanfatta rubrikavsnitten.",
                    "output_fields": [
                        {
                            "name": "overall_summary",
                            "field_type": "string",
                            "description": "Sammanfattning av hela mötet.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Bygg dokument med rubriker och innehåll",
                    "instructions": "Skriv dokumentets fullständiga text från alla tidigare steg.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type=final_output_type,
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    body_step = compiled.steps[-2]
    assert body_step.name == "Bygg dokument med rubriker och innehåll"
    assert body_step.input_source.value == "previous_step"
    assert body_step.input_type.value == "text"
    assert body_step.output_type.value == "text"
    assert body_step.input_bindings is not None
    body_question = body_step.input_bindings["question"]
    assert ".output.structured.sections" in body_question
    assert ".output.structured.overall_summary" in body_question
    assert compiled.steps[-2].input_contract is None
    assert compiled.steps[-1].output_type.value == final_output_type
    assert validation.valid


def test_compile_outline_audio_docx_four_phase_body_step_fans_in_prior_work() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Rensa transkription",
                    "instructions": "Normalisera transkriptionen inför analys.",
                },
                {
                    "name": "Identifiera rubrikavsnitt",
                    "instructions": "Dela in mötet i rubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "object",
                            "description": "Rubrikindelat innehåll.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "introduction",
                                    "field_type": "string",
                                    "description": "Introduktion.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Skapa sammanfattning",
                    "instructions": "Sammanfatta rubrikavsnitten.",
                    "output_fields": [
                        {
                            "name": "overall_summary",
                            "field_type": "string",
                            "description": "Sammanfattning av hela mötet.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Bygg DOCX-dokument",
                    "instructions": "Skriv dokumentets fullständiga text från alla tidigare steg.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    body_step = compiled.steps[-2]
    assert body_step.name == "Bygg DOCX-dokument"
    assert body_step.input_source.value == "previous_step"
    assert body_step.input_type.value == "text"
    assert body_step.output_type.value == "text"
    assert body_step.input_bindings is not None
    body_question = body_step.input_bindings["question"]
    assert ".output.structured.sections" in body_question
    assert ".output.structured.overall_summary" in body_question
    assert "Source material: {{ step_a.output.text }}" in body_question
    assert compiled.steps[-2].input_contract is None
    assert validation.valid


def test_compile_outline_audio_docx_body_step_auto_authors_targeted_refs_when_json_predecessor() -> (
    None
):
    """When the audio→DOCX skeleton produces a body composer text step with
    JSON predecessors, the dataflow normalizer must switch input_source to
    `previous_step` and auto-populate `uses_previous_fields` so the
    `prefer_targeted_underlag_over_all_previous_steps` semantic invariant
    does not fire and the LLM is not stuck in a repair loop it cannot fix.
    """
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötesrapport från ljud till Word",
            "plan_rationale": "Transkribera ljud och skapa DOCX-rapport.",
            "steps": [
                {
                    "name": "Identifiera mötesmetadata",
                    "instructions": "Identifiera deltagare och datum från transkriptionen.",
                    "output_fields": [
                        {
                            "name": "meeting_title",
                            "field_type": "string",
                            "description": "Mötestitel.",
                            "required": True,
                        },
                        {
                            "name": "participants",
                            "field_type": "string",
                            "description": "Deltagare.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Identifiera beslut",
                    "instructions": "Lista alla beslut.",
                    "output_fields": [
                        {
                            "name": "decisions_summary",
                            "field_type": "string",
                            "description": "Beslut sammanfattat.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Skriv strukturerad rapport",
                    "instructions": "Skriv en strukturerad mötesrapport på svenska.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    body_step = compiled.steps[-2]
    assert body_step.name == "Skriv strukturerad rapport"
    assert body_step.output_type.value == "text"
    assert body_step.input_source.value == "previous_step"
    assert body_step.input_type.value == "text"
    assert body_step.input_bindings is not None
    body_question = body_step.input_bindings["question"]
    assert "meeting_title" in body_question
    assert "decisions_summary" in body_question

    composer = compiled.steps[-2]
    assert composer.input_bindings is not None
    question = composer.input_bindings["question"]
    assert "step_" in question and "output.structured" in question

    context = CriticContext(
        spec=compiled,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(terminal_output="docx_document"),
        mixed_audio_doc_input=False,
        requested_output_sections=RequestedOutputSections.empty(),
    )
    issues = evaluate_critic_invariants(context, invariants=CRITIC_INVARIANTS)
    issue_ids = [issue.id for issue in issues]
    assert "prefer_targeted_underlag_over_all_previous_steps" not in issue_ids, (
        f"prefer_targeted_underlag must not fire after auto-binding; issues={issue_ids}"
    )
    assert validation.valid


def test_auto_bind_targeted_underlag_rewrites_aggregate_but_not_compare() -> None:
    """`compare` retains broad fan-in, but `aggregate` still gets targeted
    underlag because aggregate classification is intentionally conservative.
    """
    steps_before = [
        NewStepDraft(
            name="Sektion A",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("section_a", "string", description="Sektion A.")],
        ),
        NewStepDraft(
            name="Sektion B",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("section_b", "string", description="Sektion B.")],
        ),
        NewStepDraft(
            name="Aggregera",
            instructions="x",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
    ]

    for intent in ("aggregate", "compare"):
        draft = steps_before
        result = auto_bind_targeted_underlag_for_text_composer(
            draft,
            aggregation_intent=cast(AggregationIntent, intent),
        )
        composer = result[2]
        if intent == "compare":
            assert result is draft
            assert result == steps_before, (
                f"intent={intent!r} should be a no-op, but the composer was rewritten"
            )
            assert composer.input_source.value == "all_previous_steps"
            assert composer.uses_previous_fields == []
        else:
            assert result is not draft
            assert composer.input_source.value == "previous_step"
            assert {
                (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
            } >= {
                (1, "section_a"),
                (2, "section_b"),
            }


def test_auto_bind_targeted_underlag_two_step_linear_flow_is_unchanged() -> None:
    """A 2-step `flow_input → text_summary` flow with linear intent must NOT
    be rewritten. The skeleton already defaults the terminal to
    `previous_step` for linear shapes, so auto-bind has nothing to do.
    Reviewer concern: a 2-step shape with `composer_index == 1` and a JSON
    predecessor could otherwise force `uses_previous_fields` even when user
    intent is "summarize what came before" via broad fan-in.
    """
    steps_before = [
        NewStepDraft(
            name="Hämta data",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("payload", "string", description="API-svar.")],
        ),
        NewStepDraft(
            name="Skriv kommentar",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
    ]

    draft = steps_before
    result = auto_bind_targeted_underlag_for_text_composer(
        draft, aggregation_intent="linear"
    )
    assert result is draft
    assert result == steps_before, "2-step linear flow must be a no-op"
    composer = result[1]
    assert composer.input_source.value == "previous_step"
    assert composer.uses_previous_fields == []
    assert composer.uses_previous_outputs == []


def test_auto_bind_targeted_underlag_skips_when_text_priors_exceed_soft_cap() -> None:
    # Pins 78bf7994: the soft cap counts text priors, not JSON priors.
    from eneo.flows.ai_builder.ai_builder_underlag_policy import (
        TARGETED_UNDERLAG_SOFT_CAP,
    )

    text_priors: list[NewStepDraft] = []
    for index in range(TARGETED_UNDERLAG_SOFT_CAP + 1):
        text_priors.append(
            NewStepDraft(
                name=f"Skriv del {index}",
                instructions="x",
                input_source="flow_input" if index == 0 else "previous_step",
                input_type="text",
                output_type="text",
            )
        )
    json_anchor = NewStepDraft(
        name="Extrahera fakta",
        instructions="x",
        input_source="previous_step",
        input_type="text",
        output_type="json",
        output_fields=[_field("summary", "string")],
    )
    composer = NewStepDraft(
        name="Slutrapport",
        instructions="x",
        input_source="all_previous_steps",
        input_type="text",
        output_type="text",
    )
    steps_before = [*text_priors, json_anchor, composer]

    draft = steps_before
    result = auto_bind_targeted_underlag_for_text_composer(
        draft, aggregation_intent="linear"
    )
    assert result is draft
    assert result == steps_before, "over-cap text priors should bail out"
    assert result[-1].input_source.value == "all_previous_steps"


def test_auto_bind_targeted_underlag_fires_when_many_json_priors_with_few_text_priors() -> (
    None
):
    # Pins 78bf7994: many JSON priors should still auto-bind targeted refs.
    from eneo.flows.ai_builder.ai_builder_underlag_policy import (
        TARGETED_UNDERLAG_SOFT_CAP,
    )

    transcription = NewStepDraft(
        name="Transkribera ljudet",
        instructions="x",
        input_source="flow_input",
        input_type="audio",
        output_type="text",
    )
    json_extractions: list[NewStepDraft] = []
    for index in range(TARGETED_UNDERLAG_SOFT_CAP + 2):
        json_extractions.append(
            NewStepDraft(
                name=f"Extrahera del {index}",
                instructions="x",
                input_source="previous_step",
                input_type="json" if index > 0 else "text",
                output_type="json",
                output_fields=[
                    _field(f"section_{index}", "string", description=f"Del {index}.")
                ],
            )
        )
    composer = NewStepDraft(
        name="Skriv sammanfattning",
        instructions="x",
        input_source="previous_step",
        input_type="json",
        output_type="text",
    )
    steps_before = [transcription, *json_extractions, composer]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    assert result != steps_before, (
        "auto-binder must fire when bulk of priors is JSON+output_fields, "
        "even if total prior count exceeds the text-prior cap"
    )
    rewritten_composer = result[-1]
    assert rewritten_composer.input_source.value == "previous_step"
    assert len(rewritten_composer.uses_previous_fields) == len(json_extractions), (
        "every JSON predecessor's structured field must be referenced"
    )
    referenced_steps = {
        ref.from_step for ref in rewritten_composer.uses_previous_fields
    }
    assert referenced_steps == {index + 2 for index in range(len(json_extractions))}, (
        "field refs must point at every JSON predecessor by 1-indexed position"
    )
    assert any(
        ref.from_step == 1 for ref in rewritten_composer.uses_previous_outputs
    ), "the transcription text prior must be wired via uses_previous_outputs"


def test_auto_bind_targeted_underlag_rewrites_nonterminal_all_previous_composer() -> (
    None
):
    """A report-body composer can be followed by a review step before the
    artifact renderer. The body composer is still the step that must avoid
    broad `all_previous_steps`; otherwise runtime prompt material is bloated
    before the review/revision chain even starts.
    """
    steps_before = [
        NewStepDraft(
            name="Läs PDF",
            instructions="x",
            input_source="flow_input",
            input_type="document",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera bakgrund",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("background", "string", description="Bakgrund.")],
        ),
        NewStepDraft(
            name="Extrahera risker",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("risks", "string", description="Risker.")],
        ),
        NewStepDraft(
            name="Förbered rapporttext",
            instructions="x",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Granska rapporttext",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skapa PDF",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="pdf",
        ),
    ]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    assert result != steps_before
    body_composer = result[3]
    assert body_composer.input_source.value == "previous_step"
    assert body_composer.input_type.value == "text"
    field_refs = {
        (ref.from_step, ref.field_path) for ref in body_composer.uses_previous_fields
    }
    assert field_refs == {(2, "background"), (3, "risks")}
    assert any(ref.from_step == 1 for ref in body_composer.uses_previous_outputs), (
        "the original source text must remain available as targeted material"
    )


def test_auto_bind_targeted_underlag_rewrites_multiple_eligible_composers() -> None:
    """Each eligible all_previous text composer is evaluated against its own
    prior material. Stopping after the final composer leaves earlier generated
    report sections broad and token-heavy.
    """
    steps_before = [
        NewStepDraft(
            name="Läs underlag",
            instructions="x",
            input_source="flow_input",
            input_type="document",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera resultat",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("findings", "string", description="Resultat.")],
        ),
        NewStepDraft(
            name="Skriv första utkast",
            instructions="x",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera risker",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("risks", "string", description="Risker.")],
        ),
        NewStepDraft(
            name="Skriv reviderad text",
            instructions="x",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
    ]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    assert result != steps_before
    first_composer = result[2]
    assert first_composer.input_source.value == "previous_step"
    assert {
        (ref.from_step, ref.field_path) for ref in first_composer.uses_previous_fields
    } == {(2, "findings")}

    second_composer = result[4]
    assert second_composer.input_source.value == "previous_step"
    assert {
        (ref.from_step, ref.field_path) for ref in second_composer.uses_previous_fields
    } == {(2, "findings"), (4, "risks")}
    assert {ref.from_step for ref in second_composer.uses_previous_outputs} == {1, 3}


def test_auto_bind_targeted_underlag_leaves_text_only_all_previous_composer() -> None:
    steps_before = [
        NewStepDraft(
            name="Skriv del ett",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv del två",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Sammanställ text",
            instructions="x",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
    ]

    draft = steps_before
    result = auto_bind_targeted_underlag_for_text_composer(
        draft, aggregation_intent="linear"
    )

    assert result is draft
    assert result == steps_before
    assert result[-1].input_source.value == "all_previous_steps"
    assert result[-1].uses_previous_fields == []


def test_auto_bound_c2_shape_does_not_trigger_targeted_underlag_critic_loop() -> None:
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    steps = [
        NewStepDraft(
            name="Läs PDF",
            instructions="x",
            input_source="flow_input",
            input_type="document",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera bakgrund",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("background", "string", description="Bakgrund.")],
        ),
        NewStepDraft(
            name="Extrahera resultat",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("findings", "string", description="Resultat.")],
        ),
        NewStepDraft(
            name="Förbered PDF-innehåll",
            instructions="x",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Granska och färdigställ",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skapa PDF",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="pdf",
        ),
    ]
    rebound_steps = auto_bind_targeted_underlag_for_text_composer(
        steps,
        aggregation_intent="linear",
    )
    spec = _compile_create_steps(
        flow_name="PDF-rapport",
        steps=rebound_steps,
    )
    context = CriticContext(
        spec=spec,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(terminal_output="pdf_document"),
        mixed_audio_doc_input=False,
        requested_output_sections=RequestedOutputSections.empty(),
    )

    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            context,
            invariants=CRITIC_INVARIANTS,
        )
    }

    assert "prefer_targeted_underlag_over_all_previous_steps" not in issue_ids
    assert "final_text_step_must_reference_relevant_structured_outputs" not in issue_ids


def test_auto_bind_targeted_underlag_rewrites_previous_step_composer_with_multiple_json_priors() -> (
    None
):
    """When the final text composer reads from `previous_step` and at least
    two prior content steps emit JSON with output_fields, auto-bind must
    populate `uses_previous_fields` with refs across all JSON priors. The
    composer keeps `previous_step` as its source — the goal is targeted
    fan-in, not concatenated body text. The 1-JSON-prior linear case
    remains a no-op (pinned by
    `test_auto_bind_targeted_underlag_two_step_linear_flow_is_unchanged`).
    """
    steps_before = [
        NewStepDraft(
            name="Extrahera produktdata",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[
                _field("product_name", "string", description="Produktnamn."),
                _field("product_price", "string", description="Produktpris."),
            ],
        ),
        NewStepDraft(
            name="Extrahera kunddata",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[
                _field("customer_segment", "string", description="Kundsegment."),
            ],
        ),
        NewStepDraft(
            name="Extrahera leveransdata",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[
                _field("delivery_window", "string", description="Leveransfönster."),
            ],
        ),
        NewStepDraft(
            name="Skriv sammanfattning",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    assert result != steps_before, (
        "composer with previous_step source and ≥2 JSON priors must be rewritten"
    )
    composer = result[-1]
    assert composer.input_source.value == "previous_step", (
        "input_source should remain previous_step (targeted fan-in, not concat)"
    )

    field_refs = {
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    }
    assert (1, "product_name") in field_refs
    assert (1, "product_price") in field_refs
    assert (2, "customer_segment") in field_refs
    assert (3, "delivery_window") in field_refs
    assert len(field_refs) == 4, (
        f"expected 4 field refs across 3 JSON priors, got {len(field_refs)}"
    )


def test_auto_bind_targeted_underlag_caps_and_distributes_declared_fields() -> None:
    from collections import Counter

    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP,
        TARGETED_UNDERLAG_TOTAL_FIELD_CAP,
    )

    steps_before = [
        NewStepDraft(
            name=f"Extrahera område {prior_index}",
            instructions="x",
            input_source="flow_input" if prior_index == 1 else "previous_step",
            input_type="text" if prior_index == 1 else "json",
            output_type="json",
            output_fields=[
                _field(
                    f"required_{prior_index}_{field_index}",
                    "string",
                    description=f"Obligatoriskt {prior_index}.{field_index}.",
                    required=True,
                )
                if field_index < 2
                else _field(
                    f"optional_{prior_index}_{field_index}",
                    "string",
                    description=f"Valfritt {prior_index}.{field_index}.",
                    required=False,
                )
                for field_index in range(5)
            ],
        )
        for prior_index in range(1, 5)
    ]
    first_prior_fields = list(steps_before[0].output_fields or [])
    steps_before[0] = steps_before[0].model_copy(
        update={
            "output_fields": [
                first_prior_fields[0],
                _field(
                    "required_1_0",
                    "string",
                    description="Duplicerat namn.",
                    required=True,
                ),
                *first_prior_fields[1:],
            ]
        }
    )
    steps_before.append(
        NewStepDraft(
            name="Skriv sammanfattning",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        )
    )

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    composer = result[-1]
    refs = composer.uses_previous_fields
    assert len(refs) == TARGETED_UNDERLAG_TOTAL_FIELD_CAP
    per_prior = Counter(ref.from_step for ref in refs)
    assert set(per_prior) == {1, 2, 3, 4}
    assert all(
        count <= TARGETED_UNDERLAG_FIELDS_PER_JSON_PRIOR_CAP
        for count in per_prior.values()
    )
    assert [(ref.from_step, ref.field_path) for ref in refs[:4]] == [
        (1, "required_1_0"),
        (2, "required_2_0"),
        (3, "required_3_0"),
        (4, "required_4_0"),
    ]
    assert [(ref.from_step, ref.field_path) for ref in refs[4:]] == [
        (1, "required_1_1"),
        (2, "required_2_1"),
        (3, "required_3_1"),
        (4, "required_4_1"),
    ]

    spec = _compile_create_steps(
        flow_name="Fältbegränsad rapport",
        steps=result,
    )
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            CriticContext(
                spec=spec,
                flow=None,
                answer_signals={},
                text="",
                requirements_text="",
                signal_text="",
                planner_patterns=PlannerPatternSignals(),
                output_intent=OutputIntentResolution(terminal_output="text"),
                mixed_audio_doc_input=False,
                requested_output_sections=RequestedOutputSections.empty(),
            ),
            invariants=CRITIC_INVARIANTS,
        )
    }
    assert "final_text_step_must_reference_relevant_structured_outputs" not in issue_ids


def test_normalize_create_step_mechanics_treats_prebound_targeted_text_composer_as_text_input() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousFieldRef

    steps = [
        NewStepDraft(
            name="Extrahera produktdata",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("product_name", "string")],
        ),
        NewStepDraft(
            name="Extrahera kunddata",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("customer_segment", "string")],
        ),
        NewStepDraft(
            name="Skriv sammanfattning",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
            uses_previous_fields=[
                PreviousFieldRef(
                    from_step=1,
                    field_path="product_name",
                    label="Produktnamn",
                ),
                PreviousFieldRef(
                    from_step=2,
                    field_path="customer_segment",
                    label="Kundsegment",
                ),
            ],
        ),
    ]

    normalized = _normalize_create_steps(flow_name="Förbunden rapport", steps=steps)

    composer = normalized[-1]
    assert composer.input_type.value == "text", (
        "explicit targeted underlag is text prompt material even when the "
        "immediate predecessor emits JSON"
    )
    assert {
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    } == {(1, "product_name"), (2, "customer_segment")}


def test_normalize_create_step_mechanics_treats_previous_output_text_composer_as_text_input() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousOutputRef

    steps = [
        NewStepDraft(
            name="Förbered text",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera struktur",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("summary", "string")],
        ),
        NewStepDraft(
            name="Skriv sluttext",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
            uses_previous_outputs=[PreviousOutputRef(from_step=1, label="Källtext")],
        ),
    ]

    normalized = _normalize_create_steps(
        flow_name="Förbunden textsammanfattning",
        steps=steps,
    )

    composer = normalized[-1]
    assert composer.input_type.value == "text"
    assert [(ref.from_step, ref.label) for ref in composer.uses_previous_outputs] == [
        (1, "Källtext")
    ]


def test_auto_bind_targeted_underlag_skips_previous_step_composer_with_single_json_prior() -> (
    None
):
    """A composer reading `previous_step` from exactly one JSON prior is a
    valid linear extract→summarize pipeline. Auto-bind must not inflate it
    with multi-source attachment.
    """
    steps_before = [
        NewStepDraft(
            name="Extrahera fält",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[
                _field("payload", "string", description="Extraherad data."),
            ],
        ),
        NewStepDraft(
            name="Skriv kommentar",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    draft = steps_before
    result = auto_bind_targeted_underlag_for_text_composer(
        draft, aggregation_intent="linear"
    )

    assert result is draft
    assert result == steps_before, (
        "single-JSON-prior + previous_step composer must remain a no-op"
    )
    composer = result[-1]
    assert composer.input_source.value == "previous_step"
    assert composer.uses_previous_fields == []


def test_auto_bind_targeted_underlag_routes_single_json_source_to_section_writers() -> (
    None
):
    extraction_fields = [
        _field(
            "tidplan",
            "string",
            description="Planerad tidplan och viktiga datum.",
        ),
        _field(
            "malgrupper",
            "array",
            description="Berörda målgrupper och behovsgrupper.",
        ),
        _field(
            "resursbehov",
            "string",
            description="Roller, kompetenser, timmar och kostnader.",
        ),
        _field(
            "nyttobedomning",
            "string",
            description="Direkt ekonomisk nytta, kostnader och nyttokvot.",
        ),
        _field(
            "kvalitativa_nyttor",
            "string",
            description="Kvalitativa nyttor för verksamhet och medborgare.",
        ),
        _field(
            "losningsinriktning",
            "string",
            description="Lösningsförslag och önskat nyläge.",
        ),
        _field(
            "nulage_och_problem",
            "string",
            description="Nuläge, problembeskrivning och behov av förändring.",
        ),
        _field(
            "finansieringsmojligheter",
            "string",
            description="Möjliga finansieringskällor och budgetar.",
        ),
        _field(
            "ansvarig_nyttorealisering",
            "string",
            description="Person eller roll som ansvarar för nyttorealisering.",
        ),
        _field(
            "sammanfattning_av_underlag",
            "string",
            description="Sammanfattning av dokumentunderlaget som helhet.",
        ),
    ]
    steps_before = [
        NewStepDraft(
            name="Läs underlag",
            instructions="Läs hela Word-dokumentet.",
            input_source="flow_input",
            input_type="document",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera centrala fakta ur underlaget",
            instructions="Extrahera återanvändbara fält för alla avsnitt.",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=extraction_fields,
        ),
        NewStepDraft(
            name="Skriv Problem och nuläge",
            instructions="Beskriv nuläge, målgrupp, problem och förändringsbehov.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv Lösningsförslag och nyläge",
            instructions="Beskriv lösningsförslag och önskat nyläge.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv Resursåtgång",
            instructions="Ange roller, kompetenser, timmar och kostnader.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv Planerad tidplan",
            instructions="Skriv den tänkta tidplanen.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv Finansiering",
            instructions="Beskriv hur kostnaderna föreslås finansieras.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv Ansvarig för nyttorealisering",
            instructions="Ange ansvarig person eller roll.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv oklar specialrubrik",
            instructions="Skriv ett kort avsnitt utan tydlig semantisk koppling.",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
    ]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    refs_by_step = {
        step.name: {ref.field_path for ref in step.uses_previous_fields}
        for step in result
    }
    assert "nulage_och_problem" in refs_by_step["Skriv Problem och nuläge"]
    assert "losningsinriktning" in refs_by_step["Skriv Lösningsförslag och nyläge"]
    assert "resursbehov" in refs_by_step["Skriv Resursåtgång"]
    assert "tidplan" in refs_by_step["Skriv Planerad tidplan"]
    assert "finansieringsmojligheter" in refs_by_step["Skriv Finansiering"]
    assert (
        "ansvarig_nyttorealisering"
        in refs_by_step["Skriv Ansvarig för nyttorealisering"]
    )
    assert refs_by_step["Skriv oklar specialrubrik"] == {
        "sammanfattning_av_underlag"
    }, "unmatched section writers should not all reuse the first declared fields"
    for step in result[2:]:
        assert {ref.from_step for ref in step.uses_previous_fields} == {2}
        assert step.uses_previous_outputs == []


def test_compile_create_steps_to_spec_section_writers_use_json_schema_as_underlag() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Utvecklingsärende från Word",
        steps=[
            NewStepDraft(
                name="Läs underlag",
                instructions="Läs hela Word-dokumentet.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Extrahera centrala fakta ur underlaget",
                instructions="Extrahera återanvändbara fält för alla avsnitt.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                output_fields=[
                    _field(
                        "nulage_och_problem",
                        "string",
                        description="Nuläge, problem och behov av förändring.",
                    ),
                    _field(
                        "losningsinriktning",
                        "string",
                        description="Lösningsförslag och nyläge.",
                    ),
                    _field(
                        "sammanfattning_av_underlag",
                        "string",
                        description="Sammanfattning av dokumentunderlaget.",
                    ),
                ],
            ),
            NewStepDraft(
                name="Skriv Problem och nuläge",
                instructions="Beskriv nuläge och problem.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Skriv Lösningsförslag och nyläge",
                instructions="Beskriv lösningsförslag och nyläge.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Skriv Plan för nyttorealisering",
                instructions="Skriv plan för nyttorealisering.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    spec = draft

    extraction = spec.steps[1]
    assert extraction.output_type == OutputType.JSON
    assert extraction.output_contract is not None
    assert set(extraction.output_contract["properties"]) == {
        "nulage_och_problem",
        "losningsinriktning",
        "sammanfattning_av_underlag",
    }

    problem_step, solution_step, benefit_plan_step = spec.steps[2:5]
    assert problem_step.input_type == InputType.TEXT
    assert problem_step.input_contract is None
    assert problem_step.input_bindings is not None
    assert (
        "step_b.output.structured.nulage_och_problem"
        in problem_step.input_bindings["question"]
    )

    assert solution_step.input_type == InputType.TEXT
    assert solution_step.input_contract is None
    assert solution_step.input_bindings is not None
    assert (
        "step_b.output.structured.losningsinriktning"
        in solution_step.input_bindings["question"]
    )

    assert benefit_plan_step.input_type == InputType.TEXT
    assert benefit_plan_step.input_contract is None
    assert benefit_plan_step.input_bindings is not None
    assert (
        "step_b.output.structured.sammanfattning_av_underlag"
        in (benefit_plan_step.input_bindings["question"])
    )


def test_compile_create_steps_to_spec_broad_document_composers_use_full_json_schema() -> (
    None
):
    extraction_fields = [
        _field(name, "string", description=description)
        for name, description in [
            ("syfte", "Syfte och behov."),
            ("nulage", "Nuläge, problem och behovsgrupp."),
            ("losningsforslag", "Lösningsförslag och nyläge."),
            ("resursbehov", "Roller, kompetenser, timmar och kostnader."),
            ("tidplan", "Planerad tidplan."),
            ("nytta_och_kostnader", "Ekonomisk nytta och kostnader."),
            ("nyttor", "Kvalitativa nyttor och målgrupper."),
            ("finansiering", "Föreslagen finansiering."),
            ("ansvar", "Ansvarig för nyttorealisering."),
            ("komplexitet", "Förändringens komplexitet."),
            ("nyttorealisering", "Plan för nyttorealisering."),
        ]
    ]
    draft = _compile_create_steps(
        flow_name="Dokument till verksamhetsunderlag",
        steps=[
            NewStepDraft(
                name="Extrahera centrala fakta",
                instructions="Extrahera återanvändbara fält för hela dokumentet.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=extraction_fields,
            ),
            NewStepDraft(
                name="Skriv verksamhetsavsnitt",
                instructions=(
                    "Skriv alla avsnitt och alla rubriker som användaren "
                    "efterfrågade i verksamhetsunderlaget."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Sammanställ slutligt Word-dokument",
                instructions="Sammanställ slutligt Word-dokument.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Skapa DOCX",
                instructions="Skapa DOCX från föregående text.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    spec = draft

    expected_selectors = {
        f"step_a.output.structured.{field.name}" for field in extraction_fields
    }
    section_writer_question = spec.steps[1].input_bindings["question"]
    final_composer_question = spec.steps[2].input_bindings["question"]
    assert expected_selectors.issubset(set(section_writer_question.split()))
    assert expected_selectors.issubset(set(final_composer_question.split()))
    assert "{{ step_b.output.text }}" in final_composer_question
    assert spec.steps[0].output_contract is not None
    assert set(spec.steps[0].output_contract["properties"]) == {
        field.name for field in extraction_fields
    }
    for composer in spec.steps[1:3]:
        assert composer.input_type == InputType.TEXT
        assert composer.input_contract is None
    assert spec.steps[3].input_bindings is None


def test_compile_create_steps_to_spec_section_writers_do_not_duplicate_full_json_schema() -> (
    None
):
    extraction_fields = [
        _field(name, "string", description=description)
        for name, description in [
            ("syfte", "Syfte och behov."),
            ("nulage", "Nuläge, problem och behovsgrupp."),
            ("losningsforslag", "Lösningsförslag och nyläge."),
            ("resurser", "Roller, kompetenser, timmar och kostnader."),
            ("tidplan", "Planerad tidplan."),
            ("kostnader", "Ekonomisk nytta och kostnader."),
            ("nyttor", "Kvalitativa nyttor och målgrupper."),
            ("finansiering", "Föreslagen finansiering."),
            ("komplexitet", "Förändringens komplexitet."),
            ("nyttorealisering", "Plan för nyttorealisering."),
        ]
    ]
    draft = _compile_create_steps(
        flow_name="Analys och utkast till verksamhetsunderlag",
        steps=[
            NewStepDraft(
                name="Extrahera centrala fakta",
                instructions="Extrahera återanvändbara fält för hela dokumentet.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=extraction_fields,
            ),
            NewStepDraft(
                name="Skriv problem och lösningsförslag",
                instructions=(
                    "Skriv avsnittet utifrån hela det ursprungliga dokumentet. "
                    "Beskriv nuläge, problem, behov och lösningsförslag."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Beskriv resurser och tidplan",
                instructions=(
                    "Skriv avsnittet utifrån hela det ursprungliga dokumentet. "
                    "Ange resurser, roller, kostnader och planerad tidplan."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Förbered DOCX-innehåll",
                instructions="Sammanställ slutligt Word-dokument.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    spec = draft

    first_writer_question = spec.steps[1].input_bindings["question"]
    second_writer_question = spec.steps[2].input_bindings["question"]
    final_question = spec.steps[3].input_bindings["question"]

    assert "step_a.output.structured.nulage" in first_writer_question
    assert "step_a.output.structured.losningsforslag" in first_writer_question
    assert "step_a.output.structured.tidplan" not in first_writer_question
    assert "step_a.output.structured.finansiering" not in first_writer_question

    assert "step_a.output.structured.resurser" in second_writer_question
    assert "step_a.output.structured.tidplan" in second_writer_question
    assert "step_a.output.structured.kostnader" in second_writer_question
    assert "step_a.output.structured.losningsforslag" not in second_writer_question

    expected_final_selectors = {
        f"step_a.output.structured.{field.name}" for field in extraction_fields
    }
    assert expected_final_selectors.issubset(set(final_question.split()))
    assert "{{ step_b.output.text }}" in final_question
    assert "{{ step_c.output.text }}" in final_question


def test_compile_create_steps_to_spec_section_writers_ignore_passing_broad_markers() -> (
    None
):
    extraction_fields = [
        _field("nulage", "string", description="Nuläge, problem och behov."),
        _field(
            "losningsforslag",
            "string",
            description="Lösningsförslag och nyläge.",
        ),
        _field("tidplan", "string", description="Planerad tidplan."),
        _field("finansiering", "string", description="Föreslagen finansiering."),
    ]
    draft = _compile_create_steps(
        flow_name="Verksamhetsunderlag",
        steps=[
            NewStepDraft(
                name="Extrahera centrala fakta",
                instructions="Extrahera återanvändbara fält.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=extraction_fields,
            ),
            NewStepDraft(
                name="Skriv nuläge",
                instructions=(
                    "Beskriv nuläge och problem. Dokumentet exporteras till "
                    "DOCX senare."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Skriv lösningsförslag",
                instructions=(
                    "Beskriv lösningsförslag och nyläge. Slutlig granskning "
                    "sker i ett senare steg."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Förbered DOCX-innehåll",
                instructions="Sammanställ slutligt Word-dokument.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    spec = draft

    nulage_question = spec.steps[1].input_bindings["question"]
    solution_question = spec.steps[2].input_bindings["question"]
    final_question = spec.steps[3].input_bindings["question"]
    all_selectors = {
        f"step_a.output.structured.{field.name}" for field in extraction_fields
    }

    assert "step_a.output.structured.nulage" in nulage_question
    assert not all_selectors.issubset(set(nulage_question.split()))
    assert "step_a.output.structured.losningsforslag" in solution_question
    assert not all_selectors.issubset(set(solution_question.split()))
    assert all_selectors.issubset(set(final_question.split()))


def test_compile_create_steps_to_spec_unmatched_section_writer_uses_source_floor() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Verksamhetsunderlag",
        steps=[
            NewStepDraft(
                name="Extrahera centrala fakta",
                instructions="Extrahera återanvändbara fält.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=[
                    _field("syfte", "string", description="Syfte och behov."),
                    _field("tidplan", "string", description="Planerad tidplan."),
                ],
            ),
            NewStepDraft(
                name="Skriv oklar specialrubrik",
                instructions="Skriv ett kort avsnitt utan tydlig koppling.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Skriv ännu en specialrubrik",
                instructions="Skriv ett annat kort avsnitt utan tydlig koppling.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    spec = draft

    first_question = spec.steps[1].input_bindings["question"]
    second_question = spec.steps[2].input_bindings["question"]
    assert "step_a.output.structured.syfte" in first_question
    assert "step_a.output.structured.syfte" in second_question
    assert "step_a.output.structured.tidplan" not in first_question
    assert "step_a.output.structured.tidplan" not in second_question


def test_compile_create_steps_to_spec_underlag_matching_handles_swedish_inflections() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Verksamhetsunderlag",
        steps=[
            NewStepDraft(
                name="Extrahera centrala fakta",
                instructions="Extrahera återanvändbara fält.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=[
                    _field("syfte", "string", description="Syfte och behov."),
                    _field("tidplan", "string", description="Planerad tidplan."),
                    _field(
                        "resursbehov",
                        "string",
                        description="Roller och resursbehov.",
                    ),
                    _field(
                        "losningsforslag",
                        "string",
                        description="Lösningsförslag och nyläge.",
                    ),
                ],
            ),
            NewStepDraft(
                name="Utarbeta tidsplanen",
                instructions="Skriv avsnittet om den planerade tidsplanen.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Beskriv resursbehovet",
                instructions="Beskriv resurserna och resursbehovet.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            NewStepDraft(
                name="Beskriv lösningsförslaget",
                instructions="Beskriv lösningsförslaget och nyläget.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ],
    )

    spec = draft

    timeline_question = spec.steps[1].input_bindings["question"]
    resources_question = spec.steps[2].input_bindings["question"]
    solution_question = spec.steps[3].input_bindings["question"]
    assert "step_a.output.structured.tidplan" in timeline_question
    assert "step_a.output.structured.syfte" not in timeline_question
    assert "step_a.output.structured.resursbehov" in resources_question
    assert "step_a.output.structured.losningsforslag" in solution_question


def test_targeted_underlag_predicate_binds_single_json_prior_with_primary_source_ref() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )
    from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousOutputRef

    source_ref = PreviousOutputRef(from_step=1, label="Källmaterial")
    steps = [
        NewStepDraft(
            name="Transkribera ljud",
            instructions="x",
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera kontext",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("meeting_context", "string")],
        ),
        NewStepDraft(
            name="Skriv analys",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
            uses_previous_outputs=[source_ref],
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=2,
            all_previous_candidate_indexes=set(),
            primary_source_ref=source_ref,
            returns_material_report=True,
            aggregation_intent="linear",
        )
        != "skip"
    )


def test_targeted_underlag_predicate_skips_single_json_prior_without_primary_source_ref() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )

    steps = [
        NewStepDraft(
            name="Extrahera fält",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("payload", "string")],
        ),
        NewStepDraft(
            name="Skriv kommentar",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=1,
            all_previous_candidate_indexes=set(),
            primary_source_ref=None,
            returns_material_report=True,
            aggregation_intent="linear",
        )
        == "skip"
    )


def test_targeted_underlag_predicate_skips_single_json_prior_after_text_step() -> None:
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )
    from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousOutputRef

    source_ref = PreviousOutputRef(from_step=1, label="Källmaterial")
    steps = [
        NewStepDraft(
            name="Transkribera ljud",
            instructions="x",
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera kontext",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("meeting_context", "string")],
        ),
        NewStepDraft(
            name="Skriv mellantext",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
        NewStepDraft(
            name="Skriv slutsats",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("conclusion", "string")],
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=3,
            all_previous_candidate_indexes=set(),
            primary_source_ref=source_ref,
            returns_material_report=True,
            aggregation_intent="linear",
        )
        == "skip"
    )


def test_targeted_underlag_predicate_skips_single_json_prior_non_material_report() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )
    from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousOutputRef

    source_ref = PreviousOutputRef(from_step=1, label="Källmaterial")
    steps = [
        NewStepDraft(
            name="Transkribera ljud",
            instructions="x",
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera kontext",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("meeting_context", "string")],
        ),
        NewStepDraft(
            name="Extrahera beslut",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("decisions", "string")],
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=2,
            all_previous_candidate_indexes=set(),
            primary_source_ref=source_ref,
            returns_material_report=False,
            aggregation_intent="linear",
        )
        == "skip"
    )


def test_targeted_underlag_predicate_binds_two_json_priors_without_source_ref() -> None:
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )

    steps = [
        NewStepDraft(
            name="Extrahera a",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("a", "string")],
        ),
        NewStepDraft(
            name="Extrahera b",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("b", "string")],
        ),
        NewStepDraft(
            name="Skriv rapport",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=2,
            all_previous_candidate_indexes=set(),
            primary_source_ref=None,
            returns_material_report=True,
            aggregation_intent="linear",
        )
        != "skip"
    )


def test_targeted_underlag_predicate_skips_prebound_composer() -> None:
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )
    from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousFieldRef

    steps = [
        NewStepDraft(
            name="Extrahera a",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("a", "string")],
        ),
        NewStepDraft(
            name="Extrahera b",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("b", "string")],
        ),
        NewStepDraft(
            name="Skriv rapport",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
            uses_previous_fields=[
                PreviousFieldRef(from_step=1, field_path="a", label="A")
            ],
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=2,
            all_previous_candidate_indexes={2},
            primary_source_ref=None,
            returns_material_report=True,
            aggregation_intent="linear",
        )
        == "skip"
    )


def test_targeted_underlag_predicate_skips_renderer() -> None:
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )

    steps = [
        NewStepDraft(
            name="Extrahera fält",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("payload", "string")],
        ),
        NewStepDraft(
            name="Skapa DOCX",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="docx",
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=1,
            all_previous_candidate_indexes={1},
            primary_source_ref=None,
            returns_material_report=True,
            aggregation_intent="linear",
        )
        == "skip"
    )


@pytest.mark.parametrize(
    ("intent", "expected_mode"),
    [("aggregate", "with_text_priors"), ("compare", "skip")],
)
def test_targeted_underlag_predicate_handles_aggregation_intents(
    intent: AggregationIntent,
    expected_mode: str,
) -> None:
    from eneo.flows.ai_builder.ai_builder_create_dataflow import (
        _targeted_underlag_binding_mode,
    )

    steps = [
        NewStepDraft(
            name="Extrahera a",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("a", "string")],
        ),
        NewStepDraft(
            name="Extrahera b",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("b", "string")],
        ),
        NewStepDraft(
            name="Skriv rapport",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    assert (
        _targeted_underlag_binding_mode(
            steps=steps,
            composer_index=2,
            all_previous_candidate_indexes={2},
            primary_source_ref=None,
            returns_material_report=True,
            aggregation_intent=intent,
        )
        == expected_mode
    )


def test_auto_bind_is_idempotent_for_all_previous_steps_composer() -> None:
    steps_before = [
        NewStepDraft(
            name="Extrahera a",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("a", "string")],
        ),
        NewStepDraft(
            name="Extrahera b",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("b", "string")],
        ),
        NewStepDraft(
            name="Skriv sammanställning",
            instructions="x",
            input_source="all_previous_steps",
            input_type="json",
            output_type="text",
        ),
    ]

    once = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )
    twice = auto_bind_targeted_underlag_for_text_composer(
        once,
        aggregation_intent="linear",
    )

    assert twice == once


def test_source_material_targeted_underlag_converges_between_outline_and_direct_draft() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötesrapport från ljud",
            "plan_rationale": "Transkribera ljud och skapa rapport.",
            "steps": [
                {
                    "name": "Etablera möteskontext",
                    "instructions": "Skapa möteskontext.",
                    "output_fields": [
                        {
                            "name": "meeting_context",
                            "field_type": "string",
                            "description": "Möteskontext.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Analysera beslut",
                    "instructions": "Extrahera beslut.",
                    "output_fields": [
                        {
                            "name": "decisions",
                            "field_type": "string",
                            "description": "Beslut.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten från underlaget.",
                },
            ],
        }
    )
    outline_compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            ui_language="sv",
        ),
    )
    direct_compiled = _compile_create_steps(
        flow_name="Mötesrapport från ljud",
        steps=[
            NewStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera mötesljud.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_required=True,
            ),
            NewStepDraft(
                name="Etablera möteskontext",
                instructions="Skapa möteskontext.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("meeting_context", "string")],
            ),
            NewStepDraft(
                name="Analysera beslut",
                instructions="Extrahera beslut.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("decisions", "string")],
            ),
            NewStepDraft(
                name="Skriv rapport",
                instructions="Skriv rapporten från underlaget.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
        ],
    )

    outline_question = outline_compiled.steps[-1].input_bindings["question"]
    direct_question = direct_compiled.steps[-1].input_bindings["question"]

    assert "Källmaterial: {{ step_a.output.text }}" in outline_question
    assert "Källmaterial: {{ step_a.output.text }}" in direct_question
    assert "output.structured." in outline_question
    assert "output.structured." in direct_question
    assert "{{ step_b.output.structured }}" not in outline_question
    assert "{{ step_c.output.structured }}" not in outline_question
    assert "{{ step_b.output.structured }}" not in direct_question
    assert "{{ step_c.output.structured }}" not in direct_question


def test_non_material_report_multi_json_keeps_json_input_when_source_prior_bound() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="JSON-analys från ljud",
        steps=[
            NewStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera ljudet.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
            ),
            NewStepDraft(
                name="Extrahera kontext",
                instructions="Extrahera kontext.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("context", "string")],
            ),
            NewStepDraft(
                name="Extrahera beslut",
                instructions="Extrahera beslut.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("decisions", "string")],
            ),
            NewStepDraft(
                name="Skapa slutlig JSON",
                instructions="Skapa slutlig strukturerad analys.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("summary", "string")],
            ),
        ],
    )

    compiled = draft

    composer = compiled.steps[3]
    assert composer.input_type == InputType.JSON
    assert composer.input_contract is None
    assert composer.input_bindings == {
        "question": (
            "Beskrivning: {{ step_b.output.structured.context }}\n\n"
            "Beskrivning: {{ step_c.output.structured.decisions }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        )
    }


def test_normalize_create_step_mechanics_is_idempotent_for_targeted_underlag() -> None:
    ordinary = [
        NewStepDraft(
            name="Sammanfatta",
            instructions="Sammanfatta texten.",
            input_source="flow_input",
            input_type="text",
            output_type="text",
        )
    ]
    multi_json = [
        NewStepDraft(
            name="Extrahera a",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("a", "string")],
        ),
        NewStepDraft(
            name="Extrahera b",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("b", "string")],
        ),
        NewStepDraft(
            name="Skriv rapport",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]
    source_report = [
        NewStepDraft(
            name="Transkribera mötesljud",
            instructions="Transkribera mötesljudet.",
            input_source="flow_input",
            input_type="audio",
            output_type="text",
        ),
        NewStepDraft(
            name="Extrahera möteskontext",
            instructions="Extrahera kontext.",
            input_source="previous_step",
            input_type="text",
            output_type="json",
            output_fields=[_field("meeting_context", "string")],
        ),
        NewStepDraft(
            name="Skriv rapport",
            instructions="Skriv rapport.",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    for flow_name, steps in (
        ("Enkel sammanfattning", ordinary),
        ("Flera fält", multi_json),
        ("Mötesrapport från ljud", source_report),
    ):
        once = _normalize_create_steps(flow_name=flow_name, steps=steps)
        twice = _normalize_create_steps(flow_name=flow_name, steps=once)
        assert twice == once


def test_compile_outline_audio_docx_protocol_step_keeps_transcript_underlag() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötesprotokoll från ljud till Word",
            "plan_rationale": "Transkribera ljud och skapa DOCX-protokoll.",
            "steps": [
                {
                    "name": "Strukturera transkription",
                    "instructions": "Strukturera den redan transkriberade texten.",
                    "output_fields": [
                        {
                            "name": "transcription_text",
                            "field_type": "string",
                            "description": "Fullständig transkription.",
                            "required": True,
                        },
                        {
                            "name": "speaker_turns",
                            "field_type": "array",
                            "description": "Talarsegment i ordning.",
                            "required": False,
                            "item_fields": [
                                {
                                    "name": "segment_text",
                                    "field_type": "string",
                                    "description": "Text för segmentet.",
                                    "required": True,
                                }
                            ],
                        },
                    ],
                },
                {
                    "name": "Identifiera mötesmetadata",
                    "instructions": "Identifiera titel, organisation och sekreterare.",
                    "output_fields": [
                        {
                            "name": "meeting_title",
                            "field_type": "string",
                            "description": "Mötestitel.",
                            "required": True,
                        },
                        {
                            "name": "organization_name",
                            "field_type": "string",
                            "description": "Organisation.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Skapa mötesprotokoll med fasta rubriker",
                    "instructions": "Skapa protokollsektioner från metadata och transkription.",
                    "output_fields": [
                        {
                            "name": "protocol_sections",
                            "field_type": "object",
                            "description": "Innehåll per rubrik.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "Sammanfattning",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                    "required": True,
                                },
                                {
                                    "name": "Diskussion",
                                    "field_type": "string",
                                    "description": "Diskussion.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Förbered DOCX-innehåll",
                    "instructions": "Skriv dokumentets fullständiga text från tidigare steg.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state, ui_language="sv"),
    )
    compiled = draft
    validation = validate_spec(compiled)

    metadata_step = compiled.steps[2]
    assert metadata_step.input_type.value == "text"
    assert compiled.steps[2].input_bindings is not None
    metadata_question = compiled.steps[2].input_bindings["question"]
    assert (
        "Fullständig transkription.: "
        "{{ step_b.output.structured.transcription_text }}" in metadata_question
    )
    assert (
        "Talarsegment i ordning.: {{ step_b.output.structured.speaker_turns }}"
        in metadata_question
    )
    assert "Källmaterial: {{ step_a.output.text }}" in metadata_question
    assert "{{ step_b.output.structured }}" not in metadata_question

    body_step = compiled.steps[4]
    assert body_step.name == "Förbered DOCX-innehåll"
    assert body_step.input_source.value == "previous_step"
    assert body_step.input_type.value == "text"

    compiled_body_step = compiled.steps[4]
    assert compiled_body_step.input_bindings is not None
    protocol_question = compiled_body_step.input_bindings["question"]
    assert (
        "Fullständig transkription.: {{ step_b.output.structured.transcription_text }}"
        in protocol_question
    )
    assert (
        "Mötestitel.: {{ step_c.output.structured.meeting_title }}" in protocol_question
    )
    assert (
        "Innehåll per rubrik.: {{ step_d.output.structured.protocol_sections }}"
        in protocol_question
    )
    assert "Källmaterial: {{ step_a.output.text }}" in protocol_question
    assert "{{ step_d.output.structured }}" not in protocol_question
    assert validation.valid
    assert_create_spec_prepares_through_authoring_command(compiled)


def test_compile_create_steps_to_spec_direct_audio_docx_bad_shape_gets_source_underlag() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Mötesprotokoll från ljud till Word",
        steps=[
            NewStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera uppladdat ljud.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_required=True,
            ),
            NewStepDraft(
                name="Strukturera transkription",
                instructions="Strukturera transkriptionen.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("transcription_text", "string")],
            ),
            NewStepDraft(
                name="Identifiera mötesmetadata",
                instructions="Identifiera mötestitel.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("meeting_title", "string")],
            ),
            NewStepDraft(
                name="Skapa mötesprotokoll med fasta rubriker",
                instructions="Skapa protokollsektioner från metadata och transkription.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("protocol_sections", "string")],
            ),
            NewStepDraft(
                name="Skapa DOCX",
                instructions="Skapa slutdokumentet.",
                input_source="previous_step",
                input_type="json",
                output_type="docx",
                document_delivery_mode="generated",
            ),
        ],
    )

    compiled = draft
    normalized_compiled, _changes = normalize_ai_builder_spec(
        compiled,
        terminal_output_type=OutputType.DOCX,
    )

    metadata_question = compiled.steps[2].input_bindings["question"]
    protocol_question = compiled.steps[3].input_bindings["question"]
    docx_question = normalized_compiled.steps[4].input_bindings["question"]
    assert compiled.steps[2].input_type.value == "text"
    assert compiled.steps[2].input_contract is None
    assert compiled.steps[3].input_type.value == "text"
    assert compiled.steps[3].input_contract is None
    assert normalized_compiled.steps[4].input_type.value == "text"
    assert normalized_compiled.steps[4].input_contract is None
    assert metadata_question == (
        "Beskrivning: {{ step_b.output.structured.transcription_text }}\n\n"
        "Källmaterial: {{ step_a.output.text }}"
    )
    assert "{{ step_b.output.structured }}" not in metadata_question
    assert protocol_question == (
        "Beskrivning: {{ step_b.output.structured.transcription_text }}\n\n"
        "Beskrivning: {{ step_c.output.structured.meeting_title }}\n\n"
        "Källmaterial: {{ step_a.output.text }}"
    )
    assert docx_question == (
        "{{ step_d.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )
    assert validate_spec(compiled).valid


def test_compile_create_steps_to_spec_audio_report_section_extractors_keep_transcript_underlag() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Mötesrapport från ljud",
        steps=[
            NewStepDraft(
                name="Transkribera mötesljud",
                instructions="Transkribera mötesljudet till svensk text.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_required=True,
            ),
            NewStepDraft(
                name="Etablera möteskontext",
                instructions="Skapa möteskontext baserat på transkriberingen.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("meeting_context", "string")],
            ),
            NewStepDraft(
                name="Analysera bakgrund",
                instructions="Läs hela transkriberingen och extrahera bakgrund.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("background_notes", "string")],
            ),
            NewStepDraft(
                name="Analysera genomgång och diskussion",
                instructions=(
                    "Läs hela transkriberingen och extrahera diskussionsunderlag."
                ),
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("discussion_notes", "string")],
            ),
            NewStepDraft(
                name="Skriv fullständig mötesrapport",
                instructions="Skriv rapporten från möteskontext och alla underlag.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("report_text", "string")],
            ),
            NewStepDraft(
                name="Skapa DOCX",
                instructions="Skapa slutdokumentet.",
                input_source="previous_step",
                input_type="json",
                output_type="docx",
                document_delivery_mode="generated",
            ),
        ],
    )

    compiled = draft
    normalized_compiled, _changes = normalize_ai_builder_spec(
        compiled,
        terminal_output_type=OutputType.DOCX,
    )

    for step_index in (2, 3, 4):
        step = compiled.steps[step_index]
        assert step.input_type.value == "text"
        assert step.input_contract is None
        assert step.input_bindings is not None
        question = step.input_bindings["question"]
        assert "Källmaterial: {{ step_a.output.text }}" in question
    terminal_step = normalized_compiled.steps[5]
    assert terminal_step.input_type.value == "text"
    assert terminal_step.input_contract is None
    assert terminal_step.input_bindings is not None
    assert (
        "Källmaterial: {{ step_a.output.text }}"
        in terminal_step.input_bindings["question"]
    )
    assert (
        "Beskrivning: {{ step_b.output.structured.meeting_context }}"
        in compiled.steps[2].input_bindings["question"]
    )
    assert (
        "{{ step_b.output.structured }}"
        not in compiled.steps[2].input_bindings["question"]
    )
    assert (
        "Beskrivning: {{ step_c.output.structured.background_notes }}"
        in compiled.steps[3].input_bindings["question"]
    )
    assert (
        "{{ step_c.output.structured }}"
        not in compiled.steps[3].input_bindings["question"]
    )
    assert (
        "Beskrivning: {{ step_d.output.structured.discussion_notes }}"
        in compiled.steps[4].input_bindings["question"]
    )
    assert "{{ step_e.output.structured }}" in terminal_step.input_bindings["question"]
    assert validate_spec(compiled).valid


def test_compile_create_steps_to_spec_text_report_keeps_source_and_structured_underlag() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Mötesrapport från ljud",
        steps=[
            NewStepDraft(
                name="Transkribera mötesljud",
                instructions="Transkribera mötesljudet till svensk text.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_required=True,
            ),
            NewStepDraft(
                name="Etablera möteskontext",
                instructions="Skapa möteskontext baserat på transkriberingen.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("meeting_context", "string")],
            ),
            NewStepDraft(
                name="Analysera beslut",
                instructions="Extrahera beslut från mötet.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("decisions", "string")],
            ),
            NewStepDraft(
                name="Skriv rapport",
                instructions="Skriv en textbaserad rapport från underlaget.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
        ],
    )

    compiled = draft

    analysis_step = compiled.steps[2]
    report_step = compiled.steps[3]
    assert analysis_step.input_type.value == "text"
    assert analysis_step.input_contract is None
    assert analysis_step.input_bindings == {
        "question": (
            "Beskrivning: {{ step_b.output.structured.meeting_context }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        )
    }
    assert report_step.input_type.value == "text"
    assert report_step.input_contract is None
    assert report_step.input_bindings is not None
    report_question = report_step.input_bindings["question"]
    assert (
        "Beskrivning: {{ step_b.output.structured.meeting_context }}" in report_question
    )
    assert "Beskrivning: {{ step_c.output.structured.decisions }}" in report_question
    assert "Källmaterial: {{ step_a.output.text }}" in report_question
    assert "{{ step_b.output.structured }}" not in report_question
    assert "{{ step_c.output.structured }}" not in report_question
    assert validate_spec(compiled).valid


def test_compile_outline_audio_pdf_protocol_step_auto_authors_targeted_underlag() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötesprotokoll från ljud till PDF",
            "plan_rationale": "Transkribera ljud och skapa PDF-protokoll.",
            "steps": [
                {
                    "name": "Strukturera transkription",
                    "instructions": "Strukturera den redan transkriberade texten.",
                    "output_fields": [
                        {
                            "name": "transcription_text",
                            "field_type": "string",
                            "description": "Fullständig transkription.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Identifiera mötesmetadata",
                    "instructions": "Identifiera titel, organisation och sekreterare.",
                    "output_fields": [
                        {
                            "name": "meeting_title",
                            "field_type": "string",
                            "description": "Mötestitel.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Skapa mötesprotokoll med fasta rubriker",
                    "instructions": "Skapa protokollsektioner från metadata och transkription.",
                    "output_fields": [
                        {
                            "name": "protocol_sections",
                            "field_type": "object",
                            "description": "Innehåll per rubrik.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "Sammanfattning",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state, ui_language="sv"),
    )
    compiled = draft
    validation = validate_spec(compiled)

    protocol_step = compiled.steps[3]
    assert protocol_step.input_source.value == "previous_step"
    assert protocol_step.input_type.value == "text"
    assert protocol_step.output_type.value == "text"
    assert compiled.steps[3].input_bindings is not None
    protocol_question = compiled.steps[3].input_bindings["question"]
    assert "transcription_text" in protocol_question
    assert "meeting_title" in protocol_question
    assert validation.valid


@pytest.mark.parametrize("final_output_type", ["docx", "pdf"])
def test_compile_outline_audio_document_without_pattern_still_creates_transcript_source(
    final_output_type: str,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötesrapport från ljud",
            "plan_rationale": "Analysera transkriberat ljud och skapa rapport.",
            "steps": [
                {
                    "name": "Etablera gemensam möteskontext",
                    "instructions": "Läs hela den transkriberade mötestexten.",
                    "output_fields": [
                        {
                            "name": "meeting_context",
                            "field_type": "object",
                            "description": "Gemensam möteskontext.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "meeting_type",
                                    "field_type": "string",
                                    "description": "Mötestyp.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Analysera bakgrund",
                    "instructions": "Analysera hela transkriberingen med fokus på bakgrund.",
                    "output_fields": [
                        {
                            "name": "background_points",
                            "field_type": "array",
                            "description": "Bakgrundspunkter.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "point",
                                    "field_type": "string",
                                    "description": "Bakgrundspunkt.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Skriv strukturerad mötesrapport",
                    "instructions": (
                        "Skriv en fullständig strukturerad mötesrapport på svenska "
                        "utifrån allt ackumulerat analysunderlag."
                    ),
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType(final_output_type),
            ui_language="sv",
        ),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [
        (step.input_source.value, step.input_type.value, step.output_type.value)
        for step in compiled.steps
    ] == [
        ("flow_input", "audio", "text"),
        ("previous_step", "text", "json"),
        ("previous_step", "text", "json"),
        ("previous_step", "text", "text"),
        ("previous_step", "text", final_output_type),
    ]
    assert [step.name for step in draft.steps[:4]] == [
        "Transkribera ljud",
        "Etablera gemensam möteskontext",
        "Analysera bakgrund",
        "Skriv strukturerad mötesrapport",
    ]
    assert compiled.steps[0].output_mode == OutputMode.TRANSCRIBE_ONLY
    assert not any(
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type == InputType.AUDIO
        and step.output_type == OutputType.JSON
        for step in compiled.steps
    )
    assert compiled.steps[2].input_bindings == {
        "question": (
            "Gemensam möteskontext.: "
            "{{ step_b.output.structured.meeting_context }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        )
    }
    assert compiled.steps[3].input_source == InputSource.PREVIOUS_STEP
    assert compiled.steps[3].input_bindings is not None
    body_question = compiled.steps[3].input_bindings["question"]
    assert "meeting_context" in body_question
    assert "background_points" in body_question
    assert compiled.steps[4].input_source == InputSource.PREVIOUS_STEP
    assert validation.valid


def test_compile_outline_audio_document_json_hint_keeps_transcript_source() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötesrapport från ljud",
            "plan_rationale": "Transkribera ljud och skapa rapport.",
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "instructions": "Transkribera uppladdat mötesljud till text.",
                    "output_type": "json",
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv en rapport från transkriberingen.",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.PDF,
            ui_language="sv",
        ),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert compiled.steps[0].input_source == InputSource.FLOW_INPUT
    assert compiled.steps[0].input_type == InputType.AUDIO
    assert compiled.steps[0].output_type == OutputType.TEXT
    assert compiled.steps[0].output_mode == OutputMode.TRANSCRIBE_ONLY
    assert not any(
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type == InputType.AUDIO
        and step.output_type == OutputType.JSON
        for step in compiled.steps
    )
    assert compiled.steps[2].input_bindings == {
        "question": (
            "Important source facts extracted from the input material.: "
            "{{ step_b.output.structured.source_facts }}\n\n"
            "Källmaterial: {{ step_a.output.text }}"
        )
    }
    assert validation.valid


def test_compile_outline_wraps_skeleton_materialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Broken skeleton",
            "plan_rationale": "Compile a broken skeleton.",
            "steps": [{"name": "Analyze", "instructions": "Analyze the input."}],
        }
    )

    def _raise_value_error(**_kwargs: object) -> None:
        raise ValueError("invalid skeleton tuple")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        _raise_value_error,
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(outline)

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.detail == "invalid skeleton tuple"
    assert exc_info.value.log_context["runtime_input_type"] == "text"
    assert exc_info.value.log_context["final_output_type"] == "text"
    assert exc_info.value.log_context["semantic_step_count"] == 1


def test_compile_outline_flow_audio_artifact_aggregate_keeps_synthesis_before_terminal() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Aggregate audio report",
            "plan_rationale": "Aggregate several analyses into one PDF.",
            "steps": [
                {"name": "Extract themes", "instructions": "Extract main themes."},
                {
                    "name": "Assess risks",
                    "instructions": "Assess risks in the recording.",
                },
                {"name": "Synthesize", "instructions": "Synthesize all prior work."},
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
            aggregation_intent="aggregate",
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Extract themes",
        "Assess risks",
        "Synthesize",
        "Create PDF",
    ]
    assert draft.steps[-2].input_source.value == "previous_step"
    assert draft.steps[-2].input_type.value == "text"
    assert draft.steps[-1].input_source.value == "previous_step"
    assert draft.steps[-1].input_type.value == "text"
    assert compiled.steps[-1].input_bindings is None
    assert validation.valid


def test_compile_outline_flow_keeps_text_artifact_step_after_audio_transcription() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio text report",
            "plan_rationale": "Create a readable report from uploaded audio.",
            "steps": [
                {
                    "name": "Write report",
                    "instructions": "Write a concise report from the transcribed audio.",
                    "output_type": "text",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Write report",
    ]
    assert draft.steps[0].input_type.value == "audio"
    assert draft.steps[1].input_source.value == "previous_step"
    assert compiled.steps[0].input_config["runtime_input"]["input_format"] == "audio"
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert compiled.steps[1].output_mode.value == "pass_through"
    assert validation.valid


def test_outline_compile_context_reads_pattern_chain_from_architecture_commit() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.pattern_ids == ("audio_to_artifact_report",)
    assert context.pattern_chain_steps == (
        FLOW_INPUT_AUDIO_TRANSCRIPTION,
        TERMINAL_ARTIFACT_STEP,
    )


def test_outline_compile_context_preserves_compiled_chain_and_semantic_patterns() -> (
    None
):
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[
                "multi_step_quality_chain",
                "form_field_runtime_inputs",
            ],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert set(context.pattern_ids) == {
        "form_field_runtime_inputs",
        "multi_step_quality_chain",
    }
    assert STRUCTURED_EXTRACTION_STEP in context.pattern_chain_steps
    assert TERMINAL_ARTIFACT_STEP in context.pattern_chain_steps


def test_compile_outline_flow_realizes_docx_template_chain_from_pattern() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from uploaded material.",
            "steps": [
                {
                    "name": "Prepare report content",
                    "instructions": "Prepare the content that should be placed in the template.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Prepare report content",
        "Fill DOCX template",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "json",
        "text",
        "docx",
    ]
    assert draft.steps[2].output_mode == OutputMode.TEMPLATE_FILL
    assert compiled.steps[0].input_config["runtime_input"]["input_format"] == "document"
    assert compiled.steps[2].output_mode.value == "template_fill"
    assert validation.valid
    assert_create_spec_prepares_through_authoring_command(compiled)


def test_compile_outline_flow_docx_chain_preserves_all_semantic_steps() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from uploaded material.",
            "steps": [
                {
                    "name": "Extract findings",
                    "instructions": "Extract the findings that matter for the report.",
                },
                {
                    "name": "Write narrative",
                    "instructions": "Write the narrative content for the template.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Extract findings",
        "Write narrative",
        "Fill DOCX template",
    ]
    assert compiled.steps[-1].output_mode.value == "template_fill"
    assert validation.valid


def test_compile_outline_template_fill_places_fan_in_on_synthesis_step() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template comparison report",
            "plan_rationale": "Compare uploaded material before filling the template.",
            "steps": [
                {
                    "name": "Extract findings",
                    "instructions": "Extract findings from the uploaded material.",
                },
                {
                    "name": "Write synthesis",
                    "instructions": "Compare all prior work and write the report narrative.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
            aggregation_intent="compare",
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Extract findings",
        "Write synthesis",
        "Fill DOCX template",
    ]
    assert draft.steps[-2].input_source.value == "all_previous_steps"
    assert compiled.steps[-2].input_bindings is None
    assert draft.steps[-1].input_source.value == "previous_step"
    assert draft.steps[-1].output_mode == OutputMode.TEMPLATE_FILL
    assert validation.valid
    assert_create_spec_prepares_through_authoring_command(compiled)


def test_compile_outline_flow_docx_chain_still_wraps_rich_template_outline() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from several phases.",
            "steps": [
                {
                    "name": f"Prepare section {index}",
                    "instructions": f"Prepare section {index} for the template.",
                }
                for index in range(1, 6)
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Prepare section 1",
        "Prepare section 2",
        "Prepare section 3",
        "Prepare section 4",
        "Prepare section 5",
        "Fill DOCX template",
    ]
    assert compiled.steps[-1].output_mode.value == "template_fill"
    assert validation.valid


def test_compile_outline_flow_uses_committed_template_fill_mode_without_pattern() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from uploaded material.",
            "steps": [
                {
                    "name": "Prepare report",
                    "instructions": "Prepare the report content for the template.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=[],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    context = create_compile_context_from_planning_state(state)
    draft = compile_create_intent_to_spec(outline, context=context)
    compiled = draft
    validation = validate_spec(compiled)

    assert context is not None
    assert context.final_output_mode is not None
    assert context.final_output_mode.value == "template_fill"
    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Prepare report",
        "Fill DOCX template",
    ]
    assert draft.steps[-1].output_mode == OutputMode.TEMPLATE_FILL
    assert compiled.steps[-1].output_mode.value == "template_fill"
    assert validation.valid


def test_compile_outline_flow_realizes_structured_quality_chain_from_pattern() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured report",
            "plan_rationale": "Analyze uploaded material and produce a final PDF.",
            "steps": [
                {
                    "name": "Analyze material",
                    "instructions": "Analyze the uploaded material and produce the requested report.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract structured foundation",
        "Analyze material",
        "Review and finalize",
        "Create PDF",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "json",
        "text",
        "text",
        "pdf",
    ]
    assert draft.steps[0].output_contract is not None
    assert compiled.steps[0].input_config["runtime_input"]["input_format"] == "document"
    assert compiled.steps[1].input_type.value == "json"
    assert compiled.steps[3].output_type.value == "pdf"
    assert validation.valid
    assert_create_spec_prepares_through_authoring_command(compiled)


def test_compile_outline_flow_structured_quality_text_terminal_uses_reviewed_output() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Jämför dokument",
            "plan_rationale": "Extrahera fakta, identifiera motsägelser och skriv svar.",
            "steps": [
                {
                    "name": "Identifiera motsägelser",
                    "instructions": "Identifiera motsägelser mellan källorna.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
            aggregation_intent="compare",
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(
            state,
            ui_language="sv",
        ),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extrahera strukturerad grund",
        "Identifiera motsägelser",
        "Granska och färdigställ",
        "Skapa slutresultat",
    ]
    assert draft.steps[-1].input_source == InputSource.PREVIOUS_STEP
    assert compiled.steps[-1].input_source == InputSource.PREVIOUS_STEP
    assert validation.valid


def test_compile_outline_flow_localizes_server_owned_final_step_name() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Riskanalys",
            "plan_rationale": "Analysera uppladdade dokument.",
            "steps": [
                {
                    "name": "Analysera innehåll",
                    "instructions": "Identifiera risker och beslutspunkter.",
                    "output_type": "json",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(
            state,
            ui_language="sv",
        ),
    )

    assert draft.steps[-1].name == "Skapa slutresultat"
    assert draft.steps[-1].assistant_spec.instructions.startswith(
        "Skapa slutresultatet"
    )


def test_compile_outline_flow_quality_chain_preserves_all_semantic_steps() -> None:
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured report",
            "plan_rationale": "Analyze uploaded material and produce a final PDF.",
            "steps": [
                {
                    "name": "Analyze material",
                    "instructions": "Analyze the uploaded material.",
                },
                {
                    "name": "Draft report",
                    "instructions": "Draft the report from the analysis.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract structured foundation",
        "Analyze material",
        "Draft report",
        "Review and finalize",
        "Create PDF",
    ]
    assert compiled.document_body_writer_step_refs == ("step_d",)
    assert compiled.steps[-1].output_type.value == "pdf"
    assert validation.valid

    context = CriticContext(
        spec=compiled,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(terminal_output="pdf_document"),
        mixed_audio_doc_input=False,
        requested_output_sections=RequestedOutputSections.empty(),
    )
    issue_ids = {issue.id for issue in evaluate_critic_invariants(context)}
    assert "terminal_renderer_must_not_consume_review_only_step" not in issue_ids


def test_compile_outline_flow_quality_chain_wraps_rich_outline_from_pattern() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Detailed report",
            "plan_rationale": "The model already supplied a detailed semantic plan.",
            "steps": [
                {
                    "name": f"Phase {index}",
                    "instructions": f"Perform analysis phase {index}.",
                }
                for index in range(1, 5)
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract structured foundation",
        "Phase 1",
        "Phase 2",
        "Phase 3",
        "Phase 4",
        "Review and finalize",
        "Create PDF",
    ]
    assert draft.steps[-1].output_type.value == "pdf"
    assert compiled.steps[-1].output_type.value == "pdf"
    assert validation.valid


def test_compile_outline_flow_treats_output_fields_as_structured_signal() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured extraction",
            "plan_rationale": "Extract fields, then summarize.",
            "steps": [
                {
                    "name": "Extract fields",
                    "instructions": "Extract stable facts.",
                    "output_type": "text",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Concise summary.",
                            "required": True,
                        }
                    ],
                },
                {"name": "Write summary", "instructions": "Write the final summary."},
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft

    assert draft.steps[0].output_type.value == "json"
    assert draft.steps[0].output_contract is not None
    assert compiled.steps[1].input_type.value == "json"
    assert compiled.steps[1].input_contract == compiled.steps[0].output_contract


def test_compile_outline_flow_preserves_requested_json_intermediate() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured intermediate",
            "plan_rationale": "Create an intermediate JSON result before prose.",
            "steps": [
                {
                    "name": "Build structure",
                    "instructions": "Create structured intermediate data.",
                    "output_type": "json",
                },
                {"name": "Write answer", "instructions": "Write the final answer."},
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    assert draft.steps[0].output_type.value == "json"
    assert draft.steps[1].input_type.value == "json"
    assert compiled.steps[1].input_bindings is None
    assert validation.valid


def test_compile_create_steps_to_spec_bridges_structured_previous_output_into_text_input() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Structured bridge",
        steps=[
            NewStepDraft(
                name="Extract fields",
                instructions="Extract stable fields.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[_field("summary", "string")],
            ),
            NewStepDraft(
                name="Write body",
                instructions="Write the document body from the structured fields.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
            ),
        ],
    )

    compiled = draft

    assert compiled.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}"
    }


def test_compile_create_steps_to_spec_prefers_specific_previous_fields_for_text_input() -> (
    None
):
    draft = _compile_create_steps(
        flow_name="Structured bridge",
        steps=[
            NewStepDraft(
                name="Extract fields",
                instructions="Extract stable fields.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field("summary", "string"),
                    _field("details", "string"),
                ],
            ),
            NewStepDraft(
                name="Write body",
                instructions="Write the document body from selected fields.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "summary",
                        "label": "Summary",
                    }
                ],
            ),
        ],
    )

    compiled = draft

    assert compiled.steps[1].input_bindings == {
        "question": "Summary: {{ step_a.output.structured.summary }}"
    }


def test_compile_outline_flow_logs_semantic_output_type_drift(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "DOCX report",
            "plan_rationale": "Backend owns the artifact output.",
            "steps": [
                {
                    "name": "Write report",
                    "instructions": "Write report content.",
                    "output_type": "pdf",
                }
            ],
        }
    )

    with caplog.at_level(
        logging.INFO,
        logger=CREATE_COMPILER_LOGGER,
    ):
        draft = compile_create_intent_to_spec(
            outline,
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                final_output_type=OutputType.DOCX,
            ),
        )
    drift_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_skeleton_semantic_output_type_drift"
    ]

    assert [step.output_type.value for step in draft.steps] == ["text", "docx"]
    assert len(drift_records) == 1
    assert getattr(drift_records[0], "slot_id") == "final_response"
    assert getattr(drift_records[0], "slot_ordinal") == 0
    assert getattr(drift_records[0], "requested_output_type") == "pdf"
    assert getattr(drift_records[0], "enforced_output_type") == "text"


def test_compile_outline_flow_default_outline_stays_linear() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Synthesis",
            "plan_rationale": "Analyze two branches and synthesize.",
            "steps": [
                {"name": "Branch A", "instructions": "Analyze from angle A."},
                {"name": "Branch B", "instructions": "Analyze from angle B."},
                {
                    "name": "Synthesize",
                    "instructions": "Synthesize all earlier work.",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.input_source.value for step in draft.steps] == [
        "flow_input",
        "previous_step",
        "previous_step",
    ]
    assert [step.input_source.value for step in compiled.steps] == [
        "flow_input",
        "previous_step",
        "previous_step",
    ]
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )


def test_compile_outline_flow_preserves_step_mcp_refs() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "MCP-flöde",
            "plan_rationale": "Hämtar extern ärendedata innan analys.",
            "steps": [
                {
                    "name": "Hämta ärendedata",
                    "instructions": "Hämta aktuell status från ärendesystemet.",
                    "mcp_tool_refs": ["case_lookup_tool"],
                },
                {
                    "name": "Sammanfatta",
                    "instructions": "Sammanfatta statusen för användaren.",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)

    assert draft.steps[0].assistant_spec.mcp_tool_refs == ["case_lookup_tool"]
    assert draft.steps[0].assistant_spec.mcp_server_refs == []


def test_compile_outline_flow_does_not_fold_mcp_entry_step() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "MCP-flöde",
            "plan_rationale": "Hämtar externt underlag och skriver svar.",
            "steps": [
                {
                    "name": "Hämta underlag",
                    "instructions": "Använd MCP-verktyget för att hämta underlag.",
                    "mcp_tool_refs": ["lookup_tool"],
                },
                {
                    "name": "Skriv svar",
                    "instructions": "Skriv ett tydligt svar.",
                },
            ],
        }
    )

    draft = compile_create_intent_to_spec(outline)

    assert [step.name for step in draft.steps] == ["Hämta underlag", "Skriv svar"]
    assert draft.steps[0].assistant_spec.mcp_tool_refs == ["lookup_tool"]


def test_compile_outline_flow_comparison_pattern_owns_final_fan_in() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Comparison",
            "plan_rationale": "Analyze branches, then compare.",
            "steps": [
                {"name": "Extract source facts", "instructions": "Extract facts."},
                {"name": "Assess differences", "instructions": "Assess differences."},
                {"name": "Compare and conclude", "instructions": "Compare all work."},
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["comparison"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.input_source.value for step in draft.steps] == [
        "flow_input",
        "previous_step",
        "all_previous_steps",
    ]
    assert compiled.steps[2].input_bindings is None
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )


def test_compile_outline_flow_multiple_document_scope_owns_one_fan_in() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Multi-document report",
            "plan_rationale": "Extract facts, analyze them, and write a report.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract structured facts from the uploaded material.",
                    "output_type": "json",
                    "output_fields": [{"name": "facts", "field_type": "array"}],
                },
                {
                    "name": "Analyze differences",
                    "instructions": "Analyze the extracted facts and highlight differences.",
                    "output_type": "json",
                    "output_fields": [{"name": "differences", "field_type": "array"}],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the final report.",
                    "output_type": "docx",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="documents",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="docx_document",
            source="structured_answer",
            confidence="high",
        ),
        "document_material_scope": ResolvedSlot(
            name="document_material_scope",
            value="multiple_documents_case",
            source="heuristic",
            confidence="high",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.input_source.value for step in draft.steps] == [
        "flow_input",
        "previous_step",
        "all_previous_steps",
    ]
    assert draft.steps[2].input_type.value == "text"
    assert compiled.steps[2].input_bindings is None
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )


def test_compile_context_ignores_medium_comparison_scope_after_linear_commit() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Weak comparison evidence",
            "plan_rationale": "Analyze uploaded material.",
            "steps": [
                {"name": "Extract source facts", "instructions": "Extract facts."},
                {"name": "Assess findings", "instructions": "Assess findings."},
                {"name": "Write conclusion", "instructions": "Write conclusion."},
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["document_to_structured_report"],
            required_capabilities=["input_document", "output_mode_pass_through"],
            aggregation_intent="linear",
        )
    )
    state.resolved_slots["comparison_scope"] = ResolvedSlot(
        name="comparison_scope",
        value="same_run_compare",
        source="model",
        confidence="medium",
    )

    context = create_compile_context_from_planning_state(state)
    draft = compile_create_intent_to_spec(outline, context=context)

    assert context is not None
    assert context.aggregation_intent == "linear"
    assert "all_previous_steps" not in {step.input_source.value for step in draft.steps}


def test_compile_context_trusts_high_model_comparison_scope_after_linear_commit() -> (
    None
):
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["document_to_structured_report"],
            required_capabilities=["input_document", "output_mode_pass_through"],
            aggregation_intent="linear",
        )
    )
    state.resolved_slots["comparison_scope"] = ResolvedSlot(
        name="comparison_scope",
        value="same_run_compare",
        source="model",
        confidence="high",
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.aggregation_intent == "compare"


def test_compile_outline_flow_audio_docx_ignores_document_scope_fan_in() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Summarize recording",
                    "instructions": "Summarize the transcribed audio for a final document.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="docx_document",
            source="structured_answer",
            confidence="high",
        ),
        "document_material_scope": ResolvedSlot(
            name="document_material_scope",
            value="multiple_documents_case",
            source="heuristic",
            confidence="medium",
        ),
    }

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert [step.input_source.value for step in draft.steps] == [
        "flow_input",
        "previous_step",
        "previous_step",
    ]
    assert compiled.steps[-1].output_type == OutputType.DOCX
    assert validation.valid


def test_compile_outline_flow_all_previous_with_form_fields_avoids_relisting_sources() -> (
    None
):
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Comparison with metadata",
            "plan_rationale": "Compare all prior work with runtime metadata.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {"name": "Extract source facts", "instructions": "Extract facts."},
                {"name": "Assess differences", "instructions": "Assess differences."},
                {
                    "name": "Compare",
                    "instructions": "Compare all work.",
                    "uses_form_fields": ["audience"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["comparison"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_create_intent_to_spec(
        outline,
        context=create_compile_context_from_planning_state(state),
    )
    compiled = draft
    validation = validate_spec(compiled)

    assert draft.steps[2].input_source.value == "all_previous_steps"
    assert compiled.steps[2].input_bindings is None
    assert (
        "audience: {{ flow_input.audience }}"
        in compiled.steps[2].assistant_spec.instructions
    )
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )
    assert_create_spec_prepares_through_authoring_command(compiled)

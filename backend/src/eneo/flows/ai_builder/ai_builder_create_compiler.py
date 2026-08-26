"""Create-mode compile pipeline. Owns semantic intent -> spec."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_assembly import (
    CreateAssemblyRejection,
    try_compile_create_intent_with_assembly,
)
from eneo.flows.ai_builder.ai_builder_checkpoint_contract import (
    checkpoint_intent_mismatches,
    project_checkpoint_intents,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import CreateCompileContext
from eneo.flows.ai_builder.ai_builder_domain_models import LintWarning
from eneo.flows.ai_builder.ai_builder_flow_schema_values import FlowInputFieldProvenance
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    resolve_schema_properties,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
)
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AttestedResultField,
    CreateFlowIntent,
    ProposalObligationProjection,
    attested_result_contract_violations,
    attested_result_fields_from_drafts,
    attested_violation_message,
    resolve_attested_result_contract,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    fold_result_field_name,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    MAX_TEMPLATE_PREPARATION_STAGES,
    apply_template_attachment_contract,
    template_preparation_stage_limit_exceeded,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputType,
)
from eneo.flows.flow_variable_definitions import (
    FLOW_INPUT_JSON_ALIAS,
)
from eneo.json_types import JsonObject, JsonValue
from eneo.main.logging import get_logger

logger = get_logger(__name__)


def compile_create_intent_to_spec(
    intent: CreateFlowIntent,
    *,
    context: CreateCompileContext | None = None,
    field_diagnostics: list[LintWarning] | None = None,
    obligation_projection: ProposalObligationProjection | None = None,
) -> FlowDraftSpecCore:
    envelope_output_fields = (
        context.result_contract_output_fields if context is not None else ()
    )
    intent = _canonicalize_attested_output_fields(
        intent,
        projection=obligation_projection,
    )
    runtime_input_type = (
        context.effective_runtime_input_type if context is not None else InputType.TEXT
    )
    final_output_type = (
        context.final_output_type
        if context is not None and context.final_output_type is not None
        else OutputType.TEXT
    )
    (
        form_fields,
        dropped_primary_input_field_names,
    ) = _compile_form_fields(
        context=context,
        runtime_input_type=runtime_input_type,
        field_diagnostics=field_diagnostics,
    )
    prepared_template_field_names = _template_fields_prepared_by_intent(
        intent=intent,
        context=context,
    )
    if prepared_template_field_names:
        # A placeholder the flow prepares itself must not also demand a
        # runtime form field: the template contract binds it to the prepared
        # step output, and a leftover required field would shadow that
        # content with an empty runtime prompt.
        form_fields = [
            field
            for field in form_fields
            if field.name not in prepared_template_field_names
        ]
    final_output_mode = context.final_output_mode if context is not None else None
    pattern_ids = context.pattern_ids if context is not None else ()
    chain_steps = context.pattern_chain_steps if context is not None else ()
    aggregation_intent = context.aggregation_intent if context is not None else "linear"
    source_reader_required_fields, translated_capture_fields = (
        _admitted_source_reader_required_fields(
            context=context,
            runtime_input_type=runtime_input_type,
            text_source_reader_planned=(
                runtime_input_type is InputType.TEXT
                and (
                    final_output_type is OutputType.JSON
                    or (len(intent.steps) > 1 and bool(intent.steps[0].output_fields))
                )
            ),
        )
    )
    terminal_obligation_instructions = _translated_capture_obligation_sentence(
        translated_capture_fields,
        ui_language=context.ui_language if context is not None else None,
    )
    field_provenance: dict[str, FlowInputFieldProvenance] = {
        hint.variable_name: hint.provenance
        for hint in (
            context.template_placeholder_field_hints if context is not None else ()
        )
    }
    field_provenance.update(
        {
            record.value.variable_name: record.value.provenance
            for record in (context.runtime_input_fields if context is not None else ())
        }
    )
    assembly_spec = try_compile_create_intent_with_assembly(
        intent,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        is_pure_audio_transcription=(
            context.is_pure_audio_transcription if context is not None else False
        ),
        form_fields=form_fields,
        runtime_input_fields=(
            context.runtime_input_fields if context is not None else ()
        ),
        template_form_field_names=(
            tuple(
                hint.variable_name for hint in context.template_placeholder_field_hints
            )
            if context is not None and context.selected_template_count == 1
            else ()
        ),
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
        aggregation_intent=aggregation_intent,
        terminal_output_schema=context.terminal_output_schema if context else None,
        source_reader_required_fields=source_reader_required_fields,
        result_contract_output_fields=envelope_output_fields,
        result_contract_required_roles=(
            context.result_contract_required_roles if context is not None else ()
        ),
        requested_output_sections=(
            context.requested_output_sections
            if context is not None
            else EMPTY_REQUESTED_OUTPUT_SECTIONS
        ),
        report_disposition=context.report_disposition if context is not None else None,
        runtime_required=context.runtime_required if context is not None else True,
        runtime_max_files=context.runtime_max_files if context is not None else None,
        ui_language=context.ui_language if context is not None else None,
        terminal_obligation_instructions=terminal_obligation_instructions,
        field_provenance=field_provenance,
        field_diagnostics=field_diagnostics,
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
                "semantic_step_count": len(intent.steps),
                "field_names": ",".join(assembly_spec.field_names),
            },
        )
    else:
        assembly_spec = _apply_flow_input_schema(
            assembly_spec,
            flow_input_schema=context.flow_input_schema if context else None,
        )
        _log_dropped_primary_input_shadow_fields(
            field_names=dropped_primary_input_field_names,
            runtime_input_type=runtime_input_type,
        )
        compiled_spec = assembly_spec
        if (
            context is not None
            and context.selected_template_count is not None
            and context.checkpoint_intents is not None
        ):
            # Template normalization keeps an intentionally reviewed report
            # writer, but may remove an unused JSON preparation step. Project
            # once to protect the writer, then again below onto final topology.
            compiled_spec = project_checkpoint_intents(
                compiled_spec,
                context.checkpoint_intents,
            )
        if context is not None and context.selected_template_count is not None:
            compiled_spec = apply_template_attachment_contract(
                compiled_spec,
                selected_template_count=context.selected_template_count,
                placeholders=context.selected_template_placeholders,
            )
        if context is not None and context.checkpoint_intents is not None:
            compiled_spec = project_checkpoint_intents(
                compiled_spec,
                context.checkpoint_intents,
            )
            mismatches = checkpoint_intent_mismatches(
                compiled_spec,
                context.checkpoint_intents,
            )
            if mismatches:
                # The transcription step is backend-inserted; the proposal model
                # cannot add one, so a transcript checkpoint without its producer
                # is a planning/architecture contradiction, not a repairable plan.
                transcript_producer_missing = any(
                    mismatch.kind == "producer_missing"
                    and mismatch.producer_kind == "transcript"
                    for mismatch in mismatches
                )
                if transcript_producer_missing:
                    raise AIBuilderArchitectureError(
                        public_code="architecture_materialization_failed",
                        detail=(
                            "A transcript review checkpoint was requested, but the "
                            "committed architecture compiles no transcription step "
                            "to attach it to."
                        ),
                        log_context={
                            "failure_code": "checkpoint_transcript_producer_missing",
                            "reason": "checkpoint_transcript_producer_missing",
                            "mismatch_count": len(mismatches),
                        },
                    )
                raise AIBuilderArchitectureError(
                    public_code="architecture_materialization_failed",
                    detail=(
                        "The compiled Flow cannot place every requested review checkpoint "
                        "on its typed output producer. Add the missing semantic result "
                        "producer and try again."
                    ),
                    log_context={
                        "failure_code": "checkpoint_intent_mismatch",
                        "reason": "checkpoint_intent_mismatch",
                        "mismatch_count": len(mismatches),
                    },
                )
        if template_preparation_stage_limit_exceeded(compiled_spec):
            raise AIBuilderArchitectureError(
                public_code="architecture_materialization_failed",
                detail=(
                    "DOCX template-fill flows support at most "
                    f"{MAX_TEMPLATE_PREPARATION_STAGES} semantic preparation "
                    "stages. Consolidate related analysis, validation, or writing "
                    "stages and try again."
                ),
                log_context={
                    "failure_code": "template_preparation_stage_limit_exceeded",
                    "reason": "template_preparation_stage_limit_exceeded",
                },
            )
        return _spec_satisfying_attested_contract(
            compiled_spec, projection=obligation_projection
        )


def _canonicalize_attested_output_fields(
    intent: CreateFlowIntent,
    *,
    projection: ProposalObligationProjection | None,
) -> CreateFlowIntent:
    """Normalize attested siblings in place throughout the terminal tree."""

    if projection is None or not intent.steps:
        return intent
    terminal = intent.steps[-1]
    fields = list(terminal.output_fields or ())
    if not fields:
        return intent
    resolution = resolve_attested_result_contract(
        attested_result_fields_from_drafts(fields),
        projection=projection,
    )
    if resolution.violations:
        return intent
    attested_paths = {location.path for location in resolution.locations}
    ordered_names_by_parent: dict[tuple[str, ...], list[str]] = {}
    for location in resolution.locations:
        ordered_names_by_parent.setdefault(location.path[:-1], []).append(
            location.path[-1]
        )

    def normalize_siblings(
        siblings: list[StructuredFieldDraft],
        parent_path: tuple[str, ...],
    ) -> list[StructuredFieldDraft]:
        normalized: list[StructuredFieldDraft] = []
        for field in siblings:
            path = (*parent_path, field.name)
            updates: dict[str, object] = {}
            children = field.fields or field.item_fields
            if children:
                normalized_children = normalize_siblings(list(children), path)
                if field.field_type == "object":
                    updates["fields"] = normalized_children
                else:
                    updates["item_fields"] = normalized_children
            if path in attested_paths:
                updates["required"] = True
                if field.field_type not in ("object", "array"):
                    updates["nullable"] = True
            normalized.append(field.model_copy(update=updates) if updates else field)

        attested_names = ordered_names_by_parent.get(parent_path, [])
        if not attested_names:
            return normalized
        by_name = {field.name: field for field in normalized}
        attested = [by_name[name] for name in attested_names]
        attested_name_set = set(attested_names)
        return attested + [
            field for field in normalized if field.name not in attested_name_set
        ]

    reordered = normalize_siblings(fields, ())
    new_terminal = terminal.model_copy(update={"output_fields": reordered})
    return intent.model_copy(update={"steps": [*intent.steps[:-1], new_terminal]})


def _spec_satisfying_attested_contract(
    spec: FlowDraftSpecCore,
    *,
    projection: ProposalObligationProjection | None,
) -> FlowDraftSpecCore:
    """Compiler postcondition: the SAME predicate admission ran, re-run on the
    compiled terminal contract.

    A defect detector, never a repair: admission already verified the model's
    declaration, so a violation here means compilation dropped, renamed or
    retyped a name the user was shown at confirmation. It fails closed as a
    non-repairable architecture failure rather than asking a model to fix a
    server bug.
    """

    if projection is None:
        return spec
    outcome_contract = next(
        (
            step.output_contract
            for step in reversed(spec.steps)
            if step.output_contract is not None
        ),
        None,
    )
    schema = outcome_contract if isinstance(outcome_contract, dict) else {}
    terminal_fields = _attested_fields_from_schema(schema)
    violations = attested_result_contract_violations(
        terminal_fields,
        projection=projection,
    )
    if not violations:
        return spec
    detail = "; ".join(
        attested_violation_message(violation) for violation in violations
    )
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=(f"The compiled Flow broke the attested result contract: {detail}."),
        log_context={
            "failure_code": "attested_result_contract_broken",
            "reason": ";".join(f"{v.kind}:{v.key_name}" for v in violations),
            "field_names": ",".join(v.key_name for v in violations),
        },
    )


def _attested_fields_from_schema(
    schema: dict[str, Any],
) -> tuple[AttestedResultField, ...]:
    fields: list[AttestedResultField] = []
    for raw_name, raw_value in resolve_schema_properties(schema).items():
        if not isinstance(raw_value, dict):
            continue
        value = cast(dict[str, Any], raw_value)
        field_type = _schema_field_type(value)
        child_schema = value
        if field_type == "array" and isinstance(value.get("items"), dict):
            child_schema = cast(dict[str, Any], value["items"])
        fields.append(
            AttestedResultField(
                name=str(raw_name),
                field_type=field_type,
                children=_attested_fields_from_schema(child_schema),
            )
        )
    return tuple(fields)


def _schema_field_type(schema: dict[str, Any]) -> str:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        return next(
            (
                item
                for item in cast(list[object], raw_type)
                if isinstance(item, str) and item != "null"
            ),
            "",
        )
    return ""


def _apply_flow_input_schema(
    spec: FlowDraftSpecCore,
    *,
    flow_input_schema: JsonObject | None,
) -> FlowDraftSpecCore:
    if flow_input_schema is None:
        return spec

    target_index = next(
        (
            index
            for index, step in enumerate(spec.steps)
            if step.input_source is InputSource.FLOW_INPUT
            and step.input_type is InputType.JSON
        ),
        None,
    )
    if target_index is None:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail="The resolved JSON input schema has no Flow-input JSON consumer.",
            log_context={"failure_code": "flow_input_schema_target_missing"},
        )

    target_step = spec.steps[target_index]
    raw_json_binding = {"question": f"{{{{ {FLOW_INPUT_JSON_ALIAS} }}}}"}
    if target_step.input_bindings not in (None, raw_json_binding):
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail=(
                "The resolved JSON input schema cannot be combined with "
                "additional Flow-input bindings."
            ),
            log_context={
                "failure_code": "flow_input_schema_composite_bindings_unsupported",
                "step_index": target_index + 1,
            },
        )

    input_contract = _flow_input_schema_with_form_fields(
        flow_input_schema,
        form_fields=spec.form_fields or [],
        step_index=target_index + 1,
    )

    compiled_steps = list(spec.steps)
    compiled_steps[target_index] = target_step.model_copy(
        update={
            "input_bindings": None,
            "input_contract": input_contract,
        }
    )
    return spec.model_copy(update={"steps": compiled_steps})


def _flow_input_schema_with_form_fields(
    flow_input_schema: JsonObject,
    *,
    form_fields: list[FormFieldSpec],
    step_index: int,
) -> FlowPersistedJsonObject:
    merged = cast(FlowPersistedJsonObject, deepcopy(flow_input_schema))
    if merged.get("type") != "object":
        _raise_flow_input_schema_form_conflict(step_index=step_index)
    raw_properties = merged.get("properties")
    if raw_properties is None:
        raw_properties = {}
        merged["properties"] = raw_properties
    raw_required = merged.get("required")
    if raw_required is None:
        raw_required = []
        merged["required"] = raw_required
    if not isinstance(raw_properties, dict) or not isinstance(raw_required, list):
        _raise_flow_input_schema_form_conflict(step_index=step_index)
    properties = cast(JsonObject, raw_properties)
    required = cast(list[JsonValue], raw_required)

    for field in form_fields:
        form_schema = _form_field_json_schema(field)
        existing = properties.get(field.name)
        if existing is None:
            properties[field.name] = form_schema
        else:
            _raise_flow_input_schema_form_conflict(
                step_index=step_index,
                field_name=field.name,
            )
        if field.required and field.name not in required:
            required.append(field.name)
    return merged


def _form_field_json_schema(field: FormFieldSpec) -> FlowPersistedJsonObject:
    if field.type == "number":
        return {"type": "number"}
    if field.type in {"multiselect", "list"}:
        items: FlowPersistedJsonObject = {"type": "string"}
        if field.type == "multiselect" and field.options:
            items["enum"] = list(field.options)
        return {"type": "array", "items": items}
    schema: FlowPersistedJsonObject = {"type": "string"}
    if field.type == "select" and field.options:
        schema["enum"] = list(field.options)
    return schema


def _raise_flow_input_schema_form_conflict(
    *,
    step_index: int,
    field_name: str | None = None,
) -> None:
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=(
            "The resolved JSON input schema conflicts with a confirmed "
            "runtime form field."
        ),
        log_context={
            "failure_code": "flow_input_schema_composite_bindings_unsupported",
            "step_index": step_index,
            "field_name": field_name,
        },
    )


def _template_fields_prepared_by_intent(
    *,
    intent: CreateFlowIntent,
    context: CreateCompileContext | None,
) -> set[str]:
    """Template-derived field names the proposed steps already prepare.

    A bare template placeholder normally becomes a required runtime form
    field, but when a semantic step declares a string output field whose
    folded name matches the placeholder, the template contract binds the
    placeholder to that prepared value instead. User-confirmed runtime
    fields and intent-declared input fields keep their runtime ownership.
    """

    if context is None or not context.template_placeholder_field_hints:
        return set()
    runtime_hint_names = {
        hint.variable_name for hint in context.runtime_input_field_hints
    }
    prepared_folded_names = {
        fold_result_field_name(field.name)
        for step in intent.steps
        for field in step.output_fields or ()
        if field.field_type == "string"
    }
    return {
        hint.variable_name
        for hint in context.template_placeholder_field_hints
        if hint.variable_name not in runtime_hint_names
        and fold_result_field_name(hint.variable_name) in prepared_folded_names
    }


def _compile_form_fields(
    *,
    context: CreateCompileContext | None,
    runtime_input_type: InputType | None,
    field_diagnostics: list[LintWarning] | None,
) -> tuple[list[FormFieldSpec], list[str]]:
    runtime_input_field_hints = (
        context.runtime_input_field_hints if context is not None else ()
    )
    template_placeholder_field_hints = (
        context.template_placeholder_field_hints if context is not None else ()
    )
    fields: list[FormFieldSpec] = []
    dropped_primary_input_field_names: list[str] = []
    seen: set[str] = set()
    for hint in (*runtime_input_field_hints, *template_placeholder_field_hints):
        if is_primary_runtime_input_shadow_field(
            variable_name=hint.variable_name,
            field_type=hint.field_type,
            runtime_input_type=runtime_input_type,
        ):
            _reject_or_diagnose_field_drops(
                fields=[hint],
                code="primary_input_shadow_form_field_dropped",
                field_diagnostics=field_diagnostics,
            )
            dropped_primary_input_field_names.append(hint.variable_name)
            continue
        if hint.variable_name in seen:
            continue
        fields.append(_compile_form_field(hint))
        seen.add(hint.variable_name)
    return fields, dropped_primary_input_field_names


def _reject_or_diagnose_field_drops(
    *,
    fields: list[RuntimeInputFieldHint],
    code: str,
    field_diagnostics: list[LintWarning] | None,
) -> None:
    confirmed_names = sorted(
        field.variable_name for field in fields if field.provenance == "user_confirmed"
    )
    if confirmed_names:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail="Confirmed runtime fields are incompatible with the selected input contract.",
            log_context={
                "failure_code": "confirmed_form_field_incompatible",
                "field_names": ",".join(confirmed_names),
            },
        )
    if field_diagnostics is None:
        return
    for field in fields:
        field_diagnostics.append(
            LintWarning(
                code=code,
                message=(
                    f"Runtime field '{field.variable_name}' was removed during "
                    "form-field normalization."
                ),
                field_name=field.variable_name,
                field_provenance=field.provenance,
            )
        )


def _admitted_source_reader_required_fields(
    *,
    context: CreateCompileContext | None,
    runtime_input_type: InputType,
    text_source_reader_planned: bool = False,
) -> tuple[tuple[SourceCaptureField, ...], tuple[SourceCaptureField, ...]]:
    """Split capture fields into structured-reader and terminal obligations.

    Document and file inputs always materialize a source reader. Text inputs
    retain the capture contract only when the semantic topology already plans
    a structured reader; a direct prose writer receives the same obligation in
    its server-owned instructions. Other inputs cannot host a source reader.
    """
    if context is None or not context.source_reader_required_fields:
        return (), ()
    if runtime_input_type in {InputType.DOCUMENT, InputType.FILE} or (
        runtime_input_type is InputType.TEXT and text_source_reader_planned
    ):
        return context.source_reader_required_fields, ()
    logger.info(
        "ai_builder_source_reader_fields_translated_for_input_type",
        extra={
            "field_names": sorted(
                field.name for field in context.source_reader_required_fields
            ),
            "runtime_input_type": runtime_input_type.value,
        },
    )
    return (), context.source_reader_required_fields


def _translated_capture_obligation_sentence(
    translated_fields: tuple[SourceCaptureField, ...],
    *,
    ui_language: str | None,
) -> str | None:
    """Render unreadable capture obligations as one server-owned sentence.

    The assembly module appends it to the retained content producer after
    terminal-helper normalization, so the planning state's obligation survives
    regardless of how the model worded its steps.
    """
    if not translated_fields:
        return None
    is_swedish = ui_language is None or ui_language.casefold().startswith("sv")
    sentences: list[str] = []
    for field in translated_fields:
        if field.name == "summary":
            sentences.append(
                "Resultatet ska innehålla en kort sammanfattning grundad i källmaterialet."
                if is_swedish
                else "The result must include a concise summary grounded in the source material."
            )
        elif field.description:
            sentences.append(
                f"Resultatet ska innehålla: {field.description}"
                if is_swedish
                else f"The result must include: {field.description}"
            )
    return " ".join(sentences) or None


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


def _compile_form_field(
    field: RuntimeInputFieldHint,
) -> FormFieldSpec:
    return FormFieldSpec(
        name=field.variable_name,
        label=field.label,
        type=field.field_type,
        required=field.required,
        options=list(field.options) or None,
    )

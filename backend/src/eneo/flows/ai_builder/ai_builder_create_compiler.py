"""Create-mode compile pipeline. Owns semantic intent -> spec."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, cast

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_assembly import (
    CreateAssemblyRejection,
    try_compile_create_intent_with_assembly,
)
from eneo.flows.ai_builder.ai_builder_assembly.plan import SOURCE_READER_INPUT_TYPES
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
    structured_field_draft_names,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
)
from eneo.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    fold_result_field_name,
    structured_field_names_satisfy_result_field,
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
from eneo.json_types import JsonObject

logger = logging.getLogger(__name__)


def compile_create_intent_to_spec(
    intent: CreateFlowIntent,
    *,
    context: CreateCompileContext | None = None,
    field_diagnostics: list[LintWarning] | None = None,
) -> FlowDraftSpecCore:
    obligated_output_fields = intent.obligated_output_fields
    envelope_output_fields = (
        context.result_contract_output_fields if context is not None else ()
    )
    intent = _intent_with_obligated_output_fields(
        intent,
        envelope_fields=envelope_output_fields,
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
        # With obligations, the envelope is already merged onto the terminal
        # step above, under a precedence the assembly's any-depth completion
        # cannot express. Leaving it here as well would let it re-complete
        # that branch against the merged graph.
        result_contract_output_fields=(
            () if obligated_output_fields else envelope_output_fields
        ),
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
        if context is not None and context.selected_template_count is not None:
            compiled_spec = apply_template_attachment_contract(
                compiled_spec,
                selected_template_count=context.selected_template_count,
                placeholders=context.selected_template_placeholders,
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
        if context is None or context.checkpoint_intents is None:
            return _spec_preserving_obligations(compiled_spec, obligated_output_fields)
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
        return _spec_preserving_obligations(compiled_spec, obligated_output_fields)


def _intent_with_obligated_output_fields(
    intent: CreateFlowIntent,
    *,
    envelope_fields: tuple[StructuredFieldDraft, ...],
) -> CreateFlowIntent:
    """Place the admitted obligation graph on the terminal step, once.

    Precedence is explicit and it is enforced where it cannot be defeated.
    Routing obligations through the server-owned result-contract parameter
    would not do it: that path only *completes* a field it cannot already
    find, and it finds one at any depth and under any folded alias
    (`_complete_result_contract_output_fields` in the assembly), so a
    model-authored nested `documents: string` would silently stand in for an
    obligated root `documents: array`.

    The same any-depth search cuts the other way, so the envelope is completed
    here too rather than in the assembly: an obligation nested as
    `assessment{risks}` must not stand in for the server's own required root
    `risks`. Only an obligated ROOT may satisfy an envelope role; the model's
    own fields keep the assembly's existing satisfaction rule, so nothing about
    plans without obligations changes. The assembly's global alias semantics
    are untouched — it simply has nothing left to complete on this branch.

    Order matters and it is the whole correctness argument: what the model
    keeps is decided FIRST, and everything afterwards — collisions, envelope
    satisfaction — is judged against the fields that actually survive. Judging
    against the fields that were merely submitted let a discarded subtree both
    demand a repair and suppress an envelope root it would never emit.
    """

    obligated = intent.obligated_output_fields
    if not obligated or not intent.steps:
        return intent
    # Two sets, because they answer two questions. Only a ROOT can outrank a
    # model root; but EVERY obligated name, at any depth, may exist in exactly
    # one place.
    obligated_root_identities = {
        fold_result_field_name(field.name) for field in obligated
    }
    obligated_identities = {
        fold_result_field_name(name) for name in structured_field_draft_names(obligated)
    }
    terminal_step = intent.steps[-1]
    surviving_model_fields = [
        field
        for field in (terminal_step.output_fields or [])
        if fold_result_field_name(field.name) not in obligated_root_identities
    ]
    _reject_obligated_name_collisions(
        surviving_model_fields,
        obligated_identities=obligated_identities,
    )
    model_declared_names = structured_field_draft_names(tuple(surviving_model_fields))
    uncovered_envelope_fields = [
        field
        for field in envelope_fields
        if fold_result_field_name(field.name) not in obligated_root_identities
        and not structured_field_names_satisfy_result_field(
            model_declared_names,
            field.name,
        )
    ]
    model_fields = surviving_model_fields
    return intent.model_copy(
        update={
            "steps": [
                *intent.steps[:-1],
                terminal_step.model_copy(
                    update={
                        "output_fields": [
                            *obligated,
                            *model_fields,
                            *uncovered_envelope_fields,
                        ]
                    }
                ),
            ]
        }
    )


def _reject_obligated_name_collisions(
    fields: list[StructuredFieldDraft],
    *,
    obligated_identities: set[str],
    path: str = "",
) -> None:
    """Refuse a surviving model field that repeats a user-named result.

    A model ROOT of an obligated root's identity is simply outranked and has
    already been removed before this runs, so nothing here asks for a repair
    the model's own text could not perform. What remains is a second,
    contradictory home for a name the contract binds exactly once — including
    a nested obligation such as `assessment{risks}` reappearing under some
    other branch — and that is repairable feedback rather than a silent choice
    between two placements.
    """

    for field in fields:
        field_path = f"{path}.{field.name}" if path else field.name
        if fold_result_field_name(field.name) in obligated_identities:
            raise AIBuilderArchitectureError(
                public_code="architecture_materialization_failed",
                detail=(
                    f"{field_path} repeats a result field the user named. Each "
                    "user-named field belongs in exactly one place; remove this "
                    "copy and let the named field keep its own placement."
                ),
                log_context={
                    "failure_code": "named_result_obligation_collision",
                    "reason": "named_result_obligation_collision",
                    "field_names": field_path,
                },
            )
        _reject_obligated_name_collisions(
            (field.fields or []) + (field.item_fields or []),
            obligated_identities=obligated_identities,
            path=field_path,
        )


def _missing_obligation_paths(
    fields: tuple[StructuredFieldDraft, ...],
    schema: dict[str, Any],
    *,
    path: str = "",
) -> list[str]:
    """Obligation paths the compiled contract does not carry, in graph order.

    Each obligation is looked for beneath its own obligated parent, so the
    answer is a path and not a name. Identity is still folded per segment, so
    a fold-equivalent spelling of the same field is preserved rather than
    reported.
    """

    properties = {
        fold_result_field_name(str(name)): value
        for name, value in resolve_schema_properties(_schema_object(schema)).items()
    }
    missing: list[str] = []
    for field in fields:
        field_path = f"{path}.{field.name}" if path else field.name
        declared = properties.get(fold_result_field_name(field.name))
        if not isinstance(declared, dict):
            missing.append(field_path)
            continue
        children = tuple((field.fields or []) + (field.item_fields or []))
        if children:
            missing.extend(
                _missing_obligation_paths(
                    children,
                    cast(dict[str, Any], declared),
                    path=field_path,
                )
            )
    return missing


def _schema_object(schema: dict[str, Any]) -> dict[str, Any]:
    """The object node whose properties a field's children live in.

    An array's children are declared on its `items`, and the obligated graph
    reaches them through `item_fields` without a numeric segment, so the array
    node is transparent here.
    """

    items = schema.get("items")
    if schema.get("type") == "array" and isinstance(items, dict):
        return _schema_object(cast(dict[str, Any], items))
    return schema


def _spec_preserving_obligations(
    spec: FlowDraftSpecCore,
    obligated_output_fields: tuple[StructuredFieldDraft, ...],
) -> FlowDraftSpecCore:
    """Compiler postcondition: every admitted obligation survived compilation.

    A defect detector, never a repair. The model cannot cause this to fire —
    placement is server-owned above — so firing means the compiler dropped a
    name the user was already shown at confirmation, and shipping that plan
    would break the promise the confirmation made. It fails closed as a
    non-repairable architecture failure rather than asking a model to fix a
    server bug.

    It checks every admitted obligation at its own PATH, not merely somewhere
    in the contract: a lost `assessment.risks` is exactly as broken a promise
    as a lost `assessment`, and the same name legitimately exists at another
    depth — the server's envelope `risks` sits at the root while the user's
    `risks` sits inside `assessment` — so a flat name set would let one mask
    the other's loss.
    """

    if not obligated_output_fields:
        return spec
    outcome_contract = next(
        (
            step.output_contract
            for step in reversed(spec.steps)
            if step.output_contract is not None
        ),
        None,
    )
    missing = _missing_obligation_paths(
        obligated_output_fields,
        outcome_contract if isinstance(outcome_contract, dict) else {},
    )
    if not missing:
        return spec
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=(
            "The compiled Flow lost result fields the user named: "
            f"{', '.join(missing)}."
        ),
        log_context={
            "failure_code": "named_result_obligation_dropped",
            "reason": "named_result_obligation_dropped",
            "field_names": ",".join(missing),
        },
    )


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

    compiled_steps = list(spec.steps)
    compiled_steps[target_index] = target_step.model_copy(
        update={
            "input_bindings": None,
            "input_contract": cast(
                FlowPersistedJsonObject,
                deepcopy(flow_input_schema),
            ),
        }
    )
    return spec.model_copy(update={"steps": compiled_steps})


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
) -> tuple[tuple[SourceCaptureField, ...], tuple[SourceCaptureField, ...]]:
    """Split capture fields into (admitted, translated) for this input type.

    A source-reader step only exists for document/file/text runtime input.
    Passing capture fields through for e.g. audio makes the FlowAssemblyPlan
    invariant fail deterministically — the planner cannot repair a constraint
    it does not control, so the whole proposal turn dies after exhausting
    repairs. Fields that cannot be captured by a reader are returned in the
    second tuple so the caller can translate the obligation into server-owned
    terminal-step instructions instead of silently losing it.
    """
    if context is None or not context.source_reader_required_fields:
        return (), ()
    if runtime_input_type in SOURCE_READER_INPUT_TYPES:
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

"""Create-mode compile pipeline. Owns semantic intent -> spec."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

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
from eneo.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_step_mechanics,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    MAX_SOURCE_CAPTURE_FIELDS,
    SourceCaptureField,
    compile_new_step_draft,
    make_plan_step_ref,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
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
from eneo.flows.ai_builder.ai_builder_step_skeleton import (
    StepSkeletonOutputTypeDrift,
    StepSkeletonSemanticContent,
    materialize_step_skeleton,
    resolve_step_skeleton_patterns,
)
from eneo.flows.ai_builder.pattern_registry import (
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    PATTERN_REGISTRY,
)
from eneo.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommit,
    ArchitectureCommitDraft,
    PlanningState,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.json_types import JsonObject

logger = logging.getLogger(__name__)
_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
_COMPARISON_FAN_IN_PATTERN_IDS = frozenset({"comparison"})
_SOURCE_CAPTURE_INPUT_TYPES = frozenset(
    {InputType.DOCUMENT, InputType.FILE, InputType.TEXT}
)
# Broader than the document/file dataflow fold: source text can still expose a
# JSON contract, even when there is no source-reader refinement chain to fold.
_SOURCE_CONTRACT_INPUT_TYPES = frozenset(
    {InputType.DOCUMENT, InputType.FILE, InputType.TEXT}
)
_SOURCE_CONTRACT_FORM_FIELD_PREFIX_TOKENS = frozenset(
    {
        "manual",
        "manuell",
        "manuella",
        "provided",
        "runtime",
        "user",
    }
)
# Deliberately not a general synonym registry. This only collapses the common
# source-document date/year slot so "manual_year" does not survive beside an
# extracted "document_date". Broader semantic matching belongs upstream in the
# slot classifier or model guidance, not in the compiler.
_SOURCE_CONTRACT_TOKEN_ALIASES = {
    "år": "date",
    "ar": "date",
    "year": "date",
}
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
    aggregation_intent: AggregationIntent = "linear"
    terminal_output_schema: JsonObject | None = None
    source_reader_required_fields: tuple[SourceCaptureField, ...] = ()

    def __post_init__(self) -> None:
        if self.runtime_input_type is InputType.ANY:
            raise ValueError("CreateCompileContext.runtime_input_type cannot be ANY")
        if self.runtime_max_files is not None and self.runtime_max_files < 1:
            raise ValueError("runtime_max_files must be at least 1 when provided")


@dataclass(frozen=True, slots=True)
class RuntimeInputFieldHintSource:
    aggregated_conversation_text: str


@dataclass(frozen=True, slots=True)
class SemanticStepRewrite:
    steps: list[SemanticStepIntent]
    original_to_current_step: dict[int, int]


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
    referenced_hint_names = {
        field_name
        for semantic_step in intent.steps
        for field_name in semantic_step.uses_form_fields
    }
    form_fields, dropped_primary_input_field_names = _compile_form_fields(
        intent_fields=intent.input_fields,
        context=context,
        runtime_input_type=runtime_input_type,
        referenced_hint_names=referenced_hint_names,
    )
    known_field_order = [field.name for field in form_fields]
    known_field_names = set(known_field_order)

    final_output_mode = context.final_output_mode if context is not None else None
    pattern_ids = context.pattern_ids if context is not None else ()
    chain_steps = context.pattern_chain_steps if context is not None else ()
    pattern_resolution = resolve_step_skeleton_patterns(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        final_output_mode=final_output_mode,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
    )
    backend_audio_transcription_inserted = _backend_audio_transcription_inserted(
        pattern_ids=pattern_resolution.pattern_ids,
        chain_steps=pattern_resolution.chain_steps,
    )
    semantic_steps_original = list(intent.steps)
    semantic_step_rewrite = _normalize_leading_audio_transcription_step(
        steps=list(intent.steps),
        runtime_input_type=runtime_input_type,
        backend_audio_transcription_inserted=backend_audio_transcription_inserted,
    )
    backend_audio_transcription_review_mode = (
        _redundant_leading_audio_transcription_review_mode(
            steps=list(intent.steps),
            runtime_input_type=runtime_input_type,
            backend_audio_transcription_inserted=backend_audio_transcription_inserted,
        )
    )
    semantic_step_rewrite = _fold_leading_zero_contract_text_steps(
        rewrite=semantic_step_rewrite,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
    )
    semantic_steps_input = _remap_declared_previous_refs_after_semantic_rewrite(
        rewrite=semantic_step_rewrite,
        original_steps=semantic_steps_original,
    )

    semantic_steps: list[StepSkeletonSemanticContent] = []
    for semantic_step in semantic_steps_input:
        uses_form_fields = [
            field_name
            for field_name in semantic_step.uses_form_fields
            if field_name in known_field_names
        ]
        dropped_primary_input_field_names.extend(
            [
                field_name
                for field_name in semantic_step.uses_form_fields
                if field_name not in known_field_names
                and is_primary_runtime_input_shadow_field(
                    variable_name=field_name,
                    field_type="text",
                    runtime_input_type=runtime_input_type,
                )
            ]
        )
        semantic_steps.append(
            _semantic_content_from_intent_step(
                semantic_step,
                uses_form_fields=uses_form_fields,
            )
        )

    aggregation_intent = context.aggregation_intent if context is not None else "linear"
    try:
        skeleton_plan = materialize_step_skeleton(
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
            pattern_ids=pattern_ids,
            chain_steps=chain_steps,
            aggregation_intent=aggregation_intent,
            runtime_required=context.runtime_required if context is not None else True,
            runtime_max_files=(
                context.runtime_max_files if context is not None else None
            ),
            ui_language=context.ui_language if context is not None else None,
        )
        composition = skeleton_plan.compose(semantic_steps)
    except ValueError as error:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail=str(error),
            log_context={
                "runtime_input_type": runtime_input_type.value,
                "final_output_type": final_output_type.value,
                "final_output_mode": (
                    final_output_mode.value if final_output_mode is not None else None
                ),
                "pattern_ids": ",".join(pattern_ids),
                "chain_steps": ",".join(chain_steps),
                "semantic_step_count": len(semantic_steps),
            },
        ) from error
    _log_skeleton_output_type_drifts(composition.output_type_drifts)
    steps = list(composition.steps)
    if backend_audio_transcription_review_mode is not None:
        steps = _apply_backend_audio_transcription_review_mode(
            steps=steps,
            review_mode=backend_audio_transcription_review_mode,
        )
    terminal_output_schema = context.terminal_output_schema if context else None
    steps = _attach_unreferenced_form_fields_to_final_step(
        steps=steps,
        known_field_order=known_field_order,
        semantic_step_count=len(semantic_steps),
    )
    _log_dropped_primary_input_shadow_fields(
        field_names=dropped_primary_input_field_names,
        runtime_input_type=runtime_input_type,
    )
    return compile_create_steps_to_spec(
        flow_name=intent.flow_name,
        flow_description=intent.flow_description,
        form_fields=form_fields,
        steps=steps,
        document_body_writer_step_indexes=composition.document_body_writer_step_indexes,
        aggregation_intent=aggregation_intent,
        terminal_output_schema=terminal_output_schema,
        source_reader_required_fields=(
            context.source_reader_required_fields if context is not None else ()
        ),
        ui_language=context.ui_language if context is not None else None,
    )


def _semantic_content_from_intent_step(
    step: SemanticStepIntent,
    *,
    uses_form_fields: list[str],
) -> StepSkeletonSemanticContent:
    return StepSkeletonSemanticContent(
        name=step.name,
        instructions=step.instructions,
        requested_output_type=(
            OutputType(step.output_type) if step.output_type is not None else None
        ),
        output_fields=tuple(step.output_fields or ()),
        uses_form_fields=tuple(uses_form_fields),
        uses_previous_fields=tuple(step.uses_previous_fields),
        uses_previous_outputs=tuple(step.uses_previous_outputs),
        model_ref=step.model_ref,
        knowledge_refs=tuple(step.knowledge_refs),
        mcp_server_refs=tuple(step.mcp_server_refs),
        mcp_tool_refs=tuple(step.mcp_tool_refs),
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )


def _remap_declared_previous_refs_after_semantic_rewrite(
    *,
    rewrite: SemanticStepRewrite,
    original_steps: list["SemanticStepIntent"],
) -> list["SemanticStepIntent"]:
    if rewrite.steps == original_steps:
        return rewrite.steps

    updated: list[SemanticStepIntent] = []
    for current_step_number, step in enumerate(rewrite.steps, start=1):
        if not step.uses_previous_fields and not step.uses_previous_outputs:
            updated.append(step)
            continue
        remapped_fields = _remap_declared_previous_field_refs(
            step.uses_previous_fields,
            original_to_current_step=rewrite.original_to_current_step,
            current_step_number=current_step_number,
        )
        remapped_outputs = _remap_declared_previous_output_refs(
            step.uses_previous_outputs,
            original_to_current_step=rewrite.original_to_current_step,
            current_step_number=current_step_number,
        )
        if (
            remapped_fields == step.uses_previous_fields
            and remapped_outputs == step.uses_previous_outputs
        ):
            updated.append(step)
            continue
        updated.append(
            step.model_copy(
                update={
                    "uses_previous_fields": remapped_fields,
                    "uses_previous_outputs": remapped_outputs,
                }
            )
        )
    return updated


def _remap_declared_previous_field_refs(
    refs: list[PreviousFieldRef],
    *,
    original_to_current_step: dict[int, int],
    current_step_number: int,
) -> list[PreviousFieldRef]:
    remapped: list[PreviousFieldRef] = []
    for ref in refs:
        current_source_step = original_to_current_step.get(ref.from_step)
        if current_source_step is None or current_source_step >= current_step_number:
            continue
        remapped.append(ref.model_copy(update={"from_step": current_source_step}))
    return remapped


def _remap_declared_previous_output_refs(
    refs: list[PreviousOutputRef],
    *,
    original_to_current_step: dict[int, int],
    current_step_number: int,
) -> list[PreviousOutputRef]:
    remapped: list[PreviousOutputRef] = []
    for ref in refs:
        current_source_step = original_to_current_step.get(ref.from_step)
        if current_source_step is None or current_source_step >= current_step_number:
            continue
        remapped.append(ref.model_copy(update={"from_step": current_source_step}))
    return remapped


def _log_skeleton_output_type_drifts(
    output_type_drifts: tuple[StepSkeletonOutputTypeDrift, ...],
) -> None:
    for drift in output_type_drifts:
        logger.info(
            "ai_builder_skeleton_semantic_output_type_drift",
            extra={
                "slot_id": drift.slot_id,
                "slot_ordinal": drift.slot_ordinal,
                "requested_output_type": drift.requested_output_type.value,
                "enforced_output_type": drift.enforced_output_type.value,
                "dropped_output_fields": drift.dropped_output_fields,
            },
        )


def compile_create_steps_to_spec(
    *,
    flow_name: str,
    flow_description: str | None = None,
    form_fields: list[FormFieldSpec] | None = None,
    steps: list[NewStepDraft],
    document_body_writer_step_indexes: tuple[int, ...] = (),
    aggregation_intent: AggregationIntent = "linear",
    terminal_output_schema: JsonObject | None = None,
    source_reader_required_fields: tuple[SourceCaptureField, ...] = (),
    ui_language: str | None = None,
) -> FlowDraftSpecCore:
    form_fields = list(form_fields or [])
    steps = _clear_terminal_schema_output_fields(
        steps=steps,
        terminal_output_schema=terminal_output_schema,
    )
    steps = _complete_source_reader_contracts(
        steps=steps,
        terminal_output_schema=terminal_output_schema,
        required_fields=source_reader_required_fields,
    )
    normalized_steps = normalize_create_step_mechanics(
        steps=steps,
        form_fields=form_fields or [],
        flow_name=flow_name,
        flow_description=flow_description,
        aggregation_intent=aggregation_intent,
    )
    normalized_steps, form_fields, dropped_source_contract_field_names = (
        _drop_source_contract_shadow_form_fields(
            steps=normalized_steps,
            form_fields=form_fields,
        )
    )
    _log_dropped_source_contract_shadow_fields(
        field_names=dropped_source_contract_field_names
    )
    source_capture_fields_by_index = _source_capture_fields_by_step_index(
        steps=normalized_steps,
        terminal_output_schema=terminal_output_schema,
    )
    compiled_steps: list[StepSpec] = []
    for index, step_draft in enumerate(normalized_steps):
        compiled_steps.append(
            compile_new_step_draft(
                step_draft=step_draft,
                plan_step_ref=make_plan_step_ref(index),
                prior_steps=compiled_steps,
                source_capture_fields=source_capture_fields_by_index.get(index, ()),
                ui_language=ui_language,
            )
        )
    compiled_steps = _apply_terminal_output_schema(
        compiled_steps,
        terminal_output_schema=terminal_output_schema,
    )

    compiled = FlowDraftSpecCore(
        flow_name=normalize_flow_name(flow_name),
        flow_description=flow_description or "",
        steps=compiled_steps,
        form_fields=form_fields or None,
        document_body_writer_step_refs=_document_body_writer_step_refs(
            compiled_steps=compiled_steps,
            step_indexes=document_body_writer_step_indexes,
        ),
    )
    return compiled


def _complete_source_reader_contracts(
    *,
    steps: list[NewStepDraft],
    terminal_output_schema: JsonObject | None,
    required_fields: tuple[SourceCaptureField, ...],
) -> list[NewStepDraft]:
    source_reader_indexes = tuple(
        index for index, step in enumerate(steps) if _is_source_json_contract_step(step)
    )
    if not source_reader_indexes:
        return steps

    fields_by_index: dict[int, list[SourceCaptureField]] = {}
    terminal_fields = (
        _capture_fields_from_terminal_schema(terminal_output_schema)
        if terminal_output_schema is not None
        else ()
    )
    global_fields = _dedupe_capture_fields([*required_fields, *terminal_fields])
    missing_global_fields = [
        field
        for field in global_fields
        if not any(
            _structured_fields_have_leaf(steps[index].output_fields or [], field.name)
            for index in source_reader_indexes
        )
    ]
    if missing_global_fields:
        if len(source_reader_indexes) != 1:
            raise AIBuilderArchitectureError(
                public_code="architecture_materialization_failed",
                detail=(
                    "Source-reader contract completion found required fields "
                    "but could not attribute them to exactly one reader."
                ),
                log_context={
                    "source_reader_count": len(source_reader_indexes),
                    "required_fields": ",".join(
                        field.name for field in missing_global_fields
                    ),
                },
            )
        fields_by_index.setdefault(source_reader_indexes[0], []).extend(
            missing_global_fields
        )

    for step in steps:
        for ref in step.uses_previous_fields:
            source_index = ref.from_step - 1
            if source_index < 0 or source_index >= len(steps):
                continue
            source_step = steps[source_index]
            if not _is_source_json_contract_step(source_step):
                continue
            field_name = _leaf_field_name(ref.field_path)
            if not field_name or _structured_fields_have_leaf(
                source_step.output_fields or [], field_name
            ):
                continue
            fields_by_index.setdefault(source_index, []).append(
                SourceCaptureField(name=field_name, description=ref.label)
            )

    if not fields_by_index:
        return steps

    updated_steps = list(steps)
    for index, fields in fields_by_index.items():
        step = steps[index]
        output_fields = step.output_fields or []
        completed_fields = _add_missing_source_reader_fields(
            output_fields,
            required_fields=_dedupe_capture_fields(fields),
        )
        if completed_fields == output_fields:
            continue
        updated_steps[index] = step.model_copy(
            update={"output_fields": completed_fields}
        )
        logger.info(
            "ai_builder_source_reader_contract_completed",
            extra={
                "step_index": index + 1,
                "field_names": [field.name for field in fields],
            },
        )

    return updated_steps


def _add_missing_source_reader_fields(
    fields: list[StructuredFieldDraft],
    *,
    required_fields: tuple[SourceCaptureField, ...],
) -> list[StructuredFieldDraft]:
    missing_fields = [
        field
        for field in required_fields
        if not _structured_fields_have_leaf(fields, field.name)
    ]
    if not missing_fields:
        return fields

    if len(fields) == 1:
        field = fields[0]
        if field.field_type == "array" and field.item_fields:
            return [
                field.model_copy(
                    update={
                        "item_fields": _append_structured_leaf_fields(
                            field.item_fields,
                            missing_fields=missing_fields,
                        )
                    }
                )
            ]
        if field.field_type == "object" and field.fields:
            return [
                field.model_copy(
                    update={
                        "fields": _append_structured_leaf_fields(
                            field.fields,
                            missing_fields=missing_fields,
                        )
                    }
                )
            ]

    return _append_structured_leaf_fields(fields, missing_fields=missing_fields)


def _append_structured_leaf_fields(
    fields: list[StructuredFieldDraft],
    *,
    missing_fields: list[SourceCaptureField],
) -> list[StructuredFieldDraft]:
    return [
        *fields,
        *(
            StructuredFieldDraft(
                name=field.name,
                field_type="string",
                description=field.description
                or f"Source-derived value for {field.name}.",
            )
            for field in missing_fields
        ),
    ]


def _structured_fields_have_leaf(
    fields: list[StructuredFieldDraft],
    required_name: str,
) -> bool:
    return any(
        _field_name_matches_required_leaf(field.name, required_name)
        for field in _iter_output_capture_fields(fields)
    )


def _field_name_matches_required_leaf(field_name: str, required_name: str) -> bool:
    field_key = _field_name_match_key(field_name)
    required_key = _field_name_match_key(required_name)
    return field_key == required_key or field_key.endswith(f"_{required_key}")


def _field_name_match_key(value: str) -> str:
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _leaf_field_name(field_path: str) -> str:
    return next(
        (
            segment.strip()
            for segment in reversed(field_path.split("."))
            if segment.strip() and not segment.strip().isdigit()
        ),
        "",
    )


def _drop_source_contract_shadow_form_fields(
    *,
    steps: list[NewStepDraft],
    form_fields: list[FormFieldSpec],
) -> tuple[list[NewStepDraft], list[FormFieldSpec], list[str]]:
    if not form_fields:
        return steps, form_fields, []
    source_contract_token_sets = _source_contract_field_token_sets(steps)
    if not source_contract_token_sets:
        return steps, form_fields, []

    kept_fields: list[FormFieldSpec] = []
    dropped_names: set[str] = set()
    for field in form_fields:
        if _form_field_shadows_source_contract(
            field,
            source_contract_token_sets=source_contract_token_sets,
        ):
            dropped_names.add(field.name)
            continue
        kept_fields.append(field)

    if not dropped_names:
        return steps, form_fields, []
    return (
        [_without_form_field_refs(step, dropped_names=dropped_names) for step in steps],
        kept_fields,
        sorted(dropped_names),
    )


def _source_contract_field_token_sets(
    steps: list[NewStepDraft],
) -> frozenset[frozenset[str]]:
    token_sets: set[frozenset[str]] = set()
    for step in steps:
        if not _is_source_json_contract_step(step):
            continue
        token_sets.update(_structured_field_token_sets(step.output_fields))
    return frozenset(token_sets)


def _is_source_json_contract_step(step: NewStepDraft) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in _SOURCE_CONTRACT_INPUT_TYPES
        and step.output_type == OutputType.JSON
        and bool(step.output_fields)
    )


def _structured_field_token_sets(
    fields: list[StructuredFieldDraft] | None,
) -> set[frozenset[str]]:
    token_sets: set[frozenset[str]] = set()
    for field in fields or []:
        tokens = _source_contract_name_tokens(field.name)
        if tokens:
            token_sets.add(frozenset(tokens))
        token_sets.update(_structured_field_token_sets(field.fields))
        token_sets.update(_structured_field_token_sets(field.item_fields))
    return token_sets


def _form_field_shadows_source_contract(
    field: FormFieldSpec,
    *,
    source_contract_token_sets: frozenset[frozenset[str]],
) -> bool:
    candidates = (
        _source_contract_name_tokens(field.name),
        _source_contract_name_tokens(field.label),
    )
    return any(
        candidate
        and any(
            candidate.issubset(source_tokens)
            for source_tokens in source_contract_token_sets
        )
        for candidate in candidates
    )


def _source_contract_name_tokens(value: str) -> frozenset[str]:
    normalized = normalize_discovery_text(value.replace("_", " ").replace("-", " "))
    tokens = tuple(
        _SOURCE_CONTRACT_TOKEN_ALIASES.get(token, token) for token in normalized.split()
    )
    while tokens and tokens[0] in _SOURCE_CONTRACT_FORM_FIELD_PREFIX_TOKENS:
        tokens = tokens[1:]
    return frozenset(tokens)


def _without_form_field_refs(
    step: NewStepDraft,
    *,
    dropped_names: set[str],
) -> NewStepDraft:
    if not step.uses_form_fields:
        return step
    uses_form_fields = [
        field_name
        for field_name in step.uses_form_fields
        if field_name not in dropped_names
    ]
    if uses_form_fields == step.uses_form_fields:
        return step
    return step.model_copy(update={"uses_form_fields": uses_form_fields})


def _log_dropped_source_contract_shadow_fields(
    *,
    field_names: list[str],
) -> None:
    if not field_names:
        return
    logger.info(
        "ai_builder_source_contract_shadow_input_fields_dropped",
        extra={"field_names": field_names},
    )


def _source_capture_fields_by_step_index(
    *,
    steps: list[NewStepDraft],
    terminal_output_schema: JsonObject | None,
) -> dict[int, tuple[SourceCaptureField, ...]]:
    fields_by_index: dict[int, tuple[SourceCaptureField, ...]] = {}
    for index, step in enumerate(steps):
        if not _is_source_capture_step(step):
            continue
        fields = _nearest_downstream_capture_fields(
            steps=steps,
            source_index=index,
            terminal_output_schema=terminal_output_schema,
        )
        if fields:
            fields_by_index[index] = fields
    return fields_by_index


def _is_source_capture_step(step: NewStepDraft) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in _SOURCE_CAPTURE_INPUT_TYPES
        and step.output_type == OutputType.TEXT
    )


def _nearest_downstream_capture_fields(
    *,
    steps: list[NewStepDraft],
    source_index: int,
    terminal_output_schema: JsonObject | None,
) -> tuple[SourceCaptureField, ...]:
    for downstream_index in range(source_index + 1, len(steps)):
        step = steps[downstream_index]
        if step.output_type != OutputType.JSON:
            continue
        fields = _capture_fields_from_output_fields(step.output_fields)
        if (
            not fields
            and terminal_output_schema is not None
            and downstream_index == len(steps) - 1
        ):
            fields = _capture_fields_from_terminal_schema(terminal_output_schema)
        if fields:
            return fields
    return ()


def _capture_fields_from_output_fields(
    output_fields: list[StructuredFieldDraft] | None,
) -> tuple[SourceCaptureField, ...]:
    if not output_fields:
        return ()
    return _dedupe_capture_fields(_iter_output_capture_fields(output_fields))


def _iter_output_capture_fields(
    output_fields: list[StructuredFieldDraft],
) -> list[SourceCaptureField]:
    fields: list[SourceCaptureField] = []
    for field in output_fields:
        object_fields = field.fields if field.field_type == "object" else None
        item_fields = field.item_fields if field.field_type == "array" else None
        if object_fields:
            fields.extend(_iter_output_capture_fields(object_fields))
        elif item_fields:
            fields.extend(_iter_output_capture_fields(item_fields))
        elif field.name:
            fields.append(
                SourceCaptureField(name=field.name, description=field.description)
            )
    return fields


def _capture_fields_from_terminal_schema(
    terminal_output_schema: JsonObject,
) -> tuple[SourceCaptureField, ...]:
    names = schema_leaf_property_names(cast(dict[str, Any], terminal_output_schema))
    return _dedupe_capture_fields(
        [SourceCaptureField(name=name, description=None) for name in names]
    )


def _dedupe_capture_fields(
    fields: list[SourceCaptureField],
) -> tuple[SourceCaptureField, ...]:
    deduped: list[SourceCaptureField] = []
    seen: set[str] = set()
    for field in fields:
        name = field.name.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(SourceCaptureField(name=name, description=field.description))
        if len(deduped) == MAX_SOURCE_CAPTURE_FIELDS:
            break
    return tuple(deduped)


def _clear_terminal_schema_output_fields(
    *,
    steps: list[NewStepDraft],
    terminal_output_schema: JsonObject | None,
) -> list[NewStepDraft]:
    if (
        terminal_output_schema is None
        or not steps
        or steps[-1].output_type != OutputType.JSON
        or steps[-1].output_fields is None
    ):
        return steps
    # Avoid prompt guidance from stale model fields contradicting the exact schema.
    return [*steps[:-1], steps[-1].model_copy(update={"output_fields": None})]


def _apply_terminal_output_schema(
    compiled_steps: list[StepSpec],
    *,
    terminal_output_schema: JsonObject | None,
) -> list[StepSpec]:
    if (
        terminal_output_schema is None
        or not compiled_steps
        or compiled_steps[-1].output_type != OutputType.JSON
    ):
        return compiled_steps
    terminal_step = compiled_steps[-1].model_copy(
        update={
            "output_contract": cast(
                FlowPersistedJsonObject,
                deepcopy(terminal_output_schema),
            )
        }
    )
    return [*compiled_steps[:-1], terminal_step]


def _document_body_writer_step_refs(
    *,
    compiled_steps: list[StepSpec],
    step_indexes: tuple[int, ...],
) -> tuple[str, ...]:
    return tuple(
        compiled_steps[index].plan_step_ref
        for index in step_indexes
        if 0 <= index < len(compiled_steps)
    )


def create_compile_context_from_planning_state(
    planning_state: PlanningState | None,
    *,
    ui_language: str | None = None,
    runtime_input_hint_source: RuntimeInputFieldHintSource | None = None,
) -> CreateCompileContext | None:
    runtime_metadata_state = _runtime_metadata_state_from_planning_state(planning_state)
    metadata_disables_declared_input_fields = (
        _runtime_metadata_disables_declared_input_fields_from_planning_state(
            planning_state
        )
    )
    runtime_input_field_hints = _runtime_input_field_hints_from_source(
        runtime_metadata_state=runtime_metadata_state,
        runtime_input_hint_source=runtime_input_hint_source,
    )
    if planning_state is None:
        if ui_language is None and not runtime_input_field_hints:
            return None
        return CreateCompileContext(
            ui_language=ui_language,
            runtime_metadata_state=runtime_metadata_state,
            runtime_metadata_disables_declared_input_fields=(
                metadata_disables_declared_input_fields
            ),
            runtime_input_field_hints=runtime_input_field_hints,
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
            name=_summary_source_reader_field_name(ui_language),
            description=_summary_source_reader_field_description(ui_language),
        ),
    )


def _summary_source_reader_field_name(ui_language: str | None) -> str:
    if ui_language is None or ui_language.casefold().startswith("sv"):
        return "sammanfattning"
    return "summary"


def _summary_source_reader_field_description(ui_language: str | None) -> str:
    if ui_language is None or ui_language.casefold().startswith("sv"):
        return "Kort sammanfattning grundad i källmaterialet."
    return "Concise summary grounded in the source material."


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
    runtime_input_hint_source: RuntimeInputFieldHintSource | None,
) -> tuple[RuntimeInputFieldHint, ...]:
    if runtime_input_hint_source is None:
        return ()
    source_text = runtime_input_hint_source.aggregated_conversation_text.strip()
    if not source_text:
        return ()
    if not runtime_metadata_allows_input_fields(runtime_metadata_state):
        return ()
    return extract_runtime_input_field_hints(source_text)


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
    referenced_hint_names: set[str],
) -> tuple[list[FormFieldSpec], list[str]]:
    runtime_metadata_state = (
        context.runtime_metadata_state if context is not None else None
    )
    runtime_input_field_hints = (
        context.runtime_input_field_hints if context is not None else ()
    )
    metadata_disables_declared_input_fields = (
        context.runtime_metadata_disables_declared_input_fields
        if context is not None
        else False
    )
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
        runtime_input_field_hints = ()
        if metadata_disables_declared_input_fields:
            return [], []

    fields: list[FormFieldSpec] = []
    dropped_primary_input_field_names: list[str] = []
    for field in intent_fields:
        if is_primary_runtime_input_shadow_field(
            variable_name=field.variable_name,
            field_type=field.field_type,
            runtime_input_type=runtime_input_type,
        ):
            dropped_primary_input_field_names.append(field.variable_name)
            continue
        fields.append(_compile_input_field(field))

    seen = {field.name for field in fields}
    for hint in runtime_input_field_hints:
        if is_primary_runtime_input_shadow_field(
            variable_name=hint.variable_name,
            field_type=hint.field_type,
            runtime_input_type=runtime_input_type,
        ):
            dropped_primary_input_field_names.append(hint.variable_name)
            continue
        if hint.variable_name not in referenced_hint_names:
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
    return fields, dropped_primary_input_field_names


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


def _fold_leading_zero_contract_text_steps(
    *,
    rewrite: SemanticStepRewrite,
    runtime_input_type: InputType,
    final_output_type: OutputType,
) -> SemanticStepRewrite:
    """Fold low-value leading text hops without interpreting their wording.

    Small models sometimes emit a first step whose only job is "receive/use the
    user text" before the first real step. For text runtime input that hop adds
    latency and token cost but no Flow contract. We fold only a leading
    structural no-op into the next semantic target and preserve its instructions
    verbatim by concatenation.
    """

    steps = rewrite.steps
    if runtime_input_type != InputType.TEXT or len(steps) < 2:
        return rewrite

    target_index = _leading_fold_target_index(
        steps=steps,
        final_output_type=final_output_type,
    )
    if target_index is None or target_index == 0:
        return rewrite

    folded_steps = steps[:target_index]
    target_step = steps[target_index]
    merged_instructions = "\n\n".join(
        [*(step.instructions for step in folded_steps), target_step.instructions]
    )
    merged = target_step.model_copy(update={"instructions": merged_instructions})

    logger.info(
        "ai_builder_create_intent_zero_contract_steps_folded",
        extra={
            "folded_count": len(folded_steps),
            "folded_step_names": [step.name for step in folded_steps],
            "target_step_name": target_step.name,
            "runtime_input_type": runtime_input_type.value,
            "final_output_type": final_output_type.value,
        },
    )
    current_to_original_step = {
        current_step: original_step
        for original_step, current_step in rewrite.original_to_current_step.items()
    }
    original_to_current_step = {
        original_step: current_step - target_index
        for current_step, original_step in current_to_original_step.items()
        if current_step >= target_index + 1
    }
    return SemanticStepRewrite(
        steps=[merged, *steps[target_index + 1 :]],
        original_to_current_step=original_to_current_step,
    )


def _normalize_leading_audio_transcription_step(
    *,
    steps: list["SemanticStepIntent"],
    runtime_input_type: InputType,
    backend_audio_transcription_inserted: bool,
) -> SemanticStepRewrite:
    unchanged = SemanticStepRewrite(
        steps=steps,
        original_to_current_step={
            step_number: step_number for step_number in range(1, len(steps) + 1)
        },
    )
    if (
        runtime_input_type != InputType.AUDIO
        or not backend_audio_transcription_inserted
        or len(steps) < 2
    ):
        return unchanged
    first_step = steps[0]
    if not _is_redundant_audio_transcription_step(first_step):
        return unchanged
    if not _has_no_external_step_refs(first_step):
        return unchanged
    if not _is_plain_text_semantic_step(first_step):
        rewritten = first_step.model_copy(
            update={
                "name": _structured_transcript_step_name(first_step),
                "instructions": _structured_transcript_step_instructions(first_step),
            }
        )
        logger.info(
            "ai_builder_redundant_audio_transcription_semantic_step_rewritten",
            extra={"step_name": first_step.name},
        )
        return SemanticStepRewrite(
            steps=[rewritten, *steps[1:]],
            original_to_current_step=unchanged.original_to_current_step,
        )

    logger.info(
        "ai_builder_redundant_audio_transcription_semantic_step_dropped",
        extra={"step_name": first_step.name},
    )
    return SemanticStepRewrite(
        steps=steps[1:],
        original_to_current_step={
            step_number: step_number - 1 for step_number in range(2, len(steps) + 1)
        },
    )


def _redundant_leading_audio_transcription_review_mode(
    *,
    steps: list["SemanticStepIntent"],
    runtime_input_type: InputType,
    backend_audio_transcription_inserted: bool,
) -> FlowStepReviewMode | None:
    if (
        runtime_input_type != InputType.AUDIO
        or not backend_audio_transcription_inserted
        or len(steps) < 2
    ):
        return None
    first_step = steps[0]
    if first_step.review_mode is None:
        return None
    if not _is_redundant_audio_transcription_step(first_step):
        return None
    if not _has_no_external_step_refs(first_step):
        return None
    if not _is_plain_text_semantic_step(first_step):
        return None
    return first_step.review_mode


def _apply_backend_audio_transcription_review_mode(
    *,
    steps: list[NewStepDraft],
    review_mode: FlowStepReviewMode,
) -> list[NewStepDraft]:
    if not steps:
        return steps
    first_step = steps[0]
    if (
        first_step.input_type != InputType.AUDIO
        or first_step.output_type != OutputType.TEXT
        or first_step.input_source != InputSource.FLOW_INPUT
    ):
        return steps
    return [
        first_step.model_copy(update={"review_mode": review_mode}),
        *steps[1:],
    ]


def _backend_audio_transcription_inserted(
    *,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
) -> bool:
    return (
        "audio_to_artifact_report" in pattern_ids
        or FLOW_INPUT_AUDIO_TRANSCRIPTION in chain_steps
    )


def _is_redundant_audio_transcription_step(step: "SemanticStepIntent") -> bool:
    normalized_name = normalize_discovery_text(step.name)
    if contains_any_token_prefix(normalized_name, ("transkrib", "transcrib")):
        return True

    normalized = normalize_discovery_text(f"{step.name} {step.instructions}")
    if contains_any_token_prefix(normalized, ("transkrib", "transcrib")) and any(
        phrase in normalized
        for phrase in (
            "till text",
            "to text",
            "into text",
        )
    ):
        return True

    return contains_any_token_prefix(
        normalized,
        ("audio", "ljud", "tal", "speech"),
    ) and any(
        phrase in normalized
        for phrase in (
            "audio to text",
            "speech to text",
            "ljud till text",
            "tal till text",
        )
    )


def _structured_transcript_step_name(step: "SemanticStepIntent") -> str:
    normalized = normalize_discovery_text(f"{step.name} {step.instructions}")
    if contains_any_token_prefix(normalized, ("transkrib", "ljud", "möte")):
        return "Strukturera transkription"
    return "Structure transcript"


def _structured_transcript_step_instructions(step: "SemanticStepIntent") -> str:
    normalized = normalize_discovery_text(f"{step.name} {step.instructions}")
    if contains_any_token_prefix(normalized, ("transkrib", "ljud", "möte")):
        prefix = (
            "Strukturera den redan transkriberade texten från föregående steg. "
            "Begär inte en ny ljudtranskribering; bevara tider och talarbyten "
            "endast när de finns i texten."
        )
    else:
        prefix = (
            "Structure the already transcribed text from the previous step. "
            "Do not request a new audio transcription; preserve timestamps and "
            "speaker turns only when they are present in the text."
        )
    return f"{prefix}\n\n{step.instructions}"


def _is_plain_text_semantic_step(step: "SemanticStepIntent") -> bool:
    return (
        _declared_output_type(step) == OutputType.TEXT
        and not step.output_fields
        and not step.uses_form_fields
        and _has_no_external_step_refs(step)
    )


def _has_no_external_step_refs(step: "SemanticStepIntent") -> bool:
    return (
        not step.knowledge_refs
        and not step.mcp_server_refs
        and not step.mcp_tool_refs
        and not step.uses_previous_fields
        and not step.uses_previous_outputs
        and not step.citations_requested
    )


def _leading_fold_target_index(
    *,
    steps: list["SemanticStepIntent"],
    final_output_type: OutputType,
) -> int | None:
    folded_count = 0
    for index, step in enumerate(steps[:-1]):
        if not _is_zero_contract_text_step(step):
            break
        candidate_index = index + 1
        candidate = steps[candidate_index]
        if not _can_absorb_leading_zero_contract_step(
            candidate=candidate,
            candidate_index=candidate_index,
            step_count=len(steps),
            final_output_type=final_output_type,
        ):
            break
        folded_count += 1

    return folded_count if folded_count else None


def _can_absorb_leading_zero_contract_step(
    *,
    candidate: "SemanticStepIntent",
    candidate_index: int,
    step_count: int,
    final_output_type: OutputType,
) -> bool:
    if (
        candidate.output_fields
        or candidate.uses_form_fields
        or candidate.mcp_server_refs
        or candidate.mcp_tool_refs
    ):
        return True
    if candidate.citations_requested:
        return True
    if _declared_output_type(candidate) in _DOCUMENT_OUTPUT_TYPES | {OutputType.JSON}:
        return True
    return candidate_index == step_count - 1 and final_output_type != OutputType.TEXT


def _is_zero_contract_text_step(step: "SemanticStepIntent") -> bool:
    return (
        _declared_output_type(step) == OutputType.TEXT
        and not step.output_fields
        and not step.uses_form_fields
        and not step.model_ref
        and not step.knowledge_refs
        and not step.mcp_server_refs
        and not step.mcp_tool_refs
        and not step.uses_previous_fields
        and not step.uses_previous_outputs
        and not step.citations_requested
        and step.review_mode is None
    )


def _declared_output_type(step: "SemanticStepIntent") -> OutputType:
    try:
        return OutputType(step.output_type) if step.output_type else OutputType.TEXT
    except ValueError:
        return OutputType.TEXT


def _compile_input_field(field: FlowInputFieldIntent) -> FormFieldSpec:
    return FormFieldSpec(
        name=field.variable_name,
        label=field.label,
        type=field.field_type,
        required=field.required,
        options=list(field.options) or None,
    )


def _attach_unreferenced_form_fields_to_final_step(
    *,
    steps: list[NewStepDraft],
    known_field_order: list[str],
    semantic_step_count: int,
) -> list[NewStepDraft]:
    if not steps or not known_field_order:
        return steps
    referenced = {field_name for step in steps for field_name in step.uses_form_fields}
    unreferenced = [
        field_name for field_name in known_field_order if field_name not in referenced
    ]
    if not unreferenced:
        return steps
    # With one semantic step there is no competing field consumer; larger flows
    # must surface unused fields to the critic instead of guessing a target.
    if semantic_step_count != 1:
        return steps
    final_step = steps[-1]
    return [
        *steps[:-1],
        final_step.model_copy(
            update={
                "uses_form_fields": [
                    *final_step.uses_form_fields,
                    *unreferenced,
                ]
            }
        ),
    ]

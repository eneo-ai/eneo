from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from intric.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_create_dataflow import (
    auto_bind_targeted_underlag_for_text_composer,
)
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    FlowCreateDraft,
)
from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_token_prefix,
    normalize_discovery_text,
)
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_type_values,
    builder_output_type_values,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import (
    AIBuilderMCPResourceInput,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_new_step_schema import (
    build_review_mode_schema,
    build_structured_field_schema,
)
from intric.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    NO_EXTRA_RUNTIME_METADATA,
    RuntimeInputFieldHint,
    RuntimeMetadataState,
    normalize_runtime_metadata_state,
)
from intric.flows.ai_builder.ai_builder_step_skeleton import (
    StepSkeletonOutputTypeDrift,
    StepSkeletonSemanticContent,
    materialize_step_skeleton,
    resolve_step_skeleton_patterns,
)
from intric.flows.ai_builder.ai_builder_structured_field_normalizer import (
    looks_like_structured_field_spec,
    normalize_structured_field_list,
)
from intric.flows.ai_builder.pattern_registry import (
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    PATTERN_REGISTRY,
)
from intric.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommit,
    ArchitectureCommitDraft,
    PlanningState,
)
from intric.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH
from intric.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.flow_review_policy import FlowStepReviewMode

OUTLINE_FLOW_TOOL_NAME = "outline_flow"
# Safety guard against runaway tool output. This should not be a practical
# product cap for legitimate advanced flows.
MAX_OUTLINE_STEPS = 256

_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
_COMPARISON_FAN_IN_PATTERN_IDS = frozenset({"comparison"})
_OUTLINE_STEP_BACKEND_OWNED_KEYS = frozenset(
    {
        "aggregate_prior_outputs",
        "document_delivery_mode",
        "input_bindings",
        "input_config",
        "input_contract",
        "input_source",
        "input_strategy",
        "input_type",
        "output_config",
        "output_contract",
        "output_mode",
        "plan_step_ref",
        "runtime_max_files",
        "runtime_required",
        "runtime_upload",
        "uses_previous_fields",
        "uses_previous_outputs",
    }
)
logger = logging.getLogger(__name__)
_OUTLINE_STEP_ONLY_ROOT_IGNORED_KEYS = frozenset(
    {
        "citations_requested",
        "knowledge_refs",
        "mcp_server_refs",
        "mcp_tool_refs",
        "model_ref",
        "name",
        "output_fields",
        "output_type",
        "reasoning",
        "review_mode",
        "task",
        "uses_input_fields",
    }
)
_OUTLINE_ROOT_IGNORED_KEYS = (
    _OUTLINE_STEP_BACKEND_OWNED_KEYS | _OUTLINE_STEP_ONLY_ROOT_IGNORED_KEYS
)
_DOCUMENT_MATERIAL_RUNTIME_INPUT_TYPES = frozenset({InputType.DOCUMENT, InputType.FILE})
_DOCUMENT_SCOPE_AGGREGATION_VALUES = frozenset(
    {
        "multiple_documents_case",
        "multiple_pdfs_same_run",
        "same_run_multiple_documents",
    }
)
ArchitectureEnvelope = ArchitectureCommit | ArchitectureCommitDraft


@dataclass(frozen=True, slots=True)
class OutlineCompileContext:
    """Server-owned create-mode architecture envelope.

    The LLM-facing outline is semantic. Core architecture facts already
    resolved by discovery must not be re-decided by the model when it
    proposes a plan.
    """

    runtime_input_type: InputType | None = None
    final_output_type: OutputType | None = None
    final_output_mode: OutputMode | None = None
    pattern_ids: tuple[str, ...] = ()
    pattern_chain_steps: tuple[str, ...] = ()
    ui_language: str | None = None
    runtime_metadata_state: RuntimeMetadataState | None = None
    runtime_input_field_hints: tuple[RuntimeInputFieldHint, ...] = ()
    aggregation_intent: AggregationIntent = "linear"


def outline_runtime_input_type_values() -> list[str]:
    """Input types the outline compiler can safely place on the first step."""

    return [
        value for value in builder_input_type_values() if value != InputType.ANY.value
    ]


class OutlineRuntimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_type: str = InputType.TEXT.value
    required: bool = True
    max_files: int | None = None

    @field_validator("input_type")
    @classmethod
    def _validate_input_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in outline_runtime_input_type_values():
            allowed = ", ".join(outline_runtime_input_type_values())
            raise ValueError(f"input_type must be one of: {allowed}")
        return normalized

    @field_validator("max_files")
    @classmethod
    def _validate_max_files(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("max_files must be at least 1 when provided.")
        return value


class OutlineInputField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable_name: str
    label: str
    field_type: str = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)

    @field_validator("variable_name", "label")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Input fields require non-empty text values.")
        return normalized

    @field_validator("field_type")
    @classmethod
    def _validate_field_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in {"text", "number", "date", "select", "multiselect"}:
            raise ValueError(
                "field_type must be one of: text, number, date, select, multiselect"
            )
        return normalized

    @field_validator("options")
    @classmethod
    def _normalize_options(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for option in value:
            candidate = option.strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized


class OutlineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    task: str
    output_type: str | None = None
    output_fields: list[StructuredFieldDraft] | None = None
    uses_input_fields: list[str] = Field(default_factory=list)
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    mcp_tool_refs: list[str] = Field(default_factory=list)
    citations_requested: bool = False
    review_mode: FlowStepReviewMode | None = None

    @field_validator("name", "task")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Outline steps require non-empty text values.")
        if "{{" in normalized or "}}" in normalized:
            raise ValueError("Outline steps must not contain template variables.")
        return normalized

    @field_validator("output_type")
    @classmethod
    def _validate_output_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized not in builder_output_type_values():
            allowed = ", ".join(builder_output_type_values())
            raise ValueError(f"output_type must be one of: {allowed}")
        return normalized

    @field_validator("output_fields", mode="before")
    @classmethod
    def _normalize_output_fields(cls, value: Any) -> Any:
        return normalize_structured_field_list(value)

    @field_validator(
        "uses_input_fields", "knowledge_refs", "mcp_server_refs", "mcp_tool_refs"
    )
    @classmethod
    def _normalize_string_list(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            candidate = raw.strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized

    @field_validator("model_ref")
    @classmethod
    def _normalize_optional_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_resource_mode(self) -> "OutlineStep":
        if self.knowledge_refs and (self.mcp_server_refs or self.mcp_tool_refs):
            raise ValueError(
                "Outline steps cannot combine knowledge_refs with MCP refs."
            )
        return self


def _empty_outline_input_fields() -> list[OutlineInputField]:
    return []


class FlowCreateOutline(BaseModel):
    """Small LLM-facing contract for create mode.

    The outline is semantic. It intentionally omits Flow mechanics such as
    input_source, output_mode, input_bindings, runtime config, step refs, and
    document output config; the backend compiler owns those.
    """

    model_config = ConfigDict(extra="forbid")

    flow_name: str
    flow_description: str | None = None
    plan_rationale: str
    runtime_input: OutlineRuntimeInput = Field(default_factory=OutlineRuntimeInput)
    final_output_type: str = OutputType.TEXT.value
    input_fields: list[OutlineInputField] = Field(
        default_factory=_empty_outline_input_fields
    )
    steps: list[OutlineStep]
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("flow_name", "plan_rationale")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Outline fields require non-empty text values.")
        if "{{" in normalized or "}}" in normalized:
            raise ValueError("Outline fields must not contain template variables.")
        return normalized

    @field_validator("flow_description")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if "{{" in normalized or "}}" in normalized:
            raise ValueError("flow_description must not contain template variables.")
        return normalized or None

    @field_validator("final_output_type")
    @classmethod
    def _validate_final_output_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in builder_output_type_values():
            allowed = ", ".join(builder_output_type_values())
            raise ValueError(f"final_output_type must be one of: {allowed}")
        return normalized

    @field_validator("steps")
    @classmethod
    def _validate_steps(cls, value: list[OutlineStep]) -> list[OutlineStep]:
        if not value:
            raise ValueError("outline_flow requires at least one step.")
        if len(value) > MAX_OUTLINE_STEPS:
            raise ValueError(
                f"outline_flow supports at most {MAX_OUTLINE_STEPS} semantic steps."
            )
        return value

    @field_validator("assumptions")
    @classmethod
    def _normalize_assumptions(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            candidate = raw.strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized


def parse_outline_flow_arguments(arguments: dict[str, Any]) -> FlowCreateOutline:
    try:
        return FlowCreateOutline.model_validate(_normalize_outline_arguments(arguments))
    except ValidationError as error:
        raise OutlineFlowArgumentError(error) from error


class OutlineFlowArgumentError(ValueError):
    """Safe outline validation feedback for logs and model repair prompts.

    Pydantic's default message can include input excerpts. The AI Builder logs
    and retry prompts only need field paths, error types, and human-readable
    validation messages.
    """

    def __init__(self, error: ValidationError) -> None:
        self.issues = safe_validation_issues(error)
        super().__init__("; ".join(self.issues))


def safe_validation_issues(error: ValidationError) -> tuple[str, ...]:
    issues: list[str] = []
    for item in error.errors(
        include_context=False,
        include_input=False,
        include_url=False,
    ):
        loc = ".".join(str(part) for part in item.get("loc", ())) or "root"
        message = str(item.get("msg") or "Validation failed")
        issue_type = str(item.get("type") or "validation_error")
        issues.append(f"{loc}: {message} [{issue_type}]")
    return tuple(issues) or ("outline_flow validation failed [validation_error]",)


def _normalize_outline_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Strip backend-owned mechanics from outline-flow tool arguments.

    Outline mode is semantic. Some model outputs may still include fields
    outside that contract, but those fields must never become the source of
    truth for Flow wiring.
    """

    normalized = {
        key: value
        for key, value in arguments.items()
        if key not in _OUTLINE_ROOT_IGNORED_KEYS
    }
    raw_steps = normalized.get("steps")
    if isinstance(raw_steps, list):
        typed_steps = cast(list[Any], raw_steps)
        normalized["steps"] = _normalize_outline_steps(typed_steps)
    return normalized


def _normalize_outline_steps(raw_steps: list[Any]) -> list[Any]:
    """Recover common small-model shape errors without weakening Flow models.

    Outline steps are semantic units with a task. When a model accidentally
    places an output field object directly inside steps[], keep that semantic
    schema hint by attaching it to the previous step instead of treating it as a
    broken step.
    """

    steps: list[Any] = []
    for raw_step in raw_steps:
        step = _strip_backend_owned_step_keys(raw_step)
        if _looks_like_orphan_output_field(step):
            _attach_orphan_output_field(steps, cast(dict[str, Any], step))
            continue
        steps.append(step)
    return steps


def _strip_backend_owned_step_keys(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {
        key: step_value
        for key, step_value in cast(dict[str, Any], value).items()
        if key not in _OUTLINE_STEP_BACKEND_OWNED_KEYS
    }


def _looks_like_orphan_output_field(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    raw = cast(dict[str, Any], value)
    if "task" in raw:
        return False
    return looks_like_structured_field_spec(raw) and any(
        key in raw
        for key in (
            "description",
            "field_type",
            "fields",
            "item_fields",
            "items",
            "properties",
            "required",
            "type",
        )
    )


def _attach_orphan_output_field(
    steps: list[Any],
    field: dict[str, Any],
) -> None:
    if not steps or not isinstance(steps[-1], dict):
        return
    previous_step = cast(dict[str, Any], steps[-1])
    output_fields = previous_step.get("output_fields")
    if isinstance(output_fields, list):
        normalized_output_fields = [*cast(list[Any], output_fields), field]
    elif output_fields is None:
        normalized_output_fields = [field]
    else:
        normalized_output_fields = [output_fields, field]
    previous_step["output_fields"] = normalized_output_fields
    previous_step.setdefault("output_type", OutputType.JSON.value)


def outline_compile_context_from_planning_state(
    planning_state: PlanningState | None,
    *,
    ui_language: str | None = None,
    runtime_input_field_hints: tuple[RuntimeInputFieldHint, ...] = (),
) -> OutlineCompileContext | None:
    if planning_state is None:
        if ui_language is None and not runtime_input_field_hints:
            return None
        return OutlineCompileContext(
            ui_language=ui_language,
            runtime_input_field_hints=runtime_input_field_hints,
        )
    architecture = _architecture_envelope_from_planning_state(planning_state)
    runtime_metadata_state = runtime_metadata_state_from_planning_state(planning_state)
    return OutlineCompileContext(
        runtime_input_type=(
            _runtime_input_type_from_architecture(architecture)
            or _runtime_input_type_from_planning_state(planning_state)
        ),
        final_output_type=(
            _final_output_type_from_architecture(architecture)
            or _final_output_type_from_planning_state(planning_state)
        ),
        final_output_mode=_final_output_mode_from_architecture(architecture),
        pattern_ids=_pattern_ids_from_architecture(architecture),
        pattern_chain_steps=_pattern_chain_steps_from_architecture(architecture),
        ui_language=ui_language,
        runtime_metadata_state=runtime_metadata_state,
        runtime_input_field_hints=runtime_input_field_hints,
        aggregation_intent=_aggregation_intent_for_compile_context(
            planning_state,
            architecture,
        ),
    )


def runtime_metadata_state_from_planning_state(
    planning_state: PlanningState | None,
) -> RuntimeMetadataState | None:
    if planning_state is None:
        return None
    slot = planning_state.resolved_slots.get("runtime_metadata_fields")
    return normalize_runtime_metadata_state(slot.value if slot is not None else None)


def compile_outline_to_create_draft(
    outline: FlowCreateOutline,
    *,
    context: OutlineCompileContext | None = None,
) -> FlowCreateDraft:
    runtime_input_type = (
        context.runtime_input_type
        if context is not None and context.runtime_input_type is not None
        else InputType(outline.runtime_input.input_type)
    )
    final_output_type = (
        context.final_output_type
        if context is not None and context.final_output_type is not None
        else OutputType(outline.final_output_type)
    )
    referenced_hint_names = {
        field_name
        for outline_step in outline.steps
        for field_name in outline_step.uses_input_fields
    }
    form_fields, dropped_primary_input_field_names = _compile_form_fields(
        outline_fields=outline.input_fields,
        context=context,
        runtime_input_type=runtime_input_type,
        referenced_hint_names=referenced_hint_names,
    )
    known_field_order = [field.variable_name for field in form_fields]
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
    outline_steps = _normalize_leading_audio_transcription_step(
        steps=list(outline.steps),
        runtime_input_type=runtime_input_type,
        backend_audio_transcription_inserted=backend_audio_transcription_inserted,
    )
    backend_audio_transcription_review_mode = (
        _redundant_leading_audio_transcription_review_mode(
            steps=list(outline.steps),
            runtime_input_type=runtime_input_type,
            backend_audio_transcription_inserted=backend_audio_transcription_inserted,
        )
    )
    outline_steps = _fold_leading_zero_contract_text_steps(
        steps=outline_steps,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
    )

    semantic_steps: list[StepSkeletonSemanticContent] = []
    for outline_step in outline_steps:
        uses_form_fields = [
            field_name
            for field_name in outline_step.uses_input_fields
            if field_name in known_field_names
        ]
        dropped_primary_input_field_names.extend(
            [
                field_name
                for field_name in outline_step.uses_input_fields
                if field_name not in known_field_names
                and is_primary_runtime_input_shadow_field(
                    variable_name=field_name,
                    field_type="text",
                    runtime_input_type=runtime_input_type,
                )
            ]
        )
        semantic_steps.append(
            _semantic_content_from_outline_step(
                outline_step,
                uses_form_fields=uses_form_fields,
            )
        )

    try:
        skeleton_plan = materialize_step_skeleton(
            runtime_input_type=runtime_input_type,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
            pattern_ids=pattern_ids,
            chain_steps=chain_steps,
            aggregation_intent=(
                context.aggregation_intent if context is not None else "linear"
            ),
            runtime_required=outline.runtime_input.required,
            runtime_max_files=outline.runtime_input.max_files,
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
    steps = _attach_unreferenced_form_fields_to_final_step(
        steps=steps,
        known_field_order=known_field_order,
        semantic_step_count=len(semantic_steps),
    )
    _log_dropped_primary_input_shadow_fields(
        field_names=dropped_primary_input_field_names,
        runtime_input_type=runtime_input_type,
    )
    steps = auto_bind_targeted_underlag_for_text_composer(
        steps,
        aggregation_intent=(
            context.aggregation_intent if context is not None else "linear"
        ),
    )

    return FlowCreateDraft(
        flow_name=outline.flow_name,
        flow_description=outline.flow_description,
        plan_rationale=outline.plan_rationale,
        assumptions=outline.assumptions,
        form_fields=form_fields,
        steps=steps,
    )


def _semantic_content_from_outline_step(
    step: OutlineStep,
    *,
    uses_form_fields: list[str],
) -> StepSkeletonSemanticContent:
    return StepSkeletonSemanticContent(
        name=step.name,
        instructions=step.task,
        requested_output_type=(
            OutputType(step.output_type) if step.output_type is not None else None
        ),
        output_fields=tuple(step.output_fields or ()),
        uses_form_fields=tuple(uses_form_fields),
        model_ref=step.model_ref,
        knowledge_refs=tuple(step.knowledge_refs),
        mcp_server_refs=tuple(step.mcp_server_refs),
        mcp_tool_refs=tuple(step.mcp_tool_refs),
        citations_requested=step.citations_requested,
        review_mode=step.review_mode,
    )


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


def attach_selected_mcp_refs_to_explicit_outline_steps(
    outline: FlowCreateOutline,
    *,
    selected_server_refs: set[str] | frozenset[str],
    catalog: AIBuilderResourceCatalog,
) -> FlowCreateOutline:
    """Attach selected MCP refs when an outline step explicitly names them.

    User selection is the permission boundary. The text match is only a
    catalog-backed recovery path for outline steps that already say which MCP
    they intend to use but omit the mechanical `mcp_*_refs` fields.
    """

    selected_refs = frozenset(selected_server_refs)
    if not selected_refs:
        return outline

    changed = False
    patched_steps: list[dict[str, object]] = []
    updated_steps: list[OutlineStep] = []
    for step in outline.steps:
        if step.mcp_server_refs or step.mcp_tool_refs or step.knowledge_refs:
            updated_steps.append(step)
            continue

        step_text = f"{step.name}\n{step.task}"
        mentioned_server_refs = catalog.refs_mentioned_in_text(
            kind="mcp_server",
            text=step_text,
            allowed_refs=selected_refs,
        )
        selected_tool_refs = _tool_refs_for_servers(
            catalog=catalog,
            server_refs=selected_refs,
        )
        mentioned_tool_refs = catalog.refs_mentioned_in_text(
            kind="mcp_tool",
            text=step_text,
            allowed_refs=selected_tool_refs,
        )
        if not mentioned_server_refs and not mentioned_tool_refs:
            updated_steps.append(step)
            continue

        selected_mcp_server_refs = (
            [] if mentioned_tool_refs else sorted(mentioned_server_refs)
        )
        selected_mcp_tool_refs = sorted(mentioned_tool_refs)
        # Tool refs are enough: resource canonicalization adds the parent
        # server without widening to sibling tools. If only the server was
        # named, keep the server ref so existing server-level behavior applies.
        updated_steps.append(
            step.model_copy(
                update={
                    "mcp_server_refs": selected_mcp_server_refs,
                    "mcp_tool_refs": selected_mcp_tool_refs,
                }
            )
        )
        patched_steps.append(
            {
                "step_name": step.name,
                "mcp_server_refs": selected_mcp_server_refs,
                "mcp_tool_refs": selected_mcp_tool_refs,
            }
        )
        changed = True

    if not changed:
        return outline
    logger.info(
        "ai_builder_selected_mcp_refs_attached_to_outline_steps",
        extra={
            "patched_step_count": len(patched_steps),
            "patched_steps": patched_steps,
            "selected_mcp_server_refs": sorted(selected_refs),
        },
    )
    return outline.model_copy(update={"steps": updated_steps})


def _tool_refs_for_servers(
    *,
    catalog: AIBuilderResourceCatalog,
    server_refs: frozenset[str],
) -> frozenset[str]:
    refs: set[str] = set()
    for server_ref in server_refs:
        refs.update(catalog.mcp_tool_refs_for_server(server_ref))
    return frozenset(refs)


def _runtime_input_type_from_planning_state(state: PlanningState) -> InputType | None:
    slot = state.resolved_slots.get("primary_runtime_input")
    if slot is None:
        return None
    return {
        "audio": InputType.AUDIO,
        "document": InputType.DOCUMENT,
        "documents": InputType.DOCUMENT,
        "file": InputType.FILE,
        "json": InputType.JSON,
        "text": InputType.TEXT,
        "text_and_documents": InputType.FILE,
    }.get(slot.value)


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
        return InputType(architecture.tuples_chain[0].input_type)
    except ValueError:
        return None


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

    document_scope = _resolved_slot_value(state, "document_material_scope")
    if (
        runtime_input_type in _DOCUMENT_MATERIAL_RUNTIME_INPUT_TYPES
        and document_scope in _DOCUMENT_SCOPE_AGGREGATION_VALUES
    ):
        return "aggregate"

    comparison_scope = _resolved_slot_value(state, "comparison_scope")
    if comparison_scope == "same_run_compare":
        return "compare"
    if (
        runtime_input_type in _DOCUMENT_MATERIAL_RUNTIME_INPUT_TYPES
        and comparison_scope
        in {"same_run_multiple_documents", "multiple_documents_case"}
    ):
        return "compare"
    return "linear"


def _resolved_slot_value(state: PlanningState, slot_name: str) -> str | None:
    slot = state.resolved_slots.get(slot_name)
    return slot.value if slot is not None else None


def build_outline_flow_tool_schema(
    available_models: list[dict[str, Any]] | None = None,
    available_kbs: list[dict[str, Any]] | None = None,
    available_mcps: AIBuilderMCPResourceInput = None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
) -> dict[str, Any]:
    catalog = resource_catalog or build_ai_builder_resource_catalog(
        available_models=available_models,
        available_kbs=available_kbs,
        available_mcps=available_mcps,
    )
    model_refs = catalog.small_ref_enum_for_kind("model")
    kb_refs = catalog.small_ref_enum_for_kind("knowledge_base")
    # Keep MCP refs free-form. Catalog resolution and quality feedback handle
    # unknown or unrelated MCP selections without coercing the planner into an
    # available-but-wrong server when the requested MCP is absent.
    mcp_server_refs: list[str] | None = None
    mcp_tool_refs: list[str] | None = None
    return {
        "type": "function",
        "function": {
            "name": OUTLINE_FLOW_TOOL_NAME,
            "description": (
                "Submit a semantic create-flow outline. Describe what the flow "
                "should do; the backend will compile Flow mechanics such as "
                "input_source, runtime uploads, step refs, output_mode, and "
                "underlag/input_bindings."
            ),
            "parameters": {
                "type": "object",
                "required": [
                    "flow_name",
                    "plan_rationale",
                    "steps",
                ],
                "properties": {
                    "flow_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_FLOW_NAME_LENGTH,
                        "description": (
                            "Human-readable user-facing flow name in the user's "
                            "language. Use words and spaces, not snake_case, "
                            "internal pattern ids, or output-type token chains."
                        ),
                    },
                    "flow_description": {"type": ["string", "null"]},
                    "plan_rationale": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Short user-visible explanation of the design.",
                    },
                    "input_fields": {
                        "type": "array",
                        "description": (
                            "Optional secondary inmatningsfält/input variables the "
                            "user fills in when running the flow. Do not include the "
                            "primary text/document/file/audio material being processed."
                        ),
                        "items": _input_field_schema(),
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_OUTLINE_STEPS,
                        "items": _outline_step_schema(
                            model_refs=model_refs,
                            kb_refs=kb_refs,
                            mcp_server_refs=mcp_server_refs,
                            mcp_tool_refs=mcp_tool_refs,
                        ),
                    },
                    "assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
    }


def _input_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["variable_name", "label", "field_type", "required"],
        "properties": {
            "variable_name": {"type": "string", "minLength": 1},
            "label": {"type": "string", "minLength": 1},
            "field_type": {
                "type": "string",
                "enum": ["text", "number", "date", "select", "multiselect"],
            },
            "required": {"type": "boolean"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }


def _outline_step_schema(
    *,
    model_refs: list[str] | None = None,
    kb_refs: list[str] | None = None,
    mcp_server_refs: list[str] | None = None,
    mcp_tool_refs: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["name", "task"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "task": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Plain task instructions. Do not include template variables "
                    "or underlag/input_bindings syntax."
                ),
            },
            "output_type": {
                "type": ["string", "null"],
                "enum": [*builder_output_type_values(), None],
            },
            "output_fields": {
                "type": ["array", "null"],
                "description": "Semantic structured fields this step should produce.",
                "items": build_structured_field_schema(),
            },
            "uses_input_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Names of input_fields this step should consider. The backend "
                    "compiles them into underlag/input_bindings."
                ),
            },
            "model_ref": {
                "type": ["string", "null"],
                "description": "Optional portable model slot ref to use for this step.",
            },
            "knowledge_refs": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": (
                    "Portable knowledge slot refs this semantic step needs. "
                    "Do not combine with MCP refs on the same step."
                ),
            },
            "mcp_server_refs": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": (
                    "Portable MCP server slot refs this semantic step needs. Use only "
                    "for external tools/live data and never together with knowledge_refs."
                ),
            },
            "mcp_tool_refs": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": (
                    "Portable MCP tool slot refs for least-privilege tool access. "
                    "Prefer tool refs over whole-server refs when possible."
                ),
            },
            "citations_requested": {"type": "boolean", "default": False},
            "review_mode": build_review_mode_schema(),
        },
        "additionalProperties": False,
    }
    properties = cast(dict[str, Any], schema["properties"])
    if model_refs is not None:
        model_ref_property = cast(dict[str, Any], properties["model_ref"])
        model_ref_property["enum"] = [*model_refs, None]
    if kb_refs is not None:
        knowledge_ref_property = cast(dict[str, Any], properties["knowledge_refs"])
        knowledge_ref_items = cast(dict[str, Any], knowledge_ref_property["items"])
        knowledge_ref_items["enum"] = kb_refs
    if mcp_server_refs is not None:
        server_refs_property = cast(dict[str, Any], properties["mcp_server_refs"])
        server_refs_items = cast(dict[str, Any], server_refs_property["items"])
        server_refs_items["enum"] = mcp_server_refs
    if mcp_tool_refs is not None:
        tool_refs_property = cast(dict[str, Any], properties["mcp_tool_refs"])
        tool_refs_items = cast(dict[str, Any], tool_refs_property["items"])
        tool_refs_items["enum"] = mcp_tool_refs
    return schema


def _compile_form_fields(
    *,
    outline_fields: list[OutlineInputField],
    context: OutlineCompileContext | None,
    runtime_input_type: InputType | None,
    referenced_hint_names: set[str],
) -> tuple[list[CreateFormFieldDraft], list[str]]:
    runtime_metadata_state = (
        context.runtime_metadata_state if context is not None else None
    )
    runtime_input_field_hints = (
        context.runtime_input_field_hints if context is not None else ()
    )
    if runtime_metadata_state == NO_EXTRA_RUNTIME_METADATA:
        _log_dropped_runtime_metadata_input_fields(
            field_names=[
                *(field.variable_name for field in outline_fields),
                *(hint.variable_name for hint in runtime_input_field_hints),
            ],
            runtime_metadata_state=NO_EXTRA_RUNTIME_METADATA,
        )
        return [], []

    fields: list[CreateFormFieldDraft] = []
    dropped_primary_input_field_names: list[str] = []
    for field in outline_fields:
        if is_primary_runtime_input_shadow_field(
            variable_name=field.variable_name,
            field_type=field.field_type,
            runtime_input_type=runtime_input_type,
        ):
            dropped_primary_input_field_names.append(field.variable_name)
            continue
        fields.append(_compile_input_field(field))

    seen = {field.variable_name for field in fields}
    for hint in context.runtime_input_field_hints if context is not None else ():
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
            CreateFormFieldDraft(
                variable_name=hint.variable_name,
                label=hint.label,
                field_type=cast(Any, hint.field_type),
                required=hint.required,
                options=list(hint.options),
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
    steps: list["OutlineStep"],
    runtime_input_type: InputType,
    final_output_type: OutputType,
) -> list["OutlineStep"]:
    """Fold low-value leading text hops without interpreting their wording.

    Small models sometimes emit a first step whose only job is "receive/use the
    user text" before the first real step. For text runtime input that hop adds
    latency and token cost but no Flow contract. We fold only a leading
    structural no-op into the next semantic target and preserve its instructions
    verbatim by concatenation.
    """

    if runtime_input_type != InputType.TEXT or len(steps) < 2:
        return steps

    target_index = _leading_fold_target_index(
        steps=steps,
        final_output_type=final_output_type,
    )
    if target_index is None or target_index == 0:
        return steps

    folded_steps = steps[:target_index]
    target_step = steps[target_index]
    merged_task = "\n\n".join([*(step.task for step in folded_steps), target_step.task])
    merged = target_step.model_copy(update={"task": merged_task})

    logger.info(
        "ai_builder_outline_zero_contract_steps_folded",
        extra={
            "folded_count": len(folded_steps),
            "folded_step_names": [step.name for step in folded_steps],
            "target_step_name": target_step.name,
            "runtime_input_type": runtime_input_type.value,
            "final_output_type": final_output_type.value,
        },
    )
    return [merged, *steps[target_index + 1 :]]


def _normalize_leading_audio_transcription_step(
    *,
    steps: list["OutlineStep"],
    runtime_input_type: InputType,
    backend_audio_transcription_inserted: bool,
) -> list["OutlineStep"]:
    if (
        runtime_input_type != InputType.AUDIO
        or not backend_audio_transcription_inserted
        or len(steps) < 2
    ):
        return steps
    first_step = steps[0]
    if not _is_redundant_audio_transcription_step(first_step):
        return steps
    if not _has_no_external_step_refs(first_step):
        return steps
    if not _is_plain_text_semantic_step(first_step):
        rewritten = first_step.model_copy(
            update={
                "name": _structured_transcript_step_name(first_step),
                "task": _structured_transcript_step_task(first_step),
            }
        )
        logger.info(
            "ai_builder_redundant_audio_transcription_outline_step_rewritten",
            extra={"step_name": first_step.name},
        )
        return [rewritten, *steps[1:]]

    logger.info(
        "ai_builder_redundant_audio_transcription_outline_step_dropped",
        extra={"step_name": first_step.name},
    )
    return steps[1:]


def _redundant_leading_audio_transcription_review_mode(
    *,
    steps: list["OutlineStep"],
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


def _is_redundant_audio_transcription_step(step: "OutlineStep") -> bool:
    normalized_name = normalize_discovery_text(step.name)
    if contains_any_token_prefix(normalized_name, ("transkrib", "transcrib")):
        return True

    normalized = normalize_discovery_text(f"{step.name} {step.task}")
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


def _structured_transcript_step_name(step: "OutlineStep") -> str:
    normalized = normalize_discovery_text(f"{step.name} {step.task}")
    if contains_any_token_prefix(normalized, ("transkrib", "ljud", "möte")):
        return "Strukturera transkription"
    return "Structure transcript"


def _structured_transcript_step_task(step: "OutlineStep") -> str:
    normalized = normalize_discovery_text(f"{step.name} {step.task}")
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
    return f"{prefix}\n\n{step.task}"


def _is_plain_text_semantic_step(step: "OutlineStep") -> bool:
    return (
        _declared_output_type(step) == OutputType.TEXT
        and not step.output_fields
        and not step.uses_input_fields
        and _has_no_external_step_refs(step)
    )


def _has_no_external_step_refs(step: "OutlineStep") -> bool:
    return (
        not step.knowledge_refs
        and not step.mcp_server_refs
        and not step.mcp_tool_refs
        and not step.citations_requested
    )


def _leading_fold_target_index(
    *,
    steps: list["OutlineStep"],
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
    candidate: "OutlineStep",
    candidate_index: int,
    step_count: int,
    final_output_type: OutputType,
) -> bool:
    if (
        candidate.output_fields
        or candidate.uses_input_fields
        or candidate.mcp_server_refs
        or candidate.mcp_tool_refs
    ):
        return True
    if candidate.citations_requested:
        return True
    if _declared_output_type(candidate) in _DOCUMENT_OUTPUT_TYPES | {OutputType.JSON}:
        return True
    return candidate_index == step_count - 1 and final_output_type != OutputType.TEXT


def _is_zero_contract_text_step(step: "OutlineStep") -> bool:
    return (
        _declared_output_type(step) == OutputType.TEXT
        and not step.output_fields
        and not step.uses_input_fields
        and not step.model_ref
        and not step.knowledge_refs
        and not step.mcp_server_refs
        and not step.mcp_tool_refs
        and not step.citations_requested
        and step.review_mode is None
    )


def _declared_output_type(step: "OutlineStep") -> OutputType:
    try:
        return OutputType(step.output_type) if step.output_type else OutputType.TEXT
    except ValueError:
        return OutputType.TEXT


def _compile_input_field(field: OutlineInputField) -> CreateFormFieldDraft:
    return CreateFormFieldDraft(
        variable_name=field.variable_name,
        label=field.label,
        field_type=cast(Any, field.field_type),
        required=field.required,
        options=list(field.options),
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


__all__ = [
    "FlowCreateOutline",
    "OUTLINE_FLOW_TOOL_NAME",
    "OutlineCompileContext",
    "OutlineFlowArgumentError",
    "attach_selected_mcp_refs_to_explicit_outline_steps",
    "build_outline_flow_tool_schema",
    "compile_outline_to_create_draft",
    "outline_compile_context_from_planning_state",
    "outline_runtime_input_type_values",
    "parse_outline_flow_arguments",
    "runtime_metadata_state_from_planning_state",
    "safe_validation_issues",
]

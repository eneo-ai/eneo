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
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    FlowCreateDraft,
)
from intric.flows.ai_builder.ai_builder_flow_name import MAX_FLOW_NAME_LENGTH
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_input_type_values,
    builder_output_type_values,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import (
    AIBuilderMCPResourceInput,
)
from intric.flows.ai_builder.ai_builder_models import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    MAX_STRUCTURED_FIELD_DEPTH,
    DocumentDeliveryMode,
    NewStepDraft,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_new_step_schema import (
    build_structured_field_schema,
    small_ref_enums,
)
from intric.flows.ai_builder.ai_builder_outline_pattern_chains import (
    chain_requests_docx_template_fill,
    realize_outline_pattern_chain,
)
from intric.flows.ai_builder.ai_builder_primary_input_fields import (
    is_primary_runtime_input_shadow_field,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
)
from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommit,
    ArchitectureCommitDraft,
    PlanningState,
)

OUTLINE_FLOW_TOOL_NAME = "outline_flow"
# Safety guard against runaway tool output. This should not be a practical
# product cap for legitimate advanced flows.
MAX_OUTLINE_STEPS = 256

_FILE_INPUT_TYPES = {InputType.AUDIO, InputType.DOCUMENT, InputType.FILE}
_DOCUMENT_OUTPUT_TYPES = {OutputType.DOCX, OutputType.PDF}
_COMPARISON_FAN_IN_PATTERN_IDS = frozenset({"comparison"})
_IMPLICIT_TEMPLATE_FILL_PATTERN_ID = "document_to_docx_template"
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
    }
)
logger = logging.getLogger(__name__)
_OUTLINE_ROOT_IGNORED_KEYS = frozenset(
    {
        "citations_requested",
        "output_fields",
        "output_type",
        "reasoning",
        "uses_input_fields",
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
        return _normalize_structured_field_list(value)

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
    """Strip legacy low-level mechanics from outline-flow tool arguments.

    Outline mode is semantic. Weak or stale models may still emit fields from
    the old create-flow contract, but those fields must never become the source
    of truth for Flow wiring.
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
    return _looks_like_field_spec(raw) and any(
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
        runtime_input_field_hints=runtime_input_field_hints,
        aggregation_intent=_aggregation_intent_for_compile_context(
            planning_state,
            architecture,
        ),
    )


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
    form_fields, dropped_primary_input_field_names = _compile_form_fields(
        outline_fields=outline.input_fields,
        context=context,
        runtime_input_type=runtime_input_type,
    )
    known_field_order = [field.variable_name for field in form_fields]
    known_field_names = set(known_field_order)

    outline_steps = _fold_leading_zero_contract_text_steps(
        steps=list(outline.steps),
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
    )
    outline_steps = _apply_server_pattern_chain(
        steps=outline_steps,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        context=context,
    )

    steps: list[NewStepDraft] = []
    for index, outline_step in enumerate(outline_steps):
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
        fan_in_required = _requires_server_owned_fan_in(
            step_index=index,
            step_count=len(outline_steps),
            context=context,
        )
        output_type = _derive_step_output_type(
            step=outline_step,
            is_last=index == len(outline_steps) - 1,
            final_output_type=final_output_type,
        )
        steps.append(
            NewStepDraft(
                name=outline_step.name,
                instructions=outline_step.task,
                input_source=_derive_step_input_source(
                    step_index=index,
                    fan_in_required=fan_in_required,
                ),
                input_type=_derive_step_input_type(
                    step_index=index,
                    runtime_input_type=runtime_input_type,
                    prior_step=steps[-1] if steps else None,
                    fan_in_required=fan_in_required,
                    uses_form_fields=uses_form_fields,
                ),
                output_type=output_type,
                runtime_upload=(index == 0 and runtime_input_type in _FILE_INPUT_TYPES),
                runtime_required=(
                    index == 0
                    and runtime_input_type in _FILE_INPUT_TYPES
                    and outline.runtime_input.required
                ),
                runtime_max_files=(
                    outline.runtime_input.max_files
                    if index == 0 and runtime_input_type in _FILE_INPUT_TYPES
                    else None
                ),
                uses_form_fields=uses_form_fields,
                model_ref=outline_step.model_ref,
                knowledge_refs=list(outline_step.knowledge_refs),
                mcp_server_refs=list(outline_step.mcp_server_refs),
                mcp_tool_refs=list(outline_step.mcp_tool_refs),
                document_delivery_mode=_document_delivery_mode_for_step(
                    output_type=output_type,
                    is_last=index == len(outline_steps) - 1,
                    context=context,
                ),
                citations_requested=(
                    outline_step.citations_requested and output_type == OutputType.TEXT
                ),
                output_fields=(
                    outline_step.output_fields
                    if output_type == OutputType.JSON
                    else None
                ),
            )
        )

    steps = _ensure_final_artifact_step(
        steps=steps,
        final_output_type=final_output_type,
        context=context,
    )
    steps = _ensure_required_server_owned_fan_in(steps=steps, context=context)
    steps = _attach_unreferenced_form_fields_to_final_step(
        steps=steps,
        known_field_order=known_field_order,
    )
    _log_dropped_primary_input_shadow_fields(
        field_names=dropped_primary_input_field_names,
        runtime_input_type=runtime_input_type,
    )

    return FlowCreateDraft(
        flow_name=outline.flow_name,
        flow_description=outline.flow_description,
        plan_rationale=outline.plan_rationale,
        assumptions=outline.assumptions,
        form_fields=form_fields,
        steps=steps,
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

    if architecture is not None:
        if architecture.aggregation_intent != "linear":
            return architecture.aggregation_intent
        if _COMPARISON_FAN_IN_PATTERN_IDS & set(architecture.chosen_patterns):
            return "compare"

    document_scope = _resolved_slot_value(state, "document_material_scope")
    if document_scope in {
        "multiple_documents_case",
        "multiple_pdfs_same_run",
        "same_run_multiple_documents",
    }:
        return "aggregate"

    comparison_scope = _resolved_slot_value(state, "comparison_scope")
    if comparison_scope in {
        "same_run_compare",
        "same_run_multiple_documents",
        "multiple_documents_case",
    }:
        return "compare"
    return "linear"


def _resolved_slot_value(state: PlanningState, slot_name: str) -> str | None:
    slot = state.resolved_slots.get(slot_name)
    return slot.value if slot is not None else None


def build_outline_flow_tool_schema(
    available_models: list[dict[str, Any]] | None = None,
    available_kbs: list[dict[str, Any]] | None = None,
    available_mcps: AIBuilderMCPResourceInput = None,
) -> dict[str, Any]:
    model_refs = small_ref_enums(available_models)
    kb_refs = small_ref_enums(available_kbs)
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
                "description": "Optional canonical model ref to use for this step.",
            },
            "knowledge_refs": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": (
                    "Canonical knowledge base refs this semantic step needs. "
                    "Do not combine with MCP refs on the same step."
                ),
            },
            "mcp_server_refs": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": (
                    "Canonical MCP server refs this semantic step needs. Use only "
                    "for external tools/live data and never together with knowledge_refs."
                ),
            },
            "mcp_tool_refs": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": (
                    "Canonical MCP tool refs for least-privilege tool access. "
                    "Prefer tool refs over whole-server refs when possible."
                ),
            },
            "citations_requested": {"type": "boolean", "default": False},
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
) -> tuple[list[CreateFormFieldDraft], list[str]]:
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


def _apply_server_pattern_chain(
    *,
    steps: list[OutlineStep],
    runtime_input_type: InputType,
    final_output_type: OutputType,
    context: OutlineCompileContext | None,
) -> list[OutlineStep]:
    pattern_ids, chain_steps = _pattern_context_for_compilation(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        context=context,
    )
    return realize_outline_pattern_chain(
        steps=steps,
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        pattern_ids=pattern_ids,
        chain_steps=chain_steps,
        make_step=_make_outline_step,
    )


def _pattern_context_for_compilation(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    context: OutlineCompileContext | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if context is None:
        return (), ()

    pattern_ids = list(context.pattern_ids)
    chain_steps = list(context.pattern_chain_steps)
    if _should_add_implicit_template_fill_chain(
        runtime_input_type=runtime_input_type,
        final_output_type=final_output_type,
        context=context,
    ):
        pattern = PATTERN_REGISTRY[_IMPLICIT_TEMPLATE_FILL_PATTERN_ID]
        pattern_ids.append(pattern.id)
        chain_steps.extend(
            chain_step
            for chain_step in pattern.chain_steps
            if chain_step not in chain_steps
        )
    return tuple(pattern_ids), tuple(chain_steps)


def _should_add_implicit_template_fill_chain(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    context: OutlineCompileContext,
) -> bool:
    if _IMPLICIT_TEMPLATE_FILL_PATTERN_ID in context.pattern_ids:
        return False
    return (
        runtime_input_type in _FILE_INPUT_TYPES
        and final_output_type == OutputType.DOCX
        and context.final_output_mode == OutputMode.TEMPLATE_FILL
    )


def _make_outline_step(
    name: str,
    task: str,
    output_type: str | None,
    output_fields: list[StructuredFieldDraft] | None,
) -> OutlineStep:
    return OutlineStep(
        name=name,
        task=task,
        output_type=output_type,
        output_fields=output_fields,
    )


def _normalize_structured_field_list(
    value: Any,
    *,
    depth: int = 1,
) -> list[dict[str, Any]] | None:
    """Coerce common LLM-shaped field hints into strict field drafts.

    This is intentionally scoped to the LLM-facing outline contract. The
    internal `StructuredFieldDraft` model remains strict for callers that
    bypass `outline_flow`.
    """

    raw_items = _coerce_field_items(value)
    if raw_items is None:
        return None

    fields: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items):
        field = _normalize_structured_field_item(
            raw_item,
            fallback_name=f"field_{index + 1}",
            depth=depth,
        )
        if field is not None:
            fields.append(field)
    return fields or None


def _coerce_field_items(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return cast(list[Any], value)
    if isinstance(value, dict):
        raw = cast(dict[str, Any], value)
        if _looks_like_field_spec(raw):
            return [raw]
        properties = raw.get("properties")
        if isinstance(properties, dict):
            raw_properties = cast(dict[str, Any], properties)
            return [
                {"name": name, **cast(dict[str, Any], spec)}
                if isinstance(spec, dict)
                else {"name": name, "field_type": _field_type_from_scalar(spec)}
                for name, spec in raw_properties.items()
            ]
        return [
            {"name": name, **cast(dict[str, Any], spec)}
            if isinstance(spec, dict)
            else {"name": name, "field_type": _field_type_from_scalar(spec)}
            for name, spec in raw.items()
        ]
    if isinstance(value, str) and value.strip():
        return [value]
    return None


def _normalize_structured_field_item(
    value: Any,
    *,
    fallback_name: str,
    depth: int,
) -> dict[str, Any] | None:
    if isinstance(value, StructuredFieldDraft):
        return value.model_dump()

    if isinstance(value, str):
        name = _field_name(value, fallback=fallback_name)
        return _strict_field(name=name, field_type="string", description=value)

    if not isinstance(value, dict):
        return None

    raw = cast(dict[str, Any], value)
    if not _looks_like_field_spec(raw) and len(raw) == 1:
        name, spec = next(iter(raw.items()))
        if isinstance(spec, dict):
            raw = {"name": name, **cast(dict[str, Any], spec)}
        else:
            raw = {"name": name, "field_type": _field_type_from_scalar(spec)}

    name = _field_name(raw.get("name"), fallback=fallback_name)
    field_type = _normalize_field_type(
        raw.get("field_type") or raw.get("type"),
        raw=raw,
    )
    description = _field_description(raw, fallback=name.replace("_", " "))
    required = raw.get("required")
    normalized: dict[str, Any] = _strict_field(
        name=name,
        field_type=field_type,
        description=description,
        required=required if isinstance(required, bool) else True,
    )

    child_fields = raw.get("fields") or raw.get("properties")
    item_fields = raw.get("item_fields")
    items = raw.get("items")

    if field_type == "object":
        if depth >= MAX_STRUCTURED_FIELD_DEPTH:
            normalized["field_type"] = "string"
            return normalized
        normalized_children = _normalize_structured_field_list(
            child_fields,
            depth=depth + 1,
        )
        if normalized_children:
            normalized["fields"] = normalized_children
        else:
            normalized["field_type"] = "string"
        return normalized

    if field_type == "array":
        if depth >= MAX_STRUCTURED_FIELD_DEPTH:
            return normalized
        normalized_item_fields = _normalize_structured_field_list(
            item_fields,
            depth=depth + 1,
        )
        if normalized_item_fields is None:
            normalized_item_fields = _normalize_array_item_fields(
                items,
                depth=depth + 1,
            )
        if normalized_item_fields is None:
            normalized_item_fields = _normalize_structured_field_list(
                child_fields,
                depth=depth + 1,
            )
        if normalized_item_fields:
            normalized["item_fields"] = normalized_item_fields
        return normalized

    return normalized


def _normalize_array_item_fields(
    value: Any,
    *,
    depth: int,
) -> list[dict[str, Any]] | None:
    if isinstance(value, dict):
        raw = cast(dict[str, Any], value)
        properties = raw.get("properties")
        if isinstance(properties, dict):
            return _normalize_structured_field_list(properties, depth=depth)
        if _looks_like_field_spec(raw):
            return _normalize_structured_field_list(raw, depth=depth)
    return None


def _strict_field(
    *,
    name: str,
    field_type: str,
    description: str,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "field_type": field_type,
        "description": description,
        "required": required,
    }


def _looks_like_field_spec(value: dict[str, Any]) -> bool:
    return bool(
        {
            "name",
            "field_type",
            "type",
            "description",
            "title",
            "fields",
            "item_fields",
            "items",
        }
        & value.keys()
    )


def _field_name(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _field_description(value: dict[str, Any], *, fallback: str) -> str:
    for key in ("description", "title"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return fallback


def _normalize_field_type(value: Any, *, raw: dict[str, Any]) -> str:
    if not isinstance(value, str) or not value.strip():
        if raw.get("fields") is not None or raw.get("properties") is not None:
            return "object"
        if raw.get("item_fields") is not None or raw.get("items") is not None:
            return "array"
        return "string"

    normalized = value.strip().lower()
    aliases = {
        "str": "string",
        "text": "string",
        "integer": "number",
        "float": "number",
        "double": "number",
        "bool": "boolean",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"string", "number", "boolean", "object", "array"}:
        return "string"
    return normalized


def _field_type_from_scalar(value: Any) -> str:
    if isinstance(value, str):
        return _normalize_field_type(value, raw={})
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _derive_step_output_type(
    *,
    step: OutlineStep,
    is_last: bool,
    final_output_type: OutputType,
) -> OutputType:
    if step.output_fields and step.output_type not in {
        OutputType.DOCX.value,
        OutputType.PDF.value,
    }:
        return OutputType.JSON
    if step.output_type is not None:
        return OutputType(step.output_type)
    if step.output_fields:
        return OutputType.JSON
    if is_last:
        return final_output_type
    return OutputType.TEXT


def _derive_step_input_source(
    *,
    step_index: int,
    fan_in_required: bool,
) -> InputSource:
    if step_index == 0:
        return InputSource.FLOW_INPUT
    if fan_in_required:
        return InputSource.ALL_PREVIOUS_STEPS
    return InputSource.PREVIOUS_STEP


def _derive_step_input_type(
    *,
    step_index: int,
    runtime_input_type: InputType,
    prior_step: NewStepDraft | None,
    fan_in_required: bool,
    uses_form_fields: list[str],
) -> InputType:
    if step_index == 0:
        return runtime_input_type
    if fan_in_required:
        return InputType.TEXT
    if uses_form_fields:
        return InputType.TEXT
    if prior_step is not None and prior_step.output_type == OutputType.JSON:
        return InputType.JSON
    return InputType.TEXT


def _requires_server_owned_fan_in(
    *,
    step_index: int,
    step_count: int,
    context: OutlineCompileContext | None,
) -> bool:
    if context is None or step_index <= 0 or step_count < 3:
        return False
    if step_index != step_count - 1:
        return False
    return bool(_COMPARISON_FAN_IN_PATTERN_IDS & set(context.pattern_ids))


def _ensure_required_server_owned_fan_in(
    *,
    steps: list[NewStepDraft],
    context: OutlineCompileContext | None,
) -> list[NewStepDraft]:
    if len(steps) < 2 or context is None:
        return steps
    if not (
        context.aggregation_intent in {"aggregate", "compare"}
        or bool(_COMPARISON_FAN_IN_PATTERN_IDS & set(context.pattern_ids))
    ):
        return steps
    if any(step.input_source == InputSource.ALL_PREVIOUS_STEPS for step in steps):
        return steps

    fan_in_index = _server_owned_fan_in_target_index(steps)
    if fan_in_index is None:
        return steps
    return [
        step.model_copy(
            update={
                "input_source": InputSource.ALL_PREVIOUS_STEPS,
                "input_type": InputType.TEXT,
            }
        )
        if index == fan_in_index
        else step
        for index, step in enumerate(steps)
    ]


def _server_owned_fan_in_target_index(steps: list[NewStepDraft]) -> int | None:
    """Return the semantic synthesis step that should receive broad fan-in.

    Template-fill DOCX steps are renderers: their own output_config bindings
    perform document placement. Feed broad `all_previous_steps` into the last
    semantic content step before such a renderer instead of the renderer itself.
    Generated DOCX/PDF/text/json terminal steps still count as semantic writers.
    """
    for index in range(len(steps) - 1, 0, -1):
        if _is_template_fill_renderer(steps[index]):
            continue
        return index
    return None


def _is_template_fill_renderer(step: NewStepDraft) -> bool:
    return (
        step.output_type == OutputType.DOCX
        and step.document_delivery_mode == "template_fill"
    )


def _document_delivery_mode(output_type: OutputType) -> DocumentDeliveryMode:
    if output_type in _DOCUMENT_OUTPUT_TYPES:
        return "generated"
    return "not_applicable"


def _document_delivery_mode_for_step(
    *,
    output_type: OutputType,
    is_last: bool,
    context: OutlineCompileContext | None,
) -> DocumentDeliveryMode:
    if (
        is_last
        and output_type == OutputType.DOCX
        and context is not None
        and (
            context.final_output_mode == OutputMode.TEMPLATE_FILL
            or chain_requests_docx_template_fill(
                pattern_ids=context.pattern_ids,
                chain_steps=context.pattern_chain_steps,
            )
        )
    ):
        return "template_fill"
    return _document_delivery_mode(output_type)


def _ensure_final_artifact_step(
    *,
    steps: list[NewStepDraft],
    final_output_type: OutputType,
    context: OutlineCompileContext | None,
) -> list[NewStepDraft]:
    if not steps:
        return steps
    if steps[-1].output_type == final_output_type:
        return steps
    if final_output_type == OutputType.JSON:
        return [
            *steps[:-1],
            steps[-1].model_copy(
                update={
                    "output_type": OutputType.JSON,
                    "document_delivery_mode": "not_applicable",
                }
            ),
        ]

    return [
        *steps,
        NewStepDraft(
            name=_default_final_step_name(
                final_output_type,
                ui_language=context.ui_language if context is not None else None,
            ),
            instructions=_default_final_step_instructions(
                ui_language=context.ui_language if context is not None else None,
            ),
            input_source=InputSource.PREVIOUS_STEP,
            input_type=(
                InputType.JSON
                if steps[-1].output_type == OutputType.JSON
                else InputType.TEXT
            ),
            output_type=final_output_type,
            document_delivery_mode=_document_delivery_mode_for_step(
                output_type=final_output_type,
                is_last=True,
                context=context,
            ),
        ),
    ]


def _default_final_step_name(
    output_type: OutputType,
    *,
    ui_language: str | None,
) -> str:
    if ui_language == "sv":
        if output_type == OutputType.DOCX:
            return "Skapa DOCX"
        if output_type == OutputType.PDF:
            return "Skapa PDF"
        if output_type == OutputType.JSON:
            return "Skapa strukturerad JSON"
        return "Skapa slutresultat"

    if output_type == OutputType.DOCX:
        return "Create DOCX"
    if output_type == OutputType.PDF:
        return "Create PDF"
    if output_type == OutputType.JSON:
        return "Create structured JSON"
    return "Create final answer"


def _default_final_step_instructions(*, ui_language: str | None) -> str:
    if ui_language == "sv":
        return (
            "Skapa slutresultatet från föregående strukturerade arbete. "
            "Bevara användarens önskade omfattning, ordning och begränsningar."
        )
    return (
        "Create the final output from the previous structured work. "
        "Preserve the user's requested scope, ordering, and constraints."
    )


def _attach_unreferenced_form_fields_to_final_step(
    *,
    steps: list[NewStepDraft],
    known_field_order: list[str],
) -> list[NewStepDraft]:
    if not steps or not known_field_order:
        return steps
    referenced = {field_name for step in steps for field_name in step.uses_form_fields}
    unreferenced = [
        field_name for field_name in known_field_order if field_name not in referenced
    ]
    if not unreferenced:
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
    "safe_validation_issues",
]

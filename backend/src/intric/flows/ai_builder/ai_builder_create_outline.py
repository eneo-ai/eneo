from __future__ import annotations

import logging
from functools import cache
from typing import Any, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    BuilderFormFieldType,
    builder_form_field_type_values,
    builder_output_type_values,
)
from intric.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
    mixes_knowledge_and_mcp_refs,
    normalize_authoring_string_list,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_step_tool_schema_fragments import (
    build_review_mode_schema,
    build_structured_field_schema,
)
from intric.flows.ai_builder.ai_builder_structured_field_normalizer import (
    looks_like_structured_field_spec,
    normalize_structured_field_list,
)
from intric.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH
from intric.flows.flow_authoring_spec import (
    OutputType,
)
from intric.flows.flow_review_policy import FlowStepReviewMode

# Safety guard against runaway tool output. This should not be a practical
# product cap for legitimate advanced flows.
MAX_OUTLINE_STEPS = 256

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
        "uses_previous_fields",
        "uses_previous_outputs",
    }
)
logger = logging.getLogger(__name__)
_OUTLINE_ROOT_IGNORED_KEYS = frozenset({"final_output_type", "reasoning"})
_OUTLINE_ASSUMPTIONS_FIELD = "assumptions"
_OUTLINE_STEP_ROOT_RECOVERED_KEYS = frozenset({_OUTLINE_ASSUMPTIONS_FIELD})


class OutlineInputField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable_name: str
    label: str
    field_type: BuilderFormFieldType = "text"
    required: bool = False
    options: list[str] = Field(default_factory=list)

    @field_validator("variable_name", "label")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Input fields require non-empty text values.")
        return normalized

    @field_validator("field_type", mode="before")
    @classmethod
    def _strip_field_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("options")
    @classmethod
    def _normalize_options(cls, value: list[str]) -> list[str]:
        return normalize_authoring_string_list(value)


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
        return normalize_authoring_string_list(values)

    @field_validator("model_ref")
    @classmethod
    def _normalize_optional_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_resource_mode(self) -> "OutlineStep":
        if mixes_knowledge_and_mcp_refs(
            knowledge_refs=self.knowledge_refs,
            mcp_server_refs=self.mcp_server_refs,
            mcp_tool_refs=self.mcp_tool_refs,
        ):
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

    @field_validator("steps")
    @classmethod
    def _validate_steps(cls, value: list[OutlineStep]) -> list[OutlineStep]:
        if not value:
            raise ValueError("propose_flow requires at least one step.")
        if len(value) > MAX_OUTLINE_STEPS:
            raise ValueError(
                f"propose_flow supports at most {MAX_OUTLINE_STEPS} semantic steps."
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
    return tuple(issues) or ("propose_flow validation failed [validation_error]",)


def _normalize_outline_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Strip fields outside the semantic outline contract before validation.

    Outline mode is semantic. Some model outputs may still include fields
    outside that contract, but those fields must never become the source of
    truth for Flow wiring.
    """

    normalized = {
        key: value
        for key, value in arguments.items()
        if key not in _outline_root_ignored_keys()
    }
    raw_steps = normalized.get("steps")
    if isinstance(raw_steps, list):
        typed_steps = cast(list[Any], raw_steps)
        normalized_steps, misplaced_assumptions = _normalize_outline_steps(typed_steps)
        normalized["steps"] = normalized_steps
        if misplaced_assumptions:
            normalized[_OUTLINE_ASSUMPTIONS_FIELD] = _merge_outline_assumptions(
                normalized.get(_OUTLINE_ASSUMPTIONS_FIELD),
                misplaced_assumptions,
            )
    return normalized


@cache
def _outline_root_ignored_keys() -> frozenset[str]:
    return (
        _OUTLINE_STEP_BACKEND_OWNED_KEYS
        | _outline_step_only_keys()
        | _OUTLINE_ROOT_IGNORED_KEYS
    )


@cache
def _outline_step_ignored_keys() -> frozenset[str]:
    return _OUTLINE_STEP_BACKEND_OWNED_KEYS | _OUTLINE_STEP_ROOT_RECOVERED_KEYS


@cache
def _outline_step_only_keys() -> frozenset[str]:
    return frozenset(OutlineStep.model_fields.keys()) - frozenset(
        FlowCreateOutline.model_fields.keys()
    )


def _normalize_outline_steps(raw_steps: list[Any]) -> tuple[list[Any], list[str]]:
    """Recover common small-model shape errors without weakening Flow models.

    Outline steps are semantic units with a task. When a model accidentally
    places assumptions on a step, keep the root source of truth by folding those
    notes into root assumptions. Orphan output field objects are attached to the
    previous step instead of being treated as broken steps.
    """

    steps: list[Any] = []
    misplaced_assumptions: list[str] = []
    recovered_step_keys: set[str] = set()
    for raw_step in raw_steps:
        step, step_assumptions, recovered_keys = _strip_ignored_outline_step_keys(
            raw_step
        )
        misplaced_assumptions.extend(step_assumptions)
        recovered_step_keys.update(recovered_keys)
        if _looks_like_orphan_output_field(step):
            _attach_orphan_output_field(steps, cast(dict[str, Any], step))
            continue
        steps.append(step)
    if recovered_step_keys:
        logger.info(
            "ai_builder_outline_step_assumptions_recovered",
            extra={"keys": sorted(recovered_step_keys)},
        )
    return steps, misplaced_assumptions


def _strip_ignored_outline_step_keys(
    value: Any,
) -> tuple[Any, list[str], frozenset[str]]:
    if not isinstance(value, dict):
        return value, [], frozenset()
    raw = cast(dict[str, Any], value)
    recovered_keys = frozenset(
        key for key in raw if key in _OUTLINE_STEP_ROOT_RECOVERED_KEYS
    )
    misplaced_assumptions = _assumption_strings(raw.get(_OUTLINE_ASSUMPTIONS_FIELD))
    return (
        {
            key: step_value
            for key, step_value in raw.items()
            if key not in _outline_step_ignored_keys()
        },
        misplaced_assumptions,
        recovered_keys,
    )


def _merge_outline_assumptions(
    raw_assumptions: Any,
    misplaced_assumptions: list[str],
) -> Any:
    if raw_assumptions is None:
        return misplaced_assumptions
    if isinstance(raw_assumptions, list):
        return [*cast(list[Any], raw_assumptions), *misplaced_assumptions]
    return raw_assumptions


def _assumption_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[Any], value) if isinstance(item, str)]


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


def build_outline_flow_tool_schema(
    *,
    resource_catalog: AIBuilderResourceCatalog,
    tool_name: str,
) -> dict[str, Any]:
    model_refs = resource_catalog.small_ref_enum_for_kind("model")
    kb_refs = resource_catalog.small_ref_enum_for_kind("knowledge_base")
    # Keep MCP refs free-form. Catalog resolution and quality feedback handle
    # unknown or unrelated MCP selections without coercing the planner into an
    # available-but-wrong server when the requested MCP is absent.
    mcp_server_refs: list[str] | None = None
    mcp_tool_refs: list[str] | None = None
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": (
                "Submit a semantic create-flow outline. Describe what the flow "
                "should do; the backend will compile Flow mechanics such as "
                "input_source, runtime input, step refs, output_mode, and "
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
                "enum": builder_form_field_type_values(),
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


__all__ = [
    "FlowCreateOutline",
    "OutlineFlowArgumentError",
    "attach_selected_mcp_refs_to_explicit_outline_steps",
    "build_outline_flow_tool_schema",
    "parse_outline_flow_arguments",
    "safe_validation_issues",
]

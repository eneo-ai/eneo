from __future__ import annotations

import logging
from functools import cache
from typing import Annotated, Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    BuilderFormFieldType,
    builder_form_field_type_values,
    builder_output_type_values,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
    ensure_structured_field_depth,
    mixes_knowledge_and_mcp_refs,
    normalize_authoring_string_list,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_step_tool_schema_fragments import (
    build_previous_field_refs_schema,
    build_previous_output_refs_schema,
    build_resource_ref_property_schemas,
    build_review_mode_schema,
    build_structured_field_schema,
)
from eneo.flows.ai_builder.ai_builder_structured_field_normalizer import (
    normalize_structured_field_list,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    MCPPolicy,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode

# Safety guard against runaway tool output. This should not be a practical
# product cap for legitimate advanced flows.
MAX_PROPOSAL_STEPS = 256

_CREATE_INTENT_STEP_BACKEND_OWNED_KEYS = frozenset(
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
    }
)
logger = logging.getLogger(__name__)
_CREATE_INTENT_ROOT_IGNORED_KEYS = frozenset({"final_output_type", "reasoning"})


class FlowInputFieldIntent(BaseModel):
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


class SemanticStepIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    instructions: str
    output_type: OutputType | None = None
    output_fields: list[StructuredFieldDraft] | None = None
    uses_form_fields: list[str] = Field(default_factory=list)
    uses_previous_fields: list[PreviousFieldRef] = Field(
        default_factory=lambda: cast(list[PreviousFieldRef], [])
    )
    uses_previous_outputs: list[PreviousOutputRef] = Field(
        default_factory=lambda: cast(list[PreviousOutputRef], [])
    )
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    mcp_tool_refs: list[str] = Field(default_factory=list)
    citations_requested: bool = False
    review_mode: FlowStepReviewMode | None = None

    @field_validator("name", "instructions")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Semantic steps require non-empty text values.")
        if "{{" in normalized or "}}" in normalized:
            raise ValueError("Semantic steps must not contain template variables.")
        return normalized

    @field_validator("output_type", mode="before")
    @classmethod
    def _validate_output_type(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, OutputType):
            return value
        if not isinstance(value, str):
            return value
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
        "uses_form_fields", "knowledge_refs", "mcp_server_refs", "mcp_tool_refs"
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
    def _validate_resource_mode(self) -> "SemanticStepIntent":
        if mixes_knowledge_and_mcp_refs(
            knowledge_refs=self.knowledge_refs,
            mcp_server_refs=self.mcp_server_refs,
            mcp_tool_refs=self.mcp_tool_refs,
        ):
            raise ValueError(
                "Semantic steps cannot combine knowledge_refs with MCP refs."
            )
        if self.output_fields:
            ensure_structured_field_depth(self.output_fields)
        return self


class AssistantSpecPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instructions: str | None = None
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    mcp_tool_refs: list[str] = Field(default_factory=list)


class ModifyExistingStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["modify"] = "modify"
    existing_step_ref: str
    name: str | None = None
    assistant_spec: AssistantSpecPatch | None = None
    mcp_policy: MCPPolicy | None = None
    input_source: InputSource | None = None
    input_type: InputType | None = None
    output_type: OutputType | None = None
    output_contract: FlowPersistedJsonObject | None = None
    review_mode: FlowStepReviewMode | None = None
    uses_form_fields: list[str] | None = None
    uses_previous_fields: list[PreviousFieldRef] | None = None
    document_delivery_mode: DocumentDeliveryMode | None = None


class AddStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["add"] = "add"
    step: SemanticStepIntent


OrderedEditStep = Annotated[ModifyExistingStep | AddStep, Field(discriminator="kind")]


class OrderedEditProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_rationale: str
    assumptions: list[str] = Field(default_factory=list)
    flow_name: str | None = None
    flow_description: str | None = None
    steps: list[OrderedEditStep]
    removed_existing_step_refs: frozenset[str] = Field(default_factory=frozenset)
    form_fields: list[FormFieldSpec] | None = None

    @field_validator("plan_rationale")
    @classmethod
    def _normalize_plan_rationale(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("plan_rationale must not be empty.")
        return normalized

    @field_validator("assumptions")
    @classmethod
    def _normalize_assumptions(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            assumption = value.strip()
            if assumption:
                normalized.append(assumption)
        return normalized


def _empty_semantic_input_fields() -> list[FlowInputFieldIntent]:
    return []


class CreateFlowIntent(BaseModel):
    """Small LLM-facing contract for create mode.

    The intent is semantic. It intentionally omits Flow mechanics such as
    input_source, output_mode, input_bindings, runtime config, step refs, and
    document output config; the backend compiler owns those.
    """

    model_config = ConfigDict(extra="forbid")

    flow_name: str
    flow_description: str | None = None
    plan_rationale: str
    input_fields: list[FlowInputFieldIntent] = Field(
        default_factory=_empty_semantic_input_fields
    )
    steps: list[SemanticStepIntent]
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("flow_name", "plan_rationale")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Create-flow fields require non-empty text values.")
        if "{{" in normalized or "}}" in normalized:
            raise ValueError("Create-flow fields must not contain template variables.")
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
    def _validate_steps(
        cls, value: list[SemanticStepIntent]
    ) -> list[SemanticStepIntent]:
        if not value:
            raise ValueError("propose_flow requires at least one step.")
        if len(value) > MAX_PROPOSAL_STEPS:
            raise ValueError(
                f"propose_flow supports at most {MAX_PROPOSAL_STEPS} semantic steps."
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


def parse_create_flow_intent_arguments(arguments: dict[str, Any]) -> CreateFlowIntent:
    try:
        return CreateFlowIntent.model_validate(
            _normalize_create_intent_arguments(arguments)
        )
    except ValidationError as error:
        raise ProposalIntentArgumentError(error) from error


class ProposalIntentArgumentError(ValueError):
    """Safe proposal validation feedback for logs and model repair prompts.

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


def _normalize_create_intent_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Strip fields outside the semantic create-intent contract before validation.

    Create mode is semantic. Some model outputs may still include fields
    outside that contract, but those fields must never become the source of
    truth for Flow wiring.
    """

    normalized = {
        key: value
        for key, value in arguments.items()
        if key not in _create_intent_root_ignored_keys()
    }
    raw_steps = normalized.get("steps")
    if isinstance(raw_steps, list):
        normalized["steps"] = [
            _strip_backend_owned_semantic_step_keys(raw_step)
            for raw_step in cast(list[Any], raw_steps)
        ]
    return normalized


@cache
def _create_intent_root_ignored_keys() -> frozenset[str]:
    return (
        _CREATE_INTENT_STEP_BACKEND_OWNED_KEYS
        | _semantic_step_only_keys()
        | _CREATE_INTENT_ROOT_IGNORED_KEYS
    )


@cache
def _semantic_step_only_keys() -> frozenset[str]:
    return frozenset(SemanticStepIntent.model_fields.keys()) - frozenset(
        CreateFlowIntent.model_fields.keys()
    )


def _strip_backend_owned_semantic_step_keys(
    value: Any,
) -> Any:
    if not isinstance(value, dict):
        return value
    raw = cast(dict[str, Any], value)
    stripped_keys = sorted(
        key for key in raw if key in _CREATE_INTENT_STEP_BACKEND_OWNED_KEYS
    )
    if stripped_keys:
        logger.info(
            "ai_builder_create_intent_backend_step_keys_stripped",
            extra={"keys": stripped_keys},
        )
    return {
        key: step_value
        for key, step_value in raw.items()
        if key not in _CREATE_INTENT_STEP_BACKEND_OWNED_KEYS
    }


def attach_selected_mcp_refs_to_explicit_intent_steps(
    intent: CreateFlowIntent,
    *,
    selected_server_refs: set[str] | frozenset[str],
    catalog: AIBuilderResourceCatalog,
) -> CreateFlowIntent:
    """Attach selected MCP refs when a semantic step explicitly names them.

    User selection is the permission boundary. The text match is only a
    catalog-backed recovery path for semantic steps that already say which MCP
    they intend to use but omit the mechanical `mcp_*_refs` fields.
    """

    selected_refs = frozenset(selected_server_refs)
    if not selected_refs:
        return intent

    changed = False
    patched_steps: list[dict[str, object]] = []
    updated_steps: list[SemanticStepIntent] = []
    for step in intent.steps:
        if step.mcp_server_refs or step.mcp_tool_refs or step.knowledge_refs:
            updated_steps.append(step)
            continue

        step_text = f"{step.name}\n{step.instructions}"
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
        return intent
    logger.info(
        "ai_builder_selected_mcp_refs_attached_to_semantic_steps",
        extra={
            "patched_step_count": len(patched_steps),
            "patched_steps": patched_steps,
            "selected_mcp_server_refs": sorted(selected_refs),
        },
    )
    return intent.model_copy(update={"steps": updated_steps})


def _tool_refs_for_servers(
    *,
    catalog: AIBuilderResourceCatalog,
    server_refs: frozenset[str],
) -> frozenset[str]:
    refs: set[str] = set()
    for server_ref in server_refs:
        refs.update(catalog.mcp_tool_refs_for_server(server_ref))
    return frozenset(refs)


def build_create_flow_tool_schema(
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
                "Submit a semantic create-flow intent. Describe what the flow "
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
                        "items": _input_field_intent_schema(),
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_PROPOSAL_STEPS,
                        "items": build_semantic_step_schema(
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


def _input_field_intent_schema() -> dict[str, Any]:
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


def build_semantic_step_schema(
    *,
    include_previous_refs: bool = False,
    model_refs: list[str] | None = None,
    kb_refs: list[str] | None = None,
    mcp_server_refs: list[str] | None = None,
    mcp_tool_refs: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["name", "instructions"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "instructions": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Plain step instructions. Do not include template variables "
                    "or underlag/input_bindings syntax."
                ),
            },
            "output_type": {
                "type": ["string", "null"],
                "enum": [*builder_output_type_values(), None],
            },
            "output_fields": {
                "type": ["array", "null"],
                "description": (
                    "Semantic structured fields this step should produce. For JSON "
                    "source-reading steps, every user-named source fact needed by "
                    "later text, document, or JSON output must be an explicit field "
                    "or nested item field, not only instruction prose or a generic "
                    "facts/notes envelope."
                ),
                "items": build_structured_field_schema(),
            },
            "uses_form_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Names of input_fields this step should consider. The backend "
                    "compiles them into underlag/input_bindings."
                ),
            },
            **(
                {
                    "uses_previous_fields": build_previous_field_refs_schema(),
                    "uses_previous_outputs": build_previous_output_refs_schema(),
                }
                if include_previous_refs
                else {}
            ),
            **build_resource_ref_property_schemas(
                model_refs=model_refs,
                kb_refs=kb_refs,
                mcp_server_refs=mcp_server_refs,
                mcp_tool_refs=mcp_tool_refs,
            ),
            "citations_requested": {"type": "boolean", "default": False},
            "review_mode": build_review_mode_schema(),
        },
        "additionalProperties": False,
    }
    return schema


__all__ = [
    "CreateFlowIntent",
    "ProposalIntentArgumentError",
    "AddStep",
    "AssistantSpecPatch",
    "FlowInputFieldIntent",
    "ModifyExistingStep",
    "OrderedEditProposal",
    "OrderedEditStep",
    "SemanticStepIntent",
    "attach_selected_mcp_refs_to_explicit_intent_steps",
    "build_create_flow_tool_schema",
    "build_semantic_step_schema",
    "parse_create_flow_intent_arguments",
    "safe_validation_issues",
]

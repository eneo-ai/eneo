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
        "uses_previous_fields",
        "uses_previous_outputs",
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
    # Parser compatibility for older create payloads and current edit payloads.
    # Create-mode schema does not advertise this; the compiler derives step
    # output types from output_fields, terminal architecture, and assembly rules.
    output_type: OutputType | None = None
    output_fields: list[StructuredFieldDraft] | None = None
    uses_form_fields: list[str] = Field(default_factory=list)
    # Create-mode parsing strips these stale mechanical keys before validation;
    # edit mode still uses the same semantic step model and schema.
    uses_previous_fields: list[PreviousFieldRef] = Field(
        default_factory=lambda: cast(list[PreviousFieldRef], [])
    )
    uses_previous_outputs: list[PreviousOutputRef] = Field(
        default_factory=lambda: cast(list[PreviousOutputRef], [])
    )
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
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

    @field_validator("uses_form_fields", "knowledge_refs")
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
        if self.output_fields:
            ensure_structured_field_depth(self.output_fields)
        return self


class AssistantSpecPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instructions: str | None = None
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)


class ModifyExistingStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["modify"] = "modify"
    existing_step_ref: str
    name: str | None = None
    assistant_spec: AssistantSpecPatch | None = None
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


def build_create_flow_tool_schema(
    *,
    resource_catalog: AIBuilderResourceCatalog,
    tool_name: str,
) -> dict[str, Any]:
    model_refs = resource_catalog.small_ref_enum_for_kind("model")
    kb_refs = resource_catalog.small_ref_enum_for_kind("knowledge_base")
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
                            include_output_type=False,
                            model_refs=model_refs,
                            kb_refs=kb_refs,
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
    include_output_type: bool = True,
    include_previous_refs: bool = False,
    model_refs: list[str] | None = None,
    kb_refs: list[str] | None = None,
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
            **(
                {
                    "output_type": {
                        "type": ["string", "null"],
                        "enum": [*builder_output_type_values(), None],
                    },
                }
                if include_output_type
                else {}
            ),
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
    "build_create_flow_tool_schema",
    "build_semantic_step_schema",
    "parse_create_flow_intent_arguments",
    "safe_validation_issues",
]

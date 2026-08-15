from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from eneo.flows.ai_builder.ai_builder_flow_schema_values import (
    BuilderFormFieldType,
    FlowInputFieldProvenance,
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
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
    render_confirmed_runtime_input_requirements,
)
from eneo.flows.ai_builder.ai_builder_step_tool_schema_fragments import (
    build_create_structured_field_schema,
    build_knowledge_refs_property_schema,
    build_model_ref_property_schema,
    build_previous_field_refs_schema,
    build_previous_output_refs_schema,
    build_review_mode_schema,
    build_structured_field_schema,
)
from eneo.flows.ai_builder.ai_builder_structured_field_normalizer import (
    normalize_structured_field_list,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_name import MAX_FLOW_NAME_LENGTH
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode

# Safety guard against runaway tool output. This should not be a practical
# product cap for legitimate advanced flows.
MAX_PROPOSAL_STEPS = 256


class FlowInputFieldIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    variable_name: str = Field(
        alias="name",
    )
    label: str
    field_type: BuilderFormFieldType = Field(
        default="text",
        alias="type",
    )
    required: bool = False
    options: list[str] = Field(default_factory=list)
    provenance: FlowInputFieldProvenance = "model_proposed"

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
    # Create rejects model-authored values; edit and backend-synthesized create
    # steps still use this shared semantic representation.
    output_type: OutputType | None = None
    output_fields: list[StructuredFieldDraft] | None = None
    uses_form_fields: list[str] = Field(default_factory=list)
    # The create argument model excludes explicit wiring. Edit and
    # backend-synthesized steps retain it on this compiler-facing model.
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

    @field_validator("output_type", mode="before", check_fields=False)
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

    @field_validator("uses_form_fields", "knowledge_refs", check_fields=False)
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


class _CreateSemanticStepArguments(BaseModel):
    """Closed provider-authored subset of ``SemanticStepIntent``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    instructions: str
    output_fields: list[StructuredFieldDraft] | None = None
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    citations_requested: bool = False


def _validate_create_semantic_step(value: object) -> dict[str, object]:
    return _CreateSemanticStepArguments.model_validate(value).model_dump()


CreateSemanticStepIntent = Annotated[
    SemanticStepIntent,
    BeforeValidator(_validate_create_semantic_step),
]


class AssistantSpecPatch(BaseModel):
    """Assistant fields an edit may change on an existing step.

    A saved step's model is not one of them: the step's model picker is the
    only place a model changes, so chat cannot silently move work onto a model
    with a different security classification.
    """

    model_config = ConfigDict(extra="forbid")

    instructions: str | None = None
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
    form_fields: list[FlowInputFieldIntent] | None = None

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
    steps: list[CreateSemanticStepIntent]
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
        cls, value: list[CreateSemanticStepIntent]
    ) -> list[CreateSemanticStepIntent]:
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
        return CreateFlowIntent.model_validate(arguments)
    except ValidationError as error:
        raise ProposalIntentArgumentError(safe_validation_issues(error)) from error


class ProposalIntentArgumentError(ValueError):
    """Safe proposal validation feedback for logs and model repair prompts.

    Pydantic's default message can include input excerpts. The AI Builder logs
    and retry prompts only need field paths, error types, and human-readable
    validation messages.
    """

    def __init__(self, issues: tuple[str, ...]) -> None:
        self.issues = issues
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


def build_create_flow_tool_schema(
    *,
    resource_catalog: AIBuilderResourceCatalog,
    tool_name: str,
    is_pure_audio_transcription: bool = False,
    confirmed_runtime_inputs: tuple[ConfirmedRuntimeInputRequirement, ...] = (),
) -> dict[str, Any]:
    model_refs = resource_catalog.small_ref_enum_for_kind("model")
    kb_refs = resource_catalog.small_ref_enum_for_kind("knowledge_base")
    step_schema = build_semantic_step_schema(
        include_output_type=False,
        include_review_mode=False,
        include_form_field_refs=False,
        model_refs=model_refs,
        kb_refs=kb_refs,
    )
    step_schema["properties"]["knowledge_refs"].pop("uniqueItems")
    step_schema["properties"]["citations_requested"].pop("default")
    if is_pure_audio_transcription:
        step_schema["properties"] = {
            name: step_schema["properties"][name] for name in ("name", "instructions")
        }
    else:
        step_schema["properties"]["output_fields"].update(
            {
                "minItems": 1,
                "items": build_create_structured_field_schema(),
            }
        )
    step_schema["required"] = list(step_schema["properties"])
    if confirmed_runtime_inputs and not is_pure_audio_transcription:
        rendered_runtime_inputs = render_confirmed_runtime_input_requirements(
            confirmed_runtime_inputs
        )
        output_fields_description = step_schema["properties"]["output_fields"][
            "description"
        ]
        step_schema["properties"]["output_fields"]["description"] = (
            f"{output_fields_description} Confirmed server-owned runtime inputs: "
            f"{rendered_runtime_inputs}. Do not repeat any exact runtime-input "
            "identity as a source output field."
        )
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
                    "flow_description",
                    "plan_rationale",
                    "steps",
                    "assumptions",
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
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": (
                            1 if is_pure_audio_transcription else MAX_PROPOSAL_STEPS
                        ),
                        "items": step_schema,
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


def build_semantic_step_schema(
    *,
    include_output_type: bool = True,
    include_review_mode: bool = True,
    include_form_field_refs: bool = True,
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
            **(
                {
                    "uses_form_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Names of form fields this edit step should consider. "
                            "The backend compiles them into underlag/input_bindings."
                        ),
                    }
                }
                if include_form_field_refs
                else {}
            ),
            **(
                {
                    "uses_previous_fields": build_previous_field_refs_schema(),
                    "uses_previous_outputs": build_previous_output_refs_schema(),
                }
                if include_previous_refs
                else {}
            ),
            **build_model_ref_property_schema(model_refs=model_refs),
            **build_knowledge_refs_property_schema(kb_refs=kb_refs),
            "citations_requested": {"type": "boolean", "default": False},
            **(
                {"review_mode": build_review_mode_schema()}
                if include_review_mode
                else {}
            ),
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

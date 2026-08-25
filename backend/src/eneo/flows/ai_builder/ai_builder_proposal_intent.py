from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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

from eneo.flows.ai_builder.ai_builder_field_identity import fold_result_field_name
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
    StructuredFieldType,
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


@dataclass(frozen=True, slots=True)
class ObligatedResultKey:
    """One user-attested result key the proposal is verified against."""

    name: str
    declared_shape: Literal["array", "object"] | None = None


@dataclass(frozen=True, slots=True)
class ProposalObligationProjection:
    """The attested result keys, in the order the confirmation showed them.

    One instance is built at request preparation, travels with the prepared
    request, and is read again by the prompt rule, admission verification and
    the compiled postcondition, so all three always hold the proposal to the
    very key set the user attested. It also fixes the canonicalized order of
    the attested roots in the compiled contract. Which keys are eligible is
    re-derived from one pure rule; the ORDER is never re-derived.
    """

    keys: tuple[ObligatedResultKey, ...]

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("An obligation projection requires at least one key")
        if len({key.name for key in self.keys}) != len(self.keys):
            raise ValueError("Obligation projection keys must be unique")

    @property
    def ordered_keys(self) -> tuple[str, ...]:
        return tuple(key.name for key in self.keys)


@dataclass(frozen=True, slots=True)
class AttestedContractViolation:
    """One way the terminal root fails the attested result contract."""

    kind: Literal["missing_root", "rename", "duplicate_roots", "shape_conflict"]
    key_name: str
    declared_shape: Literal["array", "object"] | None
    matched_names: tuple[str, ...]


def attested_result_contract_violations(
    terminal_root_fields: Sequence[tuple[str, str]],
    *,
    projection: ProposalObligationProjection,
) -> tuple[AttestedContractViolation, ...]:
    """The ONE verification predicate for the attested result contract.

    Read by admission over the model's draft fields AND by the compiler over
    the compiled terminal schema, so the two can never disagree: the model
    authors its own declaration and the server verifies it against the
    attested contract.

    The contract per projected key: exactly one terminal-ROOT field whose
    spelling exactly matches the attested name; folding only locates a
    rename for an actionable error, it never satisfies the contract; a
    declared shape constrains the effective type; an undeclared shape
    accepts any legal structured type. Nested occurrences are invisible
    here on purpose — a nested-only occurrence IS a missing root.
    """

    violations: list[AttestedContractViolation] = []
    for key in projection.keys:
        folded = fold_result_field_name(key.name)
        group = [
            (name, field_type)
            for name, field_type in terminal_root_fields
            if fold_result_field_name(name) == folded
        ]
        exact = [(n, ft) for n, ft in group if n == key.name]
        if not group:
            kind = "missing_root"
        elif not exact:
            kind = "rename"
        elif len(group) > 1:
            kind = "duplicate_roots"
        elif key.declared_shape is not None and exact[0][1] != key.declared_shape:
            kind = "shape_conflict"
        else:
            continue
        violations.append(
            AttestedContractViolation(
                kind=kind,
                key_name=key.name,
                declared_shape=key.declared_shape,
                matched_names=tuple(n for n, _ in group),
            )
        )
    return tuple(violations)


def attested_violation_message(violation: AttestedContractViolation) -> str:
    """One actionable sentence per violation kind, shared by both callers."""

    if violation.kind == "missing_root":
        return (
            f"the user-named result `{violation.key_name}` must exist at the "
            "top level of the final step's output_fields"
        )
    if violation.kind == "rename":
        found = ", ".join(f"`{name}`" for name in violation.matched_names)
        return (
            f"rename {found} to exactly `{violation.key_name}` — the user "
            "attested to that spelling"
        )
    if violation.kind == "duplicate_roots":
        return (
            f"declare `{violation.key_name}` exactly once at the top level of "
            "the final step's output_fields"
        )
    return (
        f"`{violation.key_name}` must be of type "
        f"`{violation.declared_shape}` — the user declared that shape"
    )


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
    output_fields: list["CreateStructuredFieldIntent"] | None = None
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)
    citations_requested: bool = False


class CreateStructuredFieldIntent(BaseModel):
    """Compact create-only field tree lowered into the authoring field model.

    The provider only needs one recursive edge. ``field_type`` tells the server
    whether ``children`` are object members or array-item members; exposing both
    internal branches made the tool grammar larger without adding information.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    field_type: StructuredFieldType
    description: str
    required: bool = True
    nullable: bool = False
    children: list["CreateStructuredFieldIntent"] | None = None

    @model_validator(mode="after")
    def _validate_children(self) -> "CreateStructuredFieldIntent":
        if self.nullable and self.field_type in ("object", "array"):
            raise ValueError(
                f"Only primitive structured fields may be nullable ({self.name!r})."
            )
        if self.field_type not in ("object", "array") and self.children is not None:
            raise ValueError(
                f"Only object or array fields may declare children ({self.name!r})."
            )
        if self.children == []:
            raise ValueError(
                f"Field {self.name!r} must declare non-empty children or null."
            )
        return self

    def to_structured_field_draft(self) -> StructuredFieldDraft:
        children = (
            [child.to_structured_field_draft() for child in self.children]
            if self.children
            else None
        )
        return StructuredFieldDraft(
            name=self.name,
            field_type=self.field_type,
            description=self.description,
            required=self.required,
            nullable=self.nullable,
            fields=children if self.field_type == "object" else None,
            item_fields=children if self.field_type == "array" else None,
            allow_additional_properties=(
                self.field_type == "object" and children is None
            ),
        )


def _validate_create_semantic_step(value: object) -> dict[str, object]:
    step = _CreateSemanticStepArguments.model_validate(value)
    lowered = step.model_dump(exclude={"output_fields"})
    lowered["output_fields"] = (
        [field.to_structured_field_draft() for field in step.output_fields]
        if step.output_fields
        else None
    )
    return lowered


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


def parse_create_flow_intent_arguments(
    arguments: dict[str, Any],
    *,
    obligation_projection: ProposalObligationProjection | None = None,
) -> CreateFlowIntent:
    remaining = dict(arguments)
    try:
        intent = CreateFlowIntent.model_validate(remaining)
    except ValidationError as error:
        raise ProposalIntentArgumentError(safe_validation_issues(error)) from error
    if obligation_projection is not None:
        _verify_attested_result_contract(
            intent,
            projection=obligation_projection,
        )
    return intent


def _verify_attested_result_contract(
    intent: CreateFlowIntent,
    *,
    projection: ProposalObligationProjection,
) -> None:
    """Admission arm of the one verification predicate.

    The model authors its own output_fields; this verifies the attested
    contract on the TERMINAL step's roots and rejects with the exact path.
    """

    if not intent.steps:
        return
    terminal_index = len(intent.steps) - 1
    terminal = intent.steps[terminal_index]
    fields = list(terminal.output_fields or ())
    roots = tuple((field.name, str(field.field_type)) for field in fields)
    violations = attested_result_contract_violations(roots, projection=projection)
    if not violations:
        return
    prefix = f"steps.{terminal_index}.output_fields"
    index_of = {field.name: i for i, field in enumerate(fields)}

    def _path(violation: AttestedContractViolation) -> str:
        # The exact offending property: a rename points at the misspelled
        # field's name, a shape conflict at the field's type; a missing or
        # duplicated root has no single field to point at.
        if violation.kind == "rename" and violation.matched_names:
            return f"{prefix}.{index_of[violation.matched_names[0]]}.name"
        if violation.kind == "shape_conflict":
            return f"{prefix}.{index_of[violation.key_name]}.field_type"
        return prefix

    raise ProposalIntentArgumentError(
        tuple(
            f"{_path(v)}: {attested_violation_message(v)} [value_error]"
            for v in violations
        )
    )


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
        # Keep the only recursive step property last on the wire. Non-strict
        # providers are less likely to strand later step properties at the
        # proposal root when closing a nested field tree.
        output_fields_schema = step_schema["properties"].pop("output_fields")
        step_schema["properties"]["output_fields"] = output_fields_schema
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
                    "assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    # The recursive proposal body stays last for the same
                    # reason as output_fields inside each step.
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": (
                            1 if is_pure_audio_transcription else MAX_PROPOSAL_STEPS
                        ),
                        "items": step_schema,
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
    "ObligatedResultKey",
    "ProposalIntentArgumentError",
    "ProposalObligationProjection",
    "AddStep",
    "AssistantSpecPatch",
    "FlowInputFieldIntent",
    "ModifyExistingStep",
    "OrderedEditProposal",
    "OrderedEditStep",
    "SemanticStepIntent",
    "build_create_flow_tool_schema",
    "attested_result_contract_violations",
    "attested_violation_message",
    "AttestedContractViolation",
    "build_semantic_step_schema",
    "parse_create_flow_intent_arguments",
    "safe_validation_issues",
]

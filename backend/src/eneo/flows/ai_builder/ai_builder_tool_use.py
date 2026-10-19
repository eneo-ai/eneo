"""A step the planner proposes to read the answer of one MCP tool.

The planner never writes the step's tool configuration. It names a tool of
the turn's catalogue by its ref and, per argument, where the value comes
from: a fixed value, a field of the run form, or a field an earlier step
declares. This module is the one owner of that wire shape, of binding the
ref to the tool, of the run-form field an argument asked at run time
becomes, and of compiling it all into the ``ToolInputConfig`` the editor
writes (``compile_tool_input_config``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from eneo.flows.ai_builder.ai_builder_flow_schema_values import BuilderFormFieldType
from eneo.flows.ai_builder.ai_builder_tool_catalog import AIBuilderToolCatalog
from eneo.flows.ai_builder.ai_builder_tool_question_ids import TOOL_USE_REF_PATTERN
from eneo.flows.application.flow_tool_options import FlowToolOption
from eneo.flows.domain.tool_input import (
    TOOL_INPUT_CONFIG_KEY,
    ToolArgumentError,
    ToolInputConfig,
    required_tool_arguments,
)
from eneo.flows.flow_authoring_spec import FormFieldSpec, StepSpec
from eneo.flows.flow_metadata import parse_form_field_options
from eneo.flows.flow_variable_definitions import form_field_reference_expression
from eneo.flows.input_binding_contract_rules import SourceRefBinding
from eneo.json_types import JsonValue
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolRefusal

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_architecture_errors import (
        AIBuilderArchitectureError,
    )

ToolArgumentSourceKind = Literal["fixed", "run_input", "earlier_step", "ask_user"]
# How much of the user's words a use may cite.
TOOL_USE_EVIDENCE_MAX_CHARS = 240
# The proposal's alternative to a plan when the person asks for a tool the
# turn does not list, and how much of their words naming it it carries.
TOOL_REQUEST_UNRESOLVED_KEY: Final = "tool_request_unresolved"
# For the texts written without the proposal schema at hand; the schema's own
# description names the carriers it offers (``plan_carriers_sentence``).
TOOL_REQUEST_PLAN_FIELDS_RULE: Final = (
    "the plan fields null or empty (steps and, in an edit, also the step "
    "removals, run form, name and description)"
)
TOOL_REQUEST_TEXT_MAX_CHARS: Final = 240


class FixedToolArgument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["fixed"] = "fixed"
    name: str
    value: JsonValue


class RunInputToolArgument(BaseModel):
    """An argument the person gives when they start a run: a run-form field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["run_input"] = "run_input"
    name: str
    field_name: str
    # The label a field this argument adds to the run form gets.
    field_label: str | None = None


class EarlierStepToolArgument(BaseModel):
    """An argument bound to a field an earlier step's JSON output declares:
    the shape of a previous-field reference (``PreviousFieldRef``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["earlier_step"] = "earlier_step"
    name: str
    from_step: int = Field(ge=1)
    field_path: str

    @field_validator("field_path")
    @classmethod
    def _dot_path(cls, value: str) -> str:
        path = value.strip()
        if not path or any(not segment.strip() for segment in path.split(".")):
            raise ValueError("field_path must be a dot path without empty segments.")
        return path


class AskUserToolArgument(BaseModel):
    """An argument whose value the planner does not know: the person is
    asked where it comes from (``tool_argument`` question). The field it would
    get in the run form, when that is the answer, may be suggested."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["ask_user"] = "ask_user"
    name: str
    field_name: str | None = None
    field_label: str | None = None


ToolArgument: TypeAlias = Annotated[
    FixedToolArgument
    | RunInputToolArgument
    | EarlierStepToolArgument
    | AskUserToolArgument,
    Field(discriminator="kind"),
]
# What a compiled step's argument is: the person's question has an answer.
SettledToolArgument: TypeAlias = (
    FixedToolArgument | RunInputToolArgument | EarlierStepToolArgument
)


class _ToolArgumentWire(BaseModel):
    """One argument as the planner writes it. Strict tool schemas need every
    property, so the kinds share one flat shape; only the fields of the
    named source are read, the others are dropped."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source: ToolArgumentSourceKind
    value_json: str | None = None
    field_name: str | None = None
    field_label: str | None = None
    from_step: int | None = None
    field_path: str | None = None

    def lowered(self) -> ToolArgument:
        name = self.name.strip()
        if not name:
            raise ValueError("A tool argument needs its name.")
        if self.source == "fixed":
            if self.value_json is None:
                raise ValueError(f"Argument '{name}': a fixed value needs value_json.")
            try:
                value = _JSON_VALUE.validate_json(self.value_json)
            except ValidationError:
                value = None
                exact = False
            else:
                exact = holds_exact_numbers(value)
            if not exact:
                raise ValueError(
                    f"Argument '{name}': value_json must be one JSON value, "
                    'written as text (a string is "quoted"), whose numbers lie '
                    "within ±9007199254740991 (no NaN or infinity)."
                )
            return FixedToolArgument(name=name, value=value)
        label = (self.field_label or "").strip() or None
        if self.source == "ask_user":
            return AskUserToolArgument(
                name=name,
                field_name=(self.field_name or "").strip() or None,
                field_label=label,
            )
        if self.source == "run_input":
            field_name = (self.field_name or "").strip()
            if not field_name:
                raise ValueError(f"Argument '{name}': run_input needs field_name.")
            return RunInputToolArgument(
                name=name, field_name=field_name, field_label=label
            )
        if self.from_step is None or self.field_path is None:
            raise ValueError(
                f"Argument '{name}': earlier_step needs from_step and field_path."
            )
        return EarlierStepToolArgument(
            name=name, from_step=self.from_step, field_path=self.field_path
        )


class ToolUseIntent(BaseModel):
    """The tool a proposed step reads and where each argument comes from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # The use's key across proposals: kept while the step reads the same
    # tool, so the person's decisions about the use outlive a re-proposal.
    use_ref: str = Field(pattern=TOOL_USE_REF_PATTERN)
    tool_ref: str
    # Other listed tools that would serve the same use: with any, the person
    # chooses (``tool_choice`` question).
    alternative_refs: tuple[str, ...] = ()
    # The user's words that ask for this tool, if any: shown with the
    # question as why, when they are the user's own (``settle_tool_uses``);
    # never a reason to skip one.
    evidence_quote: str | None = Field(
        default=None, max_length=TOOL_USE_EVIDENCE_MAX_CHARS
    )
    arguments: tuple[ToolArgument, ...] = ()

    @field_validator("arguments", mode="before")
    @classmethod
    def _lower_wire_arguments(cls, value: object) -> object:
        try:
            items = _OBJECT_LIST.validate_python(value, strict=True)
        except ValidationError:
            # Not the wire's list: the field's own validation judges it.
            return value
        return [
            _ToolArgumentWire.model_validate(wire).lowered()
            if (wire := _json_object(item)) is not None and "source" in wire
            else item
            for item in items
        ]

    @field_validator("arguments")
    @classmethod
    def _unique_names(cls, value: tuple[ToolArgument, ...]) -> tuple[ToolArgument, ...]:
        names = [argument.name for argument in value]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(f"Each argument is given once: {', '.join(repeated)}.")
        return value


@dataclass(frozen=True, slots=True)
class BoundToolUse:
    """A tool use whose ref names a usable tool of the turn's catalogue."""

    tool: FlowToolOption
    arguments: tuple[ToolArgument, ...]


@dataclass(frozen=True, slots=True)
class ToolUseRefUnknown:
    tool_ref: str


@dataclass(frozen=True, slots=True)
class ToolUseRefUnavailable:
    tool_ref: str
    server_name: str
    tool_name: str
    reason: UnattendedToolRefusal


ToolUseBinding: TypeAlias = BoundToolUse | ToolUseRefUnknown | ToolUseRefUnavailable


def bind_tool_use(
    intent: ToolUseIntent, catalog: AIBuilderToolCatalog
) -> ToolUseBinding:
    """The tool ``intent`` names, or why it names none the step may read."""
    resolved = catalog.resolve_ref(intent.tool_ref)
    if resolved is None:
        return ToolUseRefUnknown(tool_ref=intent.tool_ref)
    if isinstance(resolved, FlowToolOption):
        return BoundToolUse(tool=resolved, arguments=intent.arguments)
    return ToolUseRefUnavailable(
        tool_ref=intent.tool_ref,
        server_name=resolved.server_name,
        tool_name=resolved.tool_name,
        reason=resolved.reason,
    )


def require_bound_tool_use(
    intent: ToolUseIntent, catalog: AIBuilderToolCatalog
) -> BoundToolUse:
    """The tool of a use whose ref the turn already admitted
    (``tool_use_ref_outcome``); any other ref is a server defect."""
    binding = bind_tool_use(intent, catalog)
    if not isinstance(binding, BoundToolUse):
        raise ValueError(
            f"Tool ref '{intent.tool_ref}' was compiled without being admitted."
        )
    return binding


def tool_use_property_schema(listed_refs: Sequence[str]) -> dict[str, Any]:
    """The ``tool_use`` property of a step on the wire: offered only with the
    refs the turn's prompt lists."""
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "required": [
            "use_ref",
            "tool_ref",
            "alternative_refs",
            "evidence_quote",
            "arguments",
        ],
        "description": (
            "Null for a step that reads no MCP tool. Set it only on a step whose "
            "input is the answer of one listed tool: the step's instructions then "
            "say what to do with that answer."
        ),
        "properties": {
            "use_ref": {
                "type": "string",
                "pattern": TOOL_USE_REF_PATTERN,
                "description": (
                    "A short key for this use of a tool, unique in the plan; "
                    "keep it in later proposals while the step reads the same "
                    "tool, so decisions about it are kept."
                ),
            },
            "tool_ref": {"type": "string", "enum": list(listed_refs)},
            "alternative_refs": {
                "type": "array",
                "items": {"type": "string", "enum": list(listed_refs)},
                "description": (
                    "Other listed tools that would serve this use as well; "
                    "empty when only this one fits."
                ),
            },
            "evidence_quote": {
                "type": ["string", "null"],
                "maxLength": TOOL_USE_EVIDENCE_MAX_CHARS,
                "description": (
                    "The user's words that ask for this tool, copied exactly; "
                    "null when they did not name it."
                ),
            },
            "arguments": {
                "type": "array",
                "description": (
                    "One entry per argument the step gives the tool: every "
                    "argument its input_schema requires, and others only when "
                    "the request needs them."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "name",
                        "source",
                        "value_json",
                        "field_name",
                        "field_label",
                        "from_step",
                        "field_path",
                    ],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "source": {
                            "type": "string",
                            "enum": ["fixed", "run_input", "earlier_step", "ask_user"],
                            "description": (
                                "fixed: the same value every run (value_json). "
                                "run_input: the person enters it when starting a "
                                "run (field_name, field_label). earlier_step: a "
                                "field an earlier step's JSON output declares "
                                "(from_step, field_path). ask_user: a required "
                                "value the request does not give; the person is "
                                "asked (field_name and field_label may suggest a "
                                "run-form field)."
                            ),
                        },
                        "value_json": {
                            "type": ["string", "null"],
                            "description": (
                                "fixed only: the value as JSON text, valid for "
                                'the argument\'s schema (a string is "quoted").'
                            ),
                        },
                        "field_name": {
                            "type": ["string", "null"],
                            "description": (
                                "run_input (and ask_user): the run-form field."
                            ),
                        },
                        "field_label": {
                            "type": ["string", "null"],
                            "description": (
                                "run_input only: the field's label in the "
                                "user's language."
                            ),
                        },
                        "from_step": {
                            "type": ["integer", "null"],
                            "minimum": 1,
                            "description": (
                                "earlier_step only: the 1-based number of that "
                                "step in this proposal's steps list."
                            ),
                        },
                        "field_path": {
                            "type": ["string", "null"],
                            "description": (
                                "earlier_step only: dot path of a field that "
                                "step's output_fields declare."
                            ),
                        },
                    },
                },
            },
        },
    }


class ToolRequestUnresolvedIntent(BaseModel):
    """The planner's answer, instead of a plan, that the person asked for a
    tool the turn does not list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_text: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=TOOL_REQUEST_TEXT_MAX_CHARS,
        ),
    ]


def offer_tool_request_unresolved(parameters: dict[str, Any]) -> None:
    """Let a proposal that may name tools answer, instead of a plan, that the
    person asked for one it does not list: the alternative property, and a
    ``steps`` that may then be null (``tool_request_outcome`` refuses both
    at once). The prompt says when (``_resource_context_block``). The
    caller describes the property: which plan fields it leaves empty is the
    schema's."""
    properties: dict[str, Any] = parameters["properties"]
    steps = properties.pop("steps")
    steps["type"] = ["array", "null"]
    properties[TOOL_REQUEST_UNRESOLVED_KEY] = {
        "type": ["object", "null"],
        "additionalProperties": False,
        "required": ["request_text"],
        "properties": {
            "request_text": {
                "type": "string",
                "minLength": 1,
                "maxLength": TOOL_REQUEST_TEXT_MAX_CHARS,
                "description": "The person's words that name the tool, copied exactly.",
            }
        },
    }
    # The recursive plan body stays last on the wire (see the create schema).
    properties["steps"] = steps


@dataclass(frozen=True, slots=True)
class RunFormFieldShape:
    field_type: BuilderFormFieldType
    options: tuple[str, ...] = ()


def tool_argument_form_field(argument_schema: object) -> RunFormFieldShape | None:
    """The run-form field type that hands an argument a value its schema
    accepts, read from the argument's own JSON Schema keywords only; None
    when no field type does (an object, a union, a reference)."""
    schema = _json_object(argument_schema)
    if schema is None:
        return None
    declared = schema.get("type")
    if "enum" in schema:
        # A present enum is the argument's whole contract: a field that does
        # not hold it exactly is no field for the argument, not a plain one.
        return _enum_field_shape(schema, "select")
    if declared == "string":
        return RunFormFieldShape("date" if schema.get("format") == "date" else "text")
    if declared in ("integer", "number"):
        return RunFormFieldShape("number")
    if declared == "array":
        items = _json_object(schema.get("items"))
        if items is None:
            return None
        if "enum" in items:
            return _enum_field_shape(items, "multiselect")
        if items.get("type") == "string" and "format" not in items:
            return RunFormFieldShape("list")
    return None


def _enum_field_shape(
    schema: Mapping[str, object], field_type: Literal["select", "multiselect"]
) -> RunFormFieldShape | None:
    enum = _string_enum(schema)
    if enum is None or schema.get("type") not in (None, "string"):
        return None
    return RunFormFieldShape(field_type, enum)


_OBJECT_LIST = TypeAdapter[list[object]](list[object])
_JSON_VALUE = TypeAdapter[JsonValue](JsonValue)
_JSON_OBJECT = TypeAdapter[dict[str, object]](dict[str, object])
_STRINGS = TypeAdapter[list[str]](list[str])


# The largest whole number the flow editor holds exactly (JavaScript's
# Number.MAX_SAFE_INTEGER, holdsInexactNumber in the editor's tool form).
_EXACT_INTEGER_LIMIT = 2**53 - 1


def holds_exact_numbers(value: JsonValue) -> bool:
    """Whether every number of ``value`` is one the editor shows and saves
    as written: within its exact range, which no NaN or infinity is (and
    every float beyond it is whole)."""
    if isinstance(value, int | float):
        return abs(value) <= _EXACT_INTEGER_LIMIT
    if isinstance(value, list):
        return all(holds_exact_numbers(item) for item in value)
    if isinstance(value, dict):
        return all(holds_exact_numbers(item) for item in value.values())
    return True


def _json_object(value: object) -> dict[str, object] | None:
    try:
        return _JSON_OBJECT.validate_python(value, strict=True)
    except ValidationError:
        return None


def _string_enum(schema: Mapping[str, object]) -> tuple[str, ...] | None:
    """The enum as the options of a choice field, when the run form keeps
    each value as the schema writes it."""
    try:
        values = _STRINGS.validate_python(schema.get("enum"), strict=True)
        options = parse_form_field_options([*values], index=0)
    except (ValidationError, BadRequestException):
        return None
    return tuple(values) if values and options == values else None


def argument_schema(tool: FlowToolOption, argument: str) -> object:
    """The schema the tool's input schema gives ``argument`` at its top-level
    ``properties``; None when it gives none."""
    properties = _json_object((tool.input_schema or {}).get("properties"))
    return None if properties is None else properties.get(argument)


# How much of the tool's input schema a repair names (an argument's schema,
# or the names it declares), so one repair can meet it.
ARGUMENT_SCHEMA_FEEDBACK_MAX_CHARS = 1_000


def declared_arguments_text(tool: FlowToolOption) -> str:
    """The argument names the tool's input schema declares in its top-level
    ``properties``, as a repair names them; "none" for none."""
    properties = _json_object((tool.input_schema or {}).get("properties"))
    text = ", ".join(properties or ())
    if len(text) > ARGUMENT_SCHEMA_FEEDBACK_MAX_CHARS:
        return text[:ARGUMENT_SCHEMA_FEEDBACK_MAX_CHARS] + "…"
    return text or "none"


def run_form_fields_for_tool_uses(
    uses: Sequence[BoundToolUse],
    *,
    form_fields: Sequence[FormFieldSpec],
) -> list[FormFieldSpec]:
    """The run-form fields the uses' run_input arguments add to ``form_fields``,
    each typed from its argument's schema and required when any argument that
    reads it is. An argument whose field the form already has is bound to it
    when the types agree, the field offers only values the argument accepts
    and it is required if the argument is.

    Raises a model-correctable ``AIBuilderArchitectureError`` for an argument
    no field type fits, whose field has another type, other options or is
    optional where the argument is required, or that names a field of the form
    in another case (form field names are one name in any case,
    and a reference names the field as the form writes it).
    """
    known = {field.name.casefold(): field for field in form_fields}
    added: dict[str, FormFieldSpec] = {}
    for use in uses:
        required = set(required_tool_arguments(use.tool.input_schema or {}))
        for argument in use.arguments:
            if not isinstance(argument, RunInputToolArgument):
                continue
            schema = argument_schema(use.tool, argument.name)
            shape = tool_argument_form_field(schema)
            if shape is None:
                raise _argument_error(
                    use,
                    argument.name,
                    "tool_argument_run_input_unfit",
                    (
                        "no run-form field type gives a value its schema "
                        "accepts; give a fixed value or a field of an earlier step"
                    )
                    if schema is not None
                    else (
                        "the tool's input_schema gives no argument of that name "
                        "a schema, so no run-form field type is known to fit; "
                        "its declared arguments are: "
                        + declared_arguments_text(use.tool)
                    ),
                )
            key = argument.field_name.casefold()
            needed = argument.name in required
            existing = known.get(key)
            if existing is None:
                known[key] = added[key] = FormFieldSpec(
                    name=argument.field_name,
                    type=shape.field_type,
                    label=argument.field_label or argument.field_name,
                    required=needed,
                    options=list(shape.options) or None,
                )
                continue
            if existing.name != argument.field_name:
                raise _argument_error(
                    use,
                    argument.name,
                    "tool_argument_run_input_field_name_case",
                    f"the run form has this field as '{existing.name}'; "
                    "write field_name exactly so",
                )
            if existing.type != shape.field_type:
                raise _argument_error(
                    use,
                    argument.name,
                    "tool_argument_run_input_type_mismatch",
                    f"run-form field '{existing.name}' is of type "
                    f"'{existing.type}', but the argument needs a "
                    f"'{shape.field_type}' field; use another field_name",
                )
            # Every value the field offers must be one the argument accepts.
            if not set(existing.options or ()) <= set(shape.options):
                raise _argument_error(
                    use,
                    argument.name,
                    "tool_argument_run_input_options_mismatch",
                    f"run-form field '{existing.name}' offers options the "
                    "argument's schema does not accept; use another field_name",
                )
            if needed and not existing.required:
                if key not in added:
                    raise _argument_error(
                        use,
                        argument.name,
                        "tool_argument_run_input_required_mismatch",
                        f"run-form field '{existing.name}' is optional, but "
                        "the argument is required; use another field_name",
                    )
                known[key] = added[key] = existing.model_copy(update={"required": True})
    return list(added.values())


def compile_tool_input_config(
    use: BoundToolUse, *, numbered_steps: Sequence[StepSpec]
) -> dict[str, Any]:
    """The step's ``input_config``: the tool's ids and each argument as a
    fixed value or one whole reference, written by the owners every other
    read uses. Earlier-step sources must already be checked against
    ``numbered_steps``, the steps ``from_step`` counts
    (``_require_resolvable_previous_refs``)."""
    arguments: dict[str, JsonValue] = {}
    for argument in use.arguments:
        if isinstance(argument, AskUserToolArgument):
            raise ValueError(
                f"Argument '{argument.name}' was compiled before the person "
                "answered where it comes from."
            )
        if isinstance(argument, FixedToolArgument):
            arguments[argument.name] = argument.value
        elif isinstance(argument, RunInputToolArgument):
            arguments[argument.name] = form_field_reference_expression(
                argument.field_name
            )
        else:
            producer = numbered_steps[argument.from_step - 1]
            arguments[argument.name] = SourceRefBinding(
                step_ref=producer.plan_step_ref,
                output="structured",
                field_path=tuple(argument.field_path.split(".")),
            ).template_expression()
    config = ToolInputConfig(
        mcp_server_id=use.tool.mcp_server_id,
        tool_id=use.tool.tool_id,
        arguments=arguments,
    )
    fixed = {
        argument.name
        for argument in use.arguments
        if isinstance(argument, FixedToolArgument)
    }
    try:
        # Only a fixed value can hold a reference this does not admit, or
        # one that would be read as a binding.
        offending = sorted(
            bound.name for bound in config.bound_arguments() if bound.name in fixed
        )
    except ToolArgumentError as error:
        offending = [error.argument]
    if offending:
        raise _argument_error(
            use,
            offending[0],
            "tool_argument_fixed_reference",
            "a fixed value is data and holds no {{ }} reference; use run_input "
            "or earlier_step for a value of the run",
        )
    return {TOOL_INPUT_CONFIG_KEY: config.model_dump(mode="json")}


def _argument_error(
    use: BoundToolUse, argument: str, failure_code: str, problem: str
) -> AIBuilderArchitectureError:
    # Imported here: the error's module reaches the proposal intent, which
    # imports this one for its wire shape.
    from eneo.flows.ai_builder.ai_builder_architecture_errors import (
        AIBuilderArchitectureError,
    )

    return AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        repair_disposition="model_correctable",
        detail=(f"Tool '{use.tool.tool_name}', argument '{argument}': {problem}."),
        log_context={"failure_code": failure_code, "reason": failure_code},
    )

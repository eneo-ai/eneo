"""The configuration of a step whose input is the answer of one MCP tool.

It lives in ``input_config`` under ``tool``. An argument of the tool is either
a fixed JSON value or ONE reference to a run value, written the way templates
write it (``{{step_1.output.structured.days}}``). The reference is replaced by
the value it names, with its JSON type: a list stays a list. Text is never
composed into an argument, so nothing in a flow assembles a query out of run
data.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from eneo.flows.domain.canonical_json_hash import (
    SHA256_HEX_PATTERN,
    canonical_json_hash,
)
from eneo.flows.domain.schema_engine import ref_ignores_siblings
from eneo.flows.enums import FlowInputType
from eneo.flows.flow_validators_template import EXACT_TEMPLATE_EXPRESSION_PATTERN
from eneo.flows.http_transport.authored_config import ConfigPath
from eneo.flows.variable_resolver import TEMPLATE_VARIABLE_PATTERN
from eneo.json_types import JsonValue

TOOL_INPUT_CONFIG_KEY = "tool"
# A tool answers with text or JSON; it hands over no file.
TOOL_INPUT_TYPES: frozenset[FlowInputType] = frozenset(
    {FlowInputType.TEXT, FlowInputType.JSON}
)


class ToolArgumentProblem(StrEnum):
    # Text beside a reference, or more than one reference, in one argument.
    COMPOSED_TEXT = "composed_text"
    # A reference inside a list or an object: it would fill part of an argument.
    NESTED_REFERENCE = "nested_reference"
    # The step gives no value for an argument the tool's input schema requires.
    MISSING_REQUIRED = "missing_required"
    # The step's fixed value for an argument is one that the tool's input
    # schema refuses for that argument.
    OUTSIDE_SCHEMA = "outside_schema"
    # The step gives an argument whose name the tool's input schema refuses
    # whatever its value (``undeclared_tool_arguments``).
    UNDECLARED_ARGUMENT = "undeclared_argument"


class ToolArgumentError(ValueError):
    def __init__(self, argument: str, problem: ToolArgumentProblem) -> None:
        super().__init__(f"Argument '{argument}': {problem.value}.")
        self.argument = argument
        self.problem = problem


@dataclass(frozen=True, slots=True)
class BoundArgument:
    """An argument that is one whole reference to a run value."""

    name: str
    # The argument as it is stored: ``{{ step_1.output.text }}``.
    template: str
    # The reference between the braces: ``step_1.output.text``.
    expression: str


def _empty_arguments() -> dict[str, JsonValue]:
    return {}


class ToolInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_server_id: UUID
    tool_id: UUID
    arguments: dict[str, JsonValue] = Field(default_factory=_empty_arguments)

    def bound_arguments(self) -> tuple[BoundArgument, ...]:
        """Each argument that is bound to a run value.

        Raises ToolArgumentError for an argument that composes text or holds
        a reference below its top level.
        """
        return tuple(
            bound
            for name, value in self.arguments.items()
            if (bound := _bound_argument(name, value)) is not None
        )

    def reference_sites(self) -> list[tuple[ConfigPath, str]]:
        """Where this configuration reads run values: each bound argument's
        path in ``input_config`` and the template it holds."""
        return [
            ((TOOL_INPUT_CONFIG_KEY, "arguments", bound.name), bound.template)
            for bound in self.bound_arguments()
        ]


class PublishedToolInputConfig(ToolInputConfig):
    """The configuration in a published definition: what the author saved and
    the pin, which is what publish read on the server's own tool row. An
    editable step never holds the pin: ``ToolInputConfig`` refuses its keys."""

    tool_name: str = Field(min_length=1)
    # tool_input_schema_sha256 of the input schema that was approved then.
    input_schema_sha256: str = Field(pattern=SHA256_HEX_PATTERN)


_ARGUMENT_NAMES = TypeAdapter[list[str]](list[str])
_PROPERTIES = TypeAdapter[dict[str, object]](dict[str, object])

# Lineage is asked about editable steps and about published ones.
_SAVED_OR_PUBLISHED = TypeAdapter[ToolInputConfig](
    ToolInputConfig | PublishedToolInputConfig
)


def tool_input_schema_sha256(input_schema: Mapping[str, object] | None) -> str:
    """The fingerprint of a tool's input schema. A tool that declares none is
    fingerprinted as the empty object."""
    return canonical_json_hash(input_schema or {})


def required_tool_arguments(input_schema: Mapping[str, object]) -> tuple[str, ...]:
    """The argument names a tool's input schema requires: its top-level
    ``required`` when that is a list of strings, else none. Nothing else of
    the schema is read (no ``required`` below the top level or inside
    ``anyOf``). None either when the schema's draft reads no keyword beside
    its top-level ``$ref`` (``ref_ignores_siblings``): the run's validator
    does not read that ``required``."""
    if ref_ignores_siblings(input_schema):
        return ()
    try:
        return tuple(_ARGUMENT_NAMES.validate_python(input_schema.get("required")))
    except ValidationError:
        return ()


def undeclared_tool_arguments(
    input_schema: Mapping[str, object], names: Iterable[str]
) -> tuple[str, ...]:
    """The names among ``names`` that the tool's input schema refuses
    whatever their values: its top-level ``additionalProperties`` is false,
    no ``patternProperties`` stands beside it, and its top-level
    ``properties`` does not name them. Any other schema leaves every name to
    the run's check, as does a top-level ``$ref`` in a draft that reads no
    keyword beside it (``ref_ignores_siblings``)."""
    if (
        ref_ignores_siblings(input_schema)
        or input_schema.get("additionalProperties") is not False
        or "patternProperties" in input_schema
    ):
        return ()
    try:
        declared = _PROPERTIES.validate_python(
            input_schema.get("properties", {}), strict=True
        )
    except ValidationError:
        declared = {}
    return tuple(name for name in names if name not in declared)


def read_tool_input_config(
    input_config: Mapping[str, object] | None,
) -> ToolInputConfig:
    """The tool configuration an editable step's ``input_config`` holds. Raises
    pydantic's ValidationError when the key is absent or its value is not one."""
    return ToolInputConfig.model_validate(
        (input_config or {}).get(TOOL_INPUT_CONFIG_KEY)
    )


def read_published_tool_input_config(
    input_config: Mapping[str, object] | None,
) -> PublishedToolInputConfig:
    """The pinned tool configuration a published step's ``input_config`` holds.
    Raises pydantic's ValidationError when it is absent, unreadable or
    without the pin."""
    return PublishedToolInputConfig.model_validate(
        (input_config or {}).get(TOOL_INPUT_CONFIG_KEY)
    )


def read_stored_tool_input_config(
    input_config: Mapping[str, object] | None,
) -> ToolInputConfig | None:
    """The tool configuration a step's ``input_config`` holds, editable or
    published. None when it cannot be read as either."""
    try:
        return _SAVED_OR_PUBLISHED.validate_python(
            (input_config or {}).get(TOOL_INPUT_CONFIG_KEY)
        )
    except ValidationError:
        return None


def tool_reference_sites(
    input_config: Mapping[str, object] | None,
) -> list[tuple[ConfigPath, str]] | None:
    """Where a step's tool configuration, editable or published, reads run
    values. None when the configuration cannot be read."""
    config = read_stored_tool_input_config(input_config)
    if config is None:
        return None
    try:
        return config.reference_sites()
    except ToolArgumentError:
        return None


def _bound_argument(name: str, value: JsonValue) -> BoundArgument | None:
    if not isinstance(value, str):
        if _holds_reference(value):
            raise ToolArgumentError(name, ToolArgumentProblem.NESTED_REFERENCE)
        return None
    whole = EXACT_TEMPLATE_EXPRESSION_PATTERN.match(value)
    if whole is not None:
        return BoundArgument(
            name=name, template=value, expression=whole.group(1).strip()
        )
    if TEMPLATE_VARIABLE_PATTERN.search(value) is not None:
        raise ToolArgumentError(name, ToolArgumentProblem.COMPOSED_TEXT)
    return None


def _holds_reference(value: JsonValue) -> bool:
    if isinstance(value, str):
        return TEMPLATE_VARIABLE_PATTERN.search(value) is not None
    if isinstance(value, list):
        return any(_holds_reference(item) for item in value)
    if isinstance(value, dict):
        return any(_holds_reference(item) for item in value.values())
    return False

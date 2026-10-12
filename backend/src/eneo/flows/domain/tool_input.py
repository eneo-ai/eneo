"""The configuration of a step whose input is the answer of one MCP tool.

It lives in ``input_config`` under ``tool``. An argument of the tool is either
a fixed JSON value or ONE reference to a run value, written the way templates
write it (``{{step_1.output.structured.days}}``). The reference is replaced by
the value it names, with its JSON type: a list stays a list. Text is never
composed into an argument, so nothing in a flow assembles a query out of run
data.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.flow_validators_template import EXACT_TEMPLATE_EXPRESSION_PATTERN
from eneo.flows.http_transport.authored_config import ConfigPath
from eneo.flows.variable_resolver import TEMPLATE_VARIABLE_PATTERN
from eneo.json_types import JsonValue

TOOL_INPUT_CONFIG_KEY = "tool"


class ToolArgumentProblem(StrEnum):
    # Text beside a reference, or more than one reference, in one argument.
    COMPOSED_TEXT = "composed_text"
    # A reference inside a list or an object: it would fill part of an argument.
    NESTED_REFERENCE = "nested_reference"


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

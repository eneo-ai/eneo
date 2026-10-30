"""What publish asks and writes for a step whose input is the answer of a tool.

The decision is the MCP module's: publish reads what every level has stored
about the tool for the flow's space and refuses with the first level that
refuses. What it read on the server's own tool row goes into the published
step as the pin.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from eneo.flows.domain.flow_invariant_exceptions import FlowInvariantError
from eneo.flows.domain.flow_step_validation import FlowStepValidationError
from eneo.flows.domain.tool_facts import UnattendedToolFactsSource
from eneo.flows.domain.tool_input import (
    TOOL_INPUT_CONFIG_KEY,
    PublishedToolInputConfig,
    ToolArgumentProblem,
    ToolInputConfig,
    read_tool_input_config,
    required_tool_arguments,
    tool_input_schema_sha256,
    undeclared_tool_arguments,
)
from eneo.flows.domain.tool_input_validation import (
    invalid_tool_config,
    tool_argument_context,
)
from eneo.flows.enums import FlowInputSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.output_processing import (
    ContractUnevaluable,
    refuse_unevaluable_contract,
    refuse_unknown_dialect,
)
from eneo.flows.runtime.tool_argument_check import (
    FixedPropertyViolation,
    ToolArgumentCheckFailed,
    check_fixed_tool_properties,
)
from eneo.main.exceptions import TypedIOValidationException
from eneo.mcp_servers.application.unattended_tool_use import (
    UnattendedToolRefusal,
    unattended_tool_refusal,
)

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool


# What is wrong and who can change it, for the author who publishes. Where no
# administrator can change it, the sentence says what the author can do.
REFUSAL_SENTENCES: Mapping[UnattendedToolRefusal, str] = {
    UnattendedToolRefusal.SERVER_NOT_FOUND: (
        "The tool's MCP server no longer exists, so choose another tool."
    ),
    UnattendedToolRefusal.SERVER_DISABLED: (
        "The tool's MCP server is switched off, which the instance administrator "
        "can change."
    ),
    UnattendedToolRefusal.SERVER_NOT_GENERAL: (
        "The tool belongs to a built-in capability that a flow cannot call as a "
        "tool, so choose another tool."
    ),
    UnattendedToolRefusal.SERVER_FORWARDS_IDENTITY: (
        "The tool's MCP server answers as the signed-in user and a flow run has "
        "none, which the instance administrator can change on the server."
    ),
    UnattendedToolRefusal.SERVER_CREDENTIAL_NEEDS_HTTPS: (
        "The tool's MCP server takes a credential and its address does not use "
        "https, so the call would send the credential readable on the network; "
        "the instance administrator can register the server's https address, "
        "without a user name or password in it."
    ),
    UnattendedToolRefusal.TOOL_NOT_FOUND: (
        "The tool no longer exists on its MCP server, so choose another tool."
    ),
    UnattendedToolRefusal.TOOL_REMOVED_AT_SERVER: (
        "The MCP server no longer offers the tool, so choose another tool."
    ),
    UnattendedToolRefusal.TOOL_WAITING_FOR_REVIEW: (
        "The tool is new or has changed at its MCP server and waits for a "
        "review, which the instance administrator does."
    ),
    UnattendedToolRefusal.TOOL_SWITCHED_OFF: (
        "The tool is switched off, which the instance administrator can change."
    ),
    UnattendedToolRefusal.SPACE_IS_PERSONAL: (
        "A flow in a personal space cannot use tools, so build the flow in a "
        "shared space."
    ),
    UnattendedToolRefusal.SERVER_NOT_IN_SPACE: (
        "The tool's MCP server is not added to this space, which a space "
        "administrator can change."
    ),
    UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE: (
        "The tool is switched off in this space, which a space administrator "
        "can change."
    ),
    UnattendedToolRefusal.SERVER_BELOW_SPACE_CLASSIFICATION: (
        "The tool's MCP server has a lower security classification than this "
        "space, which a space administrator can change for the space or the "
        "instance administrator for the server."
    ),
}


@dataclass(frozen=True, slots=True)
class AllowedTool:
    server: MCPServer
    tool: MCPServerTool


async def read_allowed_tool(
    *,
    step_order: int,
    config: ToolInputConfig,
    facts_reader: UnattendedToolFactsSource,
    tenant_id: UUID,
    space_id: UUID,
) -> AllowedTool:
    """The server and the tool of a step's configuration as they are stored
    now, when every level allows the call for the space.

    The one place flows ask the MCP module's decision. Raises
    ``typed_io_tool_not_allowed`` with the first refusing level: ``context``
    holds ``step_order``, ``refusal``, ``mcp_server_id`` and ``tool_id``. The
    refusal is a TypedIOValidationException because a run's step fails with
    it too; on the publish route it is the 400 every BadRequestException is.
    """
    facts = await facts_reader.read(
        tenant_id=tenant_id,
        space_id=space_id,
        mcp_server_id=config.mcp_server_id,
        tool_id=config.tool_id,
    )
    refusal = unattended_tool_refusal(facts)
    if refusal is not None:
        raise TypedIOValidationException(
            f"Step {step_order}: {REFUSAL_SENTENCES[refusal]}",
            code=FlowApiErrorCode.TYPED_IO_TOOL_NOT_ALLOWED,
            context={
                "step_order": step_order,
                "refusal": refusal,
                "mcp_server_id": str(config.mcp_server_id),
                "tool_id": str(config.tool_id),
            },
        )
    # The decision refuses a missing server (server_not_found) and a missing
    # tool (tool_not_found), so this is not reached through it. It keeps the
    # return type true if the decision ever allows such facts.
    if facts.server is None or facts.tool is None:
        raise FlowInvariantError(
            "The tool decision allowed a tool whose server or tool row is absent."
        )
    return AllowedTool(server=facts.server, tool=facts.tool)


async def pin_tool_steps(
    steps: Sequence[FlowStep],
    *,
    facts_reader: Callable[[], UnattendedToolFactsSource],
    tenant_id: UUID,
    space_id: UUID,
) -> dict[int, PublishedToolInputConfig]:
    """The pinned configuration of every tool step, by step order.

    ``facts_reader`` is asked for only when a tool step is met, so a flow
    without one is published by a service that has no reader. Raises for the
    first step, in step order, whose tool a level refuses for
    the space (``typed_io_tool_not_allowed``), whose approved input schema
    is not a valid JSON Schema of a draft Eneo supports
    (``typed_io_tool_invalid_schema``), or that
    gives no value for an argument the schema's top-level ``required`` names,
    gives an argument whose name the schema refuses, or a fixed value that
    the schema's top-level ``properties`` refuses for its argument where
    publish judges it
    (``check_tool_configuration``; each ``typed_io_tool_invalid_config``). The steps have
    passed the graph check, so each tool configuration reads.
    """
    pins: dict[int, PublishedToolInputConfig] = {}
    # The fingerprints of the schemas this publish has found to be valid.
    checked: set[str] = set()
    for step in sorted(steps, key=lambda item: item.step_order):
        if FlowInputSource(step.input_source) is not FlowInputSource.TOOL:
            continue
        config = read_tool_input_config(step.input_config)
        tool = (
            await read_allowed_tool(
                step_order=step.step_order,
                config=config,
                facts_reader=facts_reader(),
                tenant_id=tenant_id,
                space_id=space_id,
            )
        ).tool
        fingerprint = tool_input_schema_sha256(tool.input_schema)
        finding = await check_tool_configuration(
            config,
            input_schema=tool.input_schema,
            # Once for each schema of this publish, however many steps use it.
            check_schema=fingerprint not in checked,
        )
        _refuse_for_finding(step.step_order, tool.name, finding)
        checked.add(fingerprint)
        pins[step.step_order] = PublishedToolInputConfig(
            mcp_server_id=config.mcp_server_id,
            tool_id=config.tool_id,
            arguments=config.arguments,
            tool_name=tool.name,
            input_schema_sha256=fingerprint,
        )
    return pins


class ToolConfigurationProblem(StrEnum):
    # The approved input schema is no valid JSON Schema of a draft Eneo
    # supports: no run could check the tool's arguments.
    INVALID_SCHEMA = "invalid_schema"
    MISSING_REQUIRED = ToolArgumentProblem.MISSING_REQUIRED.value
    UNDECLARED_ARGUMENT = ToolArgumentProblem.UNDECLARED_ARGUMENT.value
    OUTSIDE_SCHEMA = ToolArgumentProblem.OUTSIDE_SCHEMA.value
    # The checker of fixed values failed on the host, so nothing is proven.
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class ToolConfigurationFinding:
    problem: ToolConfigurationProblem
    argument: str | None = None
    # The schema keyword an outside-schema value fails, when it is known.
    rule: str | None = None


async def check_tool_configuration(
    config: ToolInputConfig,
    *,
    input_schema: dict[str, object] | None,
    check_schema: bool = True,
) -> ToolConfigurationFinding | None:
    """The first problem of a tool step's configuration against the tool's
    approved input schema, None when there is none: publish's checks.

    In order: a schema that is no valid JSON Schema of a draft Eneo supports
    (skipped with ``check_schema`` False, for a schema found valid before), an
    argument the schema's top-level ``required`` names that the step does not
    give, an argument whose name the schema refuses whatever its value
    (``undeclared_tool_arguments``), then a fixed value the schema's
    top-level ``properties`` refuses for its argument. A bound value is known only when the step runs, and is
    checked then. When the checker of fixed values fails on the host the
    finding is ``unverified``: nothing is proven either way.
    """
    if input_schema is not None and check_schema:
        # CPU-bound, and its time grows with the schema: off the event loop,
        # so other requests are served while it runs.
        if await asyncio.to_thread(_schema_is_unevaluable, input_schema):
            return ToolConfigurationFinding(ToolConfigurationProblem.INVALID_SCHEMA)
    for name in required_tool_arguments(input_schema or {}):
        if name not in config.arguments:
            return ToolConfigurationFinding(
                ToolConfigurationProblem.MISSING_REQUIRED, argument=name
            )
    if input_schema is None:
        return None
    if undeclared := undeclared_tool_arguments(input_schema, config.arguments):
        return ToolConfigurationFinding(
            ToolConfigurationProblem.UNDECLARED_ARGUMENT, argument=undeclared[0]
        )
    bound = {argument.name for argument in config.bound_arguments()}
    fixed = {
        name: value for name, value in config.arguments.items() if name not in bound
    }
    if not fixed:
        return None
    try:
        outside = await check_fixed_tool_properties(fixed, input_schema)
    except ToolArgumentCheckFailed:
        # The checker logs the host fault.
        return ToolConfigurationFinding(ToolConfigurationProblem.UNVERIFIED)
    if not isinstance(outside, FixedPropertyViolation):
        return None
    return ToolConfigurationFinding(
        ToolConfigurationProblem.OUTSIDE_SCHEMA,
        argument=outside.argument,
        rule=outside.violation.rule,
    )


def _schema_is_unevaluable(input_schema: dict[str, object]) -> bool:
    label = "the tool's input schema"
    try:
        refuse_unknown_dialect(input_schema, label=label)
        refuse_unevaluable_contract(input_schema, label=label)
    except ContractUnevaluable:
        return True
    return False


def _refuse_for_finding(
    step_order: int, tool_name: str, finding: ToolConfigurationFinding | None
) -> None:
    """Publish's refusal for a finding. Publishing proves no violation when
    the checker failed; the run still checks the full arguments before making
    a tool call."""
    if finding is None or finding.problem is ToolConfigurationProblem.UNVERIFIED:
        return
    if finding.problem is ToolConfigurationProblem.INVALID_SCHEMA:
        # A run checks the step's arguments against this schema before each
        # call; with a schema it cannot evaluate it could check none.
        raise FlowStepValidationError(
            f"Step {step_order}: the input schema the MCP server gives for the "
            "tool is not a valid JSON Schema, or of a draft Eneo does not "
            "support, so a flow cannot check the tool's arguments. The schema is "
            "the server's to correct.",
            step_order=step_order,
            code=FlowApiErrorCode.TYPED_IO_TOOL_INVALID_SCHEMA,
            context={"step_order": step_order},
        )
    argument = finding.argument or ""
    if finding.problem is ToolConfigurationProblem.MISSING_REQUIRED:
        # Every run would fail on it, whatever a bound argument will hold.
        message = (
            f"Step {step_order}: tool '{tool_name}' requires the argument "
            f"'{argument}', which the step does not give."
        )
    elif finding.problem is ToolConfigurationProblem.UNDECLARED_ARGUMENT:
        # Every run would fail on its name, whatever its value.
        message = (
            f"Step {step_order}: the input schema of tool '{tool_name}' "
            f"declares no argument '{argument}' and takes no other."
        )
    else:
        # A fixed value is the same at every run, so every run would fail.
        rule = "" if finding.rule is None else f" (rule '{finding.rule}')"
        message = (
            f"Step {step_order}: the fixed value of argument '{argument}' does "
            f"not fit the input schema of tool '{tool_name}'{rule}."
        )
    raise invalid_tool_config(
        message,
        step_order=step_order,
        context={
            "step_order": step_order,
            **tool_argument_context(argument, finding.problem.value),
        },
    )


def published_input_config(
    step: FlowStep, pin: PublishedToolInputConfig | None
) -> FlowPersistedJsonObject | None:
    """The step's ``input_config`` as a published definition holds it: the
    pinned tool configuration in place of the editable one."""
    if pin is None:
        return step.input_config
    return {
        **(step.input_config or {}),
        TOOL_INPUT_CONFIG_KEY: pin.model_dump(mode="json"),
    }

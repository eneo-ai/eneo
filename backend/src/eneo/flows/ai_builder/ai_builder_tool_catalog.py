"""The space's MCP tools as the Builder session knows them.

The editor's list (``read_space_tool_options``) decides which tools a flow in
the space may use; this module only projects that answer for the planner:
the usable tools in a stable order inside fixed budgets, and the refused
ones, with the refusal that names why, kept aside for guidance. The proposal
prompt then fits the projection to the model's room with
``fit_tool_catalog_projection``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal, TypeAlias
from uuid import UUID

from eneo.flows.application.flow_tool_options import (
    FlowToolOption,
    FlowToolOptionsOverBound,
    SpaceToolOptions,
)
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolRefusal

# Fixed bounds on what one turn may show of a space's catalogue, whatever the
# model: at most 18_000 characters, roughly 4.5k-6k tokens, comparable to the
# 16k-token review evidence bound the same prompt may carry
# (AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS). The model's own
# room decides how much of that is sent: the catalogue is optional prompt
# content fitted after everything else (fit_tool_catalog_projection), so the
# answer reserve and the content packed before it keep their room;
# conversation history above the configured minimum yields to it, as it does
# to attachments. The overview holds about 20 tools whose descriptions reach
# RESOURCE_DESCRIPTION_MAX_CHARS, more with shorter ones; the schemas have a
# bound of their own, so a large schema leaves the overview's tools listed
# and is itself marked as not shown.
TOOL_CATALOG_OVERVIEW_MAX_CHARS = 6_000
TOOL_CATALOG_SCHEMA_MAX_CHARS = 12_000

ToolSchemaState = Literal["included", "over_budget", "none_declared"]


@dataclass(frozen=True, slots=True)
class AIBuilderListedTool:
    """A usable tool as the planner sees it: approved text only, and no
    address or credential of its server, which the list never reads."""

    server_id: UUID
    server_name: str
    tool_id: UUID
    tool_name: str
    # The approved description, whitespace collapsed and cut.
    description: str
    # The server's classification level, while classifications are on.
    classification_level: int | None
    schema_state: ToolSchemaState
    # The approved input schema as compact JSON, when it is included.
    input_schema_json: str | None


@dataclass(frozen=True, slots=True)
class AIBuilderToolCatalogListed:
    tools: tuple[AIBuilderListedTool, ...]
    # Usable tools not listed, for the budget or the model's room; the
    # planner is told how many.
    omitted_count: int
    kind: Literal["listed"] = "listed"


@dataclass(frozen=True, slots=True)
class AIBuilderToolCatalogTooLarge:
    """The space has usable tools but none is listed: none fits the overview
    budget or the model's room, or the space's list is over the list's
    bounds. The planner is told the catalogue is not shown."""

    kind: Literal["too_large"] = "too_large"


@dataclass(frozen=True, slots=True)
class AIBuilderToolCatalogLeftOut:
    """The space has tools, but the prompt had no room for even the
    too-large sentence, so the block was left out of it."""

    kind: Literal["left_out"] = "left_out"


AIBuilderToolCatalogProjection: TypeAlias = (
    AIBuilderToolCatalogListed
    | AIBuilderToolCatalogTooLarge
    | AIBuilderToolCatalogLeftOut
)


@dataclass(frozen=True, slots=True)
class AIBuilderUnavailableTool:
    server_name: str
    tool_name: str
    reason: UnattendedToolRefusal


@dataclass(frozen=True, slots=True)
class AIBuilderToolCatalog:
    projection: AIBuilderToolCatalogProjection
    # Refused tools, in the same order, so guidance can name why a tool the
    # user asks for cannot be used instead of the planner inventing one.
    unavailable: tuple[AIBuilderUnavailableTool, ...]


EMPTY_TOOL_CATALOG = AIBuilderToolCatalog(
    projection=AIBuilderToolCatalogListed(tools=(), omitted_count=0),
    unavailable=(),
)


def build_ai_builder_tool_catalog(
    tool_options: SpaceToolOptions,
    *,
    cut_description: Callable[[str], str],
) -> AIBuilderToolCatalog:
    if isinstance(tool_options, FlowToolOptionsOverBound):
        return AIBuilderToolCatalog(
            projection=AIBuilderToolCatalogTooLarge(), unavailable=()
        )
    ordered = sorted(tool_options.options, key=_catalog_order)
    usable = [option for option in ordered if option.refusal is None]
    unavailable = tuple(
        AIBuilderUnavailableTool(
            server_name=option.mcp_server_name,
            tool_name=option.tool_name,
            reason=option.refusal,
        )
        for option in ordered
        if option.refusal is not None
    )
    listed: list[AIBuilderListedTool] = []
    overview_chars = 0
    schema_chars = 0
    for option in usable:
        tool = _listed_tool(option, cut_description=cut_description)
        schema = tool.input_schema_json
        if schema is not None and (
            schema_chars + len(schema) > TOOL_CATALOG_SCHEMA_MAX_CHARS
        ):
            tool = replace(tool, schema_state="over_budget", input_schema_json=None)
        tool_chars = _overview_chars(tool)
        if overview_chars + tool_chars > TOOL_CATALOG_OVERVIEW_MAX_CHARS:
            # Skipped, not stopped at: one oversized name hides only itself.
            continue
        overview_chars += tool_chars
        schema_chars += len(tool.input_schema_json or "")
        listed.append(tool)
    if usable and not listed:
        return AIBuilderToolCatalog(
            projection=AIBuilderToolCatalogTooLarge(), unavailable=unavailable
        )
    return AIBuilderToolCatalog(
        projection=AIBuilderToolCatalogListed(
            tools=tuple(listed), omitted_count=len(usable) - len(listed)
        ),
        unavailable=unavailable,
    )


def fit_tool_catalog_projection(
    projection: AIBuilderToolCatalogProjection,
    *,
    fits: Callable[[AIBuilderToolCatalogProjection], bool],
) -> AIBuilderToolCatalogProjection:
    """The first of the projection's reductions the prompt has room for, or
    the left-out outcome when none has.

    Schemas go first, the last listed first; then tools, the last first;
    then the whole list gives way to the too-large sentence. A reduction is
    not always shorter than the one before (a short schema is longer than
    the sentence that replaces it), so they are tried in order, at most two
    per listed tool and one more, stopping at the first that fits.
    """
    return next(
        (step for step in _reductions(projection) if fits(step)),
        AIBuilderToolCatalogLeftOut(),
    )


def _reductions(
    projection: AIBuilderToolCatalogProjection,
) -> list[AIBuilderToolCatalogProjection]:
    if not isinstance(projection, AIBuilderToolCatalogListed):
        return [projection]
    tools = list(projection.tools)
    steps: list[AIBuilderToolCatalogProjection] = [projection]
    for index in reversed(range(len(tools))):
        if tools[index].input_schema_json is None:
            continue
        tools[index] = replace(
            tools[index], schema_state="over_budget", input_schema_json=None
        )
        steps.append(replace(projection, tools=tuple(tools)))
    for kept in reversed(range(1, len(tools))):
        steps.append(
            AIBuilderToolCatalogListed(
                tools=tuple(tools[:kept]),
                omitted_count=projection.omitted_count + len(tools) - kept,
            )
        )
    if tools:
        steps.append(AIBuilderToolCatalogTooLarge())
    return steps


def render_tool_catalog_block(projection: AIBuilderToolCatalogProjection) -> str:
    """The planner's read-only view of the usable tools; empty when the
    space has none."""
    if isinstance(projection, AIBuilderToolCatalogLeftOut):
        return ""
    if isinstance(projection, AIBuilderToolCatalogTooLarge):
        return (
            "This space offers more MCP tools than fit in this context, so "
            "none are listed."
        )
    if not projection.tools:
        return ""
    lines: list[str] = []
    for tool in projection.tools:
        lines.extend((tool_overview_line(tool), _schema_line(tool)))
    if projection.omitted_count:
        lines.append(f"{projection.omitted_count} more usable tools are not listed.")
    return "\n".join(lines)


def tool_overview_line(tool: AIBuilderListedTool) -> str:
    fields = [
        f"tool={json.dumps(tool.tool_name, ensure_ascii=False)}",
        f"server={json.dumps(tool.server_name, ensure_ascii=False)}",
    ]
    if tool.classification_level is not None:
        fields.append(f"classification_level={tool.classification_level}")
    rendered = "- " + " | ".join(fields)
    if tool.description:
        rendered += f" - {json.dumps(tool.description, ensure_ascii=False)}"
    return rendered


def _schema_line(tool: AIBuilderListedTool) -> str:
    if tool.input_schema_json is not None:
        return f"  input_schema: {tool.input_schema_json}"
    if tool.schema_state == "over_budget":
        return "  input_schema: not shown (over this context's schema budget)"
    return "  input_schema: none declared"


def _overview_chars(tool: AIBuilderListedTool) -> int:
    """What a tool's two lines take of the overview budget: everything but
    the schema text, which the schema budget counts."""
    schema_text = len(tool.input_schema_json or "")
    return len(tool_overview_line(tool)) + len(_schema_line(tool)) - schema_text + 2


def _catalog_order(option: FlowToolOption) -> tuple[str, str, UUID, UUID]:
    return (
        option.mcp_server_name,
        option.tool_name,
        option.mcp_server_id,
        option.tool_id,
    )


def _listed_tool(
    option: FlowToolOption, *, cut_description: Callable[[str], str]
) -> AIBuilderListedTool:
    schema = option.input_schema
    return AIBuilderListedTool(
        server_id=option.mcp_server_id,
        server_name=option.mcp_server_name,
        tool_id=option.tool_id,
        tool_name=option.tool_name,
        description=cut_description(" ".join((option.tool_description or "").split())),
        classification_level=option.mcp_server_security_level,
        schema_state="none_declared" if schema is None else "included",
        input_schema_json=(
            None
            if schema is None
            else json.dumps(
                schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        ),
    )

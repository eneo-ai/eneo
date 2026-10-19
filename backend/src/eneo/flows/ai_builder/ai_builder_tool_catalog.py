"""The space's MCP tools as the Builder session knows them.

The editor's list (``read_space_tool_options``) decides which tools a flow in
the space may use; this module only projects that answer for the planner:
the usable tools in a stable order inside fixed budgets, and the refused
ones, with the refusal that names why, kept aside for guidance. The proposal
prompt then fits the projection to the model's room with
``fit_tool_catalog_projection``.

Each tool carries a ref the planner names it by (``tool_ref``): minted from
its server's and its own id, so it is the same in every turn, whatever else
the space adds, and it resolves (``AIBuilderToolCatalog.resolve_ref``) for
every tool of the space, also one the budgets left out of the prompt. (Two
tools whose refs coincide, which a space does not have in practice, have none.)
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
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
# The refused tools the prompt names, so a request for one is answered with
# its refusal instead of another tool: names and a code only.
TOOL_CATALOG_UNAVAILABLE_MAX_CHARS = 2_000
# Hex digits of the ids' digest a ref holds: the same for every tool, so what
# else the space offers never changes a ref. 48 bits leave two tools of one
# space sharing a ref (``_mint_refs``) a chance far below any real space's.
TOOL_REF_HEX_DIGITS = 12
TOOL_REF_PATTERN = rf"^tool_[0-9a-f]{{{TOOL_REF_HEX_DIGITS}}}$"

ToolSchemaState = Literal["included", "over_budget", "none_declared"]


@dataclass(frozen=True, slots=True)
class AIBuilderListedTool:
    """A usable tool as the planner sees it: approved text only, and no
    address or credential of its server. The list reads no stored credential, and
    the address only for the decision."""

    ref: str
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
class AIBuilderUnavailableTool:
    ref: str
    server_name: str
    tool_name: str
    reason: UnattendedToolRefusal


@dataclass(frozen=True, slots=True)
class AIBuilderToolCatalogListed:
    tools: tuple[AIBuilderListedTool, ...]
    # Usable tools not listed, for the budget or the model's room; the
    # planner is told how many.
    omitted_count: int
    kind: Literal["listed"] = "listed"
    # Refused tools named with their refusal, within their own budget.
    unavailable: tuple[AIBuilderUnavailableTool, ...] = ()


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


@dataclass(frozen=True, slots=True)
class AIBuilderToolCatalogNotOffered:
    """A create session whose person has not said to use the space's tools,
    or said not to: the prompt lists none and the step schema offers no
    tool_use."""

    kind: Literal["not_offered"] = "not_offered"


AIBuilderToolCatalogProjection: TypeAlias = (
    AIBuilderToolCatalogListed
    | AIBuilderToolCatalogTooLarge
    | AIBuilderToolCatalogLeftOut
    | AIBuilderToolCatalogNotOffered
)


def _no_usable_tools() -> Mapping[str, FlowToolOption]:
    return {}


@dataclass(frozen=True, slots=True)
class AIBuilderToolCatalog:
    projection: AIBuilderToolCatalogProjection
    # Refused tools, in the same order, so guidance can name why a tool the
    # user asks for cannot be used instead of the planner inventing one.
    unavailable: tuple[AIBuilderUnavailableTool, ...]
    # Every usable tool of the space by ref, whatever the projection lists:
    # a ref the budgets left out of this turn's prompt still names its tool.
    usable_by_ref: Mapping[str, FlowToolOption] = field(
        default_factory=_no_usable_tools
    )

    def resolve_ref(self, ref: str) -> FlowToolOption | AIBuilderUnavailableTool | None:
        """The usable tool ``ref`` names, the refused one with its refusal,
        or None for a ref no tool of the space has."""
        usable = self.usable_by_ref.get(ref)
        if usable is not None:
            return usable
        return next((tool for tool in self.unavailable if tool.ref == ref), None)

    def usable_option(self, server_id: UUID, tool_id: UUID) -> FlowToolOption | None:
        """The usable tool with these ids, None when the space has none."""
        return next(
            (
                option
                for option in self.usable_by_ref.values()
                if (option.mcp_server_id, option.tool_id) == (server_id, tool_id)
            ),
            None,
        )

    def ref_of_usable(self, server_id: UUID, tool_id: UUID) -> str | None:
        """The ref of the usable tool with these ids, None when the space has
        none."""
        return next(
            (
                ref
                for ref, option in self.usable_by_ref.items()
                if (option.mcp_server_id, option.tool_id) == (server_id, tool_id)
            ),
            None,
        )

    @property
    def listed_refs(self) -> tuple[str, ...]:
        """The refs of the tools this turn's prompt names, usable ones first,
        in its order."""
        if not isinstance(self.projection, AIBuilderToolCatalogListed):
            return ()
        return (
            *(tool.ref for tool in self.projection.tools),
            *(tool.ref for tool in self.projection.unavailable),
        )


EMPTY_TOOL_CATALOG = AIBuilderToolCatalog(
    projection=AIBuilderToolCatalogListed(tools=(), omitted_count=0),
    unavailable=(),
)


def tool_ref(server_id: UUID, tool_id: UUID) -> str:
    """The ref the planner names a tool by: ``tool_`` and the first hex digits
    of the SHA-256 of its server's and its own id. Not an index, so a tool the
    space adds moves no other tool's ref, and not a uuid, which the spec
    refuses as a portable ref."""
    digest = hashlib.sha256(f"{server_id}|{tool_id}".encode()).hexdigest()
    return f"tool_{digest[:TOOL_REF_HEX_DIGITS]}"


def tool_options_with_refs(
    options: Sequence[FlowToolOption],
) -> list[tuple[str, FlowToolOption]]:
    """Every tool of the space in catalogue order that has a ref, with the ref
    the planner names it by: the session's tool list shows the same refs."""
    ordered = sorted(options, key=_catalog_order)
    refs = _mint_refs(ordered)
    return [
        (refs[key], option)
        for option in ordered
        if (key := (option.mcp_server_id, option.tool_id)) in refs
    ]


def _mint_refs(options: list[FlowToolOption]) -> dict[tuple[UUID, UUID], str]:
    """Each tool's ref. Two distinct tools that share one ref get none: a ref
    that moved to tell them apart would change with the catalogue, and a ref
    must name one tool."""
    refs = {
        (option.mcp_server_id, option.tool_id): tool_ref(
            option.mcp_server_id, option.tool_id
        )
        for option in options
    }
    shared = Counter(refs.values())
    return {key: ref for key, ref in refs.items() if shared[ref] == 1}


def build_ai_builder_tool_catalog(
    tool_options: SpaceToolOptions,
    *,
    cut_description: Callable[[str], str],
) -> AIBuilderToolCatalog:
    if isinstance(tool_options, FlowToolOptionsOverBound):
        return AIBuilderToolCatalog(
            projection=AIBuilderToolCatalogTooLarge(), unavailable=()
        )
    with_refs = tool_options_with_refs(tool_options.options)
    usable_by_ref = {ref: option for ref, option in with_refs if option.refusal is None}
    unavailable = tuple(
        AIBuilderUnavailableTool(
            ref=ref,
            server_name=option.mcp_server_name,
            tool_name=option.tool_name,
            reason=option.refusal,
        )
        for ref, option in with_refs
        if option.refusal is not None
    )
    listed: list[AIBuilderListedTool] = []
    overview_chars = 0
    schema_chars = 0
    for ref, option in usable_by_ref.items():
        tool = _listed_tool(option, ref=ref, cut_description=cut_description)
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
    named_unavailable: list[AIBuilderUnavailableTool] = []
    unavailable_chars = 0
    for tool in unavailable:
        line_chars = len(_unavailable_line(tool)) + 1
        if unavailable_chars + line_chars > TOOL_CATALOG_UNAVAILABLE_MAX_CHARS:
            continue
        unavailable_chars += line_chars
        named_unavailable.append(tool)
    if usable_by_ref and not listed:
        return AIBuilderToolCatalog(
            projection=AIBuilderToolCatalogTooLarge(),
            unavailable=unavailable,
            usable_by_ref=usable_by_ref,
        )
    return AIBuilderToolCatalog(
        projection=AIBuilderToolCatalogListed(
            tools=tuple(listed),
            omitted_count=len(usable_by_ref) - len(listed),
            unavailable=tuple(named_unavailable),
        ),
        unavailable=unavailable,
        usable_by_ref=usable_by_ref,
    )


def fit_tool_catalog_projection(
    projection: AIBuilderToolCatalogProjection,
    *,
    fits: Callable[[AIBuilderToolCatalogProjection], bool],
) -> AIBuilderToolCatalogProjection:
    """The first of the projection's reductions the prompt has room for, or
    the left-out outcome when none has.

    The refused tools' names go first; then schemas, the last listed first;
    then tools, the last first; then the whole list gives way to the
    too-large sentence. A reduction is
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
    steps: list[AIBuilderToolCatalogProjection] = [projection]
    if projection.unavailable:
        projection = replace(projection, unavailable=())
        steps.append(projection)
    tools = list(projection.tools)
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
    if isinstance(
        projection, AIBuilderToolCatalogLeftOut | AIBuilderToolCatalogNotOffered
    ):
        return ""
    if isinstance(projection, AIBuilderToolCatalogTooLarge):
        return (
            "This space offers more MCP tools than fit in this context, so "
            "none are listed."
        )
    lines: list[str] = []
    for tool in projection.tools:
        lines.extend((tool_overview_line(tool), _schema_line(tool)))
    if projection.omitted_count:
        lines.append(f"{projection.omitted_count} more usable tools are not listed.")
    if projection.unavailable:
        lines.append("Not usable in this space (the reason is the refusal code):")
        lines.extend(_unavailable_line(tool) for tool in projection.unavailable)
    return "\n".join(lines)


def _unavailable_line(tool: AIBuilderUnavailableTool) -> str:
    return (
        f"- ref={tool.ref} | tool={json.dumps(tool.tool_name, ensure_ascii=False)}"
        f" | server={json.dumps(tool.server_name, ensure_ascii=False)}"
        f" | reason={tool.reason.value}"
    )


def tool_overview_line(tool: AIBuilderListedTool) -> str:
    fields = [
        f"ref={tool.ref}",
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
    option: FlowToolOption, *, ref: str, cut_description: Callable[[str], str]
) -> AIBuilderListedTool:
    schema = option.input_schema
    return AIBuilderListedTool(
        ref=ref,
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

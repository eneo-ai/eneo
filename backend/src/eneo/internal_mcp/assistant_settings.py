# pyright: basic
"""Session-bound tools over the assistant a helper chat is about.

Each call finds its assistant through the helper chat its token was minted
for (the chat's session and hidden assistant), never through the model's
arguments, and reads as the person: their access to the assistant and its
space decides what a call can see. What a call returns is plain text built
from an allow-list of settings, so a credential, an API key or a server's
sign-in configuration never reaches the model. Every tool here reads.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from eneo.internal_mcp.constants import ASSISTANT_SERVER_NAME
from eneo.internal_mcp.foundation import (
    build_ephemeral_server,
    default_page_cap,
    fit_lines,
    internal_tool_context,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)

mcp = FastMCP(
    name="Eneo Assistant Settings",
    stateless_http=True,
    instructions="Read the assistant this chat is about and what its space offers.",
)

# Reading tools change nothing.
_READS = ToolAnnotations(readOnlyHint=True)

AssistantSection = Literal[
    "overview", "instructions", "model", "knowledge", "tools", "access", "all"
]
OptionsSection = Literal["model", "knowledge", "tools", "all"]

# A line longer than this is cut into several, so one page always holds a
# whole line.
_LINE_CHARS = 1000

_FUNCTIONS: dict[str, str] = {
    "web_search": "search the web",
    "image_generation": "make images",
    "file_analysis": "read and analyse uploaded files and tables",
    "file_creation": "make documents and spreadsheets",
    "charts": "make charts",
    "compute": "calculate with code",
}

_SETTINGS: tuple[tuple[str, str], ...] = (
    ("temperature", "temperature"),
    ("top_p", "top p"),
    ("reasoning_effort", "reasoning effort"),
    ("verbosity", "verbosity"),
    ("presence_penalty", "presence penalty"),
    ("frequency_penalty", "frequency penalty"),
    ("top_k", "top k"),
)


# --- Calls -------------------------------------------------------------------


async def _call(
    ctx: Context, operation: Callable[[Any, Any], Awaitable[CallToolResult]]
) -> CallToolResult:
    """Run ``operation`` on the chat the token was minted for, as the person,
    in one transaction. A refusal comes back as text the model reads."""
    from eneo.assistants.application.assistant_helper_chat import ASSISTANT_TARGET
    from eneo.helper_chats.application import helper_chat_service

    try:
        async with internal_tool_context(ctx) as scope:
            if scope.session_id is None:
                raise NotFoundException("Helper chat not found.")
            chat = await helper_chat_service.load_chat(
                scope.container,
                ASSISTANT_TARGET,
                session_id=scope.session_id,
                assistant_id=scope.assistant_id,
            )
            return await operation(scope.container, chat)
    except (BadRequestException, NotFoundException, UnauthorizedException) as exc:
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text=str(exc) or type(exc).__name__)],
        )


def page_lines(
    lines: Sequence[str],
    *,
    tool: str,
    section: str,
    offset: int,
    assistant_id: UUID,
) -> CallToolResult:
    """One page of ``lines`` from line ``offset``, sized to the tool output
    cap, saying how to read on when more is left."""
    if offset < 0:
        raise BadRequestException("offset must be zero or more.")
    total = len(lines)
    if offset and offset >= total:
        raise BadRequestException(
            f"offset is past the end ({total} lines); read again from offset 0."
        )
    header = f"{_title(tool, section)} (lines {offset + 1}-"
    kept = fit_lines(lines[offset:], default_page_cap() - len(header) - 400)
    shown_to = offset + len(kept)
    text = f"{header}{shown_to} of {total}):\n" + "\n".join(kept)
    next_offset = shown_to if shown_to < total else None
    if next_offset is not None:
        text += (
            f"\n\nMore follows. Call {tool} again with section={section} and "
            f"offset={next_offset} before you say you have read it all."
        )
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent={
            "assistant_id": str(assistant_id),
            "next_offset": next_offset,
        },
    )


def _title(tool: str, section: str) -> str:
    what = "The assistant" if tool == "read_assistant" else "What the space offers"
    return f"{what}, section {section}"


# --- Formatting --------------------------------------------------------------


def _wrapped(text: str) -> list[str]:
    """``text`` as lines, none longer than ``_LINE_CHARS``."""
    lines: list[str] = []
    for line in text.splitlines() or [""]:
        while len(line) > _LINE_CHARS:
            lines.append(line[:_LINE_CHARS])
            line = line[_LINE_CHARS:]
        lines.append(line)
    return lines


def _yes(value: object) -> str:
    return "yes" if value else "no"


def _short(text: str | None, limit: int = 200) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _model_name(model: Any) -> str:
    return getattr(model, "nickname", None) or model.name


def _per_million(cost: Decimal | float | None) -> str | None:
    if cost is None:
        return None
    return f"${Decimal(str(cost)) * 1_000_000:.2f}"


def _model_facts(model: Any, *, show_pricing: bool, offered: Any) -> list[str]:
    """What the editor shows about a model, with the reasoning efforts it
    offers (``offered``: its supported settings)."""
    window = model.max_input_tokens
    facts = [
        f"context window: {window:,} tokens" if window else "context window: unknown",
        f"tool calling: {_yes(model.supports_tool_calling)}",
        f"reasoning: {_yes(model.reasoning)}",
        f"reads images: {_yes(model.vision)}",
    ]
    efforts = getattr(getattr(offered, "reasoning_effort", None), "options", None)
    if getattr(getattr(offered, "reasoning_effort", None), "supported", False):
        facts.append(f"reasoning efforts: {', '.join(efforts or [])}")
    if show_pricing:
        prices = [
            f"{label} {price}"
            for label, price in (
                ("input", _per_million(model.input_cost_per_token)),
                ("output", _per_million(model.output_cost_per_token)),
            )
            if price is not None
        ]
        if prices:
            facts.append(f"price per million tokens: {', '.join(prices)}")
    hosting = getattr(model, "hosting", None)
    if hosting:
        facts.append(f"hosting: {hosting}")
    if getattr(model, "is_deprecated", False):
        facts.append("deprecated")
    return facts


def _url(raw: str | None) -> str:
    """An address without its sign-in part or query, as a source to name."""
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.hostname:
        return ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.hostname}{port}{parts.path}"


def _website(website: Any) -> str:
    address = _url(website.url)
    return f"{website.name or address}: {address}"


def _loaded_tools(server: Any) -> list[Any]:
    """A server's tools as read; none when it was read without them."""
    return list(server.tools) if getattr(server, "tools_loaded", True) else []


def _function_line(purpose: str, availability: Iterable[Any]) -> str:
    state = next((item for item in availability if item.purpose == purpose), None)
    if state is not None and state.available:
        ready = "ready"
    elif state is not None and state.reason:
        ready = f"not ready ({state.reason})"
    else:
        ready = "not ready"
    return f"- {purpose}: {_FUNCTIONS.get(purpose, purpose)}; {ready}"


# --- read_assistant ----------------------------------------------------------


@dataclass(frozen=True)
class AssistantReading:
    """What ``read_assistant`` reports on: the assistant as the person reads
    it, with the names its saved choices point at."""

    assistant: Any
    permissions: Sequence[Any]
    effective_config: Any | None
    show_pricing: bool
    rerank_model_name: str | None = None
    document_template_name: str | None = None


def policy_locks(config: Any | None) -> list[str]:
    """The settings an organisation policy decides for the assistant."""
    if config is None:
        return []
    locks: list[str] = []
    if config.prompt_enforced:
        locks.append("instructions: set by the policy")
    if config.models_enforced:
        locked = config.locked_model
        locks.append(
            f"chat model: locked to {_model_name(locked)}"
            if locked is not None
            else "chat model: only "
            + ", ".join(_model_name(model) for model in config.available_models)
        )
    if config.reasoning_policy_configured and not (
        config.reasoning_effort_user_configurable
    ):
        locks.append("reasoning effort: set by the policy")
    if config.mcp_enforced:
        locks.append("MCP servers and functions: set by the policy")
    if config.inline_file_text is not None:
        locks.append("handling of files uploaded in a chat: set by the policy")
    return locks


def _overview(reading: AssistantReading) -> list[str]:
    assistant = reading.assistant
    model = assistant.completion_model
    text = assistant.get_prompt_text()
    lines = [
        f"Name: {assistant.name} [id {assistant.id}]",
        f"Description: {_short(assistant.description) or 'none'}",
        f"Published: {_yes(assistant.published)}",
        "Chat model: "
        + (f"{_model_name(model)} [id {model.id}]" if model is not None else "none"),
        f"Instructions: {len(text):,} characters"
        if text
        else "Instructions: none saved",
        (
            f"Knowledge: {len(assistant.collections)} collections, "
            f"{len(assistant.websites)} websites, "
            f"{len(assistant.integration_knowledge_list)} integration sources, "
            f"{len(assistant.attachments)} attachments"
        ),
        (
            f"Tools: {len(assistant.mcp_servers)} MCP servers; functions: "
            + (", ".join(assistant.enabled_capabilities) or "none")
        ),
    ]
    return lines + _rights(reading) + _locks_lines(reading)


def _rights(reading: AssistantReading) -> list[str]:
    rights = [getattr(item, "value", str(item)) for item in reading.permissions]
    return [f"The person may: {', '.join(rights) or 'read only'}"]


def _locks_lines(reading: AssistantReading) -> list[str]:
    locks = policy_locks(reading.effective_config)
    if not locks:
        return ["Locked by an organisation policy: nothing"]
    return ["Locked by an organisation policy:"] + [f"- {lock}" for lock in locks]


def _instructions(reading: AssistantReading) -> list[str]:
    text = reading.assistant.get_prompt_text()
    config = reading.effective_config
    lines: list[str] = []
    if config is not None and config.prompt_enforced:
        lines.append(
            "Locked: an organisation policy sets the instructions this assistant "
            "answers with; the text below is not used."
        )
    if not text:
        return lines + ["No instructions are saved."]
    return (
        lines + [f"Instructions as saved ({len(text):,} characters):"] + _wrapped(text)
    )


def _model(reading: AssistantReading) -> list[str]:
    assistant = reading.assistant
    model = assistant.completion_model
    if model is None:
        lines = ["Chat model: none chosen"]
        offered = None
    else:
        offered = model.get_supported_model_kwargs()
        lines = [f"Chat model: {_model_name(model)} [id {model.id}]"] + [
            f"  {fact}"
            for fact in _model_facts(
                model, show_pricing=reading.show_pricing, offered=offered
            )
        ]
    lines.append("Model settings:")
    stored = assistant.completion_model_kwargs
    for key, label in _SETTINGS:
        value = getattr(stored, key, None) if stored is not None else None
        capability = getattr(offered, key, None)
        if value is None and not getattr(capability, "supported", False):
            continue
        lines.append(
            f"  {label}: {value if value is not None else 'the model default'}"
        )
    return lines + [
        f"- {lock}"
        for lock in policy_locks(reading.effective_config)
        if lock.startswith(("chat model", "reasoning"))
    ]


def _knowledge(reading: AssistantReading) -> list[str]:
    assistant = reading.assistant
    mode = getattr(assistant.knowledge_mode, "value", assistant.knowledge_mode)

    def origin(item: Any) -> str:
        return (
            " (organisation knowledge)"
            if item.space_id is not None and item.space_id != assistant.space_id
            else ""
        )

    lines = [
        "Knowledge mode: "
        + (
            "the assistant searches its knowledge when it needs to"
            if mode == "tool"
            else "relevant parts are put in the prompt on every question"
        )
    ]
    lines.append(f"Collections ({len(assistant.collections)}):")
    lines += [
        f"- {item.name} [id {item.id}]{origin(item)}" for item in assistant.collections
    ]
    lines.append(f"Websites ({len(assistant.websites)}):")
    lines += [
        f"- {_website(item)} [id {item.id}]{origin(item)}"
        for item in assistant.websites
    ]
    lines.append(f"Integration sources ({len(assistant.integration_knowledge_list)}):")
    lines += [
        f"- {item.name} [id {item.id}]{origin(item)}"
        for item in assistant.integration_knowledge_list
    ]
    lines.append(
        "Result ranking: "
        + (
            reading.rerank_model_name
            or (
                f"[id {assistant.rerank_model_id}]"
                if assistant.rerank_model_id
                else "none"
            )
        )
    )
    inline = assistant.inline_file_text
    config = reading.effective_config
    if config is not None and config.inline_file_text is not None:
        inline = config.inline_file_text
    lines.append(
        "Files uploaded in a chat: "
        + ("put whole in the prompt" if inline else "looked up when needed")
        + (
            " (set by an organisation policy)"
            if config is not None and config.inline_file_text is not None
            else ""
        )
    )
    attachments = assistant.attachments
    lines.append(f"Attachments ({len(attachments)}):")
    inline_text = assistant.attachment_inline_text
    lines += [
        f"- {item.name}: "
        + (
            "always in the prompt"
            if inline_text.get(item.id, True)
            else "opened with a tool when needed"
        )
        for item in attachments
    ]
    return lines


def _tools(reading: AssistantReading) -> list[str]:
    assistant = reading.assistant
    overrides = dict(assistant.mcp_tools)
    lines = [f"MCP servers ({len(assistant.mcp_servers)}):"]
    for server in assistant.mcp_servers:
        description = _short(server.description)
        lines.append(
            f"- {server.name} [id {server.id}]"
            + (f": {description}" if description else "")
        )
        tools = sorted(_loaded_tools(server), key=lambda tool: tool.name)
        if tools:
            lines.append(
                "  tools: "
                + ", ".join(
                    f"{tool.display_name or tool.name} "
                    f"({'on' if overrides.get(tool.id, tool.is_enabled) else 'off'})"
                    for tool in tools
                )
            )
    lines.append(f"Functions on ({len(assistant.enabled_capabilities)}):")
    lines += [
        _function_line(purpose, assistant.available_capabilities)
        for purpose in assistant.enabled_capabilities
    ]
    choice = assistant.document_template
    if choice.mode == "default":
        template = "the organisation's default"
    elif choice.mode == "builtin":
        template = "Eneo's built-in look"
    else:
        name = reading.document_template_name or "a template"
        template = f"{name} [id {choice.template_id}]"
    lines.append(f"Document template: {template}")
    return lines + [
        f"- {lock}"
        for lock in policy_locks(reading.effective_config)
        if lock.startswith("MCP")
    ]


def _access(reading: AssistantReading) -> list[str]:
    assistant = reading.assistant
    retention = assistant.data_retention_days
    return [
        f"Published: {_yes(assistant.published)}",
        *_rights(reading),
        f"Insights: {'on' if assistant.insight_enabled else 'off'}",
        f"Conversation logging: {'on' if assistant.logging_enabled else 'off'}",
        "Conversation retention: "
        + (
            f"{retention} days"
            if retention is not None
            else "follows the space, then the organisation"
        ),
        f"The space's own chat assistant: {_yes(assistant.is_default)}",
    ]


_ASSISTANT_SECTIONS: dict[str, Callable[[AssistantReading], list[str]]] = {
    "overview": _overview,
    "instructions": _instructions,
    "model": _model,
    "knowledge": _knowledge,
    "tools": _tools,
    "access": _access,
}


def assistant_lines(reading: AssistantReading, section: str) -> list[str]:
    """The lines ``read_assistant`` pages through for ``section``."""
    if section == "all":
        lines: list[str] = []
        for name, build in _ASSISTANT_SECTIONS.items():
            lines += [f"== {name} =="] + build(reading)
        return lines
    build = _ASSISTANT_SECTIONS.get(section)
    if build is None:
        raise BadRequestException(
            "section must be one of: " + ", ".join([*_ASSISTANT_SECTIONS, "all"])
        )
    return build(reading)


async def _reading(container: Any, target_id: UUID) -> AssistantReading:
    (
        assistant,
        permissions,
        config,
    ) = await container.assistant_service().get_assistant_with_effective_config(
        target_id
    )
    rerank_name = None
    if assistant.rerank_model_id is not None:
        models = await container.rerank_model_crud_service().get_rerank_models()
        rerank_name = next(
            (
                _model_name(model)
                for model in models
                if model.id == assistant.rerank_model_id
            ),
            None,
        )
    template_name = None
    if assistant.document_template.template_id is not None:
        template_name = next(
            (
                item.name
                for item in await _document_templates(container)
                if item.id == assistant.document_template.template_id
            ),
            None,
        )
    return AssistantReading(
        assistant=assistant,
        permissions=permissions,
        effective_config=config,
        show_pricing=bool(getattr(container.user(), "can_view_model_pricing", False)),
        rerank_model_name=rerank_name,
        document_template_name=template_name,
    )


async def _document_templates(container: Any) -> list[Any]:
    from eneo.document_templates.router import list_available_document_templates

    return list((await list_available_document_templates(container=container)).items)


@mcp.tool(annotations=_READS)
async def read_assistant(
    ctx: Context, section: AssistantSection = "overview", offset: int = 0
) -> CallToolResult:
    """Read the assistant this chat is about, as saved, in plain text. The
    overview (default) is short: name, description, published, chat model,
    the length of the instructions, counts of knowledge and tools, what the
    person may do and what an organisation policy locks. Section
    "instructions" gives the instructions whole; "model" the chat model with
    what it can do and its settings; "knowledge" the knowledge mode, sources,
    result ranking, file handling and attachments; "tools" the MCP servers
    with their tools, the functions and the document template; "access"
    publishing, the person's rights, insights, logging and retention; "all"
    everything. A long section comes in parts: when the text says more
    follows, call again with the offset it gives."""

    async def operation(container, chat):
        lines = assistant_lines(await _reading(container, chat.target_id), section)
        return page_lines(
            lines,
            tool="read_assistant",
            section=section,
            offset=offset,
            assistant_id=chat.target_id,
        )

    return await _call(ctx, operation)


# --- read_options ------------------------------------------------------------


@dataclass(frozen=True)
class SpaceOffer:
    """What ``read_options`` reports on: the assistant's space as the editor
    reads it, the assistant's current choices and what a policy decides."""

    space: Any
    below_classification: Sequence[Any]
    default_model_id: UUID | None
    current_model_id: UUID | None
    effective_config: Any | None
    show_pricing: bool
    rerank_models: Sequence[Any]
    document_templates: Sequence[Any]


def _model_options(offer: SpaceOffer) -> list[str]:
    config = offer.effective_config
    models = [model for model in offer.space.completion_models if model.can_access]
    if config is not None and config.models_enforced:
        allowed = {model.id for model in config.available_models}
        models = [model for model in models if model.id in allowed]
    lines = [f"Chat models the space offers ({len(models)}):"]
    for model in models:
        marks = [
            mark
            for mark, applies in (
                ("the space's default", model.id == offer.default_model_id),
                ("in use now", model.id == offer.current_model_id),
            )
            if applies
        ]
        lines.append(
            f"- {_model_name(model)} [id {model.id}]"
            + (f" ({', '.join(marks)})" if marks else "")
        )
        lines.append(
            "  "
            + "; ".join(
                _model_facts(
                    model,
                    show_pricing=offer.show_pricing,
                    offered=model.supported_model_kwargs,
                )
            )
        )
    if offer.below_classification:
        lines.append(
            "Linked to the space but below its security classification, so "
            "they cannot be chosen: "
            + ", ".join(_model_name(model) for model in offer.below_classification)
        )
    return lines + [
        f"- {lock}"
        for lock in policy_locks(config)
        if lock.startswith(("chat model", "reasoning"))
    ]


def _knowledge_options(offer: SpaceOffer) -> list[str]:
    space = offer.space
    usable = {model.id for model in space.embedding_models}
    organisation = space.organization_space_id

    def item_line(item: Any, label: str) -> str:
        notes = []
        if (
            organisation is not None
            and item.space_id == organisation
            and (item.space_id != space.id)
        ):
            notes.append("organisation knowledge")
        if item.embedding_model.id not in usable:
            notes.append("its embedding model is not enabled in the space")
        return f"- {label} [id {item.id}]" + (f" ({'; '.join(notes)})" if notes else "")

    knowledge = space.knowledge
    lines = [f"Collections ({len(knowledge.groups.items)}):"]
    lines += [item_line(item, item.name) for item in knowledge.groups.items]
    lines.append(f"Websites ({len(knowledge.websites.items)}):")
    lines += [item_line(item, _website(item)) for item in knowledge.websites.items]
    lines.append(
        f"Integration sources ({len(knowledge.integration_knowledge_list.items)}):"
    )
    lines += [
        item_line(item, item.name)
        for item in knowledge.integration_knowledge_list.items
    ]
    rerankers = [
        model
        for model in offer.rerank_models
        if model.can_access and model.meets_security_classification is not False
    ]
    lines.append(f"Result ranking models ({len(rerankers)}):")
    lines += [f"- {_model_name(model)} [id {model.id}]" for model in rerankers]
    return lines


def _tool_options(offer: SpaceOffer) -> list[str]:
    space = offer.space
    config = offer.effective_config
    # A policy that decides the servers decides the functions too.
    source = config if config is not None and config.mcp_enforced else None
    governed = source is not None
    servers = source.available_mcp_servers if source else space.mcp_servers
    lines = [
        "MCP servers"
        + (" the organisation's policy gives" if governed else " the space offers")
        + f" ({len(servers)}):"
    ]
    for server in servers:
        server = _server_view(server)
        description = _short(server["description"])
        state = "" if server["is_enabled"] else " (turned off by an administrator)"
        lines.append(
            f"- {server['name']} [id {server['id']}]{state}"
            + (f": {description}" if description else "")
        )
        if server["tools"]:
            lines.append("  tools: " + ", ".join(server["tools"]))
    offered = source.enabled_capabilities if source else space.enabled_capabilities
    availability = (
        source.available_capabilities if source else space.available_capabilities
    )
    lines.append(f"Functions the space offers ({len(offered)}):")
    lines += [_function_line(purpose, availability) for purpose in offered]
    lines.append(
        "Document templates: the organisation's default, Eneo's built-in look"
        + ("" if offer.document_templates else ", and no others")
    )
    lines += [
        f"- {item.name} [id {item.id}]"
        + (" (the organisation's default)" if item.is_default else "")
        for item in offer.document_templates
    ]
    return lines


def _server_view(server: Any) -> dict[str, Any]:
    """The parts of a server, a domain entity or the space's view of one,
    that say what it is: never its address or sign-in configuration."""
    if isinstance(server, dict):
        tools = server.get("tools") or []
        return {
            "id": server["id"],
            "name": server["name"],
            "description": server.get("description"),
            "is_enabled": server.get("is_enabled", True),
            "tools": sorted(tool.get("display_name") or tool["name"] for tool in tools),
        }
    return {
        "id": server.id,
        "name": server.name,
        "description": server.description,
        "is_enabled": server.is_enabled,
        "tools": sorted(
            tool.display_name or tool.name for tool in _loaded_tools(server)
        ),
    }


_OPTION_SECTIONS: dict[str, Callable[[SpaceOffer], list[str]]] = {
    "model": _model_options,
    "knowledge": _knowledge_options,
    "tools": _tool_options,
}


def option_lines(offer: SpaceOffer, section: str) -> list[str]:
    """The lines ``read_options`` pages through for ``section``."""
    if section == "all":
        lines: list[str] = []
        for name, build in _OPTION_SECTIONS.items():
            lines += [f"== {name} =="] + build(offer)
        return lines
    build = _OPTION_SECTIONS.get(section)
    if build is None:
        raise BadRequestException(
            "section must be one of: " + ", ".join([*_OPTION_SECTIONS, "all"])
        )
    return build(offer)


async def _offer(container: Any, chat: Any) -> SpaceOffer:
    from eneo.ai_models.ai_models_router import get_models

    (
        assistant,
        _,
        config,
    ) = await container.assistant_service().get_assistant_with_effective_config(
        chat.target_id
    )
    space = await container.space_service().get_space(chat.space_id)
    usable = [model for model in space.completion_models if model.can_access]
    default = space.select_default_completion_model(usable)
    models = await get_models(container=container, space_id=chat.space_id)
    return SpaceOffer(
        space=container.space_assembler().from_space_to_model(space),
        below_classification=[
            model
            for model in space.completion_models_below_classification
            if model.can_access
        ],
        default_model_id=default.id if default is not None else None,
        current_model_id=(
            assistant.completion_model.id
            if assistant.completion_model is not None
            else None
        ),
        effective_config=config,
        show_pricing=bool(getattr(container.user(), "can_view_model_pricing", False)),
        rerank_models=models.rerank_models,
        document_templates=await _document_templates(container),
    )


@mcp.tool(annotations=_READS)
async def read_options(
    ctx: Context, section: OptionsSection = "all", offset: int = 0
) -> CallToolResult:
    """Read what the assistant's space offers to choose from, in plain text,
    before suggesting a choice. Section "model" gives the chat models the
    assistant may use, with what each can do (context window, tool calling,
    reasoning and its efforts, images, price when shown), the space's default
    and the one in use, and those below the space's security classification;
    "knowledge" the collections, websites and integration sources of the space
    and the organisation, and the result ranking models; "tools" the MCP
    servers with their tools, the functions and the document templates; "all"
    (default) everything. When the text says more follows, call again with
    the offset it gives."""

    async def operation(container, chat):
        lines = option_lines(await _offer(container, chat), section)
        return page_lines(
            lines,
            tool="read_options",
            section=section,
            offset=offset,
            assistant_id=chat.target_id,
        )

    return await _call(ctx, operation)


# --- The server of one turn --------------------------------------------------

EDIT_MODE_TOOLS: frozenset[str] = frozenset()
"""The tools a turn gets only in edit mode. Every tool here reads, so a turn
in either mode gets the same ones."""


async def build_assistant_settings_mcp_server(
    *, token: str, tenant_id: UUID, editing: bool = True
):
    """The assistant settings server for one turn: every tool in edit mode,
    those that change nothing while the chat only asks."""
    return await build_ephemeral_server(
        mcp,
        name=ASSISTANT_SERVER_NAME,
        description="Read the assistant this chat is about and what its space offers.",
        token=token,
        tenant_id=tenant_id,
        exclude_tools=() if editing else EDIT_MODE_TOOLS,
    )

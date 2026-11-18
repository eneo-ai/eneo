# pyright: basic
"""Session-bound tools over the assistant a helper chat is about.

Each call finds its assistant through the helper chat its token was minted
for (the chat's session and hidden assistant), never through the model's
arguments, and acts as the person: their access to the assistant and its
space decides what a call can see and change. What a call returns to the
model is plain text built from an allow-list of settings, so a credential, an
API key or a server's sign-in configuration never reaches it.

Two tools read, one proposes a change without saving it, and one, offered
only in edit mode, changes the assistant through the same update a person's
own save makes (``apply_assistant_update``), audited with the person as
actor.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from dependency_injector import providers
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import ValidationError

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.internal_mcp.constants import ASSISTANT_SERVER_NAME
from eneo.internal_mcp.foundation import (
    build_ephemeral_server,
    default_page_cap,
    fit_lines,
    internal_tool_context,
)
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    STRUCTURED_CONTENT_MAX_BYTES,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Eneo Assistant Settings",
    stateless_http=True,
    instructions=(
        "Read the assistant this chat is about and what its space offers, "
        "propose changes, and in edit mode make them."
    ),
)

# Reading tools change nothing, and neither does a proposal. A change is not
# destructive: the person sees it with its before and after and can undo it.
_READS = ToolAnnotations(readOnlyHint=True)
_CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

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
    ctx: Context,
    operation: Callable[[Any, Any], Awaitable[CallToolResult]],
    *,
    editing: bool = False,
) -> CallToolResult:
    """Run ``operation`` on the chat the token was minted for, as the person,
    in one transaction. ``editing`` makes the call a change: the assistant and
    the chat are locked, the chat must be in edit mode and the person must
    still be allowed to edit the assistant, and the audit entries the change
    logs are saved in its transaction (``_audit_in_transaction``). A refusal
    rolls the transaction back and comes back as text the model reads."""
    from eneo.assistants.application.assistant_helper_chat import ASSISTANT_TARGET
    from eneo.helper_chats.application import helper_chat_service

    try:
        async with internal_tool_context(ctx) as scope:
            if scope.session_id is None:
                raise NotFoundException("Helper chat not found.")
            if not editing:
                chat = await helper_chat_service.load_chat(
                    scope.container,
                    ASSISTANT_TARGET,
                    session_id=scope.session_id,
                    assistant_id=scope.assistant_id,
                )
                return await operation(scope.container, chat)
            chat = await helper_chat_service.load_chat(
                scope.container,
                ASSISTANT_TARGET,
                session_id=scope.session_id,
                assistant_id=scope.assistant_id,
                lock=True,
            )
            await helper_chat_service.require_edit_mode(
                scope.container, ASSISTANT_TARGET, chat, change=True
            )
            async with _audit_in_transaction(scope.container):
                return await operation(scope.container, chat)
    except (
        BadRequestException,
        ConflictException,
        NotFoundException,
        UnauthorizedException,
        ValidationError,
    ) as exc:
        return _error_result(exc)
    except Exception:
        # The transaction rolled back. The exception's own text can name rows
        # and ids, so it goes to the log and the model gets a plain refusal.
        logger.exception("An assistant settings tool call failed")
        return _refusal(
            "The call failed and nothing was changed. Try once more; if it "
            "fails again, the person makes the change in the editor."
        )


def _refusal(text: str) -> CallToolResult:
    return CallToolResult(isError=True, content=[TextContent(type="text", text=text)])


def _error_result(
    exc: BadRequestException
    | ConflictException
    | NotFoundException
    | UnauthorizedException
    | ValidationError,
) -> CallToolResult:
    """The refusal of a call that raised ``exc``: its message, never its
    context, and for a request the model got wrong the fields to fix,
    without the values it sent."""
    if isinstance(exc, ValidationError):
        return _refusal(
            invalid_changes_message(
                exc.errors(
                    include_input=False, include_context=False, include_url=False
                )
            )
        )
    return _refusal(str(exc) or type(exc).__name__)


def invalid_changes_message(errors: Iterable[Any]) -> str:
    """What is wrong with changes the assistant's update request rejects,
    field by field."""
    problems = "; ".join(
        f"{'.'.join(str(part) for part in error.get('loc', ())) or 'changes'}: "
        f"{error.get('msg', 'invalid')}"
        for error in errors
    )
    return f"The changes are not valid, and nothing was changed: {problems}."


class _HeldAudit:
    """The audit service of a change made through the chat. The entries the
    change queues are held, and ``write`` saves them in the change's
    transaction; everything else is the audit service's own."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._entries: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)

    async def log_async(self, **entry: Any) -> None:
        self._entries.append(entry)

    async def write(self) -> None:
        entries, self._entries = self._entries, []
        for entry in entries:
            await self._service.log(**entry)


@asynccontextmanager
async def _audit_in_transaction(container: Any) -> AsyncIterator[None]:
    """Save the audit entries of the change made in this block in the block's
    own transaction.

    ``AuditService.log_async`` queues an entry for a worker as soon as it is
    called, before the caller's transaction commits, so a change that is
    rolled back after it (a refusal, a failed commit) would leave an entry
    for a change that was never saved. Here the entries are held while the
    change runs and written with ``AuditService.log``, the same entry, in the
    same transaction: the change and its entries are saved together or not
    at all. A block that raises writes none."""
    held = _HeldAudit(container.audit_service())
    with container.audit_service.override(providers.Object(held)):
        yield
    await held.write()


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


# --- Changes -----------------------------------------------------------------

# How the audit entry of a change made through the chat names its origin.
HELPER_CHAT_ORIGIN = "helper_chat"

# What the chat may change, as the assistant's update request names it, with
# what the editor calls it.
_CHANGEABLE: dict[str, str] = {
    "name": "name",
    "description": "description",
    "prompt": "instructions",
    "completion_model": "chat model",
    "completion_model_kwargs": "model settings",
    "knowledge_mode": "knowledge mode",
    "inline_file_text": "handling of files uploaded in a chat",
}
_PROMPT_KEYS = frozenset({"text", "description"})
_MODEL_KEYS = frozenset({"id"})
_SETTING_KEYS = frozenset(key for key, _ in _SETTINGS)

# What a person calls the rest of an assistant's update request, to say what
# the chat cannot change.
_UNCHANGEABLE: dict[str, str] = {
    "id": "the assistant's identity",
    "space_id": "the space",
    "groups": "knowledge (collections)",
    "websites": "knowledge (websites)",
    "integration_knowledge_list": "knowledge (integration sources)",
    "rerank_model_id": "result ranking",
    "attachments": "attachments",
    "mcp_servers": "MCP servers",
    "mcp_tools": "MCP tools",
    "enabled_capabilities": "functions",
    "document_template": "the document template",
    "skill_bindings": "skills",
    "published": "publishing",
    "insight_enabled": "insights",
    "logging_enabled": "conversation logging",
    "data_retention_days": "conversation retention",
    "icon_id": "the icon",
    "metadata_json": "metadata",
    "hidden": "visibility",
    "guardrail": "the guardrail",
    "response_format": "the response format",
}

# The description a new version of the instructions gets in their version
# history: the model's, in the person's language, cut to this length, or the
# neutral line when it gives none.
_VERSION_DESCRIPTION_CHARS = 200
_CHANGED_WITH_HELPER = "Changed with the helper assistant."
_RESTORED_WITH_UNDO = (
    "Restored the instructions from before a change made with the helper assistant."
)

_CHANGES_TAKE = (
    "changes holds only these fields of the assistant; a field left out keeps "
    "its value. name: the new name. description: the new description, or null "
    'to clear it. prompt: {"text": the whole new instructions, "description": '
    "one short line in the person's language, at most 200 characters, saying "
    "what changed and that it was made with the helper; it shows in the "
    'instructions\' version history}. completion_model: {"id": a chat model '
    "read_options lists}. completion_model_kwargs: any of temperature, top_p, "
    "reasoning_effort, verbosity, presence_penalty, frequency_penalty and "
    "top_k; a setting you send replaces it, null returns it to the model's "
    "default, settings you leave out are kept, and null in place of the whole "
    'object returns them all to the defaults. knowledge_mode: "tool" (the '
    'assistant searches its knowledge when it needs to) or "inject" '
    "(relevant parts go in the prompt on every question). inline_file_text: "
    "true (files uploaded in a chat go whole into the prompt) or false "
    "(looked up when needed). Every other setting is changed in the editor."
)


def _person_name(key: str) -> str:
    return _UNCHANGEABLE.get(key) or key.replace("_", " ")


def _listing(names: Sequence[str]) -> str:
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def require_changeable(changes: dict[str, Any]) -> None:
    """Refuse changes that name anything the chat may not change, naming it
    as a person would and saying what the chat does change."""
    refused: list[str] = []
    for key, value in changes.items():
        if key not in _CHANGEABLE:
            refused.append(_person_name(key))
            continue
        allowed = {
            "prompt": _PROMPT_KEYS,
            "completion_model": _MODEL_KEYS,
            "completion_model_kwargs": _SETTING_KEYS,
        }.get(key)
        if allowed is not None and isinstance(value, dict):
            refused += [_person_name(inner) for inner in value if inner not in allowed]
    if not refused:
        return
    names = list(dict.fromkeys(refused))
    listed = _listing(names)
    raise BadRequestException(
        f"{listed[:1].upper()}{listed[1:]} cannot be changed through the chat; the "
        f"person changes {'it' if len(names) == 1 else 'them'} in the editor. "
        "Nothing was changed. The chat changes only the name, the description, "
        "the instructions, the chat model and its settings ("
        + ", ".join(label for _, label in _SETTINGS)
        + "), the knowledge mode and the handling of files uploaded in a chat."
    )


def changes_request(changes: dict[str, Any]) -> Any:
    """The assistant's update request ``changes`` make, refused when they
    name anything the chat may not change or do not have its shape."""
    from eneo.assistants.api.assistant_models import AssistantUpdatePublic

    require_changeable(changes)
    return AssistantUpdatePublic.model_validate(changes)


def version_description(text: str | None) -> str:
    """The description a new version of the instructions gets: the one
    given, on one line and cut to length, or the neutral line."""
    flat = " ".join((text or "").split())
    if not flat:
        return _CHANGED_WITH_HELPER
    if len(flat) <= _VERSION_DESCRIPTION_CHARS:
        return flat
    return flat[: _VERSION_DESCRIPTION_CHARS - 3].rstrip() + "..."


def _model_value(model: Any) -> dict[str, str]:
    return {"id": str(model.id), "name": _model_name(model)}


def assistant_settings_of(assistant: Any) -> dict[str, Any]:
    """The settings the chat may change, as the assistant has them: the
    values a change's before and after are taken from."""
    model = assistant.completion_model
    kwargs = assistant.completion_model_kwargs or ModelKwargs()
    return {
        "name": assistant.name,
        "description": assistant.description,
        "prompt": assistant.get_prompt_text(),
        "completion_model": _model_value(model) if model is not None else None,
        **{
            f"completion_model_kwargs.{key}": getattr(kwargs, key)
            for key, _ in _SETTINGS
        },
        "knowledge_mode": getattr(
            assistant.knowledge_mode, "value", assistant.knowledge_mode
        ),
        "inline_file_text": assistant.inline_file_text,
    }


def setting_changes(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    """Each setting whose value differs, with its value before and after."""
    return [
        {"field": field, "before": value, "after": after[field]}
        for field, value in before.items()
        if after[field] != value
    ]


def undo_update(
    changes: Sequence[dict[str, Any]], kwargs_before: ModelKwargs
) -> dict[str, Any]:
    """The update request that gives the changed settings their values from
    before. A chat model cannot be taken away by an update, so an assistant
    that had none keeps the one it was given."""
    undo: dict[str, Any] = {}
    for change in changes:
        field, before = change["field"], change["before"]
        if field == "prompt":
            undo["prompt"] = {"text": before, "description": _RESTORED_WITH_UNDO}
        elif field == "completion_model":
            if before is not None:
                undo["completion_model"] = {"id": before["id"]}
        elif field.startswith("completion_model_kwargs."):
            undo["completion_model_kwargs"] = kwargs_before.model_dump(
                mode="json", exclude_none=True
            )
        else:
            undo[field] = before
    return undo


@dataclass(frozen=True)
class PlannedChange:
    """A change as the chat would make it: the settings now (``settings``,
    with the model settings whole in ``kwargs``), the update request that
    makes it (``update``, only what differs from now) and each setting it
    changes with its value now and after (``changes``)."""

    settings: dict[str, Any]
    kwargs: ModelKwargs
    update: dict[str, Any]
    changes: list[dict[str, Any]]
    published: bool


def _policy_refusal(what: str) -> BadRequestException:
    return BadRequestException(
        f"An organisation policy sets {what} for this assistant, so it cannot be "
        "changed through the chat. Nothing was changed."
    )


def _merged_kwargs(stored: ModelKwargs, sent: ModelKwargs | None) -> ModelKwargs:
    """The model settings after a change: each setting sent replaces the
    stored one (null is the model's default), the rest are kept; ``None``
    returns every setting to the model's default."""
    if sent is None:
        return stored.model_copy(update=dict.fromkeys(_SETTING_KEYS))
    return stored.model_copy(
        update={
            key: getattr(sent, key)
            for key in sent.model_fields_set
            if key in _SETTING_KEYS
        }
    )


def _require_offered(model: Any, merged: ModelKwargs, stored: ModelKwargs | None):
    """Refuse model settings ``model`` does not offer, as the update refuses
    them (``validate_model_kwargs_update``), naming the settings."""
    from eneo.completion_models.infrastructure.tenant_model_capabilities import (
        validate_model_kwargs_update,
    )

    supported = model.get_supported_model_kwargs()
    try:
        validate_model_kwargs_update(merged, supported, stored=stored)
    except BadRequestException:
        refused = [
            label
            for key, label in _SETTINGS
            if getattr(merged, key) is not None
            and (stored is None or getattr(merged, key) != getattr(stored, key))
            and not getattr(supported, key).accepts(getattr(merged, key))
        ]
        raise BadRequestException(
            f"{_model_name(model)} does not offer "
            + (_listing(refused) or "these model settings")
            + " with the values given: leave them out, or choose values the "
            "model offers. Nothing was changed."
        ) from None


def _chosen_model(space: Any, config: Any | None, model_id: UUID) -> Any:
    """The space's model ``model_id`` when the assistant may be given it."""
    if not space.is_completion_model_available(model_id):
        if any(
            model.id == model_id
            for model in space.completion_models_below_classification
        ):
            raise BadRequestException(
                "That model is below the space's security classification, so it "
                "cannot be chosen. Nothing was changed."
            )
        raise BadRequestException(
            "The space does not offer that model; read_options lists the models "
            "it offers. Nothing was changed."
        )
    if config is not None and config.models_enforced:
        if model_id not in {model.id for model in config.available_models}:
            raise _policy_refusal("the chat models")
    return space.get_completion_model(model_id)


def plan_change(
    assistant: Any,
    changes: dict[str, Any],
    *,
    space: Any,
    effective_config: Any | None,
) -> PlannedChange:
    """The change ``changes`` makes to ``assistant``, checked as far as it
    can be without saving it: only settings the chat may change, the shape
    the assistant's update request takes, what an organisation policy
    decides, whether the space offers a chosen model and whether the model
    offers the model settings. A setting given the value it already has is
    left out, so it is not saved again.

    A field left out keeps its value, and so does null, except where the
    update request clears it: null clears the description, and null model
    settings return every setting to the model's default. Within the model
    settings, a setting left out keeps its value."""
    request = changes_request(changes)
    config = effective_config
    sent = request.model_fields_set
    before = assistant_settings_of(assistant)
    after = dict(before)
    update: dict[str, Any] = {}

    if request.name is not None and request.name != before["name"]:
        update["name"] = after["name"] = request.name
    if "description" in sent and request.description != before["description"]:
        update["description"] = after["description"] = request.description
    if request.prompt is not None and request.prompt.text != before["prompt"]:
        if config is not None and config.prompt_enforced:
            raise _policy_refusal("the instructions")
        update["prompt"] = {
            "text": request.prompt.text,
            "description": version_description(request.prompt.description),
        }
        after["prompt"] = request.prompt.text

    model = assistant.completion_model
    if request.completion_model is not None and (
        model is None or request.completion_model.id != model.id
    ):
        model = _chosen_model(space, config, request.completion_model.id)
        update["completion_model"] = {"id": str(model.id)}
        after["completion_model"] = _model_value(model)

    stored = (assistant.completion_model_kwargs or ModelKwargs()).model_copy()
    if "completion_model_kwargs" in sent:
        # The request model reads a null as the default settings; the null
        # itself says every setting goes back to the model's default.
        merged = _merged_kwargs(
            stored,
            None
            if changes["completion_model_kwargs"] is None
            else request.completion_model_kwargs,
        )
        changed = [
            key for key, _ in _SETTINGS if getattr(merged, key) != getattr(stored, key)
        ]
        if changed:
            if (
                "reasoning_effort" in changed
                and config is not None
                and config.reasoning_policy_configured
                and not config.reasoning_effort_user_configurable
            ):
                raise _policy_refusal("the reasoning effort")
            if model is None:
                raise BadRequestException(
                    "Choose a chat model before its settings. Nothing was changed."
                )
            same_model = (
                assistant.completion_model is not None
                and model.id == assistant.completion_model.id
            )
            _require_offered(model, merged, stored if same_model else None)
            update["completion_model_kwargs"] = merged.model_dump(
                mode="json", exclude_none=True
            )
            for key in changed:
                after[f"completion_model_kwargs.{key}"] = getattr(merged, key)

    if request.knowledge_mode is not None:
        mode = request.knowledge_mode.value
        if mode != before["knowledge_mode"]:
            update["knowledge_mode"] = after["knowledge_mode"] = mode
    if (
        request.inline_file_text is not None
        and request.inline_file_text != before["inline_file_text"]
    ):
        if config is not None and config.inline_file_text is not None:
            raise _policy_refusal("the handling of files uploaded in a chat")
        update["inline_file_text"] = after["inline_file_text"] = (
            request.inline_file_text
        )

    return PlannedChange(
        settings=before,
        kwargs=stored,
        update=update,
        changes=setting_changes(before, after),
        published=bool(assistant.published),
    )


async def _planned_change(
    container: Any, chat: Any, changes: dict[str, Any]
) -> PlannedChange:
    """The change ``changes`` makes to the chat's assistant as it is now.
    Changes the chat may not make, or of the wrong shape, are refused before
    anything is read."""
    changes_request(changes)
    (
        assistant,
        _,
        config,
    ) = await container.assistant_service().get_assistant_with_effective_config(
        chat.target_id
    )
    space = await container.space_service().get_space(chat.space_id)
    return plan_change(assistant, changes, space=space, effective_config=config)


_MODES = {
    "tool": "searched when needed",
    "inject": "put in the prompt on every question",
}
_FILES = {True: "put whole in the prompt", False: "looked up when needed"}


def _change_line(change: dict[str, Any], *, saved: bool) -> str:
    """One change for the model: the setting as the editor calls it, with
    its values when they are short. Never an id, and never the text of the
    instructions or the description."""
    field, before, after = change["field"], change["before"], change["after"]
    if field == "prompt":
        return (
            "instructions (a new version)"
            if saved
            else f"instructions (new text of {len(after or ''):,} characters)"
        )
    if field == "description":
        return "description (cleared)" if not after else "description"
    if field == "name":
        return f'name (from "{_short(before, 80)}" to "{_short(after, 80)}")'
    if field == "completion_model":
        old = before["name"] if before else "none"
        return f"chat model (from {old} to {after['name']})"
    if field == "knowledge_mode":
        return (
            f"knowledge mode (from {_MODES.get(before, before)} to "
            f"{_MODES.get(after, after)})"
        )
    if field == "inline_file_text":
        return (
            f"files uploaded in a chat (from {_FILES[bool(before)]} to "
            f"{_FILES[bool(after)]})"
        )
    label = dict(_SETTINGS).get(field.removeprefix("completion_model_kwargs."), field)

    def shown(value: Any) -> str:
        return "the model's default" if value is None else str(value)

    return f"{label} (from {shown(before)} to {shown(after)})"


def change_text(
    changes: Sequence[dict[str, Any]], *, saved: bool, published: bool
) -> str:
    """What the model is told about a change it made or proposed."""
    lines = "; ".join(_change_line(change, saved=saved) for change in changes)
    if saved:
        text = f"Saved: {lines}. The person sees before and after and can undo it."
        if published:
            text += (
                " The assistant is published, so the change already applies for "
                "everyone who uses it."
            )
        return text
    text = (
        f"Proposed, nothing saved: {lines}. The person applies it with the "
        "button on the proposal."
    )
    if any(change["field"] == "prompt" for change in changes):
        text += " The proposal shows the new instructions: do not paste them."
    if published:
        text += (
            " The assistant is published, so the change reaches everyone who uses "
            "it as soon as it is applied."
        )
    return text


def _within_cap(content: dict[str, Any]) -> dict[str, Any]:
    """``content`` within what the chat keeps of a call's structured content
    (it drops more whole). When it would not fit, the texts of the
    instructions and the description are left out of the before and after
    (marked ``too_long``) and the request bodies stay whole, so the person
    can still apply or undo the change."""

    def size() -> int:
        return len(json.dumps(content, ensure_ascii=False, default=str).encode())

    if size() <= STRUCTURED_CONTENT_MAX_BYTES:
        return content
    proposal = content.get("proposal") or {}
    for change in content.get("changes") or proposal.get("changes") or []:
        if change["field"] in ("prompt", "description"):
            change.update(before=None, after=None, too_long=True)
    return content


def _unchanged(target_id: UUID, *, proposal: bool) -> CallToolResult:
    """The result of changes that give every setting the value it has: no
    proposal, or no change and nothing to undo."""
    already = "the assistant already has these settings."
    if proposal:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Nothing to propose: {already}")],
            structuredContent={"target_id": str(target_id)},
        )
    return CallToolResult(
        content=[TextContent(type="text", text=f"Nothing changed: {already}")],
        structuredContent={"target_id": str(target_id), "changes": [], "undo": None},
    )


@mcp.tool(
    annotations=_READS,
    description=(
        "Propose a change to the assistant this chat is about, without saving "
        "anything: the person applies it with the button on the proposal, as "
        "their own save. " + _CHANGES_TAKE + " The proposal is checked as far "
        "as it can be without saving (what a policy decides, whether the space "
        "offers a model and the model its settings); applying it can still be "
        "refused, for example when the instructions and files no longer fit "
        "the model. A refusal says why and proposes nothing."
    ),
)
async def propose_changes(ctx: Context, changes: dict[str, Any]) -> CallToolResult:
    """Propose ``changes`` without saving anything. The structured content
    carries the proposal: each setting's value now and after, and the
    update request that applies it."""

    async def operation(container, chat):
        from eneo.assistants.application.assistant_helper_chat import (
            ASSISTANT_TARGET,
        )

        await ASSISTANT_TARGET.require_edit(
            container, ASSISTANT_TARGET.scoped_request(chat.space_id), chat.target_id
        )
        planned = await _planned_change(container, chat, changes)
        if not planned.update:
            return _unchanged(chat.target_id, proposal=True)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=change_text(
                        planned.changes, saved=False, published=planned.published
                    ),
                )
            ],
            structuredContent=_within_cap(
                {
                    "target_id": str(chat.target_id),
                    "proposal": {
                        "changes": planned.changes,
                        "update": planned.update,
                    },
                }
            ),
        )

    return await _call(ctx, operation)


@mcp.tool(
    annotations=_CHANGES,
    description=(
        'Change the assistant this chat is about; only in "Redigera". '
        + _CHANGES_TAKE
        + " Everything is saved or nothing; a refusal says why and saves "
        "nothing. The result says what changed; the person sees before and "
        "after and can undo it."
    ),
)
async def update_assistant(ctx: Context, changes: dict[str, Any]) -> CallToolResult:
    """Change the chat's assistant through ``apply_assistant_update``, as the
    person, audited with the person as actor. The structured content carries
    each changed setting before and after, read from the assistant, and the
    update request that undoes the change."""

    async def operation(container, chat):
        from eneo.assistants.api.assistant_models import AssistantUpdatePublic
        from eneo.assistants.application.assistant_update_operation import (
            apply_assistant_update,
        )

        planned = await _planned_change(container, chat, changes)
        if not planned.update:
            return _unchanged(chat.target_id, proposal=False)
        await apply_assistant_update(
            container,
            assistant_id=chat.target_id,
            update=AssistantUpdatePublic.model_validate(planned.update),
            audit_context={
                "origin": HELPER_CHAT_ORIGIN,
                "session_id": str(chat.session_id),
            },
        )
        after, _ = await container.assistant_service().get_assistant(chat.target_id)
        changed = setting_changes(planned.settings, assistant_settings_of(after))
        if not changed:
            return _unchanged(chat.target_id, proposal=False)
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=change_text(
                        changed, saved=True, published=bool(after.published)
                    ),
                )
            ],
            structuredContent=_within_cap(
                {
                    "target_id": str(chat.target_id),
                    "changes": changed,
                    "undo": undo_update(changed, planned.kwargs),
                }
            ),
        )

    return await _call(ctx, operation, editing=True)


# --- The server of one turn --------------------------------------------------

EDIT_MODE_TOOLS: frozenset[str] = frozenset({"update_assistant"})
"""The tools ``_call`` refuses outside edit mode. A turn in view mode does not
offer them, so the model never calls what would be refused; it proposes a
change instead."""


async def build_assistant_settings_mcp_server(
    *, token: str, tenant_id: UUID, editing: bool = True
):
    """The assistant settings server for one turn: every tool in edit mode,
    those that change nothing while the chat only asks."""
    return await build_ephemeral_server(
        mcp,
        name=ASSISTANT_SERVER_NAME,
        description=(
            "Read the assistant this chat is about and what its space offers, "
            "propose changes, and in edit mode make them."
        ),
        token=token,
        tenant_id=tenant_id,
        exclude_tools=() if editing else EDIT_MODE_TOOLS,
    )

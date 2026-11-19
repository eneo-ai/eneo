# pyright: basic
"""Session-bound tools over the assistant a helper chat is about.

Each call finds its assistant through the helper chat its token was minted
for (the chat's session and hidden assistant), never through the model's
arguments, and acts as the person: their access to the assistant and its
space decides what a call can see and change. What a call returns to the
model is plain text built from an allow-list of settings, so a credential, an
API key or a server's sign-in configuration never reaches it.

Three tools read (the assistant, what its space offers and the saved
versions of its instructions) and one proposes a change without saving it:
the person applies a proposal as their own save. One more publishes or
unpublishes the assistant through the same publishing a person's own does
(``apply_assistant_publish``), audited with the person as actor, once the
person has approved the call in the chat. A last one, ``update_assistant``,
changes the assistant through the same update a person's own save makes
(``apply_assistant_update``); only a chat in edit mode may call it, and the
chat on an assistant has none, so no turn offers it. A setting the person's
role does not let them change in the editor is refused by the tools that
propose and change it, and named as such when the assistant is read. So is
what the editor's own rules hold back while the assistant is set up as it
is: knowledge beside MCP servers, and tools and functions for a chat model
that cannot use tools.
"""

from __future__ import annotations

import json
import logging
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from dependency_injector import providers
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.governance_policy.domain.policy_resolver import (
    select_effective_completion_model,
)
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
from eneo.main.models import MCPToolSetting, ModelId
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose
from eneo.mcp_servers.domain.entities.mcp_server import is_capability_purpose
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    STRUCTURED_CONTENT_MAX_BYTES,
)

logger = logging.getLogger(__name__)

_SERVER_DESCRIPTION = (
    "Read the assistant this chat is about, what its space offers and the "
    "saved versions of its instructions, propose changes for the person to "
    "apply, and publish or unpublish the assistant once the person approves."
)

mcp = FastMCP(
    name="Eneo Assistant Settings",
    stateless_http=True,
    instructions=_SERVER_DESCRIPTION,
)

# Reading tools change nothing, and neither does a proposal. A change is not
# destructive: the person sees it with its before and after and can undo it.
# Publishing acts beyond the editor (who can use the assistant changes) and
# has no undo on its card, so it declares destructiveHint and the chat asks
# the person before each call.
_READS = ToolAnnotations(readOnlyHint=True)
_CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_ACTS = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

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
    approved: bool = False,
) -> CallToolResult:
    """Run ``operation`` on the chat the token was minted for, as the person,
    in one transaction. ``editing`` makes the call a change the chat makes by
    itself, and ``approved`` one the person approves in the chat before it
    runs. Either way the assistant and the chat are locked, the person must
    still be allowed to edit the assistant, and the audit entries the change
    logs are saved in its transaction (``_audit_in_transaction``); a change
    by the chat itself also needs edit mode, which the chat on an assistant
    never is (``helper_chat_service.require_approved_change``). A refusal
    rolls the transaction back and comes back as text the model reads."""
    from eneo.assistants.application.assistant_helper_chat import ASSISTANT_TARGET
    from eneo.helper_chats.application import helper_chat_service

    try:
        async with internal_tool_context(ctx) as scope:
            if scope.session_id is None:
                raise NotFoundException("Helper chat not found.")
            if not (editing or approved):
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
            if editing:
                await helper_chat_service.require_edit_mode(
                    scope.container, ASSISTANT_TARGET, chat, change=True
                )
            else:
                await helper_chat_service.require_approved_change(
                    scope.container, ASSISTANT_TARGET, chat
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
    title: str | None = None,
    again: str | None = None,
) -> CallToolResult:
    """One page of ``lines`` from line ``offset``, sized to the tool output
    cap, saying how to read on when more is left. ``title`` heads the page in
    place of the tool's own heading for ``section``, and ``again`` names the
    arguments, other than the offset, that read on (``section=...`` when
    left out)."""
    if offset < 0:
        raise BadRequestException("offset must be zero or more.")
    total = len(lines)
    if offset and offset >= total:
        raise BadRequestException(
            f"offset is past the end ({total} lines); read again from offset 0."
        )
    header = f"{title or _title(tool, section)} (lines {offset + 1}-"
    kept = fit_lines(lines[offset:], default_page_cap() - len(header) - 400)
    shown_to = offset + len(kept)
    text = f"{header}{shown_to} of {total}):\n" + "\n".join(kept)
    next_offset = shown_to if shown_to < total else None
    if next_offset is not None:
        arguments = f"section={section}" if again is None else again
        text += (
            f"\n\nMore follows. Call {tool} again with "
            f"{arguments + ' and ' if arguments else ''}offset={next_offset} "
            "before you say you have read it all."
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


def _website_name(website: Any) -> str:
    """A website as the editor names it: its name, else its address without
    a sign-in part or query."""
    return website.name or _url(website.url)


def _tool_name(tool: Any) -> str:
    return tool.display_name or tool.name


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
class PersonRights:
    """Whether the person's role in the assistant's space lets them change
    conversation retention, the insights switch and publishing, which the
    update and publishing check (``can_edit_retention``,
    ``can_toggle_insight``, ``can_publish_assistants``), and whether the
    space is a personal one, where nobody publishes an assistant or turns
    its insights on."""

    edit_retention: bool
    toggle_insight: bool
    publish: bool
    personal_space: bool = False

    @classmethod
    def of(cls, actor: Any) -> PersonRights:
        """The rights of ``actor``, the person's actor in the space."""
        return cls(
            edit_retention=bool(actor.can_edit_retention()),
            toggle_insight=bool(actor.can_toggle_insight()),
            publish=bool(actor.can_publish_assistants()),
            personal_space=bool(actor.space.is_personal()),
        )


# None of the rights: what a change is checked against when nothing says
# otherwise, so a check that was not prepared refuses.
NO_RIGHTS = PersonRights(edit_retention=False, toggle_insight=False, publish=False)

# Who may change what the person's role withholds, as a person would say it.
_WHO_CAN = "someone with more rights in the space, such as its administrators"
_PERSONAL_INSIGHTS = "Insights are not used for an assistant in a personal space."
_PERSONAL_PUBLISHING = "An assistant in a personal space is not published."


def withheld_settings(rights: PersonRights | None) -> list[str]:
    """The settings the person's role does not let them change, each with
    who can; none when the rights are not known."""
    if rights is None:
        return []
    others = f"{_WHO_CAN}, can"
    withheld: list[str] = []
    if not rights.edit_retention:
        withheld.append(f"conversation retention: {others}")
    if not rights.toggle_insight:
        withheld.append(
            "insights (turning them on or off): "
            + ("not used in a personal space" if rights.personal_space else others)
        )
    if not rights.publish:
        withheld.append(
            "publishing (publishing or unpublishing it): "
            + ("not used in a personal space" if rights.personal_space else others)
        )
    return withheld


def _withheld_lines(reading: AssistantReading) -> list[str]:
    withheld = withheld_settings(reading.rights)
    if not withheld:
        return []
    return ["Not the person's to change (their role does not allow it):"] + [
        f"- {setting}" for setting in withheld
    ]


async def _person_rights(container: Any, space_id: UUID) -> PersonRights:
    access = await container.space_service().get_space_access_facts(space_id)
    return PersonRights.of(container.actor_manager().get_space_actor(access))


@dataclass(frozen=True)
class AssistantReading:
    """What ``read_assistant`` reports on: the assistant as the person reads
    it, with the names its saved choices point at and, when known, what the
    person's role lets them change."""

    assistant: Any
    permissions: Sequence[Any]
    effective_config: Any | None
    show_pricing: bool
    rerank_model_name: str | None = None
    document_template_name: str | None = None
    rights: PersonRights | None = None


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


def answering_model(model: Any | None, config: Any | None) -> Any | None:
    """The chat model an assistant whose own is ``model`` answers with: that
    one, or the one a models policy steers it to, resolved as a question to
    the assistant resolves it (``select_effective_completion_model``). None
    when there is none."""
    return select_effective_completion_model(
        current_model=model, effective_config=config
    )


def _cannot_use_tools(model: Any | None) -> bool:
    """Whether ``model`` is a chat model that cannot use tools: only one
    marked as calling tools gets MCP servers and functions. No model holds
    nothing back."""
    return model is not None and not model.supports_tool_calling


def _has_knowledge(assistant: Any) -> bool:
    """Whether the assistant has knowledge as the editor counts it: a
    collection, a website or an integration source. Attachments, the ranking
    model and the knowledge mode do not count."""
    return bool(
        assistant.collections
        or assistant.websites
        or assistant.integration_knowledge_list
    )


def held_by_the_editor(assistant: Any, config: Any | None) -> list[tuple[str, str]]:
    """What the editor's own rules hold back while the assistant is set up as
    it is now, each with the section it belongs to: knowledge while the
    assistant has MCP servers and no knowledge, MCP servers while it has
    knowledge and no MCP server (one that has both stays changeable on both
    sides), and MCP servers, their tools and functions while the chat model
    it answers with cannot use tools. Where a policy sets the MCP servers
    and functions, the policy's lock says so instead."""
    held: list[tuple[str, str]] = []
    knowledge = _has_knowledge(assistant)
    servers = bool(assistant.mcp_servers)
    governed = config is not None and config.mcp_enforced
    if servers and not knowledge:
        held.append(
            (
                "knowledge",
                "knowledge: none can be added while the assistant has MCP "
                "servers (the two are not combined); removing the MCP servers "
                "comes first",
            )
        )
    if knowledge and not servers and not governed:
        held.append(
            (
                "tools",
                "MCP servers: none can be added while the assistant has "
                "knowledge (the two are not combined); removing its knowledge "
                "comes first",
            )
        )
    model = None if governed else answering_model(assistant.completion_model, config)
    if _cannot_use_tools(model):
        held.append(
            (
                "tools",
                "MCP servers, their tools and functions: the chat model "
                f"{_model_name(model)} cannot use tools, so no MCP server or "
                "function can be turned on and no single tool switched on or "
                "off; choosing a model that can use tools comes first",
            )
        )
    return held


def _held_lines(reading: AssistantReading, section: str | None = None) -> list[str]:
    """The lines saying what the editor's rules hold back now: all of them
    under a heading, or those of ``section`` as items of it."""
    held = held_by_the_editor(reading.assistant, reading.effective_config)
    if section is not None:
        return [f"- {line}" for where, line in held if where == section]
    if not held:
        return []
    return ["Held back by the editor's rules as the assistant is set up now:"] + [
        f"- {line}" for _, line in held
    ]


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
    return (
        lines
        + _rights(reading)
        + _withheld_lines(reading)
        + _locks_lines(reading)
        + _held_lines(reading)
    )


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
    return lines + _held_lines(reading, "knowledge")


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
    return (
        lines
        + [
            f"- {lock}"
            for lock in policy_locks(reading.effective_config)
            if lock.startswith("MCP")
        ]
        + _held_lines(reading, "tools")
    )


def _access(reading: AssistantReading) -> list[str]:
    assistant = reading.assistant
    retention = assistant.data_retention_days
    return [
        f"Published: {_yes(assistant.published)}",
        *_rights(reading),
        *_withheld_lines(reading),
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
        rights=await _person_rights(container, assistant.space_id),
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
    person may do, what their role does not let them change and what an
    organisation policy locks (suggest neither), and what the editor's rules
    hold back as the assistant is set up now (knowledge and MCP servers are
    not combined, and tools need a chat model that can use them; explain
    those instead of proposing around them). Section
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
    knowledge = space.knowledge
    sources = [
        *knowledge.groups.items,
        *knowledge.websites.items,
        *knowledge.integration_knowledge_list.items,
    ]
    # One assistant's knowledge shares one embedding model, so where the
    # sources use several, each says which it uses.
    several = len({item.embedding_model.id for item in sources}) > 1

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
        if several:
            notes.append(f"embedding model [id {item.embedding_model.id}]")
        return f"- {label} [id {item.id}]" + (f" ({'; '.join(notes)})" if notes else "")

    lines = (
        [
            "All the knowledge of one assistant must use the same embedding "
            "model; these sources use more than one, so combine only those "
            "with the same embedding model id."
        ]
        if several
        else []
    )
    lines.append(f"Collections ({len(knowledge.groups.items)}):")
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
    return lines + [
        f"- {lock}" for lock in policy_locks(config) if lock.startswith("MCP")
    ]


def _server_view(server: Any) -> dict[str, Any]:
    """The parts of a server, a domain entity or the space's view of one,
    that say what it is: never its address or sign-in configuration. Each
    tool is named with the id a change of the tool's setting takes."""

    def tool_label(name: str, tool_id: object) -> str:
        return f"{name} [id {tool_id}]" if tool_id else name

    if isinstance(server, dict):
        tools = server.get("tools") or []
        return {
            "id": server["id"],
            "name": server["name"],
            "description": server.get("description"),
            "is_enabled": server.get("is_enabled", True),
            "tools": sorted(
                tool_label(tool.get("display_name") or tool["name"], tool.get("id"))
                for tool in tools
            ),
        }
    return {
        "id": server.id,
        "name": server.name,
        "description": server.description,
        "is_enabled": server.is_enabled,
        "tools": sorted(
            tool_label(_tool_name(tool), tool.id) for tool in _loaded_tools(server)
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
    before suggesting a choice, with the ids a change takes. Section "model"
    gives the chat models the assistant may use, with what each can do
    (context window, tool calling, reasoning and its efforts, images, price
    when shown), the space's default and the one in use, and those below the
    space's security classification; "knowledge" the collections, websites
    and integration sources of the space and the organisation, with their
    embedding models where they differ, and the result ranking models;
    "tools" the MCP servers with their tools, the functions with whether a
    provider is ready for each, and the document templates; "all" (default)
    everything. When the text says more follows, call again with the offset
    it gives."""

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
    "groups": "knowledge (collections)",
    "websites": "knowledge (websites)",
    "integration_knowledge_list": "knowledge (integration sources)",
    "rerank_model_id": "result ranking",
    "mcp_servers": "MCP servers",
    "mcp_tools": "MCP tools",
    "enabled_capabilities": "functions",
    "document_template": "the document template",
    "data_retention_days": "conversation retention",
    "insight_enabled": "insights",
}
_PROMPT_KEYS = frozenset({"text", "description"})
_MODEL_KEYS = frozenset({"id"})
_SETTING_KEYS = frozenset(key for key, _ in _SETTINGS)
_TEMPLATE_KEYS = frozenset({"mode", "template_id"})

# The list settings: the assistant's update request replaces each whole, and
# the chat also takes additions and removals, which it applies to the list as
# stored now.
_KNOWLEDGE_LISTS = ("groups", "websites", "integration_knowledge_list")
_LIST_SETTINGS = frozenset(
    {*_KNOWLEDGE_LISTS, "mcp_servers", "mcp_tools", "enabled_capabilities"}
)

# What a person calls the rest of an assistant's update request, to say what
# the chat cannot change.
_UNCHANGEABLE: dict[str, str] = {
    "id": "the assistant's identity",
    "space_id": "the space",
    "attachments": "attachments",
    "skill_bindings": "skills",
    "published": "publishing",
    "logging_enabled": "conversation logging",
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
    "(looked up when needed). "
    "Knowledge and tools take the ids read_options lists. groups "
    "(collections), websites, integration_knowledge_list (integration "
    "sources) and mcp_servers: to add or remove some, send "
    '{"add": [{"id": ...}], "remove": [{"id": ...}]}; the rest of the list '
    'is kept. Use this form. A list in its place ([{"id": ...}, ...]) '
    "replaces the whole list, and whatever it leaves out is removed. All the "
    "knowledge of one assistant must use the same embedding model. Knowledge "
    "and MCP servers are not combined: knowledge is added only to an "
    "assistant without MCP servers and MCP servers only to one without "
    "knowledge, unless it has both already. MCP servers and functions are "
    "turned on, and single MCP tools switched, only while the chat model the "
    "assistant answers with can use tools. "
    'enabled_capabilities (functions): {"add": ["web_search"], "remove": '
    '["charts"]} in the same way, or the whole list of functions. mcp_tools '
    "(single tools of the assistant's MCP servers): "
    '{"add": [{"tool_id": ..., "is_enabled": false}], "remove": '
    '[{"tool_id": ...}]}, where add switches a tool on or off for this '
    "assistant and remove returns it to its server's own setting; a whole "
    'list [{"tool_id": ..., "is_enabled": ...}] replaces every such setting. '
    "rerank_model_id: a result ranking model read_options lists, or null for "
    'none. document_template: {"mode": "default"} (the organisation\'s '
    'default), {"mode": "builtin"} (Eneo\'s built-in look) or {"mode": '
    '"selected", "template_id": a template read_options lists}. '
    "data_retention_days: how many days conversations are kept, "
    f"{MIN_RETENTION_DAYS} to {MAX_RETENTION_DAYS}, or null to follow the "
    "space. insight_enabled: true or false. Leave out what read_assistant "
    "says the person may not change or a policy locks. Attachments, skills, "
    "the icon, API keys, the web widget and conversation logging are changed "
    "in the editor; publishing has a tool of its own."
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
            "document_template": _TEMPLATE_KEYS,
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
        + "), the knowledge mode, the handling of files uploaded in a chat, the "
        "knowledge and its result ranking, the MCP servers and their tools, the "
        "functions, the document template, conversation retention and insights."
        + (
            " Publishing and unpublishing have a tool of their own, which asks "
            "the person first."
            if "published" in changes
            else ""
        )
    )


class _IdEdit(BaseModel):
    """Additions to and removals from a list of ids."""

    model_config = ConfigDict(extra="forbid")

    add: list[ModelId] = Field(default_factory=list[ModelId])
    remove: list[ModelId] = Field(default_factory=list[ModelId])


class _FunctionEdit(BaseModel):
    """Functions to switch on and off."""

    model_config = ConfigDict(extra="forbid")

    add: list[CapabilityPurpose] = Field(default_factory=list[CapabilityPurpose])
    remove: list[CapabilityPurpose] = Field(default_factory=list[CapabilityPurpose])


class _ToolRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: UUID


class _ToolEdit(BaseModel):
    """Tools to switch on or off for the assistant, and tools to return to
    their server's own setting."""

    model_config = ConfigDict(extra="forbid")

    add: list[MCPToolSetting] = Field(default_factory=list[MCPToolSetting])
    remove: list[_ToolRef] = Field(default_factory=list[_ToolRef])


class _ListEdits(BaseModel):
    """The list settings a change gives as additions and removals."""

    model_config = ConfigDict(extra="forbid")

    groups: _IdEdit | None = None
    websites: _IdEdit | None = None
    integration_knowledge_list: _IdEdit | None = None
    mcp_servers: _IdEdit | None = None
    enabled_capabilities: _FunctionEdit | None = None
    mcp_tools: _ToolEdit | None = None


@dataclass(frozen=True)
class ChangeRequest:
    """Changes as the chat reads them: the assistant's update request
    (``update``) and the list settings given as additions and removals
    (``edits``), which are not in ``update``."""

    update: Any
    edits: _ListEdits

    def names(self, key: str) -> bool:
        """Whether the change gives the setting ``key`` a value: a list
        setting a list or additions and removals, any other setting a value
        other than null, and those an update clears with null a null too."""
        if getattr(self.edits, key, None) is not None:
            return True
        if key in ("description", "data_retention_days", "rerank_model_id"):
            return key in self.update.model_fields_set
        return getattr(self.update, key, None) is not None


def changes_request(changes: dict[str, Any]) -> ChangeRequest:
    """The request ``changes`` make, refused when they name anything the chat
    may not change or do not have its shape."""
    from eneo.assistants.api.assistant_models import AssistantUpdatePublic

    require_changeable(changes)
    edited = {
        key: value
        for key, value in changes.items()
        if key in _LIST_SETTINGS and isinstance(value, dict)
    }
    return ChangeRequest(
        update=AssistantUpdatePublic.model_validate(
            {key: value for key, value in changes.items() if key not in edited}
        ),
        edits=_ListEdits.model_validate(edited),
    )


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


# The settings a change may name beyond the base ones, in the order a change
# lists them.
_MORE_SETTINGS: tuple[str, ...] = (
    "groups",
    "websites",
    "integration_knowledge_list",
    "rerank_model_id",
    "mcp_servers",
    "mcp_tools",
    "enabled_capabilities",
    "document_template",
    "data_retention_days",
    "insight_enabled",
)

# A function as a change names it: its purpose in words.
_FUNCTION_NAMES: dict[str, str] = {
    purpose: purpose.replace("_", " ") for purpose in _FUNCTIONS
}


@dataclass(frozen=True)
class ChangeFacts:
    """What a change is checked against and named with beyond the assistant,
    its space and the policy: the person's rights, the functions a provider
    is ready for in the space, the result ranking models (the names of all,
    and the one the change chooses when the space may use it) and the
    organisation's document templates. Each offers nothing unless prepared
    (``_change_facts``), so a check that was not prepared refuses."""

    rights: PersonRights = NO_RIGHTS
    ready_functions: frozenset[str] = frozenset()
    rerank_models: Mapping[UUID, str] = field(default_factory=dict[UUID, str])
    selectable_rerank_models: frozenset[UUID] = frozenset()
    document_templates: Mapping[UUID, str] = field(default_factory=dict[UUID, str])


def _by_name(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Named entries in the order a person reads them: by name, then id, so
    two lists with the same entries are equal."""
    return sorted(
        items, key=lambda item: ((item.get("name") or "").casefold(), item["id"])
    )


def _source_value(item: Any, key: str) -> dict[str, str]:
    name = _website_name(item) if key == "websites" else item.name
    return {"id": str(item.id), "name": name}


def _server_value(server: Any) -> dict[str, str]:
    return {"id": str(server.id), "name": server.name}


def _tool_names(servers: Iterable[Any]) -> dict[UUID, str]:
    """The tools of ``servers`` by id, with the names the editor shows."""
    return {
        tool.id: _tool_name(tool)
        for server in servers
        for tool in _loaded_tools(server)
    }


def _tools_value(
    overrides: Mapping[UUID, bool], names: Mapping[UUID, str]
) -> list[dict[str, Any]]:
    """The assistant's own settings of single tools: each tool switched on or
    off for it, with its name."""
    return _by_name(
        {"id": str(tool_id), "name": names.get(tool_id), "is_enabled": enabled}
        for tool_id, enabled in overrides.items()
    )


def _functions_value(purposes: Iterable[str]) -> list[dict[str, str]]:
    return _by_name(
        {"id": purpose, "name": _FUNCTION_NAMES.get(purpose, purpose)}
        for purpose in purposes
    )


def _rerank_value(
    model_id: UUID | None, names: Mapping[UUID, str]
) -> dict[str, Any] | None:
    if model_id is None:
        return None
    return {"id": str(model_id), "name": names.get(model_id)}


def _template_value(choice: Any, names: Mapping[UUID, str]) -> dict[str, Any]:
    template_id = choice.template_id
    return {
        "mode": choice.mode,
        "template_id": str(template_id) if template_id is not None else None,
        "name": names.get(template_id) if template_id is not None else None,
    }


def _more_setting(assistant: Any, key: str, facts: ChangeFacts) -> Any:
    """The value of ``key``, one of ``_MORE_SETTINGS``, as the assistant has
    it."""
    if key in ("groups", "websites", "integration_knowledge_list"):
        items = {
            "groups": assistant.collections,
            "websites": assistant.websites,
            "integration_knowledge_list": assistant.integration_knowledge_list,
        }[key]
        return _by_name(_source_value(item, key) for item in items)
    if key == "rerank_model_id":
        return _rerank_value(assistant.rerank_model_id, facts.rerank_models)
    if key == "mcp_servers":
        return _by_name(_server_value(server) for server in assistant.mcp_servers)
    if key == "mcp_tools":
        return _tools_value(
            dict(assistant.mcp_tools), _tool_names(assistant.mcp_servers)
        )
    if key == "enabled_capabilities":
        return _functions_value(assistant.enabled_capabilities)
    if key == "document_template":
        return _template_value(assistant.document_template, facts.document_templates)
    if key == "data_retention_days":
        return assistant.data_retention_days
    if key == "insight_enabled":
        return bool(assistant.insight_enabled)
    raise KeyError(key)


def assistant_settings_of(
    assistant: Any, facts: ChangeFacts | None = None, *, more: Iterable[str] = ()
) -> dict[str, Any]:
    """The settings the chat may change, as the assistant has them: the
    values a change's before and after are taken from. The base settings
    always, and of the others (``_MORE_SETTINGS``) those in ``more``, named
    with ``facts``. A list setting is a list of ``{id, name}`` by name, and
    the tool settings also carry ``is_enabled``; a credential, an address's
    sign-in part or a server's configuration is never part of one."""
    model = assistant.completion_model
    kwargs = assistant.completion_model_kwargs or ModelKwargs()
    settings: dict[str, Any] = {
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
    wanted = set(more)
    for key in _MORE_SETTINGS:
        if key in wanted:
            settings[key] = _more_setting(assistant, key, facts or ChangeFacts())
    return settings


def setting_changes(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    """Each setting whose value differs, with its value before and after."""
    return [
        {"field": key, "before": value, "after": after[key]}
        for key, value in before.items()
        if after[key] != value
    ]


def undo_update(
    changes: Sequence[dict[str, Any]], kwargs_before: ModelKwargs
) -> dict[str, Any]:
    """The update request that gives the changed settings their values from
    before. A chat model cannot be taken away by an update, so an assistant
    that had none keeps the one it was given. A list setting gets its whole
    list from before."""
    undo: dict[str, Any] = {}
    for change in changes:
        key, before = change["field"], change["before"]
        if key == "prompt":
            undo["prompt"] = {"text": before, "description": _RESTORED_WITH_UNDO}
        elif key == "completion_model":
            if before is not None:
                undo["completion_model"] = {"id": before["id"]}
        elif key.startswith("completion_model_kwargs."):
            undo["completion_model_kwargs"] = kwargs_before.model_dump(
                mode="json", exclude_none=True
            )
        elif key in (*_KNOWLEDGE_LISTS, "mcp_servers"):
            undo[key] = [{"id": item["id"]} for item in before]
        elif key == "mcp_tools":
            undo[key] = [
                {"tool_id": item["id"], "is_enabled": item["is_enabled"]}
                for item in before
            ]
        elif key == "enabled_capabilities":
            undo[key] = [item["id"] for item in before]
        elif key == "rerank_model_id":
            undo[key] = before["id"] if before is not None else None
        elif key == "document_template":
            undo[key] = {"mode": before["mode"], "template_id": before["template_id"]}
        else:
            undo[key] = before
    return undo


@dataclass(frozen=True)
class PlannedChange:
    """A change as the chat would make it: the settings now (``settings``,
    with the model settings whole in ``kwargs``), the update request that
    makes it (``update``, only what differs from now) and each setting it
    changes with its value now and after (``changes``). ``more`` and
    ``facts`` say which settings beyond the base ones ``settings`` holds and
    what named them, so the assistant after the change is read the same
    way."""

    settings: dict[str, Any]
    kwargs: ModelKwargs
    update: dict[str, Any]
    changes: list[dict[str, Any]]
    published: bool
    more: tuple[str, ...] = ()
    facts: ChangeFacts = field(default_factory=ChangeFacts)


def _policy_refusal(what: str) -> BadRequestException:
    return BadRequestException(
        f"An organisation policy sets {what} for this assistant, so it cannot be "
        "changed through the chat. Nothing was changed."
    )


def _role_refusal(
    what: str, rights: PersonRights, *, in_personal_space: str | None = None
) -> BadRequestException:
    """The refusal of a change the person's role does not allow: who can make
    it, or, for what a personal space does not use, that."""
    if rights.personal_space and in_personal_space is not None:
        return BadRequestException(f"{in_personal_space} Nothing was changed.")
    return BadRequestException(
        f"The person's role does not let them change {what}; {_WHO_CAN}, can. "
        "Nothing was changed."
    )


_NOT_COMBINED = "Knowledge and MCP servers are not combined on one assistant"


def _not_combined_refusal(
    had_knowledge: bool, had_servers: bool
) -> BadRequestException:
    """The refusal of a change that would combine knowledge and MCP servers:
    what the assistant has that stands in the way, and what can go instead."""
    if had_servers:
        text = (
            f"{_NOT_COMBINED}, and this one has MCP servers, so no knowledge can "
            "be added to it. If the person wants knowledge in their place, "
            "remove the MCP servers in the same change."
        )
    elif had_knowledge:
        text = (
            f"{_NOT_COMBINED}, and this one has knowledge, so no MCP server can "
            "be added to it. If the person wants MCP servers in its place, "
            "remove its knowledge in the same change."
        )
    else:
        text = f"{_NOT_COMBINED}, so both cannot be added: add one or the other."
    return BadRequestException(f"{text} Nothing was changed.")


def _tools_refusal(model: Any, what: str) -> BadRequestException:
    """The refusal of what needs a chat model that can use tools, while the
    one the assistant would answer with cannot."""
    return BadRequestException(
        f"The chat model the assistant would answer with, {_model_name(model)}, "
        f"cannot use tools, so {what}. Choose a chat model that can use tools "
        "first, or in the same change; read_options says which can. Nothing was "
        "changed."
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


_T = TypeVar("_T")


def _edited_list(
    current: Sequence[_T],
    whole: Sequence[_T] | None,
    edit: tuple[Sequence[_T], Sequence[_T]] | None,
) -> list[_T] | None:
    """The whole list a change gives a list setting: the list it sends
    (``whole``), or the list as stored now (``current``) with the additions
    and without the removals of ``edit``; None when it leaves the setting
    alone. An entry is kept once; one both added and removed is removed."""
    if edit is not None:
        added, removed = edit
        gone = set(removed)
        return list(
            dict.fromkeys(
                [
                    *(item for item in current if item not in gone),
                    *(item for item in added if item not in gone),
                ]
            )
        )
    if whole is not None:
        return list(dict.fromkeys(whole))
    return None


def _edited_ids(current: Iterable[Any], whole: Any, edit: Any) -> list[UUID] | None:
    """``_edited_list`` over items with ids: the assistant's current ones, a
    sent list of ``{id}`` and additions and removals of ``{id}``."""
    return _edited_list(
        [item.id for item in current],
        [item.id for item in whole] if whole is not None else None,
        (
            [item.id for item in edit.add],
            [item.id for item in edit.remove],
        )
        if edit is not None
        else None,
    )


def one_embedding_model(assistant: Any, lists: Mapping[str, Sequence[Any]]) -> bool:
    """Whether the knowledge lists a change sets (``lists``, by request key)
    keep the rule the assistant applies when its lists are set: a list that
    is set uses one embedding model, and that is the one of the websites, or
    without websites of the collections, the list is set beside. Collections
    and websites given together are set as a pair, and the integration
    sources are set last."""
    collections = list(assistant.collections)
    websites = list(assistant.websites)

    def fits(items: Sequence[Any]) -> bool:
        if not items:
            return True
        models = {item.embedding_model.id for item in items}
        beside = websites or collections
        return len(models) == 1 and (
            not beside or beside[0].embedding_model.id in models
        )

    new_collections = lists.get("groups")
    new_websites = lists.get("websites")
    if new_collections is not None and new_websites is not None:
        collections, websites = [], []
    if new_collections is not None:
        collections = []
        if not fits(new_collections):
            return False
        collections = list(new_collections)
    if new_websites is not None:
        websites = []
        if not fits(new_websites):
            return False
        websites = list(new_websites)
    integrations = lists.get("integration_knowledge_list")
    return integrations is None or fits(integrations)


# What each knowledge list holds, one and several, as a person says it.
_SOURCES: dict[str, tuple[str, str]] = {
    "groups": ("collection", "collections"),
    "websites": ("website", "websites"),
    "integration_knowledge_list": ("integration source", "integration sources"),
}


def _require_knowledge_or_mcp(
    assistant: Any, request: ChangeRequest, config: Any | None
) -> None:
    """Refuse a change that leaves the assistant with both knowledge and MCP
    servers when it does not have both now, as the editor's two pickers do:
    knowledge is added only while the assistant has no MCP servers or has
    knowledge already, and MCP servers only while it has no knowledge or has
    an MCP server already. The change is judged on the assistant now and
    after it, so one that removes one side and adds the other is planned, as
    the editor allows it in two steps, and an assistant that has both now
    stays changeable on both sides. A change of the MCP servers a policy sets
    gets the policy's refusal instead."""
    had_knowledge = _has_knowledge(assistant)
    had_servers = bool(assistant.mcp_servers)
    if had_knowledge and had_servers:
        return

    def after(current: Sequence[Any], key: str) -> set[Any]:
        ids = _edited_ids(
            current, getattr(request.update, key), getattr(request.edits, key)
        )
        return {item.id for item in current} if ids is None else set(ids)

    knowledge = any(
        after(items, key)
        for key, items in (
            ("groups", assistant.collections),
            ("websites", assistant.websites),
            ("integration_knowledge_list", assistant.integration_knowledge_list),
        )
    )
    servers = after(assistant.mcp_servers, "mcp_servers")
    if not (knowledge and servers):
        return
    if (
        config is not None
        and config.mcp_enforced
        and servers != {server.id for server in assistant.mcp_servers}
    ):
        return
    raise _not_combined_refusal(had_knowledge, had_servers)


def _plan_knowledge(
    assistant: Any,
    request: ChangeRequest,
    space: Any,
    after: dict[str, Any],
    update: dict[str, Any],
) -> None:
    """The knowledge lists the change sets: only sources the space offers
    (its own and the organisation's), all on one embedding model."""
    stored = {
        "groups": assistant.collections,
        "websites": assistant.websites,
        "integration_knowledge_list": assistant.integration_knowledge_list,
    }
    offered_by_space = {
        "groups": space.collections,
        "websites": space.websites,
        "integration_knowledge_list": space.integration_knowledge_list,
    }
    changed: dict[str, list[Any]] = {}
    for key in _KNOWLEDGE_LISTS:
        current = list(stored[key])
        ids = _edited_ids(
            current, getattr(request.update, key), getattr(request.edits, key)
        )
        if ids is None or set(ids) == {item.id for item in current}:
            continue
        offered = {item.id: item for item in offered_by_space[key]}
        known = {item.id: item for item in current}
        one, several = _SOURCES[key]
        for item_id in ids:
            if item_id in offered:
                continue
            if item_id in known:
                name = _source_value(known[item_id], key)["name"]
                raise BadRequestException(
                    f'The space no longer offers "{_short(name, 80)}", so the '
                    f"{several} cannot be saved with it: remove it as well. "
                    "Nothing was changed."
                )
            raise BadRequestException(
                f"The space does not offer that {one}; read_options lists the "
                f"{several} it offers. Nothing was changed."
            )
        changed[key] = [offered[item_id] for item_id in ids]
    if not changed:
        return
    if not one_embedding_model(assistant, changed):
        raise BadRequestException(
            "All the knowledge of one assistant must use the same embedding "
            "model, and these sources do not; read_options says which "
            "embedding model each source uses. Nothing was changed."
        )
    for key, items in changed.items():
        update[key] = [{"id": str(item.id)} for item in items]
        after[key] = _by_name(_source_value(item, key) for item in items)


def _plan_mcp(
    assistant: Any,
    request: ChangeRequest,
    space: Any,
    config: Any | None,
    answering: Any | None,
    after: dict[str, Any],
    update: dict[str, Any],
) -> None:
    """The MCP servers and the tool settings the change sets, by the rules
    the update applies: no change under a policy that sets them, only
    servers the space offers, switched on by an administrator and not a
    function's provider, and tool settings only for tools of the servers the
    assistant has after the change. By the editor's rule, while the chat
    model the assistant would answer with (``answering``) cannot use tools,
    no server is added and no tool's own setting changes, though a server
    can go and take its tools' settings along."""
    governed = config is not None and config.mcp_enforced
    current_servers = list(assistant.mcp_servers)
    servers = current_servers
    ids = _edited_ids(
        current_servers, request.update.mcp_servers, request.edits.mcp_servers
    )
    servers_change = ids is not None and set(ids) != {
        server.id for server in current_servers
    }
    if ids is not None and servers_change:
        if governed:
            raise _policy_refusal("the MCP servers and functions")
        offered = {server.id: server for server in space.mcp_servers}
        known = {server.id: server for server in current_servers}
        for server_id in ids:
            server = offered.get(server_id)
            if server is None:
                if server_id in known:
                    raise BadRequestException(
                        f'The space no longer offers "{known[server_id].name}", so '
                        "the MCP servers cannot be saved with it: remove it as "
                        "well. Nothing was changed."
                    )
                raise BadRequestException(
                    "The space does not offer that MCP server; read_options "
                    "lists the servers it offers. Nothing was changed."
                )
            if is_capability_purpose(server.purpose):
                raise BadRequestException(
                    f'"{server.name}" provides a function: switch functions on '
                    "and off with enabled_capabilities. Nothing was changed."
                )
            if not server.is_enabled:
                raise BadRequestException(
                    f'"{server.name}" is turned off by an administrator, so the '
                    "MCP servers cannot be saved with it"
                    + (": remove it as well" if server_id in known else "")
                    + ". Nothing was changed."
                )
        if _cannot_use_tools(answering) and any(
            server_id not in known for server_id in ids
        ):
            raise _tools_refusal(answering, "no MCP server can be added")
        servers = [offered[server_id] for server_id in ids]
        update["mcp_servers"] = [{"id": str(server.id)} for server in servers]
        after["mcp_servers"] = _by_name(_server_value(server) for server in servers)

    current = dict(assistant.mcp_tools)
    # A server that goes takes the assistant's settings of its tools along.
    staying = {server.id for server in servers}
    gone = _tool_names(server for server in current_servers if server.id not in staying)
    kept = {tool_id: on for tool_id, on in current.items() if tool_id not in gone}
    tool_edit = request.edits.mcp_tools
    tool_list = request.update.mcp_tools
    if tool_edit is not None:
        overrides = dict(kept)
        overrides.update({item.tool_id: item.is_enabled for item in tool_edit.add})
        for item in tool_edit.remove:
            overrides.pop(item.tool_id, None)
    elif tool_list is not None:
        overrides = {item.tool_id: item.is_enabled for item in tool_list}
    else:
        overrides = kept
    if overrides == current:
        return
    if governed:
        raise _policy_refusal("the MCP servers and functions")
    reachable = _tool_names(servers)
    if any(
        tool_id not in reachable
        for tool_id, on in overrides.items()
        if current.get(tool_id) != on
    ):
        raise BadRequestException(
            "That tool is not a tool of the assistant's MCP servers; "
            "read_options lists each server's tools with their ids. Nothing was "
            "changed."
        )
    if overrides != kept and _cannot_use_tools(answering):
        raise _tools_refusal(
            answering,
            "no single MCP tool can be switched on or off (an MCP server can "
            "still be removed)",
        )
    if tool_edit is not None or tool_list is not None:
        update["mcp_tools"] = [
            {"tool_id": str(tool_id), "is_enabled": on}
            for tool_id, on in overrides.items()
        ]
    after["mcp_tools"] = _tools_value(
        overrides, _tool_names([*current_servers, *servers])
    )


def _plan_functions(
    assistant: Any,
    request: ChangeRequest,
    space: Any,
    config: Any | None,
    facts: ChangeFacts,
    answering: Any | None,
    after: dict[str, Any],
    update: dict[str, Any],
) -> None:
    """The functions the change sets: none under a policy that sets them,
    and only functions the space offers, while the chat model the assistant
    would answer with (``answering``) can use tools, and a provider is ready
    for are switched on, checked in the order the editor gives its reasons;
    switching one off is always allowed."""
    current = list(assistant.enabled_capabilities)
    edit = request.edits.enabled_capabilities
    purposes = _edited_list(
        current,
        request.update.enabled_capabilities,
        (edit.add, edit.remove) if edit is not None else None,
    )
    if purposes is None or set(purposes) == set(current):
        return
    if config is not None and config.mcp_enforced:
        raise _policy_refusal("the MCP servers and functions")
    added = [purpose for purpose in purposes if purpose not in current]

    def named(found: list[str]) -> str:
        return _listing([_FUNCTION_NAMES.get(purpose, purpose) for purpose in found])

    not_offered = [p for p in added if p not in space.enabled_capabilities]
    if not_offered:
        raise BadRequestException(
            f"The space does not offer {named(not_offered)}; read_options lists "
            "the functions it offers. Nothing was changed."
        )
    if added and _cannot_use_tools(answering):
        raise _tools_refusal(answering, f"{named(added)} cannot be switched on")
    not_ready = [p for p in added if p not in facts.ready_functions]
    if not_ready:
        raise BadRequestException(
            f"No provider is ready for {named(not_ready)}, so "
            f"{'it' if len(not_ready) == 1 else 'they'} cannot be switched on. "
            "Nothing was changed."
        )
    chosen = sorted(set(purposes))
    update["enabled_capabilities"] = chosen
    after["enabled_capabilities"] = _functions_value(chosen)


def _plan_choices(
    assistant: Any,
    request: ChangeRequest,
    facts: ChangeFacts,
    after: dict[str, Any],
    update: dict[str, Any],
) -> None:
    """The result ranking model, the document template, the retention and
    the insights switch the change sets: a ranking model the space may use,
    one of the organisation's templates, and retention and insights only
    when the person's role allows it."""
    from eneo.document_templates.domain import DocumentTemplateChoice

    if request.names("rerank_model_id"):
        chosen = request.update.rerank_model_id
        if chosen != assistant.rerank_model_id:
            if chosen is not None and chosen not in facts.selectable_rerank_models:
                raise BadRequestException(
                    "The space cannot use that result ranking model; "
                    "read_options lists those it can. Nothing was changed."
                )
            update["rerank_model_id"] = str(chosen) if chosen is not None else None
            after["rerank_model_id"] = _rerank_value(chosen, facts.rerank_models)

    sent = request.update.document_template
    if sent is not None:
        try:
            choice = DocumentTemplateChoice(
                mode=sent.mode, template_id=sent.template_id
            )
        except ValueError:
            raise BadRequestException(
                'A template is chosen with "mode": "selected" and its '
                "template_id, and only then is a template_id given. Nothing "
                "was changed."
            ) from None
        if choice != assistant.document_template:
            if (
                choice.template_id is not None
                and choice.template_id not in facts.document_templates
            ):
                raise BadRequestException(
                    "The organisation has no such document template; "
                    "read_options lists them. Nothing was changed."
                )
            update["document_template"] = {
                "mode": choice.mode,
                "template_id": (
                    str(choice.template_id) if choice.template_id is not None else None
                ),
            }
            after["document_template"] = _template_value(
                choice, facts.document_templates
            )

    if request.names("data_retention_days"):
        days = request.update.data_retention_days
        if days != assistant.data_retention_days:
            if not facts.rights.edit_retention:
                raise _role_refusal("how long conversations are kept", facts.rights)
            update["data_retention_days"] = after["data_retention_days"] = days

    insight = request.update.insight_enabled
    if insight is not None and insight != bool(assistant.insight_enabled):
        if not facts.rights.toggle_insight:
            raise _role_refusal(
                "whether insights are on",
                facts.rights,
                in_personal_space=_PERSONAL_INSIGHTS,
            )
        update["insight_enabled"] = after["insight_enabled"] = insight


def plan_change(
    assistant: Any,
    changes: dict[str, Any],
    *,
    space: Any,
    effective_config: Any | None,
    facts: ChangeFacts | None = None,
) -> PlannedChange:
    """The change ``changes`` makes to ``assistant``, checked as far as it
    can be without saving it: only settings the chat may change, the shape
    the assistant's update request takes, what an organisation policy
    decides, what the person's role allows (``facts``), the editor's own
    rules (knowledge and MCP servers are not combined, and MCP servers and
    functions are turned on, and tool settings changed, only while the chat
    model the assistant would answer with can use tools), whether the space
    offers a chosen model, knowledge source, MCP server, tool, function,
    ranking model or template, whether the model offers the model settings
    and whether the knowledge shares one embedding model. A setting given
    the value it already has is left out, so it is not saved again.

    A field left out keeps its value, and so does null, except where the
    update request clears it: null clears the description, the result
    ranking and the retention (which then follows the space), and null model
    settings return every setting to the model's default. Within the model
    settings, a setting left out keeps its value. A list setting is built
    whole from the assistant as stored now: the list sent, or the stored one
    with the additions and removals sent."""
    parsed = changes_request(changes)
    request = parsed.update
    facts = facts or ChangeFacts()
    config = effective_config
    sent = request.model_fields_set
    more = tuple(
        key
        for key in _MORE_SETTINGS
        if parsed.names(key) or (key == "mcp_tools" and parsed.names("mcp_servers"))
    )
    before = assistant_settings_of(assistant, facts, more=more)
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

    if more:
        # The editor's rules judge what is turned on by the model the
        # assistant answers with after the change: a model chosen in the same
        # change counts, and so does the one a models policy steers it to.
        answering = answering_model(model, config)
        _require_knowledge_or_mcp(assistant, parsed, config)
        _plan_knowledge(assistant, parsed, space, after, update)
        _plan_mcp(assistant, parsed, space, config, answering, after, update)
        _plan_functions(
            assistant, parsed, space, config, facts, answering, after, update
        )
        _plan_choices(assistant, parsed, facts, after, update)

    return PlannedChange(
        settings=before,
        kwargs=stored,
        update=update,
        changes=setting_changes(before, after),
        published=bool(assistant.published),
        more=more,
        facts=facts,
    )


async def _change_facts(
    container: Any, space: Any, request: ChangeRequest
) -> ChangeFacts:
    """What ``plan_change`` checks ``request`` against beyond the assistant
    and its space, read only for the settings the request names, through
    what the update itself checks them with: the person's actor in the space,
    the providers' readiness (``capability_availability``, which the update's
    ``validate_capability_additions`` reads), the ranking model's
    ``RerankService.selectable`` and the organisation's live templates."""
    from eneo.mcp_servers.application.capability_resolver import (
        capability_availability,
    )

    ready: frozenset[str] = frozenset()
    if request.names("enabled_capabilities"):
        states = await capability_availability(
            container.session(),
            container.user().tenant_id,
            space.security_classification,
        )
        ready = frozenset(state.purpose for state in states if state.available)
    rerank_models: dict[UUID, str] = {}
    selectable: frozenset[UUID] = frozenset()
    if request.names("rerank_model_id"):
        models = await container.rerank_model_crud_service().get_rerank_models()
        rerank_models = {model.id: _model_name(model) for model in models}
        chosen = request.update.rerank_model_id
        if isinstance(chosen, UUID) and await container.rerank_service().selectable(
            chosen, space.security_classification
        ):
            selectable = frozenset({chosen})
    templates: dict[UUID, str] = {}
    if request.names("document_template"):
        templates = {
            item.id: item.name for item in await _document_templates(container)
        }
    return ChangeFacts(
        rights=PersonRights.of(
            container.actor_manager().get_space_actor_from_space(space=space)
        ),
        ready_functions=ready,
        rerank_models=rerank_models,
        selectable_rerank_models=selectable,
        document_templates=templates,
    )


async def _planned_change(
    container: Any, chat: Any, changes: dict[str, Any]
) -> PlannedChange:
    """The change ``changes`` makes to the chat's assistant as it is now.
    Changes the chat may not make, or of the wrong shape, are refused before
    anything is read."""
    request = changes_request(changes)
    (
        assistant,
        _,
        config,
    ) = await container.assistant_service().get_assistant_with_effective_config(
        chat.target_id
    )
    space = await container.space_service().get_space(chat.space_id)
    return plan_change(
        assistant,
        changes,
        space=space,
        effective_config=config,
        facts=await _change_facts(container, space, request),
    )


_MODES = {
    "tool": "searched when needed",
    "inject": "put in the prompt on every question",
}
_FILES = {True: "put whole in the prompt", False: "looked up when needed"}


# What a list setting holds, as the editor names it.
_LISTS: dict[str, str] = {
    "groups": "collections",
    "websites": "websites",
    "integration_knowledge_list": "integration sources",
    "mcp_servers": "MCP servers",
    "enabled_capabilities": "functions",
}


def _list_line(
    label: str, before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> str:
    old = {item["id"]: item["name"] for item in before}
    new = {item["id"]: item["name"] for item in after}

    def names(found: Iterable[Any]) -> str:
        return _listing([f'"{_short(name or "", 80)}"' for name in found])

    parts = [
        f"{verb} {names(found)}"
        for verb, found in (
            ("added", [new[key] for key in new if key not in old]),
            ("removed", [old[key] for key in old if key not in new]),
        )
        if found
    ]
    return f"{label} ({'; '.join(parts)})"


def _tools_line(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    old = {item["id"]: item for item in before}
    new = {item["id"]: item for item in after}
    parts: list[str] = []
    for key in dict.fromkeys([*new, *old]):
        now, then = new.get(key), old.get(key)
        name = _short(((now or then) or {}).get("name") or "a tool", 80)
        if now is None:
            parts.append(f"{name} back to its server's setting")
        elif then is None or then["is_enabled"] != now["is_enabled"]:
            parts.append(f"{name} {'on' if now['is_enabled'] else 'off'}")
    return f"MCP tools ({', '.join(parts)})"


def _choice_line(key: str, before: Any, after: Any) -> str:
    """A change of the result ranking, the document template, the retention
    or the insights switch."""

    def shown(value: Any) -> str:
        if key == "rerank_model_id":
            return "none" if value is None else value["name"] or "another model"
        if key == "document_template":
            if value["mode"] == "default":
                return "the organisation's default"
            if value["mode"] == "builtin":
                return "Eneo's built-in look"
            return value["name"] or "a template"
        if key == "data_retention_days":
            return "following the space" if value is None else f"{value} days"
        return "on" if value else "off"

    label = {
        "rerank_model_id": "result ranking",
        "document_template": "document template",
        "data_retention_days": "conversation retention",
    }.get(key, "insights")
    return f"{label} (from {shown(before)} to {shown(after)})"


def _change_line(change: dict[str, Any], *, saved: bool) -> str:
    """One change for the model: the setting as the editor calls it, with
    its values when they are short. Never an id, and never the text of the
    instructions or the description."""
    key, before, after = change["field"], change["before"], change["after"]
    if key == "prompt":
        return (
            "instructions (a new version)"
            if saved
            else f"instructions (new text of {len(after or ''):,} characters)"
        )
    if key == "description":
        return "description (cleared)" if not after else "description"
    if key == "name":
        return f'name (from "{_short(before, 80)}" to "{_short(after, 80)}")'
    if key == "completion_model":
        old = before["name"] if before else "none"
        return f"chat model (from {old} to {after['name']})"
    if key == "knowledge_mode":
        return (
            f"knowledge mode (from {_MODES.get(before, before)} to "
            f"{_MODES.get(after, after)})"
        )
    if key == "inline_file_text":
        return (
            f"files uploaded in a chat (from {_FILES[bool(before)]} to "
            f"{_FILES[bool(after)]})"
        )
    if key in _LISTS:
        return _list_line(_LISTS[key], before, after)
    if key == "mcp_tools":
        return _tools_line(before, after)
    if key in (
        "rerank_model_id",
        "document_template",
        "data_retention_days",
        "insight_enabled",
    ):
        return _choice_line(key, before, after)
    label = dict(_SETTINGS).get(key.removeprefix("completion_model_kwargs."), key)

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
        "as it can be without saving (what a policy decides, what the person's "
        "role allows, the editor's rules on knowledge beside MCP servers and on "
        "models that cannot use tools, whether the space offers a model, "
        "knowledge source, MCP server or tool, function, ranking model or "
        "template, and the model its settings); applying it can still be "
        "refused, for example when the "
        "instructions and files no longer fit the model. A refusal says why and "
        "proposes nothing."
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
        changed = setting_changes(
            planned.settings,
            assistant_settings_of(after, planned.facts, more=planned.more),
        )
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


# --- read_prompt_history -----------------------------------------------------

# How much of each saved version the list shows: its first lines, flattened.
_PREVIEW_LINES = 3
_PREVIEW_CHARS = 200


def _when(moment: datetime | None) -> str:
    if moment is None:
        return "at an unknown time"
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _author(prompt: Any) -> str:
    """Who the version history names for a version: the user the prompt
    belongs to, as the editor's version list shows them."""
    user = prompt.user
    if user is None:
        return "unknown"
    return user.username or user.email


def _version_head(prompt: Any) -> str:
    return (
        f"saved {_when(prompt.created_at)}"
        + (" (in use now)" if prompt.is_selected else "")
        + f"; author: {_author(prompt)}; {len(prompt.text or ''):,} characters"
    )


def history_lines(prompts: Sequence[Any], version: int | None) -> list[str]:
    """The lines ``read_prompt_history`` pages through: every saved version
    of the instructions, newest first, numbered from 1, with its head, its
    description and how it begins; or, with ``version``, that version whole."""
    if version is not None:
        if not 1 <= version <= len(prompts):
            raise BadRequestException(
                f"version must be from 1 to {len(prompts)}, a number from the "
                "list read_prompt_history gives without a version."
                if prompts
                else "No versions of the instructions are saved."
            )
        prompt = prompts[version - 1]
        return [
            f"Version {version} of {len(prompts)}, {_version_head(prompt)}",
            f"Description: {_short(prompt.description) or 'none'}",
            "Text:",
            *_wrapped(prompt.text or ""),
        ]
    if not prompts:
        return ["No versions of the instructions are saved."]
    lines: list[str] = []
    for number, prompt in enumerate(prompts, start=1):
        first = [line for line in (prompt.text or "").splitlines() if line.strip()]
        lines += [
            f"{number}. {_version_head(prompt)}",
            f"   description: {_short(prompt.description) or 'none'}",
            "   begins: "
            + (_short(" / ".join(first[:_PREVIEW_LINES]), _PREVIEW_CHARS) or "(empty)"),
        ]
    return lines


@mcp.tool(annotations=_READS)
async def read_prompt_history(
    ctx: Context, offset: int = 0, version: int | None = None
) -> CallToolResult:
    """Read the saved versions of the assistant's instructions, newest
    first, as the editor's version history lists them: when each was saved,
    whether it is the one in use, its author, its description and how it
    begins. To read one version whole, call again with version set to its
    number in that list (1 is the newest); read the list again first when
    the instructions may have changed since. A long read comes in parts:
    when the text says more follows, call again with the offset it gives."""

    async def operation(container, chat):
        prompts = await container.assistant_service().get_prompts_by_assistant(
            chat.target_id
        )
        lines = history_lines(prompts, version)
        return page_lines(
            lines,
            tool="read_prompt_history",
            section="history",
            offset=offset,
            assistant_id=chat.target_id,
            title=(
                "The saved versions of the instructions, newest first"
                if version is None
                else f"Version {version} of the instructions"
            ),
            again="" if version is None else f"version={version}",
        )

    return await _call(ctx, operation)


# --- publish_assistant -------------------------------------------------------


def publish_text(published: bool) -> str:
    """What the model is told when the assistant was published or
    unpublished."""
    if published:
        return (
            "Published: the assistant is now published. The card shows the "
            "change and has no undo; to unpublish it, the person asks for that."
        )
    return (
        "Unpublished: the assistant is no longer published. The card shows the "
        "change and has no undo; to publish it again, the person asks for that."
    )


@mcp.tool(annotations=_ACTS)
async def publish_assistant(ctx: Context, published: bool) -> CallToolResult:
    """Publish the assistant (published true) or unpublish it (false), only
    when the person asks for it. The person approves each call in the chat
    before it runs; a call they decline changed nothing, so do not repeat it
    unless they ask again. Refused when the person's role does not let them
    publish, or when the assistant already is published or unpublished as
    asked."""

    async def operation(container, chat):
        from eneo.assistants.application.assistant_publish_operation import (
            apply_assistant_publish,
        )

        assistant, _ = await container.assistant_service().get_assistant(chat.target_id)
        rights = await _person_rights(container, chat.space_id)
        if not rights.publish:
            raise _role_refusal(
                "whether this assistant is published",
                rights,
                in_personal_space=_PERSONAL_PUBLISHING,
            )
        before = bool(assistant.published)
        if before == published:
            raise BadRequestException(
                "The assistant is already "
                + ("published" if published else "unpublished")
                + ". Nothing was changed."
            )
        applied = await apply_assistant_publish(
            container,
            assistant_id=chat.target_id,
            published=published,
            audit_context={
                "origin": HELPER_CHAT_ORIGIN,
                "session_id": str(chat.session_id),
            },
        )
        after = bool(applied.assistant.published)
        return CallToolResult(
            content=[TextContent(type="text", text=publish_text(after))],
            structuredContent={
                "target_id": str(chat.target_id),
                "changes": [{"field": "published", "before": before, "after": after}],
                "undo": None,
            },
        )

    return await _call(ctx, operation, approved=True)


# --- The server of one turn --------------------------------------------------

EDIT_MODE_TOOLS: frozenset[str] = frozenset({"update_assistant"})
"""The tools ``_call`` refuses outside edit mode. The chat on an assistant has
no edit mode, so no turn offers them; it proposes a change instead."""


async def build_assistant_settings_mcp_server(*, token: str, tenant_id: UUID):
    """The assistant settings server for one turn: the tools that read, the
    proposal and publishing, never a tool that needs edit mode."""
    return await build_ephemeral_server(
        mcp,
        name=ASSISTANT_SERVER_NAME,
        description=_SERVER_DESCRIPTION,
        token=token,
        tenant_id=tenant_id,
        exclude_tools=EDIT_MODE_TOOLS,
    )

# pyright: basic
# FastMCP's Context/elicit/Field surface is largely untyped; this module is a thin
# adapter over it, so strict unknown-type checking adds noise without safety here.
"""FastMCP loopback server + ephemeral-server builder for assistant "edit mode".

The same process both *hosts* this MCP server (mounted at ``/internal-mcp``) and
*connects* to it as an MCP client during a completion. Authentication rides in
the bearer token: a short-lived access token that authenticates the user and
carries scope claims (``scope_type``/``scope_id`` and a focused ``assistant_id``)
identifying what is being configured. Tools therefore need no scope argument and
cannot be pointed at another resource than the one in the token.

Tools are generated from the shared capability registry
(``intric.config_capabilities``): one FastMCP tool per capability, plus the
``ask_user`` interaction. Each tool confirms mutating changes via elicitation,
then runs the capability in a user-bound, permission-checked, audited context.
"""

from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import jwt
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field, create_model

from intric.config_capabilities import (
    CAPABILITY_REGISTRY,
    capability_context,
    run_capability,
)
from intric.config_capabilities.capability import ConfigCapability
from intric.main.config import get_settings
from intric.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool

logger = logging.getLogger(__name__)

# Name of the ephemeral MCP server eneo attaches in edit mode. The MCP proxy
# prefixes tools with a sanitized form of this (``assistant_config__set_name``).
CONFIG_SERVER_NAME = "assistant-config"

CONFIG_PERSONA_PROMPT = (
    "You are the configuration assistant for one specific Eneo assistant. "
    "The user is an administrator editing that assistant and its space. Treat "
    "every message as an instruction to inspect or change this assistant's "
    "configuration or its space's knowledge, and use the provided tools to do so. "
    "Available actions include reading the assistant's settings, renaming it, "
    "creating knowledge collections and websites in the space, and attaching "
    "knowledge to the assistant.\n\n"
    "Read the current settings (assistant_get_settings) or list space knowledge "
    "(space_list_collections) first when you need current values. When a request "
    "is ambiguous or underspecified, do NOT guess and do NOT just write a question "
    "as text: call ask_user with a single specific question and a few concrete "
    "suggestions.\n\n"
    "Every changing tool asks the user to confirm before it applies, so you do not "
    "need a separate yes/no message first: state plainly what you are about to "
    "change (old value and new value), then call the tool. The user is shown a "
    "confirmation dialog; if they decline, the tool reports the change was "
    "cancelled, so relay that and do not retry unless asked. Change only what the "
    "user asked for, one thing at a time. After a change applies, briefly confirm "
    "what changed. If a change is rejected because the user lacks permission, relay "
    "that plainly. Do not invent settings or values."
)

mcp = FastMCP(
    name="Eneo Assistant Configuration",
    instructions=(
        "Tools for reading and updating the settings of a single Eneo assistant. "
        "The target assistant is fixed by the access token; tools take no "
        "assistant id."
    ),
)


# --------------------------------------------------------------------------- #
# Request context helpers
# --------------------------------------------------------------------------- #
def _bearer_from_ctx(ctx: Context) -> str:
    request = ctx.request_context.request
    header = request.headers.get("authorization") if request is not None else None
    if not header or not header.lower().startswith("bearer "):
        raise ValueError("Missing or malformed Authorization header.")
    return header.split(" ", 1)[1].strip()


def _normalize_lang(raw: str | None) -> str:
    return "sv" if (raw or "").lower().startswith("sv") else "en"


def _lang_from_ctx(ctx: Context) -> str:
    """Read the user's locale from the token's ``lang`` claim (default English)."""
    try:
        token = _bearer_from_ctx(ctx)
        settings = get_settings()
        claims = jwt.decode(
            token,
            key=str(settings.jwt_secret),
            audience=settings.jwt_audience,
            algorithms=[settings.jwt_algorithm],
        )
        return _normalize_lang(claims.get("lang"))
    except Exception:
        return "en"


# Localized titles for non-capability tools (capability tools carry their own).
_TITLES: dict[str, dict[str, str]] = {
    "Ask the user": {"sv": "Fråga användaren"},
}

# Fixed user-facing strings. Each entry: {"en": ..., "sv": ...}; ``{v}`` is the value.
_STRINGS: dict[str, dict[str, str]] = {
    "confirm_q": {
        "en": "Apply this change to the assistant?",
        "sv": "Vill du tillämpa den här ändringen på assistenten?",
    },
    "cancelled": {
        "en": "Change cancelled by the user.",
        "sv": "Ändringen avbröts av användaren.",
    },
    "ask_declined": {
        "en": "(The user declined to answer; ask again or stop.)",
        "sv": "(Användaren avböjde att svara; fråga igen eller avsluta.)",
    },
    "ask_empty": {
        "en": "(The user submitted an empty answer.)",
        "sv": "(Användaren skickade ett tomt svar.)",
    },
    "capability_failed": {
        "en": "The change could not be completed: {v}",
        "sv": "Ändringen kunde inte slutföras: {v}",
    },
}


def _t(lang: str, key: str, value: Any = "") -> str:
    entry = _STRINGS[key]
    template = entry.get(lang) or entry["en"]
    return template.format(v=value)


class _ConfirmChange(BaseModel):
    """Empty schema: the elicitation is a pure confirm (accept/decline)."""


async def _confirm_capability(
    ctx: Context, capability: "ConfigCapability", inp: BaseModel
) -> bool:
    """Ask the user to confirm a mutating capability via MCP elicitation.

    Returns True only if the user explicitly accepts. Runs before any DB work so
    we never hold a transaction open while waiting on the user.
    """
    lang = _lang_from_ctx(ctx)
    template = (
        capability.confirm_summary_sv
        if lang == "sv" and capability.confirm_summary_sv
        else capability.confirm_summary_en
    ) or capability.title(lang)
    try:
        summary = template.format(**inp.model_dump())
    except Exception:
        summary = template
    message = f"{_t(lang, 'confirm_q')}\n\n{summary}"
    result = await ctx.elicit(message=message, schema=_ConfirmChange)
    return getattr(result, "action", None) == "accept"


def _cancelled(ctx: Context) -> str:
    """Localized 'change cancelled' message returned by a declined tool."""
    return _t(_lang_from_ctx(ctx), "cancelled")


def _failure_reason(exc: Exception) -> str:
    """Concise, human-readable reason from a capability/provider failure.

    Keeps the message short and free of stack noise: domain exceptions already
    carry a clear message; for everything else fall back to the type so the user
    sees something actionable rather than an empty string.
    """
    reason = str(exc).strip()
    if not reason:
        return exc.__class__.__name__
    return reason.splitlines()[0][:300]


async def _ask(ctx: Context, question: str, suggestions: list[str]) -> str:
    """Ask the user a free-text question (with optional suggestions) via elicitation."""
    extra: dict[str, Any] = {"suggestions": suggestions} if suggestions else {}
    answer_field = Field(
        default="",
        description="The user's answer.",
        json_schema_extra=extra,
    )
    schema = create_model("UserAnswer", answer=(str, answer_field))
    lang = _lang_from_ctx(ctx)
    result = await ctx.elicit(message=question, schema=schema)
    if getattr(result, "action", None) != "accept":
        return _t(lang, "ask_declined")
    data = getattr(result, "data", None)
    answer = getattr(data, "answer", "") if data is not None else ""
    return answer.strip() or _t(lang, "ask_empty")


# --------------------------------------------------------------------------- #
# Tools — one generated per registered capability, plus the ask_user interaction
# --------------------------------------------------------------------------- #
@mcp.tool(title="Ask the user")
async def ask_user(
    question: str,
    ctx: Context,
    suggestions: list[str] | None = None,
) -> str:
    """Ask the user a clarifying question when their request is ambiguous."""
    return await _ask(ctx, question, suggestions or [])


def _register_capability_tool(capability: "ConfigCapability") -> None:
    """Register one FastMCP tool that drives a registry capability.

    The tool's schema is derived from the capability's Pydantic input model
    (the single source of truth shared with the future form plane). The body
    confirms mutating changes via elicitation, then runs the capability inside a
    user-bound, permission-checked, audited context.
    """
    model = capability.input_model
    tool_name = capability.id.replace(".", "_")

    async def _impl(ctx: Context, **kwargs: Any):
        # Any failure here (bad args, permission, a downstream/provider error)
        # must come back as a normal tool result. If it escaped, the proxy would
        # surface a generic "Error executing tool." at best, and the edit-mode
        # stream could be left spinning with no actionable message at worst.
        try:
            inp = model(**kwargs)
            if capability.mutating and capability.confirm:
                if not await _confirm_capability(ctx, capability, inp):
                    return _cancelled(ctx)
            async with capability_context(_bearer_from_ctx(ctx)) as cctx:
                result = await run_capability(capability, cctx, inp)
        except Exception as exc:  # noqa: BLE001 - surface, never escape
            logger.warning("Config capability %s failed: %s", capability.id, exc)
            return _t(_lang_from_ctx(ctx), "capability_failed", _failure_reason(exc))
        if result.summary:
            return result.summary
        return result.data if result.data is not None else "Done."

    # Build the visible signature from the input model so FastMCP derives the
    # tool's JSON schema; ctx is injected by the SDK and excluded from the schema.
    params = [
        inspect.Parameter(
            "ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context
        )
    ]
    for fname, finfo in model.model_fields.items():
        if finfo.is_required():
            params.append(
                inspect.Parameter(
                    fname, inspect.Parameter.KEYWORD_ONLY, annotation=finfo.annotation
                )
            )
        else:
            params.append(
                inspect.Parameter(
                    fname,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=finfo.annotation,
                    default=finfo.default,
                )
            )
    _impl.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    _impl.__name__ = tool_name
    _impl.__doc__ = capability.description
    mcp.tool(
        name=tool_name, title=capability.title_en, description=capability.description
    )(_impl)


for _capability in CAPABILITY_REGISTRY.values():
    _register_capability_tool(_capability)


# --------------------------------------------------------------------------- #
# ASGI app + lifespan + ephemeral-server builder
# --------------------------------------------------------------------------- #
# Build the Streamable-HTTP ASGI app eagerly so ``mcp.session_manager`` exists
# for the lifespan below. Mounted at "/internal-mcp"; its own route is "/mcp",
# so the full loopback URL is "<base>/internal-mcp/mcp".
config_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def config_mcp_lifespan():
    """Run the Streamable-HTTP session manager for the lifetime of the app.

    Mounted sub-apps do not get their lifespan invoked by Starlette, so the
    parent app's lifespan must drive the session manager's task group.
    """
    async with mcp.session_manager.run():
        yield


def _localized_title(title: str | None, lang: str) -> str | None:
    """Swap an English tool title for its localized form when one exists."""
    if not title or lang == "en":
        return title
    return _TITLES.get(title, {}).get(lang, title)


async def _config_tool_entities(server_id: UUID, lang: str) -> list[MCPServerTool]:
    """Derive entity-side tool definitions from the live FastMCP tool list.

    The MCP proxy builds its registry from ``server.tools`` (not a live
    discovery), so these must mirror what the endpoint actually exposes. Deriving
    them from ``mcp.list_tools()`` keeps the two in sync automatically.
    """
    tools = await mcp.list_tools()
    cap_by_tool = {
        cap.id.replace(".", "_"): cap for cap in CAPABILITY_REGISTRY.values()
    }
    entities: list[MCPServerTool] = []
    for tool in tools:
        cap = cap_by_tool.get(tool.name)
        title = (
            cap.title(lang)
            if cap is not None
            else _localized_title(getattr(tool, "title", None), lang)
        )
        entities.append(
            MCPServerTool(
                mcp_server_id=server_id,
                name=tool.name,
                title=title,
                description=tool.description,
                input_schema=tool.inputSchema,
                is_enabled_by_default=True,
            )
        )
    return entities


async def build_config_mcp_server(
    *, token: str, tenant_id: UUID, language: str | None = None
) -> MCPServer:
    """Build the ephemeral MCP server eneo attaches to a completion in edit mode."""
    settings = get_settings()
    server_id = uuid4()
    tools = await _config_tool_entities(server_id, _normalize_lang(language))
    return MCPServer(
        id=server_id,
        tenant_id=tenant_id,
        name=CONFIG_SERVER_NAME,
        description="Loopback server for configuring this assistant in edit mode.",
        http_url=f"{settings.internal_mcp_base_url.rstrip('/')}/internal-mcp/mcp",
        http_auth_type="bearer",
        http_auth_config_schema={"token": token},
        is_enabled=True,
        tools=tools,
    )

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

Phase 1 substrate: two capability tools (``get_assistant_settings`` read,
``set_name`` mutating + confirm) plus ``ask_user``. Later phases generate tools
from the capability registry instead of hand-writing them here.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import jwt
from dependency_injector import providers
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field, create_model

from intric.database.database import sessionmanager
from intric.main.config import get_settings
from intric.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool

logger = logging.getLogger(__name__)

# Name of the ephemeral MCP server eneo attaches in edit mode. The MCP proxy
# prefixes tools with a sanitized form of this (``assistant_config__set_name``).
CONFIG_SERVER_NAME = "assistant-config"

CONFIG_PERSONA_PROMPT = (
    "You are the configuration assistant for one specific Eneo assistant. "
    "The user is an administrator editing that assistant's settings. Treat every "
    "message as an instruction to inspect or change THIS assistant's "
    "configuration, and use the provided tools to do so.\n\n"
    "Call get_assistant_settings first when you need the current values. When a "
    "request is ambiguous or underspecified, do NOT guess and do NOT just write a "
    "question as text: call ask_user with a single specific question and a few "
    "concrete suggestions.\n\n"
    "Every changing tool (e.g. set_name) asks the user to confirm before it "
    "applies, so you do not need a separate yes/no message first: state plainly "
    "what you are about to change (old value and new value), then call the tool. "
    "The user is shown a confirmation dialog; if they decline, the tool reports "
    "the change was cancelled, so relay that and do not retry unless asked. Change "
    "only what the user asked for, one thing at a time. After a change applies, "
    "briefly confirm what changed. If a change is rejected because the user lacks "
    "permission, relay that plainly. Do not invent settings or values."
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


def _assistant_id_from_token(token: str) -> UUID:
    settings = get_settings()
    claims = jwt.decode(
        token,
        key=str(settings.jwt_secret),
        audience=settings.jwt_audience,
        algorithms=[settings.jwt_algorithm],
    )
    raw = claims.get("assistant_id")
    if not raw:
        raise ValueError("Access token is not scoped to an assistant.")
    return UUID(str(raw))


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


# Human-readable tool titles per locale (English keys mirror the @mcp.tool titles).
_TITLES: dict[str, dict[str, str]] = {
    "Read assistant settings": {"sv": "Läs assistentinställningar"},
    "Set name": {"sv": "Sätt namn"},
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
    "sum_name": {"en": "set the name to '{v}'", "sv": "ändra namnet till '{v}'"},
}


def _t(lang: str, key: str, value: Any = "") -> str:
    entry = _STRINGS[key]
    template = entry.get(lang) or entry["en"]
    return template.format(v=value)


@asynccontextmanager
async def _config_context(ctx: Context):
    """Bootstrap a user-bound container for the token's user + assistant.

    Yields ``(container, assistant_id)``. The container is bound to the
    authenticated user, so every ``assistant_service`` call runs the normal
    ``SpaceActor`` permission checks. The surrounding transaction commits on
    clean exit and rolls back on error (e.g. a permission failure).
    """
    # Imported lazily: the Container pulls in the whole service graph (including
    # assistant_service, which imports this module), so a top-level import would
    # create a cycle.
    from intric.main.container.container import Container
    from intric.main.container.container_overrides import override_user

    token = _bearer_from_ctx(ctx)
    assistant_id = _assistant_id_from_token(token)
    async with sessionmanager.session() as session:
        async with session.begin():
            container = Container(session=providers.Object(session))
            user = await container.user_service().authenticate(token=token)
            override_user(container=container, user=user)
            yield container, assistant_id


class _ConfirmChange(BaseModel):
    """Empty schema: the elicitation is a pure confirm (accept/decline)."""


async def _confirm(ctx: Context, summary_key: str, value: Any = "") -> bool:
    """Ask the user to confirm a change via MCP elicitation (localized).

    Returns True only if the user explicitly accepts. Runs before any DB work so
    we never hold a transaction open while waiting on the user.
    """
    lang = _lang_from_ctx(ctx)
    message = f"{_t(lang, 'confirm_q')}\n\n{_t(lang, summary_key, value)}"
    result = await ctx.elicit(message=message, schema=_ConfirmChange)
    return getattr(result, "action", None) == "accept"


def _cancelled(ctx: Context) -> str:
    """Localized 'change cancelled' message returned by a declined tool."""
    return _t(_lang_from_ctx(ctx), "cancelled")


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
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool(title="Read assistant settings")
async def get_assistant_settings(ctx: Context) -> dict:
    """Return the current configurable settings of this assistant."""
    async with _config_context(ctx) as (container, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)
        model = assistant.completion_model
        return {
            "name": assistant.name,
            "prompt": assistant.get_prompt_text(),
            "completion_model": (
                {"id": str(model.id), "name": model.name} if model is not None else None
            ),
            "description": assistant.description,
            "insight_enabled": assistant.insight_enabled,
            "published": assistant.published,
        }


@mcp.tool(title="Set name")
async def set_name(name: str, ctx: Context) -> str:
    """Set the assistant's display name."""
    if not await _confirm(ctx, "sum_name", name):
        return _cancelled(ctx)
    async with _config_context(ctx) as (container, assistant_id):
        assistant, _ = await container.assistant_service().update_assistant(
            assistant_id=assistant_id, name=name
        )
        return f"Name set to '{assistant.name}'."


@mcp.tool(title="Ask the user")
async def ask_user(
    question: str,
    ctx: Context,
    suggestions: list[str] | None = None,
) -> str:
    """Ask the user a clarifying question when their request is ambiguous."""
    return await _ask(ctx, question, suggestions or [])


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
    return [
        MCPServerTool(
            mcp_server_id=server_id,
            name=tool.name,
            title=_localized_title(getattr(tool, "title", None), lang),
            description=tool.description,
            input_schema=tool.inputSchema,
            is_enabled_by_default=True,
        )
        for tool in tools
    ]


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

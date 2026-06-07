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
from intric.main.config import Settings, get_settings
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


# Localized persona blocks. ``base`` is always emitted; exactly one ``route_*``
# clause is chosen from the deployment's knowledge settings; ``naming`` +
# ``two_step`` are added only when an external provider is configured.
_PERSONA: dict[str, dict[str, str]] = {
    "en": {
        "base": (
            "You are the configuration assistant for one specific Eneo assistant. "
            "The user is an administrator editing that assistant and its space. Treat "
            "every message as an instruction to inspect or change this assistant's "
            "configuration or its space's knowledge, and use the provided tools to do "
            "so. Available actions include reading the assistant's settings, renaming "
            "it, adding knowledge to the space, and attaching knowledge to the "
            "assistant.\n\n"
            "Read the current settings (assistant_get_settings), list space knowledge "
            "(space_list_collections), or list the space's knowledge sources and MCP "
            "servers (space_list_mcp_servers) first when you need current values. When "
            "a request is ambiguous or underspecified, do NOT guess and do NOT just "
            "write a question as text: call ask_user with a single specific question "
            "and a few concrete suggestions.\n\n"
            "Every changing tool asks the user to confirm before it applies, so you do "
            "not need a separate yes/no message first: state plainly what you are about "
            "to change, then call the tool. If they decline, the tool reports the change "
            "was cancelled, so relay that and do not retry unless asked. Change only "
            "what the user asked for, one thing at a time. After a change applies, "
            "briefly confirm what changed. If a change is rejected because the user "
            "lacks permission, relay that plainly. Do not invent settings or values."
        ),
        "route_external_only": (
            "\n\nKnowledge routing: native collections are disabled on this deployment. "
            "Any request for a collection, knowledge, or source (English "
            "collection/knowledge/source; Swedish samling/kunskap/källa/kunskapskälla) "
            "means an external knowledge source: use knowledge_source_create. Never use "
            "collection_create."
        ),
        "route_prefer_external": (
            "\n\nKnowledge routing: both native collections and external knowledge "
            "sources exist. Prefer the external knowledge source: map a request for a "
            "collection, knowledge, or source (English collection/knowledge/source; "
            "Swedish samling/kunskap/källa/kunskapskälla) to knowledge_source_create, "
            "unless the user explicitly asks for a native collection."
        ),
        "route_native_only": (
            "\n\nKnowledge routing: no external knowledge provider is configured. A "
            "request for a collection or knowledge (English collection/knowledge; "
            "Swedish samling/kunskap) maps to collection_create."
        ),
        "naming": (
            "\n\nNaming: refer to an external knowledge source, when speaking to the "
            "user, as a 'knowledge source' (Swedish 'kunskapskälla'), never as an 'MCP "
            "server'. The is_knowledge_source flag from space_list_mcp_servers tells you "
            "which space servers are knowledge sources."
        ),
        "two_step": (
            "\n\nAttaching a new knowledge source to THIS assistant is two tool calls "
            "done as one action: first knowledge_source_create (creates it in the "
            "space), then assistant_set_mcp_server with enabled=true and the returned "
            "mcp_server_id (enables it on this assistant). Creating a source does not by "
            "itself attach it here; do both unless the user only asked to create it in "
            "the space."
        ),
    },
    "sv": {
        "base": (
            "Du är konfigurationsassistenten för en specifik Eneo-assistent. Användaren "
            "är en administratör som redigerar den assistenten och dess utrymme. "
            "Behandla varje meddelande som en instruktion att granska eller ändra denna "
            "assistents konfiguration eller dess utrymmes kunskap, och använd de "
            "tillhandahållna verktygen för att göra det. Tillgängliga åtgärder är att "
            "läsa assistentens inställningar, byta namn på den, lägga till kunskap i "
            "utrymmet och koppla kunskap till assistenten.\n\n"
            "Läs de aktuella inställningarna (assistant_get_settings), lista utrymmets "
            "kunskap (space_list_collections) eller lista utrymmets kunskapskällor och "
            "MCP-servrar (space_list_mcp_servers) först när du behöver aktuella värden. "
            "När en begäran är tvetydig eller otillräckligt specificerad: gissa INTE och "
            "skriv INTE bara en fråga som text – anropa ask_user med en enda specifik "
            "fråga och några konkreta förslag.\n\n"
            "Varje ändrande verktyg ber användaren bekräfta innan det tillämpas, så du "
            "behöver inte ett separat ja/nej-meddelande först: ange tydligt vad du är på "
            "väg att ändra och anropa sedan verktyget. Om de avböjer rapporterar "
            "verktyget att ändringen avbröts – vidarebefordra det och försök inte igen "
            "om du inte ombeds. Ändra endast det användaren bett om, en sak i taget. När "
            "en ändring tillämpats, bekräfta kort vad som ändrades. Om en ändring nekas "
            "för att användaren saknar behörighet, vidarebefordra det tydligt. Hitta "
            "inte på inställningar eller värden."
        ),
        "route_external_only": (
            "\n\nKunskapsrouting: inbyggda samlingar är inaktiverade i denna "
            "installation. Varje begäran om en samling, kunskap eller källa (engelska "
            "collection/knowledge/source; svenska samling/kunskap/källa/kunskapskälla) "
            "avser en extern kunskapskälla: använd knowledge_source_create. Använd "
            "aldrig collection_create."
        ),
        "route_prefer_external": (
            "\n\nKunskapsrouting: både inbyggda samlingar och externa kunskapskällor "
            "finns. Föredra den externa kunskapskällan: mappa en begäran om en samling, "
            "kunskap eller källa (engelska collection/knowledge/source; svenska "
            "samling/kunskap/källa/kunskapskälla) till knowledge_source_create, om inte "
            "användaren uttryckligen ber om en inbyggd samling."
        ),
        "route_native_only": (
            "\n\nKunskapsrouting: ingen extern kunskapsleverantör är konfigurerad. En "
            "begäran om en samling eller kunskap (engelska collection/knowledge; svenska "
            "samling/kunskap) mappas till collection_create."
        ),
        "naming": (
            "\n\nNamngivning: hänvisa till en extern kunskapskälla, när du talar med "
            "användaren, som en 'kunskapskälla', aldrig som en 'MCP-server'. Flaggan "
            "is_knowledge_source från space_list_mcp_servers visar vilka servrar i "
            "utrymmet som är kunskapskällor."
        ),
        "two_step": (
            "\n\nAtt koppla en ny kunskapskälla till DENNA assistent är två "
            "verktygsanrop som görs som en åtgärd: först knowledge_source_create (skapar "
            "den i utrymmet), sedan assistant_set_mcp_server med enabled=true och det "
            "returnerade mcp_server_id (aktiverar den på denna assistent). Att skapa en "
            "källa kopplar den inte automatiskt här; gör båda om inte användaren bara "
            "bad om att skapa den i utrymmet."
        ),
    },
}


def build_config_persona(language: str | None, settings: Settings) -> str:
    """Build the edit-mode system persona, localized and aware of knowledge config.

    The routing clause is chosen from whether an external knowledge provider is
    configured and whether native collections are disabled, so the model steers
    collection/knowledge/samling/kunskap requests to the right capability and
    refers to external sources as "knowledge sources", not "MCP servers".
    """
    lang = _normalize_lang(language)
    blocks = _PERSONA.get(lang) or _PERSONA["en"]
    external_configured = bool(
        settings.external_knowledge_provider_url
        and settings.external_knowledge_provider_api_key
    )
    native_disabled = settings.collections_require_external_provider

    if external_configured and native_disabled:
        route = blocks["route_external_only"]
    elif external_configured:
        route = blocks["route_prefer_external"]
    else:
        route = blocks["route_native_only"]

    parts = [blocks["base"], route]
    if external_configured:
        parts.append(blocks["naming"])
        parts.append(blocks["two_step"])
    return "".join(parts)


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

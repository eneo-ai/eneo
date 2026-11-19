"""The assistant settings tools: they reach only the assistant of the chat
their token was minted for, read in pages, and never give the model a
credential."""

from __future__ import annotations

import inspect
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from dependency_injector import providers
from pydantic import ValidationError

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.api.assistant_models import AssistantUpdatePublic, KnowledgeMode
from eneo.assistants.application import (
    assistant_publish_operation,
    assistant_update_operation,
)
from eneo.assistants.application.assistant_helper_chat import ASSISTANT_TARGET
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.document_templates.domain import DocumentTemplateChoice
from eneo.helper_chats.application import helper_chat_service
from eneo.internal_mcp import assistant_settings
from eneo.internal_mcp.assistant_settings import (
    AssistantReading,
    SpaceOffer,
    assistant_lines,
    option_lines,
    page_lines,
)
from eneo.internal_mcp.foundation import ToolContext
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import ResourcePermission
from eneo.mcp_servers.domain.capabilities import CapabilityAvailability
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    MCPServer,
    MCPServerTool,
)
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    STRUCTURED_CONTENT_MAX_BYTES,
)

_SERVER_TOKEN = "server-token-1f2e3d"
_URL_KEY = "url-key-9a8b7c"
_SITE_PASSWORD = "site-password-5d4c"


def _server(**overrides) -> MCPServer:
    server_id = uuid4()
    values = {
        "id": server_id,
        "tenant_id": uuid4(),
        "name": "Ärendesystemet",
        "description": "Läser och skapar ärenden.",
        "http_url": f"https://cases.example.org/mcp?key={_URL_KEY}",
        "http_auth_type": "bearer",
        "http_auth_config_schema": {"token": _SERVER_TOKEN},
        "env_vars": {"API_TOKEN": _SERVER_TOKEN},
        "tools": [
            MCPServerTool(mcp_server_id=server_id, name="search_cases", id=uuid4()),
            MCPServerTool(mcp_server_id=server_id, name="create_case", id=uuid4()),
        ],
    }
    values.update(overrides)
    return MCPServer(**values)


def _model() -> SimpleNamespace:
    offered = SupportedModelKwargs(
        reasoning_effort=ModelKwargCapability(
            supported=True, control="select", options=["low", "medium", "high"]
        )
    )
    return SimpleNamespace(
        id=uuid4(),
        name="model-large",
        nickname="Stor modell",
        max_input_tokens=128_000,
        supports_tool_calling=True,
        reasoning=True,
        vision=False,
        input_cost_per_token=0.000002,
        output_cost_per_token=0.000008,
        hosting="eu",
        is_deprecated=False,
        get_supported_model_kwargs=lambda: offered,
        supported_model_kwargs=offered,
        can_access=True,
    )


def _assistant(server: MCPServer) -> SimpleNamespace:
    space_id = uuid4()
    disabled = server.tools[1]
    return SimpleNamespace(
        id=uuid4(),
        space_id=space_id,
        name="Ärendehjälpen",
        description="Hjälper handläggare.",
        published=True,
        is_default=False,
        insight_enabled=True,
        logging_enabled=False,
        data_retention_days=None,
        completion_model=_model(),
        completion_model_kwargs=ModelKwargs(reasoning_effort="medium"),
        get_prompt_text=lambda: "Du är ärendehjälpen.\nSvara kort.",
        knowledge_mode=KnowledgeMode.TOOL,
        collections=[SimpleNamespace(id=uuid4(), name="Rutiner", space_id=space_id)],
        websites=[
            SimpleNamespace(
                id=uuid4(),
                name="Intranätet",
                url=f"https://reader:{_SITE_PASSWORD}@intra.example.org/docs?sig=abc",
                space_id=uuid4(),
            )
        ],
        integration_knowledge_list=[],
        rerank_model_id=None,
        inline_file_text=False,
        attachments=[SimpleNamespace(id=uuid4(), name="mall.docx")],
        attachment_inline_text={},
        mcp_servers=[server],
        mcp_tools=[(disabled.id, False)],
        enabled_capabilities=["file_creation"],
        available_capabilities=[
            CapabilityAvailability(purpose="file_creation", available=True)
        ],
        document_template=DocumentTemplateChoice(),
    )


def _reading(effective_config=None) -> AssistantReading:
    return AssistantReading(
        assistant=_assistant(_server()),
        permissions=[ResourcePermission.EDIT, ResourcePermission.PUBLISH],
        effective_config=effective_config,
        show_pricing=True,
    )


def _policy(**overrides) -> SimpleNamespace:
    values = {
        "prompt_enforced": True,
        "models_enforced": True,
        "locked_model": SimpleNamespace(name="model-small", nickname="Liten modell"),
        "available_models": [],
        "reasoning_policy_configured": True,
        "reasoning_effort_user_configurable": False,
        "mcp_enforced": True,
        "inline_file_text": True,
        "available_mcp_servers": [],
        "enabled_capabilities": [],
        "available_capabilities": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _text(lines: list[str]) -> str:
    return "\n".join(lines)


def test_every_section_reads_the_assistant_without_a_credential():
    reading = _reading()

    everything = _text(assistant_lines(reading, "all"))

    for secret in (_SERVER_TOKEN, _URL_KEY, _SITE_PASSWORD, "sig=abc", "reader"):
        assert secret not in everything
    assert "cases.example.org" not in everything
    # What the editor shows is there.
    assert "Ärendesystemet" in everything
    assert "create_case (off), search_cases (on)" in everything
    assert "intra.example.org/docs" in everything
    assert "(organisation knowledge)" in everything
    assert "Du är ärendehjälpen." in everything


def test_the_sections_say_what_the_editor_shows():
    reading = _reading()

    overview = _text(assistant_lines(reading, "overview"))
    assert "Name: Ärendehjälpen" in overview
    assert "Published: yes" in overview
    assert "Chat model: Stor modell" in overview
    assert "The person may: edit, publish" in overview
    assert "Locked by an organisation policy: nothing" in overview

    model = _text(assistant_lines(reading, "model"))
    assert "context window: 128,000 tokens" in model
    assert "reasoning efforts: low, medium, high" in model
    assert "price per million tokens: input $2.00, output $8.00" in model
    assert "reasoning effort: medium" in model

    knowledge = _text(assistant_lines(reading, "knowledge"))
    assert "the assistant searches its knowledge when it needs to" in knowledge
    assert "Files uploaded in a chat: looked up when needed" in knowledge
    assert "- mall.docx: always in the prompt" in knowledge

    tools = _text(assistant_lines(reading, "tools"))
    assert (
        '- "Skapa fil" [file_creation]: lets the assistant create Word, PDF and '
        "Excel files"
    ) in tools
    assert "can be used as the base; ready" in tools
    assert "Document template: the organisation's default" in tools

    access = _text(assistant_lines(reading, "access"))
    assert "Insights: on" in access
    assert "Conversation retention: follows the space, then the organisation" in (
        access
    )


def test_prices_are_left_out_for_a_person_who_may_not_see_them():
    reading = AssistantReading(
        assistant=_assistant(_server()),
        permissions=[],
        effective_config=None,
        show_pricing=False,
    )

    assert "price" not in _text(assistant_lines(reading, "model"))


def test_what_a_policy_locks_is_named_where_it_applies():
    reading = _reading(_policy())

    overview = _text(assistant_lines(reading, "overview"))
    assert "- instructions: set by the policy" in overview
    assert "- chat model: locked to Liten modell" in overview
    assert "- reasoning effort: set by the policy" in overview
    assert "- MCP servers and functions: set by the policy" in overview
    instructions = _text(assistant_lines(reading, "instructions"))
    assert instructions.startswith("Locked: an organisation policy sets")
    assert "set by an organisation policy" in _text(
        assistant_lines(reading, "knowledge")
    )
    assert "chat model: locked" in _text(assistant_lines(reading, "model"))


def test_an_unknown_section_is_refused():
    with pytest.raises(BadRequestException):
        assistant_lines(_reading(), "secrets")


def test_a_long_read_is_paged_without_losing_a_line(monkeypatch):
    monkeypatch.setattr(assistant_settings, "default_page_cap", lambda: 1600)
    lines = [f"line {number}: " + "x" * 120 for number in range(60)]
    assistant_id = uuid4()
    collected: list[str] = []
    offset = 0
    while True:
        result = page_lines(
            lines,
            tool="read_assistant",
            section="instructions",
            offset=offset,
            assistant_id=assistant_id,
        )
        text = result.content[0].text
        assert len(text) <= 1600
        body = text.split("\n", 1)[1].split("\n\nMore follows.")[0]
        collected += body.split("\n")
        next_offset = result.structuredContent["next_offset"]
        if next_offset is None:
            assert "More follows" not in text
            break
        assert f"offset={next_offset}" in text
        offset = next_offset
    assert collected == lines
    with pytest.raises(BadRequestException):
        page_lines(
            lines,
            tool="read_assistant",
            section="instructions",
            offset=len(lines),
            assistant_id=assistant_id,
        )


def test_a_very_long_line_is_cut_into_lines_that_fit_a_page():
    assert assistant_settings._wrapped("a" * 2500) == [  # pyright: ignore[reportPrivateUsage]
        "a" * 1000,
        "a" * 1000,
        "a" * 500,
    ]


def _offer(effective_config=None) -> SpaceOffer:
    usable = _model()
    other = _model()
    other.nickname = "Annan modell"
    space_id = uuid4()
    organisation_id = uuid4()
    embedding = SimpleNamespace(id=uuid4())
    server = {
        "id": str(uuid4()),
        "name": "Ärendesystemet",
        "description": "Läser ärenden.",
        "http_url": f"https://cases.example.org/mcp?key={_URL_KEY}",
        "http_auth_type": "bearer",
        "is_enabled": True,
        "tools": [{"name": "search_cases", "display_name": None}],
    }

    def items(*entries):
        return SimpleNamespace(items=list(entries))

    space = SimpleNamespace(
        id=space_id,
        organization_space_id=organisation_id,
        completion_models=[usable, other],
        embedding_models=[embedding],
        knowledge=SimpleNamespace(
            groups=items(
                SimpleNamespace(
                    id=uuid4(),
                    name="Rutiner",
                    space_id=organisation_id,
                    embedding_model=embedding,
                ),
                SimpleNamespace(
                    id=uuid4(),
                    name="Gamla rutiner",
                    space_id=space_id,
                    embedding_model=SimpleNamespace(id=uuid4()),
                ),
            ),
            websites=items(),
            integration_knowledge_list=items(),
        ),
        mcp_servers=[server],
        enabled_capabilities=["charts"],
        available_capabilities=[
            CapabilityAvailability(
                purpose="charts", available=False, reason="no_active_provider"
            )
        ],
    )
    return SpaceOffer(
        space=space,
        below_classification=[SimpleNamespace(name="open", nickname="Öppen modell")],
        default_model_id=usable.id,
        current_model_id=other.id,
        effective_config=effective_config,
        show_pricing=False,
        rerank_models=[
            SimpleNamespace(
                id=uuid4(),
                name="ranker",
                nickname="Rankaren",
                can_access=True,
                meets_security_classification=True,
            ),
            SimpleNamespace(
                id=uuid4(),
                name="hidden",
                nickname="Spärrad",
                can_access=True,
                meets_security_classification=False,
            ),
        ],
        document_templates=[
            SimpleNamespace(id=uuid4(), name="Kommunmall", is_default=True)
        ],
    )


def test_the_options_say_what_the_space_offers():
    offer = _offer()

    models = _text(option_lines(offer, "model"))
    assert "Stor modell" in models and "(the space's default)" in models
    assert "Annan modell" in models and "(in use now)" in models
    assert "below its security classification" in models and "Öppen modell" in models
    assert "price" not in models

    knowledge = _text(option_lines(offer, "knowledge"))
    assert "Rutiner" in knowledge and "organisation knowledge" in knowledge
    assert "its embedding model is not enabled in the space" in knowledge
    assert "Rankaren" in knowledge and "Spärrad" not in knowledge

    tools = _text(option_lines(offer, "tools"))
    assert "Ärendesystemet" in tools and "search_cases" in tools
    assert '- "Diagram" [charts]: lets the assistant compare values' in tools
    assert (
        "; cannot be turned on: no source is active (an administrator configures "
        'its sources under "Verktyg" > "Funktioner")'
    ) in tools
    assert "Kommunmall" in tools and "(the organisation's default)" in tools
    assert _URL_KEY not in _text(option_lines(offer, "all"))
    assert "cases.example.org" not in _text(option_lines(offer, "all"))


def test_options_a_policy_decides_are_the_policys():
    offer = _offer(
        _policy(
            available_models=[SimpleNamespace(id=uuid4())],
            available_mcp_servers=[_server(name="Policyservern")],
            enabled_capabilities=["compute"],
            available_capabilities=[
                CapabilityAvailability(purpose="compute", available=True)
            ],
        )
    )

    models = _text(option_lines(offer, "model"))
    assert "Chat models the space offers (0)" in models
    assert "chat model: locked to Liten modell" in models
    tools = _text(option_lines(offer, "tools"))
    assert "the organisation's policy gives (1)" in tools
    assert "Policyservern" in tools and "Ärendesystemet" not in tools
    # Only the policy's functions, with their sources' readiness.
    assert "Functions the organisation's policy gives (1):" in tools
    assert '- "Beräkning" [compute]: lets the assistant run exact arithmetic' in tools
    assert "spreadsheets and documents; ready" in tools
    assert "[charts]" not in tools
    assert _SERVER_TOKEN not in tools and _URL_KEY not in tools


# --- The editor's names ------------------------------------------------------

# The same table, in the same order, as the editor's functions (CAPABILITIES in
# frontend/apps/web-next/src/features/capabilities/capabilities.ts, named and
# described by its messages), whose test in
# frontend/apps/web-next/src/features/assistants/editor/setting-references.test.ts
# holds the editor to this one: change both together.
EDITOR_FUNCTIONS = (
    (
        "web_search",
        "Webbsökning",
        "Lets the assistant search the web via the organisation's search engine.",
    ),
    (
        "image_generation",
        "Bildgenerering",
        "Lets the assistant generate images via the organisation's image generator.",
    ),
    (
        "file_analysis",
        "Fråga fil",
        "Lets the assistant calculate totals, compare and join attached CSV and "
        "Excel files instead of reading them as text.",
    ),
    (
        "file_creation",
        "Skapa fil",
        "Lets the assistant create Word, PDF and Excel files that the user can "
        "download from the conversation. A Word template attached in the chat or "
        "to the assistant can be used as the base.",
    ),
    (
        "charts",
        "Diagram",
        "Lets the assistant compare values and show trends with bar, line, pie "
        "and scatter charts. Eneo’s provider shows interactive charts and can "
        "export images when requested.",
    ),
    (
        "compute",
        "Beräkning",
        "Lets the assistant run exact arithmetic, statistics, date and text "
        "calculations in an isolated sandbox instead of estimating. Results can "
        "be shown as a table and exported as CSV for charts, spreadsheets and "
        "documents.",
    ),
)

_FRAGA_FIL = (
    '- "Fråga fil" [file_analysis]: lets the assistant calculate totals, compare '
    "and join attached CSV and Excel files instead of reading them as text"
)
_WEB_SEARCH = (
    '- "Webbsökning" [web_search]: lets the assistant search the web via the '
    "organisation's search engine"
)
_TURNED_OFF = (
    "turned off in the space's settings (someone who may edit the space turns "
    'it on there, under "Funktioner")'
)


def test_the_tools_name_and_describe_every_function_as_the_editor_does():
    assert assistant_settings.FUNCTIONS == EDITOR_FUNCTIONS
    assert tuple(key for key, _, _ in EDITOR_FUNCTIONS) == CAPABILITY_PURPOSES


def test_read_options_lists_every_function_and_why_one_cannot_be_turned_on():
    offer = replace(
        _offer(),
        function_availability=[
            CapabilityAvailability(purpose="file_analysis", available=True),
            CapabilityAvailability(
                purpose="charts", available=False, reason="permission"
            ),
        ],
    )
    offer.space.enabled_capabilities = ["file_analysis", "charts"]

    tools = option_lines(offer, "tools")

    assert 'Functions (6), as the editor lists them under "Funktioner":' in tools
    assert f"{_FRAGA_FIL}; ready" in tools
    # One the space has turned off is listed with the editor's reason and who
    # changes it, where.
    assert f"{_WEB_SEARCH}; cannot be turned on: {_TURNED_OFF}" in tools
    # A source's readiness is the person's, as the editor reads it.
    charts = next(line for line in tools if "[charts]" in line)
    assert charts.endswith(
        "; cannot be turned on: the person does not have permission to use it "
        "(an administrator gives their role the permission)"
    )
    # A chat model that cannot use tools comes after the space's own switch.
    without = option_lines(replace(offer, answering_model=_without_tools()), "tools")
    assert f"{_WEB_SEARCH}; cannot be turned on: {_TURNED_OFF}" in without
    assert (
        f"{_FRAGA_FIL}; cannot be turned on: the chat model does not support tool "
        'calling (a chat model that does is chosen first, under "Chattmodell")'
    ) in without


def test_read_assistant_names_the_functions_as_the_editor_does():
    reading = _reading()
    reading.assistant.enabled_capabilities = ["file_analysis", "web_search"]
    reading.assistant.available_capabilities = [
        CapabilityAvailability(purpose="file_analysis", available=True),
        CapabilityAvailability(
            purpose="web_search", available=False, reason="space_disabled"
        ),
    ]

    overview = _text(assistant_lines(reading, "overview"))
    tools = assistant_lines(reading, "tools")

    assert (
        'functions: "Fråga fil" [file_analysis], "Webbsökning" [web_search] '
        "(not available: turned off in the space's settings)"
    ) in overview
    assert f"{_FRAGA_FIL}; ready" in tools
    assert f"{_WEB_SEARCH}; on, but not available: {_TURNED_OFF}" in tools
    for key in ("file_analysis", "web_search"):
        assert f"- {key}:" not in _text(tools)


def test_a_saved_chat_model_the_space_no_longer_offers_is_named_as_such():
    note = (
        ' (the space no longer offers it, so the editor shows "Stöds ej vald '
        'modell" under "Chattmodell"; the assistant needs one of the space\'s '
        "models, which read_options lists)"
    )
    reading = replace(_reading(), model_withdrawn_by="space")
    line = f"Chat model: Stor modell [id {reading.assistant.completion_model.id}]"

    assert line + note in assistant_lines(reading, "overview")
    assert line + note in assistant_lines(reading, "model")
    by_policy = _text(
        assistant_lines(replace(reading, model_withdrawn_by="policy"), "overview")
    )
    assert (
        "(an organisation policy does not allow it, so the editor shows "
        '"Stöds ej vald modell" under "Chattmodell"; the assistant needs one of '
        "the models it allows, which read_options lists)"
    ) in by_policy
    assert "Stöds ej" not in _text(assistant_lines(_reading(), "all"))

    offer = replace(
        _offer(), current_model_id=uuid4(), current_model_name="Gammal modell"
    )
    assert (
        "The assistant's saved chat model, Gammal modell, is not among them, so "
        'the editor shows "Stöds ej vald modell" under "Chattmodell": the '
        "assistant needs one of these."
    ) in option_lines(offer, "model")
    assert "Stöds ej" not in _text(option_lines(_offer(), "model"))


def test_who_withholds_a_saved_chat_model_is_read_as_the_editor_lists_models():
    def listed(model, **overrides):
        values = {
            "id": model.id,
            "is_org_enabled": True,
            "migrated_to_model_id": None,
            "deleted_at": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    saved, other = _model(), _model()
    withdrawn_by = assistant_settings._model_withdrawn_by  # pyright: ignore[reportPrivateUsage]

    def space(*models):
        return SimpleNamespace(completion_models=list(models))

    assert withdrawn_by(space(listed(saved)), None, saved) is None
    assert withdrawn_by(space(listed(other)), None, saved) == "space"
    for gone in ({"is_org_enabled": False}, {"deleted_at": datetime.now(UTC)}):
        assert withdrawn_by(space(listed(saved, **gone)), None, saved) == "space"
    allows_other = _policy(available_models=[other], locked_model=None)
    assert withdrawn_by(space(listed(saved)), allows_other, saved) == "policy"
    # A model a policy locks is shown in place of the saved one.
    assert withdrawn_by(space(listed(other)), _policy(), saved) is None
    assert withdrawn_by(space(), None, None) is None


def test_saved_choices_the_space_no_longer_offers_are_named_as_the_editor_shows():
    template_id = uuid4()
    reading = replace(
        _reading(),
        assistant=_assistant(_server(is_enabled=False)),
        rerank_model_name="Rankaren",
        rerank_selectable=False,
        enabled_embedding_models=frozenset({_EMBEDDING.id}),
    )
    assistant = reading.assistant
    assistant.rerank_model_id = _RANKER
    assistant.collections[0].embedding_model = _OTHER_EMBEDDING
    assistant.websites[0].embedding_model = _EMBEDDING
    assistant.document_template = DocumentTemplateChoice(
        mode="selected", template_id=template_id
    )

    knowledge = assistant_lines(reading, "knowledge")
    tools = assistant_lines(reading, "tools")

    routines = assistant.collections[0]
    assert (
        f"- Rutiner [id {routines.id}] (its embedding model is not enabled in the "
        "space)"
    ) in knowledge
    assert (
        "Result ranking: Rankaren (the space can no longer use it, so the editor "
        'shows "Otillgänglig modell" under "Rankning av träffar", and the sources '
        "are searched without it until another is chosen)"
    ) in knowledge
    server = assistant.mcp_servers[0]
    assert (
        f"- Ärendesystemet [id {server.id}] (turned off by an administrator): "
        "Läser och skapar ärenden."
    ) in tools
    assert (
        "Document template: one that is no longer among the organisation's "
        f"templates [id {template_id}], so the documents use the organisation's "
        "default, as the editor shows, until another is chosen"
    ) in tools
    # The website's embedding model is enabled: only its origin is said.
    website = next(line for line in knowledge if "intra.example.org" in line)
    assert website.endswith("(organisation knowledge)")


# --- The chat a call reaches -------------------------------------------------


def _tool_context(container, session_id, assistant_id):
    @asynccontextmanager
    async def context(_ctx, **_):
        yield ToolContext(container, SimpleNamespace(), assistant_id, session_id)

    return context


async def test_a_tool_reaches_the_assistant_only_through_the_tokens_chat(monkeypatch):
    session_id, hidden_id = uuid4(), uuid4()
    chat = SimpleNamespace(target_id=uuid4(), space_id=uuid4())
    load = AsyncMock(return_value=chat)
    monkeypatch.setattr(
        assistant_settings,
        "internal_tool_context",
        _tool_context(MagicMock(), session_id, hidden_id),
    )
    monkeypatch.setattr(helper_chat_service, "load_chat", load)
    reached = []

    async def operation(_container, loaded):
        reached.append(loaded.target_id)
        return page_lines(
            ["read"],
            tool="read_assistant",
            section="overview",
            offset=0,
            assistant_id=loaded.target_id,
        )

    result = await assistant_settings._call(MagicMock(), operation)  # pyright: ignore[reportPrivateUsage]

    assert not result.isError
    assert reached == [chat.target_id]
    assert load.await_args.args[1] is ASSISTANT_TARGET
    assert load.await_args.kwargs == {
        "session_id": session_id,
        "assistant_id": hidden_id,
    }


async def test_a_token_without_a_chat_reaches_no_assistant(monkeypatch):
    monkeypatch.setattr(
        assistant_settings,
        "internal_tool_context",
        _tool_context(MagicMock(), None, uuid4()),
    )
    load = AsyncMock()
    monkeypatch.setattr(helper_chat_service, "load_chat", load)
    operation = AsyncMock()

    result = await assistant_settings._call(MagicMock(), operation)  # pyright: ignore[reportPrivateUsage]

    assert result.isError
    load.assert_not_awaited()
    operation.assert_not_awaited()


async def test_a_chat_that_is_not_the_persons_is_refused_as_text(monkeypatch):
    monkeypatch.setattr(
        assistant_settings,
        "internal_tool_context",
        _tool_context(MagicMock(), uuid4(), uuid4()),
    )
    monkeypatch.setattr(
        helper_chat_service,
        "load_chat",
        AsyncMock(side_effect=NotFoundException("Helper chat not found.")),
    )
    operation = AsyncMock()

    result = await assistant_settings._call(MagicMock(), operation)  # pyright: ignore[reportPrivateUsage]

    assert result.isError
    assert result.content[0].text == "Helper chat not found."
    operation.assert_not_awaited()


def test_no_tool_takes_an_assistant_from_the_model():
    for tool in (assistant_settings.read_assistant, assistant_settings.read_options):
        assert set(inspect.signature(tool).parameters) == {"ctx", "section", "offset"}
    assert set(inspect.signature(assistant_settings.propose_changes).parameters) == {
        "ctx",
        "changes",
    }


async def test_a_turn_reads_proposes_and_publishes_but_never_changes_directly():
    server = await assistant_settings.build_assistant_settings_mcp_server(
        token="t", tenant_id=uuid4()
    )

    assert {tool.name for tool in server.tools} == {
        "read_assistant",
        "read_options",
        "read_prompt_history",
        "propose_changes",
        "publish_assistant",
    }
    for tool in server.tools:
        if tool.name == "publish_assistant":
            # The chat asks the person before each call.
            assert tool.annotations == {"readOnlyHint": False, "destructiveHint": True}
        else:
            assert tool.annotations == {"readOnlyHint": True}
    assert server.name == "assistant"


async def test_the_proposal_tool_says_first_when_to_call_it():
    server = await assistant_settings.build_assistant_settings_mcp_server(
        token="t", tenant_id=uuid4()
    )
    tool = next(tool for tool in server.tools if tool.name == "propose_changes")
    description = " ".join((tool.description or "").split())

    # When to call it comes before what it takes.
    when, takes = description.split("changes holds only these fields", 1)
    assert "Call it whenever the person asks for a setting to be changed" in when
    assert "even a one-word change such as a new name" in when
    # The call is the only thing the person can approve; words are not.
    assert "the only thing the person can approve" in when
    assert "a change described in words gives them nothing to apply" in when
    # Only a change that builds on the current value reads first.
    assert "such as a new name, needs no read first" in when
    assert "such as rewriting the instructions, needs read_assistant first" in when
    assert "Nothing is saved" in when
    assert "A refusal says why and proposes nothing." in takes


# --- Changes -----------------------------------------------------------------


def _offering(**settings: ModelKwargCapability) -> SupportedModelKwargs:
    return SupportedModelKwargs(**settings)


_TEMPERATURE = ModelKwargCapability(
    supported=True, control="slider", minimum=0, maximum=2
)
_EFFORTS = ModelKwargCapability(
    supported=True, control="select", options=["low", "medium", "high"]
)


def _chat_model(
    nickname: str, offered: SupportedModelKwargs, *, tools: bool = True
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=nickname.lower().replace(" ", "-"),
        nickname=nickname,
        supports_tool_calling=tools,
        get_supported_model_kwargs=lambda: offered,
    )


_INSTRUCTIONS = "Du är ärendehjälpen.\nSvara kort och sakligt."


def _changeable(**overrides) -> SimpleNamespace:
    values = {
        "name": "Ärendehjälpen",
        "description": "Hjälper handläggare.",
        "get_prompt_text": lambda: _INSTRUCTIONS,
        "completion_model": _chat_model(
            "Stor modell",
            _offering(temperature=_TEMPERATURE, reasoning_effort=_EFFORTS),
        ),
        "completion_model_kwargs": ModelKwargs(
            temperature=0.7, reasoning_effort="medium"
        ),
        "knowledge_mode": KnowledgeMode.TOOL,
        "inline_file_text": False,
        "published": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _space(*models, below=()) -> SimpleNamespace:
    by_id = {model.id: model for model in models}
    return SimpleNamespace(
        is_completion_model_available=lambda model_id: model_id in by_id,
        get_completion_model=lambda model_id: by_id[model_id],
        completion_models_below_classification=list(below),
    )


def _plan(assistant, changes, *, space=None, config=None):
    current = [assistant.completion_model] if assistant.completion_model else []
    return assistant_settings.plan_change(
        assistant,
        changes,
        space=space or _space(*current),
        effective_config=config,
    )


def test_a_change_keeps_only_what_differs_from_the_assistant_now():
    assistant = _changeable()

    planned = _plan(
        assistant,
        {
            "name": "Ärendehjälpen",
            "prompt": {"text": _INSTRUCTIONS},
            "knowledge_mode": "inject",
            "completion_model_kwargs": {"temperature": 0.2},
        },
    )

    assert planned.update == {
        "knowledge_mode": "inject",
        "completion_model_kwargs": {"temperature": 0.2, "reasoning_effort": "medium"},
    }
    assert planned.changes == [
        {"field": "completion_model_kwargs.temperature", "before": 0.7, "after": 0.2},
        {"field": "knowledge_mode", "before": "tool", "after": "inject"},
    ]


def test_a_change_that_names_only_current_values_changes_nothing():
    assistant = _changeable()

    planned = _plan(
        assistant,
        {
            "name": "Ärendehjälpen",
            "description": "Hjälper handläggare.",
            "completion_model": {"id": str(assistant.completion_model.id)},
            "completion_model_kwargs": {"reasoning_effort": "medium"},
            "inline_file_text": False,
        },
    )

    assert planned.update == {} and planned.changes == []


def test_null_keeps_a_setting_except_where_the_update_request_clears_it():
    assistant = _changeable()

    planned = _plan(
        assistant,
        {
            "name": None,
            "prompt": None,
            "completion_model": None,
            "knowledge_mode": None,
            "description": None,
        },
    )
    assert planned.update == {"description": None}

    reset = _plan(assistant, {"completion_model_kwargs": None})
    assert reset.update == {"completion_model_kwargs": {}}
    assert [change["field"] for change in reset.changes] == [
        "completion_model_kwargs.temperature",
        "completion_model_kwargs.reasoning_effort",
    ]
    cleared = _plan(assistant, {"completion_model_kwargs": {"temperature": None}})
    assert cleared.update == {"completion_model_kwargs": {"reasoning_effort": "medium"}}


def test_new_instructions_get_a_short_version_description():
    assistant = _changeable()

    given = _plan(
        assistant,
        {
            "prompt": {
                "text": "Ny text.",
                "description": "  Kortare svar,\n med hjälpen ",
            }
        },
    )
    missing = _plan(assistant, {"prompt": {"text": "Ny text."}})
    long = _plan(
        assistant, {"prompt": {"text": "Ny text.", "description": "ord " * 200}}
    )

    assert given.update["prompt"] == {
        "text": "Ny text.",
        "description": "Kortare svar, med hjälpen",
    }
    assert (
        missing.update["prompt"]["description"] == "Changed with the helper assistant."
    )
    assert len(long.update["prompt"]["description"]) <= 200
    assert long.update["prompt"]["description"].endswith("...")
    assert given.changes == [
        {"field": "prompt", "before": _INSTRUCTIONS, "after": "Ny text."}
    ]


def test_a_chosen_model_must_be_one_the_space_offers():
    assistant = _changeable()
    small = _chat_model("Liten modell", _offering(temperature=_TEMPERATURE))
    below = _chat_model("Öppen modell", _offering())
    space = _space(assistant.completion_model, small, below=[below])

    planned = _plan(assistant, {"completion_model": {"id": str(small.id)}}, space=space)
    assert planned.update == {"completion_model": {"id": str(small.id)}}
    assert planned.changes == [
        {
            "field": "completion_model",
            "before": {
                "id": str(assistant.completion_model.id),
                "name": "Stor modell",
            },
            "after": {"id": str(small.id), "name": "Liten modell"},
        }
    ]

    stranger = uuid4()
    with pytest.raises(BadRequestException) as missing:
        _plan(assistant, {"completion_model": {"id": str(stranger)}}, space=space)
    assert "does not offer that model" in str(missing.value)
    assert str(stranger) not in str(missing.value)
    with pytest.raises(BadRequestException) as classified:
        _plan(assistant, {"completion_model": {"id": str(below.id)}}, space=space)
    assert "security classification" in str(classified.value)


def test_model_settings_the_model_does_not_offer_are_refused_by_name():
    assistant = _changeable()
    small = _chat_model("Liten modell", _offering(temperature=_TEMPERATURE))
    space = _space(assistant.completion_model, small)

    with pytest.raises(BadRequestException) as refused:
        _plan(
            assistant,
            {
                "completion_model": {"id": str(small.id)},
                "completion_model_kwargs": {"temperature": 0.3},
            },
            space=space,
        )
    assert "Liten modell does not offer reasoning effort" in str(refused.value)

    with pytest.raises(BadRequestException) as out_of_range:
        _plan(assistant, {"completion_model_kwargs": {"temperature": 5}})
    assert "does not offer temperature" in str(out_of_range.value)

    without_model = _changeable(completion_model=None)
    with pytest.raises(BadRequestException) as no_model:
        _plan(without_model, {"completion_model_kwargs": {"temperature": 0.3}})
    assert "Choose a chat model before its settings" in str(no_model.value)


def test_what_a_policy_sets_is_refused_and_the_rest_is_planned():
    assistant = _changeable()
    policy = _policy(available_models=[assistant.completion_model])
    other = _chat_model("Liten modell", _offering(temperature=_TEMPERATURE))
    space = _space(assistant.completion_model, other)

    for changes, what in [
        ({"prompt": {"text": "Ny text."}}, "the instructions"),
        ({"completion_model": {"id": str(other.id)}}, "the chat models"),
        ({"completion_model_kwargs": {"reasoning_effort": "high"}}, "reasoning"),
        ({"inline_file_text": True}, "files uploaded in a chat"),
    ]:
        with pytest.raises(BadRequestException) as refused:
            _plan(assistant, changes, space=space, config=policy)
        assert "An organisation policy sets" in str(refused.value)
        assert what in str(refused.value)

    planned = _plan(assistant, {"name": "Ärendestöd"}, space=space, config=policy)
    assert planned.update == {"name": "Ärendestöd"}


def test_only_the_allowed_settings_can_be_named():
    assistant_settings.require_changeable(
        {
            "name": "x",
            "prompt": {"text": "y", "description": "z"},
            "completion_model": {"id": str(uuid4())},
            "completion_model_kwargs": {"top_k": 3},
        }
    )

    with pytest.raises(BadRequestException) as refused:
        assistant_settings.require_changeable(
            {
                "skill_bindings": [],
                "logging_enabled": True,
                "completion_model_kwargs": {"response_format": {}},
                "prompt": {"text": "y", "version_id": "v"},
            }
        )
    text = str(refused.value)
    assert text.startswith(
        "Skills, conversation logging, the response format and version id "
        "cannot be changed through the chat"
    )
    for key in ("skill_bindings", "logging_enabled", "response_format", "version_id"):
        assert key not in text
    assert "Nothing was changed." in text


def test_the_model_is_told_what_changed_without_ids_or_long_texts():
    assistant = _changeable(published=True)
    small = _chat_model("Liten modell", _offering(temperature=_TEMPERATURE))
    planned = _plan(
        assistant,
        {
            "name": "Ärendestöd",
            "description": "En ny och längre beskrivning av assistenten.",
            "prompt": {"text": "Du är ärendestödet.\nSvara alltid på svenska."},
            "completion_model": {"id": str(small.id)},
            "completion_model_kwargs": {"temperature": 0.2, "reasoning_effort": None},
        },
        space=_space(assistant.completion_model, small),
    )

    text = assistant_settings.change_text(planned.changes, published=True)
    for hidden in (
        str(small.id),
        str(assistant.completion_model.id),
        "Svara alltid på svenska",
        _INSTRUCTIONS.split("\n")[1],
        "En ny och längre beskrivning",
    ):
        assert hidden not in text
    assert 'name (from "Ärendehjälpen" to "Ärendestöd")' in text
    assert "chat model (from Stor modell to Liten modell)" in text
    assert "temperature (from 0.7 to 0.2)" in text
    assert "reasoning effort (from medium to the model's default)" in text
    assert "published" in text
    proposed = assistant_settings.change_text(planned.changes, published=False)
    assert proposed.startswith("Proposed, nothing saved:")
    assert "do not paste them" in proposed


def test_a_refused_request_names_the_fields_but_not_what_was_sent():
    secret = "not-a-mode-7f3a"
    with pytest.raises(ValidationError) as invalid:
        AssistantUpdatePublic.model_validate(
            {"knowledge_mode": secret, "prompt": {"description": "x"}}
        )

    result = assistant_settings._error_result(invalid.value)  # pyright: ignore[reportPrivateUsage]

    text = result.content[0].text
    assert result.isError
    assert "knowledge_mode" in text and "prompt.text" in text
    assert secret not in text


def test_instructions_too_long_to_keep_leave_their_text_out_but_not_the_request():
    long_text = "x" * (STRUCTURED_CONTENT_MAX_BYTES // 2)
    content = {
        "target_id": str(uuid4()),
        "proposal": {
            "changes": [
                {"field": "prompt", "before": long_text, "after": long_text + "y"},
                {"field": "name", "before": "A", "after": "B"},
            ],
            "update": {"prompt": {"text": long_text + "y"}, "name": "B"},
        },
    }

    kept = assistant_settings._within_cap(content)  # pyright: ignore[reportPrivateUsage]

    assert kept["proposal"]["changes"][0] == {
        "field": "prompt",
        "before": None,
        "after": None,
        "too_long": True,
    }
    assert kept["proposal"]["changes"][1] == {
        "field": "name",
        "before": "A",
        "after": "B",
    }
    assert kept["proposal"]["update"]["prompt"]["text"] == long_text + "y"


async def test_a_change_saves_its_audit_entries_in_its_own_transaction():
    service = SimpleNamespace(log=AsyncMock(), log_async=AsyncMock())
    container = SimpleNamespace(audit_service=providers.Factory(lambda: service))
    entry = {"tenant_id": uuid4(), "description": "Updated assistant"}

    async with assistant_settings._audit_in_transaction(container):  # pyright: ignore[reportPrivateUsage]
        await container.audit_service().log_async(**entry)
        service.log.assert_not_awaited()

    service.log_async.assert_not_awaited()
    service.log.assert_awaited_once_with(**entry)
    assert container.audit_service() is service

    service.log.reset_mock()
    with pytest.raises(BadRequestException):
        async with assistant_settings._audit_in_transaction(container):  # pyright: ignore[reportPrivateUsage]
            await container.audit_service().log_async(**entry)
            raise BadRequestException("refused")
    service.log.assert_not_awaited()
    service.log_async.assert_not_awaited()


def _chat_calls(monkeypatch):
    """A call's context as the chat gives it, with the assistant's update and
    the audit service watched."""
    chat = SimpleNamespace(target_id=uuid4(), space_id=uuid4(), session_id=uuid4())
    container = MagicMock()
    monkeypatch.setattr(
        assistant_settings,
        "internal_tool_context",
        _tool_context(container, chat.session_id, uuid4()),
    )
    monkeypatch.setattr(helper_chat_service, "load_chat", AsyncMock(return_value=chat))
    monkeypatch.setattr(ASSISTANT_TARGET, "require_edit", AsyncMock())
    apply = AsyncMock()
    monkeypatch.setattr(assistant_update_operation, "apply_assistant_update", apply)
    return container, apply


async def test_a_setting_the_chat_may_not_change_is_refused_by_the_proposal(
    monkeypatch,
):
    container, apply = _chat_calls(monkeypatch)
    changes = {"name": "Ärendestöd", "skill_bindings": []}

    result = await assistant_settings.propose_changes(MagicMock(), changes=changes)

    assert result.isError
    assert result.content[0].text.startswith(
        "Skills cannot be changed through the chat"
    )
    assert "skill_bindings" not in result.content[0].text
    apply.assert_not_awaited()
    container.assistant_service.assert_not_called()
    container.audit_service().log.assert_not_called()
    container.audit_service().log_async.assert_not_called()


async def test_a_proposal_that_changes_nothing_says_so_and_proposes_nothing(
    monkeypatch,
):
    container, apply = _chat_calls(monkeypatch)
    assistant = _changeable()
    container.assistant_service.return_value.get_assistant_with_effective_config = (
        AsyncMock(return_value=(assistant, [], None))
    )
    container.space_service.return_value.get_space = AsyncMock(
        return_value=_space(assistant.completion_model)
    )

    result = await assistant_settings.propose_changes(
        MagicMock(),
        changes={"name": "Ärendehjälpen", "prompt": {"text": _INSTRUCTIONS}},
    )

    assert not result.isError
    assert result.content[0].text == (
        "Nothing to propose: the assistant already has these settings."
    )
    assert "proposal" not in result.structuredContent
    apply.assert_not_awaited()


# --- Knowledge, tools, functions, ranking, template, retention, insights ------

_EMBEDDING = SimpleNamespace(id=uuid4())
_OTHER_EMBEDDING = SimpleNamespace(id=uuid4())
_RANKER = uuid4()
_TEMPLATE = uuid4()


def _source(name: str, *, embedding=_EMBEDDING) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), name=name, embedding_model=embedding, space_id=uuid4()
    )


def _world() -> SimpleNamespace:
    """An assistant with a source of each kind, a server with one tool
    switched off and one function, in a space that offers more."""
    routines = _source("Rutiner")
    older = _source("Gamla rutiner")
    site = SimpleNamespace(
        id=uuid4(),
        name=None,
        url=f"https://reader:{_SITE_PASSWORD}@intra.example.org/docs?sig=abc",
        embedding_model=_EMBEDDING,
        space_id=uuid4(),
    )
    folder = _source("Delad mapp")
    cases = _server()
    archive = _server(name="Diariet")
    off = _server(name="Avstängd", is_enabled=False)
    assistant = _changeable(
        collections=[routines],
        websites=[site],
        integration_knowledge_list=[folder],
        rerank_model_id=None,
        mcp_servers=[cases],
        mcp_tools=[(cases.tools[1].id, False)],
        enabled_capabilities=["file_creation"],
        document_template=DocumentTemplateChoice(),
        data_retention_days=None,
        insight_enabled=False,
    )
    space = _space(assistant.completion_model)
    space.collections = [routines, older]
    space.websites = [site]
    space.integration_knowledge_list = [folder]
    space.mcp_servers = [cases, archive, off]
    space.enabled_capabilities = ["file_creation", "web_search", "charts"]
    return SimpleNamespace(
        assistant=assistant,
        space=space,
        routines=routines,
        older=older,
        site=site,
        folder=folder,
        cases=cases,
        archive=archive,
        off=off,
    )


_ALL_RIGHTS = assistant_settings.PersonRights(
    edit_retention=True, toggle_insight=True, publish=True
)


def _facts(**overrides) -> assistant_settings.ChangeFacts:
    values = {
        "rights": _ALL_RIGHTS,
        "ready_functions": frozenset({"file_creation", "web_search"}),
        "rerank_models": {_RANKER: "Rankaren"},
        "selectable_rerank_models": frozenset({_RANKER}),
        "document_templates": {_TEMPLATE: "Kommunmall"},
    }
    values.update(overrides)
    return assistant_settings.ChangeFacts(**values)


def _plan_in(world, changes, *, facts=None, config=None):
    return assistant_settings.plan_change(
        world.assistant,
        changes,
        space=world.space,
        effective_config=config,
        facts=facts or _facts(),
    )


def _everything(world) -> dict:
    """A change of every setting added beside the base ones, lists given as
    additions and removals where the form allows."""
    return {
        "groups": {"add": [{"id": str(world.older.id)}]},
        "websites": [],
        "integration_knowledge_list": {"remove": [{"id": str(world.folder.id)}]},
        "rerank_model_id": str(_RANKER),
        "mcp_servers": {"add": [{"id": str(world.archive.id)}]},
        "mcp_tools": {
            "add": [{"tool_id": str(world.archive.tools[0].id), "is_enabled": False}],
            "remove": [{"tool_id": str(world.cases.tools[1].id)}],
        },
        "enabled_capabilities": {"add": ["web_search"], "remove": ["file_creation"]},
        "document_template": {"mode": "selected", "template_id": str(_TEMPLATE)},
        "data_retention_days": 30,
        "insight_enabled": True,
    }


def test_each_added_setting_is_planned_as_the_update_request_takes_it():
    world = _world()

    planned = _plan_in(world, _everything(world))

    assert planned.update == {
        "groups": [{"id": str(world.routines.id)}, {"id": str(world.older.id)}],
        "websites": [],
        "integration_knowledge_list": [],
        "rerank_model_id": str(_RANKER),
        "mcp_servers": [{"id": str(world.cases.id)}, {"id": str(world.archive.id)}],
        "mcp_tools": [{"tool_id": str(world.archive.tools[0].id), "is_enabled": False}],
        "enabled_capabilities": ["web_search"],
        "document_template": {"mode": "selected", "template_id": str(_TEMPLATE)},
        "data_retention_days": 30,
        "insight_enabled": True,
    }
    AssistantUpdatePublic.model_validate(planned.update)
    assert [change["field"] for change in planned.changes] == [
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
    ]
    changed = {
        change["field"]: (change["before"], change["after"])
        for change in planned.changes
    }
    routines = {"id": str(world.routines.id), "name": "Rutiner"}
    assert changed["groups"] == (
        [routines],
        [{"id": str(world.older.id), "name": "Gamla rutiner"}, routines],
    )
    # A website is named as the editor shows it: without its sign-in part.
    assert changed["websites"] == (
        [{"id": str(world.site.id), "name": "intra.example.org/docs"}],
        [],
    )
    assert changed["mcp_servers"][1] == [
        {"id": str(world.archive.id), "name": "Diariet"},
        {"id": str(world.cases.id), "name": "Ärendesystemet"},
    ]
    assert changed["mcp_tools"] == (
        [
            {
                "id": str(world.cases.tools[1].id),
                "name": "create_case",
                "is_enabled": False,
            }
        ],
        [
            {
                "id": str(world.archive.tools[0].id),
                "name": "search_cases",
                "is_enabled": False,
            }
        ],
    )
    assert changed["enabled_capabilities"] == (
        [{"id": "file_creation", "name": "Skapa fil"}],
        [{"id": "web_search", "name": "Webbsökning"}],
    )
    assert changed["rerank_model_id"] == (
        None,
        {"id": str(_RANKER), "name": "Rankaren"},
    )
    assert changed["document_template"] == (
        {"mode": "default", "template_id": None, "name": None},
        {"mode": "selected", "template_id": str(_TEMPLATE), "name": "Kommunmall"},
    )
    assert changed["data_retention_days"] == (None, 30)
    assert changed["insight_enabled"] == (False, True)


def test_additions_and_removals_build_the_whole_list_from_the_stored_one():
    world = _world()

    added = _plan_in(
        world,
        {
            "groups": {
                "add": [{"id": str(world.older.id)}, {"id": str(world.routines.id)}]
            },
            "enabled_capabilities": {"add": ["web_search"]},
        },
    )
    assert added.update == {
        "groups": [{"id": str(world.routines.id)}, {"id": str(world.older.id)}],
        "enabled_capabilities": ["file_creation", "web_search"],
    }
    # A whole list replaces the stored one.
    whole = _plan_in(world, {"groups": [{"id": str(world.older.id)}]})
    assert whole.update == {"groups": [{"id": str(world.older.id)}]}
    # Adding what is there, removing what is not, the same list in another
    # order, and an entry both added and removed change nothing.
    unchanged = _plan_in(
        world,
        {
            "groups": {
                "add": [{"id": str(world.routines.id)}],
                "remove": [{"id": str(uuid4())}],
            },
            "mcp_servers": [{"id": str(world.cases.id)}],
            "enabled_capabilities": {"add": ["web_search"], "remove": ["web_search"]},
            "mcp_tools": {
                "add": [{"tool_id": str(world.cases.tools[1].id), "is_enabled": False}]
            },
        },
    )
    assert unchanged.update == {} and unchanged.changes == []


def test_a_server_that_goes_takes_its_tool_settings_along():
    world = _world()

    planned = _plan_in(
        world, {"mcp_servers": {"remove": [{"id": str(world.cases.id)}]}}
    )

    assert planned.update == {"mcp_servers": []}
    tool = {
        "id": str(world.cases.tools[1].id),
        "name": "create_case",
        "is_enabled": False,
    }
    assert planned.changes == [
        {
            "field": "mcp_servers",
            "before": [{"id": str(world.cases.id), "name": "Ärendesystemet"}],
            "after": [],
        },
        {"field": "mcp_tools", "before": [tool], "after": []},
    ]


def test_retention_and_insights_are_refused_without_the_right_for_them():
    world = _world()
    without = _facts(rights=assistant_settings.NO_RIGHTS)

    for changes, what in (
        ({"data_retention_days": 30}, "how long conversations are kept"),
        ({"insight_enabled": True}, "whether insights are on"),
    ):
        for facts in (without, None):
            with pytest.raises(BadRequestException) as refused:
                assistant_settings.plan_change(
                    world.assistant,
                    changes,
                    space=world.space,
                    effective_config=None,
                    facts=facts,
                )
            text = str(refused.value)
            assert text.startswith(f"The person's role does not let them change {what}")
            assert "such as its administrators" in text
            assert text.endswith("Nothing was changed.")
    personal = _facts(
        rights=assistant_settings.PersonRights(
            edit_retention=True,
            toggle_insight=False,
            publish=False,
            personal_space=True,
        )
    )
    with pytest.raises(BadRequestException) as not_used:
        _plan_in(world, {"insight_enabled": True}, facts=personal)
    assert str(not_used.value) == (
        "Insights are not used for an assistant in a personal space. "
        "Nothing was changed."
    )
    # A value the assistant already has is no change, so nothing is refused.
    same = _plan_in(
        world, {"insight_enabled": False, "data_retention_days": None}, facts=without
    )
    assert same.update == {}


def test_what_the_space_does_not_offer_is_refused_without_naming_an_id():
    world = _world()
    stranger = str(uuid4())
    function_server = _server(name="Sökleverantören", purpose="web_search")
    world.space.mcp_servers.append(function_server)

    for changes, refusal in (
        ({"groups": {"add": [{"id": stranger}]}}, "does not offer that collection"),
        ({"websites": [{"id": stranger}]}, "does not offer that website"),
        (
            {"integration_knowledge_list": {"add": [{"id": stranger}]}},
            "does not offer that integration source",
        ),
        ({"mcp_servers": {"add": [{"id": stranger}]}}, "does not offer that MCP"),
        (
            {"mcp_servers": {"add": [{"id": str(world.off.id)}]}},
            "turned off by an administrator",
        ),
        (
            {"mcp_servers": {"add": [{"id": str(function_server.id)}]}},
            "provides a function",
        ),
        (
            {
                "mcp_tools": {
                    "add": [
                        {
                            "tool_id": str(world.archive.tools[0].id),
                            "is_enabled": False,
                        }
                    ]
                }
            },
            "not a tool of the assistant's MCP servers",
        ),
        (
            {"enabled_capabilities": {"add": ["compute"]}},
            '"Beräkning" [compute] cannot be turned on: turned off in the space',
        ),
        (
            {"enabled_capabilities": ["charts"]},
            '"Diagram" [charts] cannot be turned on: no source is active',
        ),
        ({"rerank_model_id": stranger}, "cannot use that result ranking model"),
        (
            {"document_template": {"mode": "selected", "template_id": stranger}},
            "no such document template",
        ),
        ({"document_template": {"mode": "selected"}}, '"mode": "selected"'),
    ):
        with pytest.raises(BadRequestException) as refused:
            _plan_in(world, changes)
        text = str(refused.value)
        assert refusal in text, changes
        assert stranger not in text
        assert text.endswith("Nothing was changed.")


def test_a_function_that_cannot_be_turned_on_is_refused_with_the_editors_reason():
    world = _world()
    sources = 'an administrator configures its sources under "Verktyg" > "Funktioner"'

    with pytest.raises(BadRequestException) as turned_off:
        _plan_in(world, {"enabled_capabilities": {"add": ["compute"]}})
    assert str(turned_off.value) == (
        f'"Beräkning" [compute] cannot be turned on: {_TURNED_OFF}. Nothing was '
        "changed."
    )

    world.space.enabled_capabilities += ["compute"]
    with pytest.raises(BadRequestException) as not_ready:
        _plan_in(
            world,
            {"enabled_capabilities": {"add": ["charts", "compute"]}},
            facts=_facts(function_blocks={"charts": "classification"}),
        )
    assert str(not_ready.value) == (
        '"Diagram" [charts] cannot be turned on: no source meets the space\'s '
        f'security classification ({sources}); "Beräkning" [compute] cannot be '
        f"turned on: no source is active ({sources}). Nothing was changed."
    )


def test_a_source_the_space_no_longer_offers_must_go_with_the_change():
    world = _world()
    world.space.collections = [world.older]

    with pytest.raises(BadRequestException) as refused:
        _plan_in(world, {"groups": {"add": [{"id": str(world.older.id)}]}})
    assert str(refused.value).startswith('The space no longer offers "Rutiner"')

    planned = _plan_in(world, {"groups": [{"id": str(world.older.id)}]})
    assert planned.update == {"groups": [{"id": str(world.older.id)}]}


def test_knowledge_on_another_embedding_model_is_refused():
    world = _world()
    foreign = _source("Annan modell", embedding=_OTHER_EMBEDDING)
    world.space.collections.append(foreign)

    with pytest.raises(BadRequestException) as refused:
        _plan_in(world, {"groups": {"add": [{"id": str(foreign.id)}]}})
    assert "must use the same embedding model" in str(refused.value)

    # Replacing every source with sources on the other model keeps the rule.
    replaced = _plan_in(
        world,
        {
            "groups": [{"id": str(foreign.id)}],
            "websites": [],
            "integration_knowledge_list": [],
        },
    )
    assert replaced.update["groups"] == [{"id": str(foreign.id)}]


def test_mcp_servers_tools_and_functions_a_policy_sets_are_refused():
    world = _world()
    policy = _policy(available_models=[world.assistant.completion_model])

    for changes in (
        {"mcp_servers": {"remove": [{"id": str(world.cases.id)}]}},
        {"mcp_tools": {"remove": [{"tool_id": str(world.cases.tools[1].id)}]}},
        {"enabled_capabilities": {"add": ["web_search"]}},
    ):
        with pytest.raises(BadRequestException) as refused:
            _plan_in(world, changes, config=policy)
        assert str(refused.value).startswith(
            "An organisation policy sets the MCP servers and functions"
        )


def test_no_credential_reaches_a_change_or_what_the_model_is_told():
    world = _world()
    planned = _plan_in(
        world,
        {
            "websites": [],
            "mcp_servers": {"add": [{"id": str(world.archive.id)}]},
            "mcp_tools": {
                "add": [{"tool_id": str(world.archive.tools[1].id), "is_enabled": True}]
            },
        },
    )
    told = assistant_settings.change_text(planned.changes, published=False)
    content = json.dumps(
        {"changes": planned.changes, "update": planned.update}, default=str
    )

    for secret in (_SERVER_TOKEN, _URL_KEY, _SITE_PASSWORD, "sig=abc", "reader"):
        assert secret not in told and secret not in content
    for address in ("cases.example.org", "https://"):
        assert address not in told and address not in content
    assert "intra.example.org/docs" in content


def test_the_model_is_told_what_was_added_and_removed_by_name():
    world = _world()
    planned = _plan_in(world, _everything(world))

    text = assistant_settings.change_text(planned.changes, published=False)

    for line in (
        'collections (added "Gamla rutiner")',
        'websites (removed "intra.example.org/docs")',
        'integration sources (removed "Delad mapp")',
        "result ranking (from none to Rankaren)",
        'MCP servers (added "Diariet")',
        "MCP tools (search_cases off, create_case back to its server's setting)",
        'functions (added "Webbsökning" [web_search]; removed "Skapa fil" '
        "[file_creation])",
        "document template (from the organisation's default to Kommunmall)",
        "conversation retention (from following the space to 30 days)",
        "insights (from off to on)",
    ):
        assert line in text
    for ident in (str(world.older.id), str(world.archive.id), str(_RANKER)):
        assert ident not in text


def test_a_list_given_in_the_wrong_shape_names_the_fields_not_the_values():
    secret = "not-an-id-5e6f"
    with pytest.raises(ValidationError) as invalid:
        assistant_settings.changes_request(
            {"groups": {"add": [{"id": secret}], "replace": []}}
        )

    text = assistant_settings._error_result(invalid.value).content[0].text  # pyright: ignore[reportPrivateUsage]

    assert "groups.add.0.id" in text and "groups.replace" in text
    assert secret not in text


def test_read_assistant_names_what_the_persons_role_does_not_let_them_change():
    reading = replace(_reading(), rights=assistant_settings.NO_RIGHTS)

    others = "someone with more rights in the space, such as its administrators, can"
    for section in ("overview", "access"):
        text = _text(assistant_lines(reading, section))
        assert "Not the person's to change (their role does not allow it):" in text
        for setting in (
            f"- conversation retention: {others}",
            f"- insights (turning them on or off): {others}",
            f"- publishing (publishing or unpublishing it): {others}",
        ):
            assert setting in text

    personal = replace(
        _reading(),
        rights=assistant_settings.PersonRights(
            edit_retention=True,
            toggle_insight=False,
            publish=False,
            personal_space=True,
        ),
    )
    text = _text(assistant_lines(personal, "access"))
    assert "- insights (turning them on or off): not used in a personal space" in text
    assert (
        "- publishing (publishing or unpublishing it): not used in a personal space"
        in (text)
    )
    assert "conversation retention:" not in text

    allowed = replace(_reading(), rights=_ALL_RIGHTS)
    assert "Not the person's to change" not in _text(assistant_lines(allowed, "all"))


def test_the_options_give_the_ids_a_change_of_a_tool_or_source_takes():
    server = _server(name="Policyservern")
    governed = _offer(_policy(available_mcp_servers=[server]))

    tools = _text(option_lines(governed, "tools"))
    assert f"search_cases [id {server.tools[0].id}]" in tools
    assert "- MCP servers and functions: set by the policy" in tools

    knowledge = _text(option_lines(_offer(), "knowledge"))
    assert knowledge.startswith(
        "All the knowledge of one assistant must use the same embedding model"
    )
    assert "embedding model [id " in knowledge


# --- The editor's own rules --------------------------------------------------

_HAS_SERVERS = (
    "Knowledge and MCP servers are not combined on one assistant, and this one "
    "has MCP servers, so no knowledge can be added to it. If the person wants "
    "knowledge in their place, remove the MCP servers in the same change. "
    "Nothing was changed."
)
_HAS_KNOWLEDGE = (
    "Knowledge and MCP servers are not combined on one assistant, and this one "
    "has knowledge, so no MCP server can be added to it. If the person wants MCP "
    "servers in its place, remove its knowledge in the same change. Nothing was "
    "changed."
)
_NO_TOOLS = (
    "The chat model the assistant would answer with, Liten modell, cannot use "
    "tools, so "
)
_WEB_SEARCH_CANNOT = '"Webbsökning" [web_search] cannot be switched on'


def _servers_only(world) -> SimpleNamespace:
    """``world`` with an assistant that has MCP servers and no knowledge."""
    world.assistant.collections = []
    world.assistant.websites = []
    world.assistant.integration_knowledge_list = []
    return world


def _knowledge_only(world) -> SimpleNamespace:
    """``world`` with an assistant that has knowledge and no MCP server."""
    world.assistant.mcp_servers = []
    world.assistant.mcp_tools = []
    return world


def _without_tools() -> SimpleNamespace:
    return _chat_model("Liten modell", _offering(), tools=False)


def _with_models(world, *models) -> SimpleNamespace:
    """``world`` with a space that also offers ``models``."""
    offered = {model.id: model for model in (world.assistant.completion_model, *models)}
    world.space.is_completion_model_available = lambda model_id: model_id in offered
    world.space.get_completion_model = lambda model_id: offered[model_id]
    return world


def test_knowledge_and_mcp_servers_are_not_combined_by_a_change():
    servers_only = _servers_only(_world())
    routines = {"id": str(servers_only.routines.id)}
    for changes in (
        {"groups": {"add": [routines]}},
        {"websites": [{"id": str(servers_only.site.id)}]},
        {"integration_knowledge_list": {"add": [{"id": str(servers_only.folder.id)}]}},
        # Another server in place of the one it has is still an MCP server.
        {"groups": [routines], "mcp_servers": [{"id": str(servers_only.archive.id)}]},
    ):
        with pytest.raises(BadRequestException) as refused:
            _plan_in(servers_only, changes)
        assert str(refused.value) == _HAS_SERVERS, changes

    knowledge_only = _knowledge_only(_world())
    with pytest.raises(BadRequestException) as refused:
        _plan_in(
            knowledge_only,
            {"mcp_servers": {"add": [{"id": str(knowledge_only.archive.id)}]}},
        )
    assert str(refused.value) == _HAS_KNOWLEDGE

    neither = _knowledge_only(_servers_only(_world()))
    routines = {"id": str(neither.routines.id)}
    server = {"id": str(neither.cases.id)}
    with pytest.raises(BadRequestException) as refused:
        _plan_in(neither, {"groups": [routines], "mcp_servers": [server]})
    assert str(refused.value) == (
        "Knowledge and MCP servers are not combined on one assistant, so both "
        "cannot be added: add one or the other. Nothing was changed."
    )
    assert _plan_in(neither, {"groups": [routines]}).update == {"groups": [routines]}
    assert _plan_in(neither, {"mcp_servers": [server]}).update == {
        "mcp_servers": [server]
    }


def test_an_assistant_with_knowledge_and_mcp_servers_stays_changeable_on_both_sides():
    world = _world()
    older = {"id": str(world.older.id)}
    archive = {"id": str(world.archive.id)}

    for changes, changed in (
        ({"groups": {"add": [older]}}, {"groups"}),
        ({"mcp_servers": {"add": [archive]}}, {"mcp_servers"}),
        (
            {"groups": {"add": [older]}, "mcp_servers": {"add": [archive]}},
            {"groups", "mcp_servers"},
        ),
        (
            {"groups": [], "websites": [], "integration_knowledge_list": []},
            {"groups", "websites", "integration_knowledge_list"},
        ),
        ({"mcp_servers": []}, {"mcp_servers"}),
    ):
        assert set(_plan_in(world, changes).update) == changed, changes


def test_a_change_that_removes_what_stands_in_the_way_may_add_in_the_same_request():
    servers_only = _servers_only(_world())
    routines = {"id": str(servers_only.routines.id)}

    planned = _plan_in(servers_only, {"mcp_servers": [], "groups": {"add": [routines]}})
    assert planned.update == {"groups": [routines], "mcp_servers": []}

    knowledge_only = _knowledge_only(_world())
    archive = {"id": str(knowledge_only.archive.id)}
    cleared = {"groups": [], "websites": [], "integration_knowledge_list": []}
    planned = _plan_in(knowledge_only, {**cleared, "mcp_servers": {"add": [archive]}})
    assert planned.update == {**cleared, "mcp_servers": [archive]}

    # Knowledge that stays still stands in the way.
    with pytest.raises(BadRequestException) as refused:
        _plan_in(knowledge_only, {"groups": [], "mcp_servers": {"add": [archive]}})
    assert str(refused.value) == _HAS_KNOWLEDGE


def test_removing_knowledge_mcp_servers_and_functions_is_always_allowed():
    world = _servers_only(_world())
    world.assistant.completion_model = _without_tools()

    planned = _plan_in(
        world,
        {
            "mcp_servers": {"remove": [{"id": str(world.cases.id)}]},
            "enabled_capabilities": {"remove": ["file_creation"]},
        },
    )

    assert planned.update == {"mcp_servers": [], "enabled_capabilities": []}
    # A server that goes takes its tools' settings along.
    assert [change["field"] for change in planned.changes] == [
        "mcp_servers",
        "mcp_tools",
        "enabled_capabilities",
    ]
    knowledge_only = _knowledge_only(_world())
    assert _plan_in(knowledge_only, {"groups": []}).update == {"groups": []}


def test_mcp_servers_tools_and_functions_need_a_model_that_can_use_tools():
    world = _world()
    world.assistant.completion_model = _without_tools()
    cases = world.cases

    for changes, what in (
        (
            {"mcp_servers": {"add": [{"id": str(world.archive.id)}]}},
            "no MCP server can be added",
        ),
        (
            {"enabled_capabilities": {"add": ["web_search"]}},
            '"Webbsökning" [web_search] cannot be switched on',
        ),
        # The editor gives the space's reason first and the provider's last.
        (
            {"enabled_capabilities": ["charts"]},
            '"Diagram" [charts] cannot be switched on',
        ),
        (
            {
                "mcp_tools": {
                    "add": [{"tool_id": str(cases.tools[0].id), "is_enabled": True}]
                }
            },
            "no single MCP tool can be switched on or off",
        ),
        # The editor shows no single tool while the model cannot use tools,
        # so switching one off or back to its server's setting is refused too.
        (
            {
                "mcp_tools": {
                    "add": [{"tool_id": str(cases.tools[0].id), "is_enabled": False}]
                }
            },
            "no single MCP tool can be switched on or off",
        ),
        (
            {"mcp_tools": {"remove": [{"tool_id": str(cases.tools[1].id)}]}},
            "no single MCP tool can be switched on or off",
        ),
    ):
        with pytest.raises(BadRequestException) as refused:
            _plan_in(world, changes)
        text = str(refused.value)
        assert text.startswith(_NO_TOOLS + what), changes
        assert "Choose a chat model that can use tools first, or in the same" in text
        assert text.endswith("Nothing was changed.")

    with pytest.raises(BadRequestException) as not_offered:
        _plan_in(world, {"enabled_capabilities": {"add": ["compute"]}})
    assert str(not_offered.value).startswith(
        '"Beräkning" [compute] cannot be turned on: turned off in the space'
    )


def test_the_model_rule_follows_a_model_chosen_in_the_same_change():
    world = _world()
    able = world.assistant.completion_model
    without = _without_tools()
    _with_models(world, without)
    web_search = {"enabled_capabilities": {"add": ["web_search"]}}

    with pytest.raises(BadRequestException) as refused:
        _plan_in(world, {"completion_model": {"id": str(without.id)}, **web_search})
    assert str(refused.value).startswith(_NO_TOOLS + _WEB_SEARCH_CANNOT)
    # The model alone may change: what is on stays on.
    alone = _plan_in(world, {"completion_model": {"id": str(without.id)}})
    assert alone.update == {"completion_model": {"id": str(without.id)}}

    world.assistant.completion_model = without
    with pytest.raises(BadRequestException):
        _plan_in(world, web_search)
    planned = _plan_in(
        world,
        {
            "completion_model": {"id": str(able.id)},
            "mcp_servers": {"add": [{"id": str(world.archive.id)}]},
            **web_search,
        },
    )
    assert planned.update["completion_model"] == {"id": str(able.id)}
    assert planned.update["enabled_capabilities"] == ["file_creation", "web_search"]
    assert planned.update["mcp_servers"][-1] == {"id": str(world.archive.id)}


def test_the_model_rule_follows_the_model_a_models_policy_answers_with():
    world = _world()
    steered = _without_tools()
    policy = _policy(
        prompt_enforced=False,
        mcp_enforced=False,
        inline_file_text=None,
        reasoning_policy_configured=False,
        available_models=[steered],
        locked_model=steered,
        policy_default_model=steered,
    )

    with pytest.raises(BadRequestException) as refused:
        _plan_in(
            world, {"enabled_capabilities": {"add": ["web_search"]}}, config=policy
        )

    assert str(refused.value).startswith(_NO_TOOLS + _WEB_SEARCH_CANNOT)


def test_read_assistant_says_what_the_editors_rules_hold_back():
    heading = "Held back by the editor's rules as the assistant is set up now:"
    assert heading not in _text(assistant_lines(_reading(), "all"))

    servers_only = _reading()
    servers_only.assistant.collections = []
    servers_only.assistant.websites = []
    knowledge_line = (
        "- knowledge: none can be added while the assistant has MCP servers (the "
        "two are not combined); removing the MCP servers comes first"
    )
    overview = _text(assistant_lines(servers_only, "overview"))
    assert f"{heading}\n{knowledge_line}" in overview
    assert knowledge_line in _text(assistant_lines(servers_only, "knowledge"))
    assert "- knowledge:" not in _text(assistant_lines(servers_only, "tools"))

    knowledge_only = _reading()
    knowledge_only.assistant.mcp_servers = []
    knowledge_only.assistant.completion_model.supports_tool_calling = False
    servers_line = (
        "- MCP servers: none can be added while the assistant has knowledge (the "
        "two are not combined); removing its knowledge comes first"
    )
    model_line = (
        "- MCP servers, their tools and functions: the chat model Stor modell "
        "cannot use tools, so no MCP server or function can be turned on and no "
        "single tool switched on or off; choosing a model that can use tools "
        "comes first"
    )
    for section in ("overview", "tools"):
        text = _text(assistant_lines(knowledge_only, section))
        assert servers_line in text and model_line in text

    # Where a policy sets the MCP servers and functions, its lock says so.
    governed = replace(knowledge_only, effective_config=_policy())
    tools = _text(assistant_lines(governed, "tools"))
    assert "- MCP servers and functions: set by the policy" in tools
    assert servers_line not in tools and model_line not in tools


async def test_the_editors_rules_are_refused_by_the_proposal_and_nothing_is_written(
    monkeypatch,
):
    container, apply = _chat_calls(monkeypatch)
    world = _knowledge_only(_world())
    container.assistant_service.return_value.get_assistant_with_effective_config = (
        AsyncMock(return_value=(world.assistant, [], None))
    )
    container.space_service.return_value.get_space = AsyncMock(return_value=world.space)
    monkeypatch.setattr(
        assistant_settings, "_change_facts", AsyncMock(return_value=_facts())
    )
    add_server = {"mcp_servers": {"add": [{"id": str(world.archive.id)}]}}
    add_function = {"enabled_capabilities": {"add": ["web_search"]}}

    propose = assistant_settings.propose_changes
    world.assistant.completion_model = _chat_model("Stor modell", _offering())
    combined = await propose(MagicMock(), changes=add_server)
    assert combined.isError
    assert combined.content[0].text == _HAS_KNOWLEDGE

    world.assistant.completion_model = _without_tools()
    without_tools = await propose(MagicMock(), changes=add_function)
    assert without_tools.isError
    assert without_tools.content[0].text.startswith(_NO_TOOLS + _WEB_SEARCH_CANNOT)
    apply.assert_not_awaited()
    container.audit_service().log.assert_not_called()
    container.audit_service().log_async.assert_not_called()


# --- read_prompt_history -----------------------------------------------------


def _version(text: str, *, minute: int, selected=False, description=None, user=None):
    return SimpleNamespace(
        text=text,
        description=description,
        is_selected=selected,
        created_at=datetime(2026, 11, 18, 12, minute, tzinfo=UTC),
        user=user,
    )


_NEWEST = "Du är ärendestödet.\n\nSvara kort.\nPå svenska.\nAlltid sakligt."


def _versions() -> list[SimpleNamespace]:
    return [
        _version(
            _NEWEST,
            minute=30,
            selected=True,
            description="Kortare svar, ändrat med hjälpassistenten",
            user=SimpleNamespace(username="anna", email="anna@example.org"),
        ),
        _version(
            "Du är ärendehjälpen.",
            minute=5,
            user=SimpleNamespace(username=None, email="bo@example.org"),
        ),
    ]


def test_the_history_lists_the_versions_newest_first_with_how_each_begins():
    lines = assistant_settings.history_lines(_versions(), None)

    assert lines == [
        "1. saved 2026-11-18 12:30 UTC (in use now); author: anna; "
        f"{len(_NEWEST)} characters",
        "   description: Kortare svar, ändrat med hjälpassistenten",
        "   begins: Du är ärendestödet. / Svara kort. / På svenska.",
        "2. saved 2026-11-18 12:05 UTC; author: bo@example.org; 20 characters",
        "   description: none",
        "   begins: Du är ärendehjälpen.",
    ]
    assert assistant_settings.history_lines([], None) == [
        "No versions of the instructions are saved."
    ]


def test_one_version_is_read_whole_by_its_number_in_the_list():
    versions = _versions()

    lines = assistant_settings.history_lines(versions, 1)

    assert lines[0].startswith("Version 1 of 2, saved 2026-11-18 12:30 UTC")
    assert lines[1] == "Description: Kortare svar, ändrat med hjälpassistenten"
    assert lines[3:] == _NEWEST.split("\n")
    for number in (0, 3):
        with pytest.raises(BadRequestException) as refused:
            assistant_settings.history_lines(versions, number)
        assert "version must be from 1 to 2" in str(refused.value)


async def test_the_history_is_read_through_the_editors_permission_check_in_pages(
    monkeypatch,
):
    container, _ = _chat_calls(monkeypatch)
    chat = helper_chat_service.load_chat.return_value  # pyright: ignore[reportFunctionMemberAccess]
    versions = _versions()
    versions[0].text = "\n".join(f"rad {number}: " + "x" * 120 for number in range(40))
    read = AsyncMock(return_value=versions)
    container.assistant_service.return_value.get_prompts_by_assistant = read
    monkeypatch.setattr(assistant_settings, "default_page_cap", lambda: 1600)

    result = await assistant_settings.read_prompt_history(MagicMock(), version=1)

    assert not result.isError
    read.assert_awaited_once_with(chat.target_id)
    text = result.content[0].text
    assert text.startswith("Version 1 of the instructions (lines 1-")
    next_offset = result.structuredContent["next_offset"]
    assert f"with version=1 and offset={next_offset} before" in text

    listed = await assistant_settings.read_prompt_history(MagicMock())
    assert listed.content[0].text.startswith(
        "The saved versions of the instructions, newest first (lines 1-6 of 6)"
    )


# --- publish_assistant -------------------------------------------------------


def _publishing(monkeypatch, *, published: bool, rights):
    container, _ = _chat_calls(monkeypatch)
    chat = helper_chat_service.load_chat.return_value  # pyright: ignore[reportFunctionMemberAccess]
    container.assistant_service.return_value.get_assistant = AsyncMock(
        return_value=(SimpleNamespace(published=published), [])
    )
    monkeypatch.setattr(
        assistant_settings, "_person_rights", AsyncMock(return_value=rights)
    )
    publish = AsyncMock(
        return_value=SimpleNamespace(
            assistant=SimpleNamespace(published=not published), permissions=[]
        )
    )
    monkeypatch.setattr(assistant_publish_operation, "apply_assistant_publish", publish)
    return chat, publish


async def test_publishing_needs_the_persons_edit_access(monkeypatch):
    chat, publish = _publishing(monkeypatch, published=False, rights=_ALL_RIGHTS)

    result = await assistant_settings.publish_assistant(MagicMock(), published=True)

    assert not result.isError, result.content[0].text
    publish.assert_awaited_once()
    # The edit access is checked on the chat's assistant before the change.
    ASSISTANT_TARGET.require_edit.assert_awaited_once()  # pyright: ignore[reportFunctionMemberAccess]
    assert ASSISTANT_TARGET.require_edit.await_args.args[2] == chat.target_id  # pyright: ignore[reportFunctionMemberAccess]
    assert helper_chat_service.load_chat.await_args.kwargs["lock"] is True  # pyright: ignore[reportFunctionMemberAccess]


async def test_publishing_is_refused_without_edit_access_before_anything_is_read(
    monkeypatch,
):
    _, publish = _publishing(monkeypatch, published=False, rights=_ALL_RIGHTS)
    monkeypatch.setattr(
        ASSISTANT_TARGET,
        "require_edit",
        AsyncMock(side_effect=ASSISTANT_TARGET.refusals.unavailable("no_edit_rights")),
    )

    result = await assistant_settings.publish_assistant(MagicMock(), published=True)

    assert result.isError
    assert result.content[0].text == (
        "You do not have permission to edit this assistant."
    )
    assistant_settings._person_rights.assert_not_awaited()  # pyright: ignore[reportPrivateUsage, reportFunctionMemberAccess]
    publish.assert_not_awaited()


async def test_publishing_is_refused_without_the_right_or_when_nothing_would_change(
    monkeypatch,
):
    _, publish = _publishing(
        monkeypatch, published=False, rights=assistant_settings.NO_RIGHTS
    )
    refused = await assistant_settings.publish_assistant(MagicMock(), published=True)
    assert refused.isError
    assert refused.content[0].text.startswith(
        "The person's role does not let them change whether this assistant is "
        "published; someone with more rights in the space"
    )

    _, publish_personal = _publishing(
        monkeypatch,
        published=False,
        rights=assistant_settings.PersonRights(
            edit_retention=True,
            toggle_insight=False,
            publish=False,
            personal_space=True,
        ),
    )
    personal = await assistant_settings.publish_assistant(MagicMock(), published=True)
    assert personal.isError
    assert personal.content[0].text == (
        "An assistant in a personal space is not published. Nothing was changed."
    )

    _, publish_again = _publishing(monkeypatch, published=True, rights=_ALL_RIGHTS)
    already = await assistant_settings.publish_assistant(MagicMock(), published=True)
    assert already.isError
    assert already.content[0].text == (
        "The assistant is already published. Nothing was changed."
    )
    publish.assert_not_awaited()
    publish_personal.assert_not_awaited()
    publish_again.assert_not_awaited()


async def test_publishing_goes_through_the_shared_operation_in_the_persons_name(
    monkeypatch,
):
    chat, publish = _publishing(monkeypatch, published=False, rights=_ALL_RIGHTS)

    result = await assistant_settings.publish_assistant(MagicMock(), published=True)

    assert not result.isError
    publish.assert_awaited_once()
    assert publish.await_args.kwargs == {
        "assistant_id": chat.target_id,
        "published": True,
        "audit_context": {"origin": "helper_chat", "session_id": str(chat.session_id)},
    }
    assert result.structuredContent == {
        "target_id": str(chat.target_id),
        "changes": [{"field": "published", "before": False, "after": True}],
        "undo": None,
    }
    assert result.content[0].text.startswith("Published: the assistant is now")


def test_the_history_and_publishing_take_no_assistant_from_the_model():
    assert set(
        inspect.signature(assistant_settings.read_prompt_history).parameters
    ) == {
        "ctx",
        "offset",
        "version",
    }
    assert set(inspect.signature(assistant_settings.publish_assistant).parameters) == {
        "ctx",
        "published",
    }

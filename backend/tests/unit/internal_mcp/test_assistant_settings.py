"""The assistant settings tools: they reach only the assistant of the chat
their token was minted for, read in pages, and never give the model a
credential."""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from dependency_injector import providers
from pydantic import ValidationError

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.api.assistant_models import AssistantUpdatePublic, KnowledgeMode
from eneo.assistants.application import assistant_update_operation
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
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
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
    assert "- file_creation: make documents and spreadsheets; ready" in tools
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
                purpose="charts", available=False, reason="no_provider"
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
    assert "- charts: make charts; not ready (no_provider)" in tools
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
    assert "- compute: calculate with code; ready" in tools
    assert _SERVER_TOKEN not in tools and _URL_KEY not in tools


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
    for tool in (
        assistant_settings.propose_changes,
        assistant_settings.update_assistant,
    ):
        assert set(inspect.signature(tool).parameters) == {"ctx", "changes"}


async def test_view_mode_offers_proposals_and_edit_mode_also_changes():
    asking = await assistant_settings.build_assistant_settings_mcp_server(
        token="t", tenant_id=uuid4(), editing=False
    )
    editing = await assistant_settings.build_assistant_settings_mcp_server(
        token="t", tenant_id=uuid4(), editing=True
    )

    assert {tool.name for tool in asking.tools} == {
        "read_assistant",
        "read_options",
        "propose_changes",
    }
    assert {tool.name for tool in editing.tools} == {
        "read_assistant",
        "read_options",
        "propose_changes",
        "update_assistant",
    }
    assert all(tool.annotations == {"readOnlyHint": True} for tool in asking.tools)
    update = next(tool for tool in editing.tools if tool.name == "update_assistant")
    assert update.annotations == {"readOnlyHint": False, "destructiveHint": False}
    assert asking.name == "assistant"


# --- Changes -----------------------------------------------------------------


def _offering(**settings: ModelKwargCapability) -> SupportedModelKwargs:
    return SupportedModelKwargs(**settings)


_TEMPERATURE = ModelKwargCapability(
    supported=True, control="slider", minimum=0, maximum=2
)
_EFFORTS = ModelKwargCapability(
    supported=True, control="select", options=["low", "medium", "high"]
)


def _chat_model(nickname: str, offered: SupportedModelKwargs) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=nickname.lower().replace(" ", "-"),
        nickname=nickname,
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
                "mcp_servers": [],
                "groups": [],
                "completion_model_kwargs": {"response_format": {}},
                "prompt": {"text": "y", "version_id": "v"},
            }
        )
    text = str(refused.value)
    assert text.startswith(
        "MCP servers, knowledge (collections), the response format and version id "
        "cannot be changed through the chat"
    )
    for key in ("mcp_servers", "groups", "response_format", "version_id"):
        assert key not in text
    assert "Nothing was changed." in text


def test_the_undo_request_gives_the_changed_settings_their_earlier_values():
    model = {"id": str(uuid4()), "name": "Stor modell"}
    changes = [
        {"field": "name", "before": "Ärendehjälpen", "after": "Ärendestöd"},
        {"field": "description", "before": None, "after": "Ny."},
        {"field": "prompt", "before": _INSTRUCTIONS, "after": "Ny text."},
        {"field": "completion_model", "before": model, "after": {"id": "x"}},
        {"field": "completion_model_kwargs.temperature", "before": 0.7, "after": 0.2},
        {"field": "inline_file_text", "before": False, "after": True},
    ]

    undo = assistant_settings.undo_update(
        changes, ModelKwargs(temperature=0.7, reasoning_effort="medium")
    )

    assert undo == {
        "name": "Ärendehjälpen",
        "description": None,
        "prompt": {
            "text": _INSTRUCTIONS,
            "description": (
                "Restored the instructions from before a change made with the "
                "helper assistant."
            ),
        },
        "completion_model": {"id": model["id"]},
        "completion_model_kwargs": {"temperature": 0.7, "reasoning_effort": "medium"},
        "inline_file_text": False,
    }
    AssistantUpdatePublic.model_validate(undo)
    no_model_before = assistant_settings.undo_update(
        [{"field": "completion_model", "before": None, "after": model}],
        ModelKwargs(),
    )
    assert no_model_before == {}


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

    for saved in (True, False):
        text = assistant_settings.change_text(
            planned.changes, saved=saved, published=True
        )
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
    proposed = assistant_settings.change_text(
        planned.changes, saved=False, published=False
    )
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
        "changes": [
            {"field": "prompt", "before": long_text, "after": long_text + "y"},
            {"field": "name", "before": "A", "after": "B"},
        ],
        "undo": {"prompt": {"text": long_text}, "name": "A"},
    }

    kept = assistant_settings._within_cap(content)  # pyright: ignore[reportPrivateUsage]

    assert kept["changes"][0] == {
        "field": "prompt",
        "before": None,
        "after": None,
        "too_long": True,
    }
    assert kept["changes"][1] == {"field": "name", "before": "A", "after": "B"}
    assert kept["undo"]["prompt"]["text"] == long_text


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


def _chat_calls(monkeypatch, *, editing: bool):
    """A call's context as a chat in ``editing`` mode gives it, with the
    assistant's update and the audit service watched."""
    chat = SimpleNamespace(
        target_id=uuid4(), space_id=uuid4(), session_id=uuid4(), editing=editing
    )
    container = MagicMock()
    monkeypatch.setattr(
        assistant_settings,
        "internal_tool_context",
        _tool_context(container, chat.session_id, uuid4()),
    )
    monkeypatch.setattr(helper_chat_service, "load_chat", AsyncMock(return_value=chat))

    async def require_edit_mode(_container, _target, loaded, *, change=False):
        if not loaded.editing:
            raise ASSISTANT_TARGET.refusals.not_editing()

    monkeypatch.setattr(helper_chat_service, "require_edit_mode", require_edit_mode)
    monkeypatch.setattr(ASSISTANT_TARGET, "require_edit", AsyncMock())
    apply = AsyncMock()
    monkeypatch.setattr(assistant_update_operation, "apply_assistant_update", apply)
    return container, apply


async def test_a_change_outside_edit_mode_is_refused_before_anything_is_read(
    monkeypatch,
):
    container, apply = _chat_calls(monkeypatch, editing=False)

    result = await assistant_settings.update_assistant(
        MagicMock(), changes={"name": "Ärendestöd"}
    )

    assert result.isError
    assert "Turn on edit mode" in result.content[0].text
    apply.assert_not_awaited()
    container.assistant_service.assert_not_called()
    container.audit_service.assert_not_called()


async def test_a_setting_the_chat_may_not_change_is_refused_by_both_tools(monkeypatch):
    container, apply = _chat_calls(monkeypatch, editing=True)
    changes = {"name": "Ärendestöd", "enabled_capabilities": ["web_search"]}

    for tool in (
        assistant_settings.propose_changes,
        assistant_settings.update_assistant,
    ):
        result = await tool(MagicMock(), changes=changes)

        assert result.isError
        assert result.content[0].text.startswith(
            "Functions cannot be changed through the chat"
        )
        assert "enabled_capabilities" not in result.content[0].text
    apply.assert_not_awaited()
    container.assistant_service.assert_not_called()
    container.audit_service().log.assert_not_called()
    container.audit_service().log_async.assert_not_called()


async def test_a_proposal_that_changes_nothing_says_so_and_proposes_nothing(
    monkeypatch,
):
    container, apply = _chat_calls(monkeypatch, editing=False)
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

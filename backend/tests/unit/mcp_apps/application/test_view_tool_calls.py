"""A tool's view may call tools on its own server, for the user, only where
one of the user's turns could: the view must belong to a finished call of the
conversation, the assistant must still reach the server, and the tool must be
offered to views. Every refusal reads the same, and the server session is
always closed. A file link the view passes on unsigned is signed again only
for a file its own call was given and the conversation or assistant holds."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.authentication.signed_urls import REDACTED_TOKEN
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.mcp_apps.application import view_tool_calls
from eneo.mcp_apps.application.view_tool_calls import (
    MAX_ARGUMENT_BYTES,
    ViewCallNotReady,
    call_tool_from_view,
)
from eneo.questions.question import ToolCallInfo

VIEW_ID = uuid4()
SERVER_ID = uuid4()
ASSISTANT_ID = uuid4()
TENANT_ID = uuid4()


def _link(file_id: UUID, token: str = REDACTED_TOKEN) -> str:
    return f"http://eneo.test/api/v1/files/{file_id}/original/download/?token={token}"


def _file(file_id: UUID):
    return SimpleNamespace(id=file_id, name=f"{file_id}.csv")


def _call(
    *,
    tool_call_id: str = "call_1",
    view_id: UUID = VIEW_ID,
    server_id: UUID = SERVER_ID,
    result_status: str | None = "succeeded",
    arguments: dict | None = None,
) -> ToolCallInfo:
    return ToolCallInfo(
        server_name="weather",
        tool_name="get_weather",
        tool_call_id=tool_call_id,
        result_status=result_status,
        arguments=arguments,
        app_view={
            "view_id": str(view_id),
            "mcp_server_id": str(server_id),
            "ui": {},
        },
    )


def _conversation(*questions: list[ToolCallInfo], files: list | None = None):
    return SimpleNamespace(
        assistant=SimpleNamespace(id=ASSISTANT_ID),
        questions=[
            SimpleNamespace(
                assistant_id=ASSISTANT_ID,
                tool_calls=calls,
                files=files or [],
                generated_files=[],
            )
            for calls in questions
        ],
    )


class _Proxy:
    def __init__(self, offered: dict[str, str], result: dict):
        self._offered = offered
        self._result = result
        self.called: list[tuple[str, dict]] = []
        self.closed = False

    def allow_file_references(self, file_ids):
        self.allowed_files = set(file_ids)

    def prefixed_tool_name(self, mcp_server_id: UUID, tool_name: str) -> str | None:
        return self._offered.get(tool_name)

    async def call_tools_parallel(self, calls):
        self.called.extend(calls)
        return [self._result for _ in calls]

    async def close(self):
        self.closed = True


class _Factory:
    def __init__(self, proxy: _Proxy):
        self.proxy = proxy
        self.created_with: dict = {}

    def create(self, servers, **kwargs):
        self.created_with = {"servers": servers, **kwargs}
        return self.proxy


class _Assistants:
    def __init__(self, server):
        self.server = server
        self.asked: list[dict] = []
        self.attachments: list = []

    async def mcp_server_for_view(self, **kwargs):
        self.asked.append(kwargs)
        return self.server

    async def attachment_files(self, assistant_id: UUID):
        return self.attachments


def _setup(*, reachable: bool = True, offered: bool = True, result: dict | None = None):
    server = SimpleNamespace(id=SERVER_ID) if reachable else None
    proxy = _Proxy(
        {"refresh_weather": "weather__refresh_weather"} if offered else {},
        result
        or {
            "content": [
                {"type": "text", "text": "13 degrees"},
                {"type": "image", "data": "aGk=", "mimeType": "image/png"},
            ],
            "structured_content": {"temperature": 13},
            "is_error": False,
        },
    )
    return _Assistants(server), _Factory(proxy), proxy


async def _run(conversation, assistants, factory, **overrides):
    return await call_tool_from_view(
        conversation=conversation,
        tool_call_id=overrides.get("tool_call_id", "call_1"),
        view_id=overrides.get("view_id", VIEW_ID),
        name=overrides.get("name", "refresh_weather"),
        arguments=overrides.get("arguments", {"city": "Sundsvall"}),
        app_view_repo=overrides.get(
            "repo",
            SimpleNamespace(
                get_for_tenant=AsyncMock(
                    return_value=SimpleNamespace(mcp_server_id=SERVER_ID)
                )
            ),
        ),
        assistant_service=assistants,  # type: ignore[arg-type]
        proxy_factory=factory,  # type: ignore[arg-type]
        identity_headers={"X-Eneo-User": "u"},
        tenant_id=TENANT_ID,
    )


async def test_view_gets_the_text_and_structured_result_of_its_servers_tool():
    assistants, factory, proxy = _setup()

    result = await _run(_conversation([_call()]), assistants, factory)

    assert result.text == "13 degrees"
    assert result.structured_content == {"temperature": 13}
    assert result.is_error is False
    assert proxy.called == [("weather__refresh_weather", {"city": "Sundsvall"})]
    assert assistants.asked == [
        {"assistant_id": ASSISTANT_ID, "mcp_server_id": SERVER_ID}
    ]
    assert factory.created_with["for_view"] is True
    assert proxy.closed


async def test_call_is_refused_for_a_view_the_conversation_does_not_show():
    assistants, factory, proxy = _setup()

    with pytest.raises(NotFoundException):
        await _run(_conversation([_call()]), assistants, factory, view_id=uuid4())

    assert assistants.asked == []
    assert proxy.called == []


async def test_newest_call_showing_the_view_decides_when_ids_repeat():
    other_server = uuid4()
    assistants, factory, _ = _setup()
    conversation = _conversation(
        [_call(view_id=uuid4(), server_id=other_server)],
        [_call()],
    )

    await _run(conversation, assistants, factory)

    assert assistants.asked[0]["mcp_server_id"] == SERVER_ID


async def test_call_waits_for_the_views_own_tool_call_to_finish():
    assistants, factory, proxy = _setup()

    with pytest.raises(ViewCallNotReady):
        await _run(_conversation([_call(result_status="pending")]), assistants, factory)

    assert proxy.called == []


async def test_call_is_refused_when_the_assistant_no_longer_reaches_the_server():
    assistants, factory, proxy = _setup(reachable=False)

    with pytest.raises(NotFoundException):
        await _run(_conversation([_call()]), assistants, factory)

    assert proxy.called == []


async def test_tool_not_offered_to_views_is_refused_and_the_session_closed():
    assistants, factory, proxy = _setup(offered=False)

    with pytest.raises(NotFoundException):
        await _run(_conversation([_call()]), assistants, factory)

    assert proxy.called == []
    assert proxy.closed


async def test_oversized_arguments_are_refused_before_any_server_is_reached():
    assistants, factory, proxy = _setup()

    with pytest.raises(BadRequestException):
        await _run(
            _conversation([_call()]),
            assistants,
            factory,
            arguments={"blob": "x" * MAX_ARGUMENT_BYTES},
        )

    assert assistants.asked == []
    assert proxy.called == []


async def test_tool_error_is_passed_to_the_view_as_an_error_result():
    assistants, factory, _ = _setup(
        result={"content": [{"type": "text", "text": "boom"}], "is_error": True}
    )

    result = await _run(_conversation([_call()]), assistants, factory)

    assert result.is_error is True
    assert result.text == "boom"
    assert result.structured_content is None


@pytest.fixture
def reference_base(monkeypatch):
    monkeypatch.setattr(
        view_tool_calls, "file_reference_base_url", lambda: "http://eneo.test"
    )


def _sent_link(proxy: _Proxy) -> str:
    return proxy.called[0][1]["file"]["url"]


async def test_link_from_the_views_own_call_is_signed_again(reference_base):
    file_id = uuid4()
    attached = _file(file_id)
    stored = {"file": {"url": _link(file_id, "signed-then"), "filename": "a.csv"}}
    conversation = _conversation([_call(arguments=stored)], files=[attached])
    assistants, factory, proxy = _setup()

    result = await _run(
        conversation,
        assistants,
        factory,
        # As the view holds it: the stored arguments, signature removed.
        arguments={"file": {"url": _link(file_id), "filename": "a.csv"}},
    )

    sent = _sent_link(proxy)
    assert f"/api/v1/files/{file_id}/original/download" in sent
    assert REDACTED_TOKEN not in sent
    assert result.signed_files == [attached]


async def test_link_to_an_attachment_of_the_assistant_is_signed_again(
    reference_base,
):
    file_id = uuid4()
    attached = _file(file_id)
    stored = {"file": {"url": _link(file_id), "filename": "a.csv"}}
    assistants, factory, proxy = _setup()
    assistants.attachments = [attached]

    result = await _run(
        _conversation([_call(arguments=stored)]),
        assistants,
        factory,
        arguments=stored,
    )

    assert REDACTED_TOKEN not in _sent_link(proxy)
    assert result.signed_files == [attached]


async def test_link_the_views_call_never_carried_stays_unsigned(reference_base):
    given, other = uuid4(), uuid4()
    stored = {"file": {"url": _link(given), "filename": "a.csv"}}
    conversation = _conversation(
        [_call(arguments=stored)], files=[_file(given), _file(other)]
    )
    assistants, factory, proxy = _setup()

    result = await _run(
        conversation,
        assistants,
        factory,
        arguments={"file": {"url": _link(other), "filename": "b.csv"}},
    )

    assert _sent_link(proxy) == _link(other)
    assert result.signed_files == []


async def test_link_the_model_wrote_to_a_file_the_conversation_lacks_stays_unsigned(
    reference_base,
):
    foreign = uuid4()
    stored = {"file": {"url": _link(foreign), "filename": "x.csv"}}
    assistants, factory, proxy = _setup()

    result = await _run(
        _conversation([_call(arguments=stored)]),
        assistants,
        factory,
        arguments=stored,
    )

    assert _sent_link(proxy) == _link(foreign)
    assert result.signed_files == []


async def test_revoked_view_cannot_call_enabled_sibling():
    assistants, factory, proxy = _setup()
    repo = SimpleNamespace(get_for_tenant=AsyncMock(return_value=None))
    with pytest.raises(NotFoundException):
        await _run(_conversation([_call()]), assistants, factory, repo=repo)
    repo.get_for_tenant.assert_awaited_once_with(
        VIEW_ID, TENANT_ID, approved_only=True, tool_name="get_weather"
    )
    assert proxy.called == []


@pytest.mark.parametrize("use_handle", [False, True])
async def test_re_signed_file_reaches_real_proxy(
    reference_base, monkeypatch, use_handle
):
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession

    file_id = uuid4()
    attached = _file(file_id)
    from eneo.files.model_file_references import file_handle

    arguments = {
        "file": {
            "url": file_handle(file_id) if use_handle else _link(file_id),
            "filename": "a.csv",
        }
    }
    server = MCPServer(
        id=SERVER_ID,
        tenant_id=TENANT_ID,
        name="weather",
        http_url="http://unused.test/mcp",
    )
    server.tools = [
        MCPServerTool(
            mcp_server_id=SERVER_ID,
            name="refresh_weather",
            description="test",
            input_schema={},
        )
    ]
    proxy = MCPProxySession([server], for_view=True)
    client = SimpleNamespace(
        call_tool=AsyncMock(return_value={"content": [], "is_error": False}),
        disconnect=AsyncMock(),
    )
    proxy._clients[SERVER_ID] = client
    monkeypatch.setattr(proxy, "_is_circuit_open", AsyncMock(return_value=False))
    monkeypatch.setattr(proxy, "_record_success", AsyncMock())
    result = await _run(
        _conversation([_call(arguments=arguments)], files=[attached]),
        _Assistants(server),
        _Factory(proxy),
        arguments=arguments,
    )
    assert not result.is_error
    client.call_tool.assert_awaited_once()
    assert REDACTED_TOKEN not in client.call_tool.call_args.args[1]["file"]["url"]
    assert proxy._reference_file_ids == {file_id}


async def test_tool_echo_does_not_return_signed_credentials_to_view():
    url = _link(uuid4(), "synthetic-secret")
    assistants, factory, _ = _setup(
        result={
            "content": [{"type": "text", "text": url}],
            "structured_content": {"url": url},
        }
    )
    result = await _run(_conversation([_call()]), assistants, factory)
    assert "synthetic-secret" not in result.text
    assert "synthetic-secret" not in result.structured_content["url"]


async def test_view_handle_only_resolves_when_original_call_and_conversation_both_allow_it(
    reference_base,
):
    from eneo.files.model_file_references import file_handle

    given, other = uuid4(), uuid4()
    stored = {"file": {"url": file_handle(given)}}
    assistants, factory, proxy = _setup()
    conversation = _conversation(
        [_call(arguments=stored)], files=[_file(given), _file(other)]
    )
    result = await _run(conversation, assistants, factory, arguments=stored)
    assert "token=" in _sent_link(proxy)
    assert {file.id for file in result.signed_files} == {given}
    # A second file in the same conversation is not an input grant to this view.
    proxy.called.clear()
    result = await _run(
        conversation,
        assistants,
        factory,
        arguments={"file": {"url": file_handle(other)}},
    )
    assert result.signed_files == []
    assert _sent_link(proxy) == file_handle(other)

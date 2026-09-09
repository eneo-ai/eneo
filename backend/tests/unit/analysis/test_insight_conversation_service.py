"""Unit tests for the insights conversation service.

Covers model resolution, timezone validation, the completion call's
contract (insights server attached, no extended logging, tool approval
off), and persistence of tool calls in both non-streaming and streaming
turns, including the partial save on stream abort.
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from eneo.analysis import insight_conversation_service as module
from eneo.analysis.insight_conversation_service import (
    InsightConversationService,
    merge_tool_call_chunk,
)
from eneo.analysis.insight_exceptions import (
    InsightsModelUnavailableError,
    InvalidTimezoneError,
)
from eneo.assistants.assistant import Assistant
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.questions.question import ToolCallInfo


def _model(*, tool_calling=True, accessible=True, created=2026, name="m"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        can_access=accessible,
        supports_tool_calling=tool_calling,
        created_at=datetime(created, 1, 1, tzinfo=timezone.utc),
    )


def _space(*, models=(), default=None, in_space=True):
    def get_default():
        if default is None:
            raise BadRequestException("no models")
        return default

    return SimpleNamespace(
        id=uuid4(),
        completion_models=list(models),
        get_default_completion_model=get_default,
        is_completion_model_in_space=lambda _id: in_space,
    )


def _assistant(model):
    assistant = Assistant.__new__(Assistant)
    assistant.completion_model = model
    assistant.name = "Bygg"
    return assistant


class TestResolveModel:
    resolve = staticmethod(InsightConversationService._resolve_model)

    def test_assistants_own_tool_capable_model_wins(self):
        own = _model()
        space = _space(models=[own], default=_model())

        assert self.resolve(_assistant(own), space) is own

    def test_own_model_outside_the_space_is_skipped(self):
        own = _model()
        default = _model()
        space = _space(models=[default], default=default, in_space=False)

        assert self.resolve(_assistant(own), space) is default

    def test_own_model_without_tool_calling_falls_back_to_space_default(self):
        default = _model()
        space = _space(models=[default], default=default)

        assert self.resolve(_assistant(_model(tool_calling=False)), space) is default

    def test_group_chats_skip_the_own_model_step(self):
        default = _model()
        space = _space(models=[default], default=default)

        assert self.resolve(SimpleNamespace(name="Team"), space) is default

    def test_newest_tool_capable_model_when_default_cannot_call_tools(self):
        older = _model(created=2024)
        newest = _model(created=2026)
        space = _space(
            models=[
                older,
                _model(tool_calling=False),
                newest,
                _model(accessible=False),
            ],
            default=_model(tool_calling=False),
        )

        assert self.resolve(SimpleNamespace(name="Team"), space) is newest

    def test_no_tool_capable_model_raises(self):
        space = _space(models=[_model(tool_calling=False)], default=None)

        with pytest.raises(InsightsModelUnavailableError) as excinfo:
            self.resolve(SimpleNamespace(name="Team"), space)
        assert excinfo.value.code == "insights_model_unavailable"


class TestMergeToolCallChunk:
    def _chunk(self, response_type, **fields):
        metadata = ToolCallMetadata(
            server_name="insights",
            tool_name=fields.pop("tool_name", "top_questions"),
            tool_call_id=fields.pop("tool_call_id", "call-1"),
            **fields,
        )
        return Completion(response_type=response_type, tool_calls_metadata=[metadata])

    def test_pending_then_result_merge_into_one_entry(self):
        calls: list[ToolCallInfo] = []

        merge_tool_call_chunk(
            calls, self._chunk(ResponseType.TOOL_CALL, result_status="pending")
        )
        merge_tool_call_chunk(
            calls,
            self._chunk(
                ResponseType.TOOL_CALL,
                arguments={"n": 5},
                result="Top 5 ...",
                result_status="success",
            ),
        )

        assert len(calls) == 1
        assert calls[0].arguments == {"n": 5}
        assert calls[0].result == "Top 5 ..."
        assert calls[0].result_status == "success"

    def test_later_chunk_does_not_blank_fields_it_lacks(self):
        calls: list[ToolCallInfo] = []
        merge_tool_call_chunk(
            calls, self._chunk(ResponseType.TOOL_CALL, arguments={"n": 5}, result="r")
        )

        merge_tool_call_chunk(calls, self._chunk(ResponseType.TOOL_CALL))

        assert calls[0].arguments == {"n": 5}
        assert calls[0].result == "r"

    def test_distinct_calls_are_kept_apart(self):
        calls: list[ToolCallInfo] = []
        merge_tool_call_chunk(calls, self._chunk(ResponseType.TOOL_CALL))
        merge_tool_call_chunk(
            calls, self._chunk(ResponseType.TOOL_CALL, tool_call_id="call-2")
        )

        assert [c.tool_call_id for c in calls] == ["call-1", "call-2"]

    def test_timeout_marks_the_call_denied(self):
        calls: list[ToolCallInfo] = []
        merge_tool_call_chunk(calls, self._chunk(ResponseType.TOOL_APPROVAL_REQUIRED))
        assert calls[0].approved is None

        merge_tool_call_chunk(calls, self._chunk(ResponseType.TOOL_APPROVAL_TIMEOUT))

        assert calls[0].approved is False
        assert calls[0].result_status == "timeout_denied"


class _Harness:
    """Fakes for every collaborator, recording what the service asked of them."""

    def __init__(self, *, response):
        self.user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), email="a@b.se")
        self.model = _model(name="gpt-tools")
        self.space = _space(models=[self.model], default=self.model)
        self.target = _assistant(self.model)
        self.session = SimpleNamespace(id=uuid4(), questions=[])
        self.question_id = uuid4()
        self.access_checks = []
        self.placeholder_kwargs = None
        self.link_writer = None
        self.completion_kwargs = None
        self.token_kwargs = None
        self.completed = []
        self.response = response

        async def assert_insight_access(**kwargs):
            self.access_checks.append(kwargs)
            return self.target, self.space

        async def check_space_permissions(space_id):
            self.access_checks.append({"space_id": space_id})

        async def create_placeholder(**kwargs):
            self.placeholder_kwargs = kwargs
            self.link_writer = kwargs["on_created"]
            return self.session, self.question_id, datetime.now(timezone.utc)

        async def complete(**kwargs):
            self.completed.append(kwargs)

        async def get_response(**kwargs):
            self.completion_kwargs = kwargs
            return self.response

        def create_token(user, **kwargs):
            self.token_kwargs = kwargs
            return "scoped-token"

        self.service = InsightConversationService(
            user=self.user,
            analysis_service=SimpleNamespace(
                assert_insight_access=assert_insight_access,
                check_space_permissions=check_space_permissions,
            ),
            session_service=SimpleNamespace(
                create_session_with_question_placeholder=create_placeholder,
                complete_question_with_answer=complete,
            ),
            completion_service=SimpleNamespace(get_response=get_response),
            auth_service=SimpleNamespace(create_scoped_mcp_token=create_token),
            session_repo=SimpleNamespace(
                get_for_insight_conversation=self._get_session,
                delete=self._delete_session,
            ),
            insight_conversation_repo=SimpleNamespace(
                get_by_session_id=self._get_link, list_for_actor=self._list
            ),
        )
        self.link = None
        self.deleted = []
        self.placeholders = []

    async def _get_link(self, session_id, tenant_id):
        return self.link

    async def _get_session(self, session_id, tenant_id):
        return self.session

    async def _delete_session(self, session_id):
        self.deleted.append(session_id)
        return self.session

    async def _list(self, **kwargs):
        self.list_kwargs = kwargs
        return [], 0, None

    def with_link(self, *, own=True, kind="assistant"):
        from eneo.analysis.insight_conversation_repo import InsightConversation

        target = uuid4()
        self.link = InsightConversation(
            id=uuid4(),
            tenant_id=self.user.tenant_id,
            session_id=self.session.id,
            assistant_id=target if kind == "assistant" else None,
            group_chat_id=target if kind == "group_chat" else None,
            actor_user_id=self.user.id if own else uuid4(),
            completion_model_id=self.model.id,
            timezone="Europe/Stockholm",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.service.session_service.create_question_placeholder = self._placeholder
        return self.link

    async def _placeholder(self, **kwargs):
        self.placeholders.append(kwargs)
        return self.question_id, datetime.now(timezone.utc)

    async def start(self, **overrides):
        kwargs = dict(
            assistant_id=uuid4(),
            group_chat_id=None,
            question="Vad frågade användarna om igår?",
            timezone="Europe/Stockholm",
            stream=False,
            selected_range=(date(2026, 8, 1), date(2026, 8, 31)),
        )
        kwargs.update(overrides)
        return await self.service.start(**kwargs)


def _tool_call(**overrides):
    fields = dict(
        server_name="insights",
        tool_name="usage_summary",
        tool_call_id="call-1",
        arguments={"start": "2026-09-07T00:00:00+02:00"},
        result="Usage for assistant 'Bygg' ...",
        result_status="success",
    )
    fields.update(overrides)
    return ToolCallMetadata(**fields)


class TestStart:
    @pytest.mark.asyncio
    async def test_requires_exactly_one_target(self):
        harness = _Harness(response=None)

        with pytest.raises(BadRequestException):
            await harness.start(assistant_id=None, group_chat_id=None)
        with pytest.raises(BadRequestException):
            await harness.start(assistant_id=uuid4(), group_chat_id=uuid4())

    @pytest.mark.asyncio
    async def test_invalid_timezone_is_rejected_before_any_access_check(self):
        harness = _Harness(response=None)

        with pytest.raises(InvalidTimezoneError) as excinfo:
            await harness.start(timezone="Mars/Olympus")
        assert excinfo.value.code == "invalid_timezone"
        assert harness.access_checks == []

    @pytest.mark.asyncio
    async def test_non_streaming_turn_persists_answer_and_tool_calls(self):
        answer = Completion(
            text="Igår ställdes 12 frågor.",
            reasoning_content="think",
            tool_calls_metadata=[_tool_call()],
        )
        harness = _Harness(
            response=SimpleNamespace(
                completion=answer,
                usage=TokenUsage(prompt_tokens=300, completion_tokens=40),
                total_token_count=999,
            )
        )
        assistant_id = uuid4()

        turn = await harness.start(assistant_id=assistant_id)

        # Access: insight view on the target, then the personal-space rule.
        assert harness.access_checks == [
            {"assistant_id": assistant_id, "group_chat_id": None},
            {"space_id": harness.space.id},
        ]
        # Token scoped to the insights target only.
        assert harness.token_kwargs == {
            "insight_target": ("assistant", assistant_id),
            "expires_in": module.INSIGHT_TOKEN_MINUTES,
        }
        # Session and placeholder keyed on the analysed target.
        assert harness.placeholder_kwargs["session_assistant_id"] == assistant_id
        assert harness.placeholder_kwargs["group_chat_id"] is None
        assert harness.placeholder_kwargs["completion_model"] is harness.model
        # Completion contract.
        kwargs = harness.completion_kwargs
        assert kwargs["model"] is harness.model
        assert kwargs["session"] is harness.session
        assert kwargs["extended_logging"] is False
        assert kwargs["require_tool_approval"] is False
        assert kwargs["version"] == 2
        assert kwargs["stream"] is False
        (server,) = kwargs["mcp_servers"]
        assert server.name == "insights"
        assert server.http_auth_config_schema == {"token": "scoped-token"}
        assert all("Target: assistant 'Bygg'." in t.description for t in server.tools)
        assert "assistant 'Bygg'" in kwargs["prompt"]
        assert "2026-08-01 to 2026-08-31" in kwargs["prompt"]
        assert "timezone Europe/Stockholm" in kwargs["prompt"]
        # Persisted turn.
        (completed,) = harness.completed
        assert completed["question_id"] == harness.question_id
        assert completed["answer"] == "Igår ställdes 12 frågor."
        assert completed["reasoning"] == "think"
        assert completed["num_tokens_question"] == 300
        assert completed["num_tokens_answer"] == 40
        assert [c.tool_name for c in completed["tool_calls"]] == ["usage_summary"]
        assert completed["tool_calls"][0].result == "Usage for assistant 'Bygg' ..."
        assert turn.answer == "Igår ställdes 12 frågor."
        assert turn.completion_model is harness.model
        assert turn.target_name == "Bygg"

    @pytest.mark.asyncio
    async def test_group_chat_turn_scopes_token_and_session_to_the_group_chat(self):
        harness = _Harness(
            response=SimpleNamespace(completion="ok", usage=None, total_token_count=5)
        )
        harness.target = SimpleNamespace(name="Team")
        group_chat_id = uuid4()

        await harness.start(assistant_id=None, group_chat_id=group_chat_id)

        assert harness.token_kwargs["insight_target"] == ("group_chat", group_chat_id)
        assert harness.placeholder_kwargs["group_chat_id"] == group_chat_id
        assert harness.placeholder_kwargs["session_assistant_id"] is None
        assert "group chat 'Team'" in harness.completion_kwargs["prompt"]
        (completed,) = harness.completed
        assert completed["answer"] == "ok"
        assert completed["num_tokens_question"] == 5
        assert completed["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_link_row_is_written_inside_the_session_transaction(
        self, monkeypatch
    ):
        harness = _Harness(
            response=SimpleNamespace(completion="ok", usage=None, total_token_count=1)
        )
        recorded = {}

        class FakeRepo:
            def __init__(self, session):
                recorded["db_session"] = session

            async def add(self, **kwargs):
                recorded["add"] = kwargs

        monkeypatch.setattr(module, "InsightConversationRepository", FakeRepo)
        assistant_id = uuid4()
        await harness.start(assistant_id=assistant_id)

        db_session = object()
        await harness.link_writer(db_session, harness.session)

        assert recorded["db_session"] is db_session
        assert recorded["add"] == {
            "tenant_id": harness.user.tenant_id,
            "session_id": harness.session.id,
            "actor_user_id": harness.user.id,
            "timezone": "Europe/Stockholm",
            "assistant_id": assistant_id,
            "group_chat_id": None,
            "completion_model_id": harness.model.id,
        }


async def _chunks(*chunks):
    for chunk in chunks:
        yield chunk


class TestStreaming:
    @pytest.mark.asyncio
    async def test_stream_yields_chunks_persists_tool_calls_and_emits_usage(self):
        stream = _chunks(
            Completion(
                response_type=ResponseType.TOOL_CALL,
                tool_calls_metadata=[_tool_call(result=None, result_status="pending")],
            ),
            Completion(
                response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[_tool_call()]
            ),
            Completion(response_type=ResponseType.REASONING, reasoning_content="hm "),
            Completion(response_type=ResponseType.TEXT, text="Igår "),
            Completion(response_type=ResponseType.TEXT, text="12 frågor."),
            # The adapter's trailing usage carrier has no response type; it
            # must feed the token counts without reaching the client.
            Completion(usage=TokenUsage(prompt_tokens=200, completion_tokens=30)),
        )
        harness = _Harness(
            response=SimpleNamespace(completion=stream, usage=None, total_token_count=1)
        )

        turn = await harness.start(stream=True)
        assert harness.completion_kwargs["stream"] is True
        yielded = [chunk async for chunk in turn.answer]

        assert [c.response_type for c in yielded] == [
            ResponseType.TOOL_CALL,
            ResponseType.TOOL_CALL,
            ResponseType.REASONING,
            ResponseType.TEXT,
            ResponseType.TEXT,
            ResponseType.TOKEN_USAGE,
        ]
        assert yielded[-1].usage.prompt_tokens == 200
        assert yielded[-1].usage.completion_tokens == 30
        (completed,) = harness.completed
        assert completed["answer"] == "Igår 12 frågor."
        assert completed["reasoning"] == "hm "
        assert completed["num_tokens_question"] == 200
        assert completed["num_tokens_answer"] == 30
        (tool_call,) = completed["tool_calls"]
        assert tool_call.result_status == "success"
        assert tool_call.result == "Usage for assistant 'Bygg' ..."

    @pytest.mark.asyncio
    async def test_abort_saves_the_partial_answer_in_the_background(self, monkeypatch):
        saved = {}

        async def fake_persist(**kwargs):
            saved.update(kwargs)

        def fake_schedule(coro):
            saved["scheduled"] = coro
            coro.close()

        monkeypatch.setattr(module, "persist_partial_question_answer", fake_persist)
        monkeypatch.setattr(module, "schedule_background_save", fake_schedule)
        stream = _chunks(
            Completion(response_type=ResponseType.TEXT, text="Igår "),
            Completion(response_type=ResponseType.TEXT, text="12 frågor."),
        )
        harness = _Harness(
            response=SimpleNamespace(completion=stream, usage=None, total_token_count=1)
        )

        turn = await harness.start(stream=True)
        generator = turn.answer
        first = await generator.__anext__()
        assert first.text == "Igår "
        await generator.aclose()

        assert harness.completed == []
        assert "scheduled" in saved

    @pytest.mark.asyncio
    async def test_abort_before_any_text_persists_nothing(self, monkeypatch):
        scheduled = []
        monkeypatch.setattr(module, "schedule_background_save", scheduled.append)
        stream = _chunks(
            Completion(
                response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[_tool_call()]
            ),
            Completion(response_type=ResponseType.TEXT, text="x"),
        )
        harness = _Harness(
            response=SimpleNamespace(completion=stream, usage=None, total_token_count=1)
        )

        turn = await harness.start(stream=True)
        generator = turn.answer
        await generator.__anext__()
        await generator.aclose()

        assert scheduled == []
        assert harness.completed == []


class TestContinueTurn:
    @pytest.mark.asyncio
    async def test_unknown_conversation_is_not_found(self):
        harness = _Harness(response=None)

        with pytest.raises(NotFoundException):
            await harness.service.continue_turn(
                session_id=uuid4(), question="q", stream=False, selected_range=None
            )

    @pytest.mark.asyncio
    async def test_another_actors_conversation_is_forbidden(self):
        harness = _Harness(response=None)
        harness.with_link(own=False)

        with pytest.raises(UnauthorizedException) as excinfo:
            await harness.service.continue_turn(
                session_id=harness.session.id,
                question="q",
                stream=False,
                selected_range=None,
            )
        assert excinfo.value.code == "forbidden_action"
        assert harness.access_checks == []

    @pytest.mark.asyncio
    async def test_follow_up_reuses_the_session_and_rechecks_access(self):
        harness = _Harness(
            response=SimpleNamespace(
                completion="Följdsvar", usage=None, total_token_count=3
            )
        )
        link = harness.with_link(kind="group_chat")
        harness.target = SimpleNamespace(name="Team")

        turn = await harness.service.continue_turn(
            session_id=harness.session.id,
            question="Och förra veckan?",
            stream=False,
            selected_range=None,
        )

        assert harness.access_checks[0] == {
            "assistant_id": None,
            "group_chat_id": link.group_chat_id,
        }
        (placeholder,) = harness.placeholders
        assert placeholder["session"] is harness.session
        assert placeholder["assistant_id"] is None
        assert harness.token_kwargs["insight_target"] == (
            "group_chat",
            link.group_chat_id,
        )
        assert harness.completion_kwargs["session"] is harness.session
        assert "timezone Europe/Stockholm" in harness.completion_kwargs["prompt"]
        assert turn.answer == "Följdsvar"
        assert turn.question_id == harness.question_id


class TestConversationManagement:
    @pytest.mark.asyncio
    async def test_list_requires_one_target_and_checks_access(self):
        harness = _Harness(response=None)

        with pytest.raises(BadRequestException):
            await harness.service.list_conversations(
                assistant_id=None, group_chat_id=None, limit=10, cursor=None
            )

        assistant_id = uuid4()
        await harness.service.list_conversations(
            assistant_id=assistant_id, group_chat_id=None, limit=10, cursor=None
        )
        assert harness.access_checks == [
            {"assistant_id": assistant_id, "group_chat_id": None}
        ]
        assert harness.list_kwargs["actor_user_id"] == harness.user.id
        assert harness.list_kwargs["assistant_id"] == assistant_id

    @pytest.mark.asyncio
    async def test_get_and_delete_are_actor_scoped(self):
        harness = _Harness(response=None)
        harness.with_link(own=False)

        with pytest.raises(UnauthorizedException):
            await harness.service.get_conversation(harness.session.id)
        with pytest.raises(UnauthorizedException):
            await harness.service.delete_conversation(harness.session.id)
        assert harness.deleted == []

        link = harness.with_link(own=True)
        assert (
            await harness.service.get_conversation(harness.session.id)
            is harness.session
        )
        assert await harness.service.delete_conversation(harness.session.id) is link
        assert harness.deleted == [harness.session.id]

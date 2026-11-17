"""Unit tests for the insights conversation service.

Covers model resolution, timezone validation, the completion call's
contract (insights server attached and scoped to the target and the
conversation, no extended logging, tool approval off, always streamed),
persistence of tool calls, the partial save of a stopped turn, the
operator-only access to saved conversations, and the refusal of an analysis
whose source was removed.
"""

from datetime import date, datetime, timezone
from functools import partial
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from eneo.analysis import insight_conversation_service as module
from eneo.analysis.insight_conversation_repo import (
    InsightConversation,
    InsightConversationPage,
)
from eneo.analysis.insight_conversation_service import (
    InsightConversationService,
    finished_tool_calls,
    merge_tool_call_chunk,
)
from eneo.analysis.insight_exceptions import (
    InsightsModelUnavailableError,
    InvalidTimezoneError,
)
from eneo.assistants.assistant import Assistant
from eneo.data_retention.derivations import DerivedSourceRemovedError
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.questions.question import ToolCallInfo
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space import Space


def _classification(level: int, *, enabled: bool = True) -> SecurityClassification:
    return SecurityClassification(
        tenant_id=uuid4(),
        name=f"level {level}",
        security_level=level,
        security_enabled=enabled,
    )


def _model(
    *,
    tool_calling: bool = True,
    accessible: bool = True,
    created: int = 2026,
    name: str = "m",
    classification: SecurityClassification | None = None,
    org_default: bool = False,
) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        can_access=accessible,
        supports_tool_calling=tool_calling,
        security_classification=classification,
        is_org_default=org_default,
        created_at=datetime(created, 1, 1, tzinfo=timezone.utc),
    )


def _space(
    *,
    models: tuple[Any, ...] = (),
    in_space: bool = True,
    classification: SecurityClassification | None = None,
) -> Any:
    """A space with the real classification and default-model policies."""
    space = SimpleNamespace(
        id=uuid4(),
        completion_models=list(models),
        security_classification=classification,
        is_completion_model_in_space=lambda _id: in_space,
    )
    space.allows_security_classification = partial(
        Space.allows_security_classification, space
    )
    space.select_default_completion_model = partial(
        Space.select_default_completion_model, space
    )
    return space


def _assistant(model: Any) -> Any:
    assistant = Assistant.__new__(Assistant)
    assistant.completion_model = model
    assistant.name = "Bygg"
    return assistant


class TestResolveModel:
    resolve = staticmethod(InsightConversationService._resolve_model)

    def test_assistants_own_tool_capable_model_wins(self):
        own = _model()
        space = _space(models=(own, _model(org_default=True)))

        assert self.resolve(_assistant(own), space) is own

    def test_own_model_outside_the_space_is_skipped(self):
        default = _model()
        space = _space(models=(default,), in_space=False)

        assert self.resolve(_assistant(_model()), space) is default

    def test_own_model_without_tool_calling_falls_back_to_the_space_default(self):
        default = _model(org_default=True)
        space = _space(models=(_model(created=2027), default))

        assert self.resolve(_assistant(_model(tool_calling=False)), space) is default

    def test_group_chats_skip_the_own_model_step(self):
        default = _model()
        space = _space(models=(default,))

        assert self.resolve(SimpleNamespace(name="Team"), space) is default

    def test_newest_tool_capable_model_when_the_default_cannot_call_tools(self):
        older = _model(created=2024)
        newest = _model(created=2026)
        space = _space(
            models=(
                older,
                _model(tool_calling=False, org_default=True),
                newest,
                _model(accessible=False, created=2027),
            )
        )

        assert self.resolve(SimpleNamespace(name="Team"), space) is newest

    def test_no_tool_capable_model_raises(self):
        space = _space(models=(_model(tool_calling=False),))

        with pytest.raises(InsightsModelUnavailableError) as excinfo:
            self.resolve(SimpleNamespace(name="Team"), space)
        assert excinfo.value.code == "insights_model_unavailable"

    def test_own_model_below_the_space_classification_is_skipped(self):
        own = _model(classification=_classification(1))
        cleared = _model(classification=_classification(2), created=2024)
        space = _space(models=(own, cleared), classification=_classification(2))

        assert self.resolve(_assistant(own), space) is cleared

    def test_unclassified_model_does_not_meet_a_classified_space(self):
        space = _space(models=(_model(),), classification=_classification(1))

        with pytest.raises(InsightsModelUnavailableError):
            self.resolve(SimpleNamespace(name="Team"), space)

    def test_classification_is_ignored_when_the_tenant_has_it_disabled(self):
        own = _model()
        space = _space(models=(own,), classification=_classification(2, enabled=False))

        assert self.resolve(_assistant(own), space) is own


def _metadata(**overrides: Any) -> ToolCallMetadata:
    fields: dict[str, Any] = dict(
        server_name="insights",
        tool_name="usage_summary",
        title="Usage summary",
        tool_call_id="call-1",
        arguments={"start": "2026-09-07T00:00:00+02:00"},
        result="Usage for assistant 'Bygg' ...",
        result_status="succeeded",
        mcp_tool_name="insights__usage_summary",
        is_internal=True,
        is_bundled=False,
    )
    fields.update(overrides)
    return ToolCallMetadata(**fields)


class TestMergeToolCallChunk:
    def _chunk(self, response_type: ResponseType, **fields: Any) -> Completion:
        return Completion(
            response_type=response_type, tool_calls_metadata=[_metadata(**fields)]
        )

    def test_pending_then_result_merge_into_one_entry(self):
        calls: list[ToolCallInfo] = []

        merge_tool_call_chunk(
            calls,
            self._chunk(
                ResponseType.TOOL_CALL,
                arguments=None,
                result=None,
                result_status="pending",
            ),
        )
        merge_tool_call_chunk(
            calls,
            self._chunk(
                ResponseType.TOOL_CALL,
                arguments={"n": 5},
                result="Top 5 ...",
                result_status="succeeded",
            ),
        )

        (call,) = calls
        assert call.arguments == {"n": 5}
        assert call.result == "Top 5 ..."
        assert call.result_status == "succeeded"
        # What history shows the call by: its server, routing and id.
        assert call.server_name == "insights"
        assert call.is_internal is True
        assert call.tool_call_id == "call-1"
        assert call.mcp_tool_name == "insights__usage_summary"

    def test_later_chunk_does_not_blank_fields_it_lacks(self):
        calls: list[ToolCallInfo] = []
        merge_tool_call_chunk(
            calls, self._chunk(ResponseType.TOOL_CALL, arguments={"n": 5}, result="r")
        )

        merge_tool_call_chunk(
            calls, self._chunk(ResponseType.TOOL_CALL, arguments=None, result=None)
        )

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
        merge_tool_call_chunk(
            calls,
            self._chunk(
                ResponseType.TOOL_APPROVAL_REQUIRED, result=None, result_status=None
            ),
        )
        assert calls[0].approved is None

        merge_tool_call_chunk(
            calls,
            self._chunk(
                ResponseType.TOOL_APPROVAL_TIMEOUT, result=None, result_status=None
            ),
        )

        assert calls[0].approved is False
        assert calls[0].result_status == "timeout_denied"


def test_a_stopped_turn_keeps_the_calls_that_ran_or_were_refused():
    ran = ToolCallInfo(server_name="insights", tool_name="a", result="r")
    refused = ToolCallInfo(server_name="insights", tool_name="b", approved=False)
    running = ToolCallInfo(
        server_name="insights", tool_name="c", result_status="pending"
    )

    assert finished_tool_calls([ran, refused, running]) == [ran, refused]


async def _chunks(*chunks: Completion):
    for chunk in chunks:
        yield chunk


class _Harness:
    """Fakes for every collaborator, recording what the service asked of them."""

    def __init__(self, *, stream: Any = None):
        self.user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), email="a@b.se")
        self.model = _model(name="tools-model")
        self.space = _space(models=(self.model,))
        self.target: Any = _assistant(self.model)
        self.session = SimpleNamespace(id=uuid4(), questions=[])
        self.question_id = uuid4()
        self.access_checks: list[dict[str, Any]] = []
        self.placeholder_kwargs: dict[str, Any] = {}
        self.link_writer: Any = None
        self.completion_kwargs: dict[str, Any] = {}
        self.token_kwargs: dict[str, Any] = {}
        self.completed: list[dict[str, Any]] = []
        self.stream = stream if stream is not None else _chunks()
        self.link: InsightConversation | None = None
        self.deleted: list[Any] = []
        self.placeholders: list[dict[str, Any]] = []
        self.list_kwargs: dict[str, Any] = {}
        self.stored_tool_call: ToolCallInfo | None = None
        # What the session read returns, and whether a miss is a copy whose
        # source was removed.
        self.loaded: Any = self.session
        self.removed_copy = False
        self.removal_checks: list[Any] = []

        async def assert_insight_access(**kwargs: Any):
            self.access_checks.append(kwargs)
            return self.target, self.space

        async def create_placeholder(**kwargs: Any):
            self.placeholder_kwargs = kwargs
            self.link_writer = kwargs["on_created"]
            return self.session, self.question_id, datetime.now(timezone.utc)

        async def complete(**kwargs: Any):
            self.completed.append(kwargs)

        async def get_response(**kwargs: Any):
            self.completion_kwargs = kwargs
            return SimpleNamespace(
                completion=self.stream, usage=None, total_token_count=1
            )

        def create_token(user: Any, **kwargs: Any):
            self.token_kwargs = kwargs
            return "scoped-token"

        async def get_tool_call_result(*, session: Any, tool_call_id: str):
            return self.stored_tool_call

        self.service = InsightConversationService(
            user=self.user,
            analysis_service=SimpleNamespace(
                assert_insight_access=assert_insight_access
            ),
            session_service=SimpleNamespace(
                create_session_with_question_placeholder=create_placeholder,
                create_question_placeholder=self._placeholder,
                complete_question_with_answer=complete,
                get_tool_call_result=get_tool_call_result,
            ),
            completion_service=SimpleNamespace(get_response=get_response),
            auth_service=SimpleNamespace(create_scoped_mcp_token=create_token),
            session_repo=SimpleNamespace(
                get_for_insight_conversation=self._get_session,
                is_removed_copy=self._is_removed_copy,
                delete=self._delete_session,
            ),
            insight_conversation_repo=SimpleNamespace(
                get_by_session_id=self._get_link, list_for_actor=self._list
            ),
        )

    async def _get_link(self, session_id: Any, tenant_id: Any):
        return self.link

    async def _get_session(self, session_id: Any, tenant_id: Any):
        return self.loaded

    async def _is_removed_copy(self, session_id: Any):
        self.removal_checks.append(session_id)
        return self.removed_copy

    async def _delete_session(self, session_id: Any):
        self.deleted.append(session_id)
        return self.session

    async def _list(self, **kwargs: Any):
        self.list_kwargs = kwargs
        return InsightConversationPage(items=[], total=0, next_cursor=None)

    async def _placeholder(self, **kwargs: Any):
        self.placeholders.append(kwargs)
        return self.question_id, datetime.now(timezone.utc)

    def with_link(self, *, own: bool = True, kind: str = "assistant"):
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
        return self.link

    async def start(self, **overrides: Any):
        kwargs: dict[str, Any] = dict(
            assistant_id=uuid4(),
            group_chat_id=None,
            question="Vad frågade användarna om igår?",
            timezone="Europe/Stockholm",
            selected_range=(date(2026, 8, 1), date(2026, 8, 31)),
        )
        kwargs.update(overrides)
        return await self.service.start(**kwargs)


class TestStart:
    async def test_requires_exactly_one_target(self):
        harness = _Harness()

        with pytest.raises(BadRequestException):
            await harness.start(assistant_id=None, group_chat_id=None)
        with pytest.raises(BadRequestException):
            await harness.start(assistant_id=uuid4(), group_chat_id=uuid4())

    async def test_invalid_timezone_is_rejected_before_any_access_check(self):
        harness = _Harness()

        with pytest.raises(InvalidTimezoneError) as excinfo:
            await harness.start(timezone="Mars/Olympus")
        assert excinfo.value.code == "invalid_timezone"
        assert harness.access_checks == []

    async def test_turn_attaches_the_scoped_insights_server_and_streams(self):
        harness = _Harness()
        assistant_id = uuid4()

        turn = await harness.start(assistant_id=assistant_id)

        # One access decision on the target, which covers the personal space.
        assert harness.access_checks == [
            {"assistant_id": assistant_id, "group_chat_id": None}
        ]
        # The token is scoped to the analysed target and to this conversation.
        assert harness.token_kwargs == {
            "insight_target": ("assistant", assistant_id),
            "session_id": harness.session.id,
            "expires_in": module.INSIGHT_TOKEN_MINUTES,
        }
        # Session and placeholder keyed on the analysed target, named by the
        # question.
        assert harness.placeholder_kwargs["name"] == "Vad frågade användarna om igår?"
        assert harness.placeholder_kwargs["session_assistant_id"] == assistant_id
        assert harness.placeholder_kwargs["group_chat_id"] is None
        assert harness.placeholder_kwargs["completion_model"] is harness.model
        # Completion contract.
        kwargs = harness.completion_kwargs
        assert kwargs["model"] is harness.model
        assert kwargs["session"] is harness.session
        assert kwargs["stream"] is True
        assert kwargs["extended_logging"] is False
        assert kwargs["require_tool_approval"] is False
        (server,) = kwargs["mcp_servers"]
        assert server.name == "insights"
        assert server.is_internal is True
        assert server.http_auth_config_schema == {"token": "scoped-token"}
        assert all("Target: assistant 'Bygg'." in t.description for t in server.tools)
        assert "assistant 'Bygg'" in kwargs["prompt"]
        assert "2026-08-01 to 2026-08-31" in kwargs["prompt"]
        assert "timezone Europe/Stockholm" in kwargs["prompt"]
        assert turn.question_id == harness.question_id
        assert turn.completion_model is harness.model
        assert turn.target_name == "Bygg"
        assert turn.space_id == harness.space.id

    async def test_group_chat_turn_scopes_token_and_session_to_the_group_chat(self):
        harness = _Harness()
        harness.target = SimpleNamespace(name="Team")
        group_chat_id = uuid4()

        await harness.start(assistant_id=None, group_chat_id=group_chat_id)

        assert harness.token_kwargs["insight_target"] == ("group_chat", group_chat_id)
        assert harness.placeholder_kwargs["group_chat_id"] == group_chat_id
        assert harness.placeholder_kwargs["session_assistant_id"] is None
        assert "group chat 'Team'" in harness.completion_kwargs["prompt"]

    async def test_link_row_is_written_inside_the_session_transaction(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        harness = _Harness()
        recorded: dict[str, Any] = {}

        class FakeRepo:
            def __init__(self, session: Any):
                recorded["db_session"] = session

            async def add(self, **kwargs: Any):
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


class TestStreaming:
    async def test_stream_passes_chunks_on_persists_tool_calls_and_emits_usage(self):
        stream = _chunks(
            Completion(
                response_type=ResponseType.TOOL_CALL,
                tool_calls_metadata=[
                    _metadata(arguments=None, result=None, result_status="pending")
                ],
            ),
            Completion(
                response_type=ResponseType.TOOL_CALL_DELTA,
                tool_call_id="call-1",
                arguments_delta='{"start": ',
            ),
            Completion(
                response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[_metadata()]
            ),
            Completion(response_type=ResponseType.REASONING, reasoning_content="hm "),
            Completion(response_type=ResponseType.TEXT, text="Igår "),
            Completion(response_type=ResponseType.TEXT, text="12 frågor."),
            # The adapter's trailing usage carrier has no response type; it
            # feeds the token counts without reaching the client.
            Completion(
                usage=TokenUsage(
                    prompt_tokens=200,
                    completion_tokens=30,
                    context_prompt_tokens=150,
                    context_completion_tokens=20,
                )
            ),
        )
        harness = _Harness(stream=stream)

        turn = await harness.start()
        yielded = [chunk async for chunk in turn.answer]

        assert [c.response_type for c in yielded] == [
            ResponseType.TOOL_CALL,
            ResponseType.TOOL_CALL_DELTA,
            ResponseType.TOOL_CALL,
            ResponseType.REASONING,
            ResponseType.TEXT,
            ResponseType.TEXT,
            ResponseType.TOKEN_USAGE,
        ]
        usage = yielded[-1].usage
        assert usage is not None
        assert (usage.prompt_tokens, usage.completion_tokens) == (200, 30)
        assert (usage.context_prompt_tokens, usage.context_completion_tokens) == (
            150,
            20,
        )
        (completed,) = harness.completed
        assert completed["question_id"] == harness.question_id
        assert completed["answer"] == "Igår 12 frågor."
        assert completed["reasoning"] == "hm "
        assert completed["num_tokens_question"] == 200
        assert completed["num_tokens_answer"] == 30
        assert completed["info_blob_chunks"] == []
        (tool_call,) = completed["tool_calls"]
        assert tool_call.result_status == "succeeded"
        assert tool_call.result == "Usage for assistant 'Bygg' ..."
        assert tool_call.is_internal is True

    async def test_stop_saves_the_partial_answer_in_the_background(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        saved: dict[str, Any] = {}

        async def fake_persist(**kwargs: Any):
            saved.update(kwargs)

        def fake_schedule(coro: Any):
            saved["scheduled"] = True
            coro.close()

        monkeypatch.setattr(module, "persist_partial_question_answer", fake_persist)
        monkeypatch.setattr(module, "schedule_background_save", fake_schedule)
        harness = _Harness(
            stream=_chunks(
                Completion(response_type=ResponseType.TEXT, text="Igår "),
                Completion(response_type=ResponseType.TEXT, text="12 frågor."),
            )
        )

        turn = await harness.start()
        first = await turn.answer.__anext__()
        assert first.text == "Igår "
        await turn.answer.aclose()

        assert harness.completed == []
        assert saved.get("scheduled") is True

    async def test_stop_after_tool_calls_keeps_only_the_calls_that_ran(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        saved: dict[str, Any] = {}

        def fake_persist(**kwargs: Any):
            saved.update(kwargs)

        monkeypatch.setattr(module, "persist_partial_question_answer", fake_persist)
        monkeypatch.setattr(module, "schedule_background_save", lambda _: None)
        harness = _Harness(
            stream=_chunks(
                Completion(
                    response_type=ResponseType.TOOL_CALL,
                    tool_calls_metadata=[_metadata()],
                ),
                Completion(
                    response_type=ResponseType.TOOL_CALL,
                    tool_calls_metadata=[
                        _metadata(
                            tool_call_id="call-2", result=None, result_status="pending"
                        )
                    ],
                ),
                Completion(response_type=ResponseType.TEXT, text="x"),
            )
        )

        turn = await harness.start()
        await turn.answer.__anext__()
        await turn.answer.__anext__()
        await turn.answer.aclose()

        assert harness.completed == []
        assert saved["answer"] == ""
        (kept,) = saved["tool_calls"]
        assert kept.tool_call_id == "call-1"
        assert kept.result == "Usage for assistant 'Bygg' ..."

    async def test_provider_error_before_anything_streamed_persists_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        scheduled: list[Any] = []
        monkeypatch.setattr(module, "schedule_background_save", scheduled.append)

        async def failing():
            raise RuntimeError("provider down")
            yield  # pragma: no cover

        harness = _Harness(stream=failing())

        turn = await harness.start()
        with pytest.raises(RuntimeError):
            await turn.answer.__anext__()

        assert scheduled == []
        assert harness.completed == []

    async def test_the_completion_stream_is_closed_when_the_client_stops(self):
        closed: list[bool] = []

        async def endless():
            try:
                while True:
                    yield Completion(response_type=ResponseType.TEXT, text="x")
            finally:
                closed.append(True)

        harness = _Harness(stream=endless())
        turn = await harness.start()
        await turn.answer.__anext__()
        await turn.answer.aclose()

        assert closed == [True]

    async def test_an_answer_never_started_still_closes_its_completion_stream(self):
        closed: list[bool] = []

        class Stream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def aclose(self):
                closed.append(True)

        harness = _Harness(stream=Stream())
        turn = await harness.start()
        await turn.answer.aclose()

        assert closed == [True]


class TestContinueTurn:
    async def test_unknown_conversation_is_not_found(self):
        harness = _Harness()

        with pytest.raises(NotFoundException):
            await harness.service.continue_turn(
                session_id=uuid4(), question="q", selected_range=None
            )

    async def test_another_actors_conversation_is_forbidden(self):
        harness = _Harness()
        harness.with_link(own=False)

        with pytest.raises(UnauthorizedException) as excinfo:
            await harness.service.continue_turn(
                session_id=harness.session.id, question="q", selected_range=None
            )
        assert excinfo.value.code == "forbidden_action"
        assert harness.access_checks == []

    async def test_follow_up_reuses_the_session_and_rechecks_access(self):
        harness = _Harness()
        link = harness.with_link(kind="group_chat")
        harness.target = SimpleNamespace(name="Team")

        turn = await harness.service.continue_turn(
            session_id=harness.session.id,
            question="Och förra veckan?",
            selected_range=None,
        )

        assert harness.access_checks == [
            {"assistant_id": None, "group_chat_id": link.group_chat_id}
        ]
        (placeholder,) = harness.placeholders
        assert placeholder["session"] is harness.session
        assert placeholder["assistant_id"] is None
        assert harness.token_kwargs["insight_target"] == (
            "group_chat",
            link.group_chat_id,
        )
        assert harness.token_kwargs["session_id"] == harness.session.id
        assert harness.completion_kwargs["session"] is harness.session
        assert "timezone Europe/Stockholm" in harness.completion_kwargs["prompt"]
        assert turn.question_id == harness.question_id


class TestConversationManagement:
    async def test_list_requires_one_target_and_checks_access(self):
        harness = _Harness()

        with pytest.raises(BadRequestException):
            await harness.service.list_conversations(
                assistant_id=None, group_chat_id=None, limit=10, cursor=None
            )

        assistant_id = uuid4()
        await harness.service.list_conversations(
            assistant_id=assistant_id, group_chat_id=None, limit=10, cursor="c"
        )
        assert harness.access_checks == [
            {"assistant_id": assistant_id, "group_chat_id": None}
        ]
        assert harness.list_kwargs["actor_user_id"] == harness.user.id
        assert harness.list_kwargs["assistant_id"] == assistant_id
        assert harness.list_kwargs["cursor"] == "c"

    async def test_reads_and_delete_are_the_operators_own(self):
        harness = _Harness()
        harness.with_link(own=False)

        with pytest.raises(UnauthorizedException):
            await harness.service.get_conversation(harness.session.id)
        with pytest.raises(UnauthorizedException):
            await harness.service.get_tool_call_result(harness.session.id, "call-1")
        with pytest.raises(UnauthorizedException):
            await harness.service.delete_conversation(harness.session.id)
        assert harness.deleted == []
        assert harness.access_checks == []

        link = harness.with_link(own=True)
        assert (
            await harness.service.get_conversation(harness.session.id)
            is harness.session
        )
        assert harness.access_checks == [
            {"assistant_id": link.assistant_id, "group_chat_id": None}
        ]
        assert await harness.service.delete_conversation(harness.session.id) is link
        assert harness.deleted == [harness.session.id]

    async def test_tool_call_result_rechecks_access_and_is_not_found_when_unknown(
        self,
    ):
        harness = _Harness()
        harness.with_link(own=True)

        with pytest.raises(NotFoundException):
            await harness.service.get_tool_call_result(harness.session.id, "nope")

        harness.stored_tool_call = ToolCallInfo(
            server_name="insights", tool_name="usage_summary", result="r"
        )
        assert (
            await harness.service.get_tool_call_result(harness.session.id, "call-1")
            is harness.stored_tool_call
        )
        assert len(harness.access_checks) == 2


class TestRemovedSource:
    """An analysis whose source was removed reads as nothing anywhere."""

    async def test_every_read_and_a_follow_up_refuse_it_after_the_access_check(
        self,
    ):
        """Mutants: a read or the follow-up answers 404 instead of the typed
        refusal, or a follow-up writes its question before refusing."""
        harness = _Harness()
        harness.with_link(own=True)
        harness.loaded = None
        harness.removed_copy = True

        with pytest.raises(DerivedSourceRemovedError):
            await harness.service.get_conversation(harness.session.id)
        with pytest.raises(DerivedSourceRemovedError):
            await harness.service.get_tool_call_result(harness.session.id, "call-1")
        with pytest.raises(DerivedSourceRemovedError):
            await harness.service.continue_turn(
                session_id=harness.session.id, question="q", selected_range=None
            )

        assert len(harness.access_checks) == 3
        assert harness.placeholders == []
        assert harness.completion_kwargs == {}

    async def test_a_missing_session_stays_not_found(self):
        harness = _Harness()
        harness.with_link(own=True)
        harness.loaded = None

        with pytest.raises(NotFoundException):
            await harness.service.get_conversation(harness.session.id)

    async def test_another_operator_learns_nothing_about_the_removal(self):
        """Mutant: the removal is checked before the caller's ownership."""
        harness = _Harness()
        harness.with_link(own=False)
        harness.loaded = None
        harness.removed_copy = True

        with pytest.raises(UnauthorizedException):
            await harness.service.get_conversation(harness.session.id)
        assert harness.removal_checks == []

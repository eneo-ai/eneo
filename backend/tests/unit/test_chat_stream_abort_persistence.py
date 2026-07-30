"""Tests for chat-stream-abort persistence (issue #349).

The bug: when an SSE chat stream is aborted (client disconnect), the user's question
and the partially-streamed assistant reply are not persisted. The fix splits chat
persistence into two phases:

1. A placeholder row is inserted before the LLM stream begins.
2. The row is updated when the stream completes — or, on abort, a fire-and-forget
   background task uses a fresh DB session to update with the partial answer.

These tests cover the unit-level building blocks. The end-to-end abort flow is
exercised in tests/integration/services/test_conversation_stream_abort.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ResponseType,
    TokenUsage,
)
from eneo.sessions import session_service as session_service_module
from eneo.sessions.session_service import (
    SessionService,
    persist_partial_question_answer,
)

# ----- Helpers --------------------------------------------------------------


def _make_user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), active_api_key=None)


def _make_session_service(*, question_id: UUID | None = None) -> SessionService:
    """Build a SessionService with mocked repos and a no-op _write_transaction context."""

    session = MagicMock()
    session.in_transaction.return_value = True  # skip session.begin() entirely
    session.begin = MagicMock()

    session_repo = SimpleNamespace(session=session, add=AsyncMock())
    return_value = SimpleNamespace(
        id=question_id or uuid4(), created_at=datetime.now(timezone.utc)
    )
    question_repo = AsyncMock()
    question_repo.session = session
    question_repo.add = AsyncMock(return_value=return_value)
    question_repo.update_with_answer = AsyncMock(return_value=None)

    return SessionService(
        session_repo=session_repo,
        question_repo=question_repo,
        user=_make_user(),
    )


def _make_session_in_db() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), questions=[])


def _skill_runtime_args(
    *,
    changed: bool = False,
    initial_skill_context_tokens: int = 0,
    final_skill_context_tokens: int = 0,
) -> dict[str, object]:
    snapshot = SimpleNamespace(
        changed=changed,
        measurement=SimpleNamespace(tokens=final_skill_context_tokens),
    )
    return {
        "skill_plan": SimpleNamespace(
            active_provenance=MagicMock(return_value=()),
            activation_evidence=MagicMock(
                return_value=SimpleNamespace(
                    effective_mode="selective",
                    skill_context_tokens=final_skill_context_tokens,
                )
            ),
        ),
        "skill_runtime": SimpleNamespace(snapshot=MagicMock(return_value=snapshot)),
        "selected_model_route": "openai/gpt-4",
        "initial_skill_context_tokens": initial_skill_context_tokens,
    }


@contextmanager
def _independent_placeholder_store(service: SessionService) -> Iterator[None]:
    @asynccontextmanager
    async def _session_scope():
        yield service.question_repo.session

    @asynccontextmanager
    async def _transaction_scope():
        yield

    service.question_repo.session.begin.return_value = _transaction_scope()
    with (
        patch.object(
            session_service_module.sessionmanager,
            "session",
            _session_scope,
        ),
        patch.object(
            session_service_module,
            "QuestionRepository",
            return_value=service.question_repo,
        ),
    ):
        yield


# ----- SessionService.create_question_placeholder ---------------------------


@pytest.mark.asyncio
async def test_create_question_placeholder_inserts_row_with_seeded_question_tokens():
    """Placeholder commits with the user's question, empty answer, and a best-effort
    `count_tokens(question, model)` so abort-only requests don't undercount in
    analytics."""
    new_question_id = uuid4()
    service = _make_session_service(question_id=new_question_id)

    with (
        patch.object(
            session_service_module, "count_tokens", return_value=42
        ) as count_mock,
        _independent_placeholder_store(service),
    ):
        returned, returned_created_at = await service.create_question_placeholder(
            question="how do I cancel a stream?",
            session=_make_session_in_db(),
            files=None,
            assistant_id=uuid4(),
            completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
        )

    assert returned == new_question_id
    assert returned_created_at is not None
    count_mock.assert_called_once_with("how do I cancel a stream?", "gpt-4")
    service.question_repo.add.assert_awaited_once()

    args, kwargs = service.question_repo.add.call_args
    question_add = args[0]
    assert question_add.question == "how do I cancel a stream?"
    assert question_add.answer == ""
    assert question_add.num_tokens_question == 42
    assert question_add.num_tokens_answer == 0
    assert question_add.tenant_id == service.user.tenant_id
    # No info_blob_chunks / generated_files / web_search on a placeholder
    assert kwargs.get("info_blob_chunks") == []
    assert kwargs.get("generated_files") == []
    assert kwargs.get("web_search_results") == []


@pytest.mark.asyncio
async def test_create_question_placeholder_falls_back_to_zero_when_count_tokens_raises():
    """tiktoken can raise on unknown model names — the placeholder write must still
    succeed with num_tokens_question=0 instead of crashing the request."""
    service = _make_session_service()

    def boom(*_: object, **__: object) -> int:
        raise KeyError("unknown model")

    with (
        patch.object(session_service_module, "count_tokens", side_effect=boom),
        _independent_placeholder_store(service),
    ):
        await service.create_question_placeholder(
            question="test",
            session=_make_session_in_db(),
            files=None,
            assistant_id=uuid4(),
            completion_model=SimpleNamespace(id=uuid4(), name="exotic-model-9000"),
        )

    service.question_repo.add.assert_awaited_once()
    args, _ = service.question_repo.add.call_args
    assert args[0].num_tokens_question == 0


@pytest.mark.asyncio
async def test_create_question_placeholder_without_model_records_zero_tokens():
    """If no completion model is configured (e.g. some sysadmin/test paths), don't
    even try to count — store 0 and move on."""
    service = _make_session_service()

    with (
        patch.object(session_service_module, "count_tokens") as count_mock,
        _independent_placeholder_store(service),
    ):
        await service.create_question_placeholder(
            question="test",
            session=_make_session_in_db(),
            files=None,
            assistant_id=None,
            completion_model=None,
        )

    count_mock.assert_not_called()
    args, _ = service.question_repo.add.call_args
    assert args[0].num_tokens_question == 0


# ----- SessionService.complete_question_with_answer -------------------------


@pytest.mark.asyncio
async def test_complete_question_with_answer_calls_repo_update():
    service = _make_session_service()
    question_id = uuid4()
    completion_model = SimpleNamespace(id=uuid4(), name="gpt-4")

    await service.complete_question_with_answer(
        question_id=question_id,
        answer="Aborting an SSE stream is done by calling abort() on the AbortController.",
        num_tokens_question=42,
        num_tokens_answer=7,
        context_prompt_tokens=24,
        context_completion_tokens=5,
        skill_context_tokens=11,
        completion_model=completion_model,
        info_blob_chunks=[],
        generated_files=None,
        logging_details=None,
        web_search_results=None,
        tool_calls=None,
    )

    service.question_repo.update_with_answer.assert_awaited_once()
    kwargs = service.question_repo.update_with_answer.call_args.kwargs
    assert kwargs["question_id"] == question_id
    assert kwargs["tenant_id"] == service.user.tenant_id
    assert kwargs["answer"].startswith("Aborting an SSE stream")
    assert kwargs["num_tokens_question"] == 42
    assert kwargs["num_tokens_answer"] == 7
    assert kwargs["context_prompt_tokens"] == 24
    assert kwargs["context_completion_tokens"] == 5
    assert kwargs["skill_context_tokens"] == 11
    assert kwargs["completion_model_id"] == completion_model.id


# ----- persist_partial_question_answer --------------------------------------


@pytest.mark.asyncio
async def test_persist_partial_question_answer_uses_fresh_session():
    """The abort helper must NOT depend on the request-scoped AsyncSession — it has
    to open its own via sessionmanager.session(), since by the time we hit `finally`
    on aclose() the request session may have been torn down by FastAPI."""

    captured: dict[str, object] = {}

    fresh_session = MagicMock()

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[object]:
        captured["entered"] = True
        yield fresh_session

    @asynccontextmanager
    async def fake_begin() -> AsyncIterator[None]:
        captured["txn_opened"] = True
        yield

    fresh_session.begin = MagicMock(return_value=fake_begin())

    update_called: dict[str, object] = {}

    async def fake_update(**kwargs: object) -> None:
        update_called.update(kwargs)

    class FakeRepo:
        def __init__(self, _session: object) -> None:
            captured["repo_session"] = _session

        async def update_with_answer(self, **kwargs: object) -> None:
            await fake_update(**kwargs)

    tenant_id = uuid4()
    question_id = uuid4()

    with (
        patch.object(
            session_service_module,
            "sessionmanager",
            SimpleNamespace(session=fake_session),
        ),
        patch.object(session_service_module, "QuestionRepository", FakeRepo),
    ):
        await persist_partial_question_answer(
            tenant_id=tenant_id,
            question_id=question_id,
            answer="part",
            num_tokens_answer=2,
            completion_model_id=None,
        )

    assert captured.get("entered") is True
    assert captured.get("txn_opened") is True
    assert captured.get("repo_session") is fresh_session
    assert update_called["question_id"] == question_id
    assert update_called["tenant_id"] == tenant_id
    assert update_called["answer"] == "part"
    assert update_called["num_tokens_answer"] == 2


@pytest.mark.asyncio
async def test_persist_partial_question_answer_swallows_db_errors():
    """Best-effort cleanup — must not raise even if the DB is unreachable."""

    @asynccontextmanager
    async def broken_session() -> AsyncIterator[object]:
        raise RuntimeError("db down")
        yield None  # pragma: no cover  (unreachable, keeps generator a generator)

    with patch.object(
        session_service_module,
        "sessionmanager",
        SimpleNamespace(session=broken_session),
    ):
        # Must not raise — broken DB is logged, not propagated
        await persist_partial_question_answer(
            tenant_id=uuid4(),
            question_id=uuid4(),
            answer="x",
            num_tokens_answer=1,
        )


# ----- _handle_response streaming abort path --------------------------------


def _make_assistant_service_for_streaming(
    session_service: AsyncMock,
) -> SimpleNamespace:
    """Build the bare minimum object on which AssistantService._handle_response can be
    invoked. The method only uses self.user.tenant_id, self.session_service, and
    (for FILES chunks) self.file_service.save_image_from_bytes."""

    return SimpleNamespace(
        user=_make_user(),
        session_service=session_service,
        file_service=SimpleNamespace(save_image_from_bytes=AsyncMock()),
    )


async def _drain_until(gen, n: int) -> list[Completion]:
    """Pull the first n chunks from an async generator."""
    out: list[Completion] = []
    async for chunk in gen:
        out.append(chunk)
        if len(out) >= n:
            break
    return out


@pytest.mark.asyncio
async def test_streaming_handle_response_schedules_partial_save_on_abort():
    """When the SSE consumer aborts after some TEXT chunks have arrived, the streaming
    generator's `finally` must fire-and-forget a background save of the partial answer."""

    async def fake_completion_stream():
        for text in ["hello ", "wor", "ld"]:
            yield Completion(
                reasoning_token_count=0,
                response_type=ResponseType.TEXT,
                text=text,
            )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=5,
        usage=None,
        extended_logging=None,
    )
    datastore_result = SimpleNamespace(info_blobs=[], no_duplicate_chunks=[])

    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    question_id = uuid4()
    completion_model = SimpleNamespace(id=uuid4(), name="gpt-4")

    persist_calls: list[dict[str, object]] = []

    async def tracking_persist(**kwargs: object) -> None:
        persist_calls.append(kwargs)

    # Patch BOTH places: assistant_service does a deferred `from eneo.sessions...
    # import persist_partial_question_answer` inside finally, so patch the source
    # module attribute.
    with patch.object(
        session_service_module,
        "persist_partial_question_answer",
        tracking_persist,
    ):
        from eneo.assistants.assistant_service import AssistantService

        gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=datastore_result,
            question="hello?",
            files=[],
            completion_model=completion_model,
            session=_make_session_in_db(),
            stream=True,
            assistant_id=uuid4(),
            question_id=question_id,
            **_skill_runtime_args(),
        )

        # Pull 2 chunks then close — simulates the SSE client disconnecting after
        # receiving the first two tokens.
        chunks = await _drain_until(gen, 2)
        assert [c.text for c in chunks] == ["hello ", "wor"]

        await gen.aclose()

        # Let the scheduled background task run.
        await asyncio.sleep(0)

    assert len(persist_calls) == 1, "expected exactly one partial-save scheduled"
    call = persist_calls[0]
    assert call["question_id"] == question_id
    assert call["tenant_id"] == svc.user.tenant_id
    assert call["answer"] == "hello wor"  # only what was streamed before close

    # The normal-completion path must NOT have run.
    session_service_mock.complete_question_with_answer.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_abort_persists_changed_skill_evidence_without_text():
    async def fake_completion_stream():
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.ENEO_EVENT,
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=5,
        usage=None,
        extended_logging=None,
    )
    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)
    persist_calls: list[dict[str, object]] = []

    async def tracking_persist(**kwargs: object) -> None:
        persist_calls.append(kwargs)

    with patch.object(
        session_service_module,
        "persist_partial_question_answer",
        tracking_persist,
    ):
        from eneo.assistants.assistant_service import AssistantService

        gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=SimpleNamespace(
                info_blobs=[],
                no_duplicate_chunks=[],
            ),
            question="hello?",
            files=[],
            completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
            session=_make_session_in_db(),
            stream=True,
            assistant_id=uuid4(),
            question_id=uuid4(),
            **_skill_runtime_args(changed=True),
        )

        await _drain_until(gen, 1)
        await gen.aclose()
        await asyncio.sleep(0)

    assert len(persist_calls) == 1
    assert persist_calls[0]["answer"] == ""
    assert persist_calls[0]["skill_provenance"] == ()
    assert persist_calls[0]["skill_activation"] is not None
    session_service_mock.complete_question_with_answer.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_handle_response_no_partial_save_on_normal_completion():
    """When the stream completes naturally, complete_question_with_answer must be
    called (once) and no partial-save task should be scheduled."""

    async def fake_completion_stream():
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.TEXT,
            text="ok",
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=3,
        usage=None,
        extended_logging=None,
    )
    datastore_result = SimpleNamespace(info_blobs=[], no_duplicate_chunks=[])

    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    question_id = uuid4()
    completion_model = SimpleNamespace(id=uuid4(), name="gpt-4")

    persist_calls: list[dict[str, object]] = []

    async def tracking_persist(**kwargs: object) -> None:
        persist_calls.append(kwargs)

    with patch.object(
        session_service_module,
        "persist_partial_question_answer",
        tracking_persist,
    ):
        from eneo.assistants.assistant_service import AssistantService

        gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=datastore_result,
            question="hello?",
            files=[],
            completion_model=completion_model,
            session=_make_session_in_db(),
            stream=True,
            assistant_id=uuid4(),
            question_id=question_id,
            **_skill_runtime_args(
                initial_skill_context_tokens=2,
                final_skill_context_tokens=7,
            ),
        )

        # Drain the generator fully — this is the "normal completion" path.
        collected: list[Completion] = [c async for c in gen]

    # The TEXT chunk + the trailing TOKEN_USAGE chunk are both expected.
    assert any(c.response_type == ResponseType.TEXT for c in collected)
    assert any(c.response_type == ResponseType.TOKEN_USAGE for c in collected)

    session_service_mock.complete_question_with_answer.assert_awaited_once()
    update_kwargs = session_service_mock.complete_question_with_answer.call_args.kwargs
    assert update_kwargs["question_id"] == question_id
    assert update_kwargs["answer"] == "ok"
    assert update_kwargs["num_tokens_question"] == 8
    assert update_kwargs["skill_provenance"] == ()
    assert update_kwargs["skill_activation"] is not None

    # Crucially: no partial-save task was scheduled on a clean finish.
    assert persist_calls == []


@pytest.mark.asyncio
async def test_streaming_handle_response_persists_cumulative_input_estimate():
    async def fake_completion_stream():
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.TEXT,
            text="ok",
        )
        yield Completion(
            reasoning_token_count=0,
            stop=True,
            usage=TokenUsage(
                prompt_tokens=None,
                completion_tokens=20,
                context_prompt_tokens=None,
                context_completion_tokens=None,
            ),
            input_token_estimate=41,
            context_input_token_estimate=23,
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=3,
        usage=None,
        extended_logging=None,
    )
    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    from eneo.assistants.assistant_service import AssistantService

    with patch("eneo.assistants.assistant_service.count_tokens", return_value=7):
        gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=SimpleNamespace(info_blobs=[], no_duplicate_chunks=[]),
            question="hello?",
            files=[],
            completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
            session=_make_session_in_db(),
            stream=True,
            assistant_id=uuid4(),
            question_id=uuid4(),
            assistant_selector_tokens=2,
            **_skill_runtime_args(
                initial_skill_context_tokens=2,
                final_skill_context_tokens=7,
            ),
        )
        async for _ in gen:
            pass

    persisted = session_service_mock.complete_question_with_answer.await_args.kwargs
    assert persisted["num_tokens_question"] == 43
    assert persisted["num_tokens_answer"] == 20
    assert persisted["context_prompt_tokens"] == 23
    assert persisted["context_completion_tokens"] == 7


@pytest.mark.asyncio
async def test_streaming_handle_response_separates_billing_from_context_usage():
    async def fake_completion_stream():
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.TEXT,
            text="ok",
        )
        yield Completion(
            stop=True,
            usage=TokenUsage(
                prompt_tokens=1020,
                completion_tokens=60,
                context_prompt_tokens=520,
                context_completion_tokens=40,
            ),
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=500,
        usage=None,
        extended_logging=None,
    )
    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    from eneo.assistants.assistant_service import AssistantService

    gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
        svc,  # pyright: ignore[reportArgumentType]
        response=response,
        datastore_result=SimpleNamespace(info_blobs=[], no_duplicate_chunks=[]),
        question="hello?",
        files=[],
        completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
        session=_make_session_in_db(),
        stream=True,
        assistant_id=uuid4(),
        question_id=uuid4(),
        **_skill_runtime_args(final_skill_context_tokens=37),
    )
    collected = [completion async for completion in gen]

    persisted = session_service_mock.complete_question_with_answer.await_args.kwargs
    assert persisted["num_tokens_question"] == 1020
    assert persisted["num_tokens_answer"] == 60
    assert persisted["context_prompt_tokens"] == 520
    assert persisted["context_completion_tokens"] == 40
    assert persisted["skill_context_tokens"] == 37

    usage_event = next(
        completion
        for completion in collected
        if completion.response_type == ResponseType.TOKEN_USAGE
    )
    assert usage_event.usage is not None
    assert usage_event.usage.prompt_tokens == 1020
    assert usage_event.usage.completion_tokens == 60
    assert usage_event.usage.context_prompt_tokens == 520
    assert usage_event.usage.context_completion_tokens == 40
    assert usage_event.skill_context_tokens == 37


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("usage", "context_input_token_estimate"),
    [
        pytest.param(
            TokenUsage(
                prompt_tokens=1020,
                completion_tokens=60,
                context_prompt_tokens=520,
                context_completion_tokens=40,
            ),
            999,
            id="provider-final-request-usage-wins",
        ),
        pytest.param(
            TokenUsage(
                prompt_tokens=None,
                completion_tokens=60,
                context_prompt_tokens=None,
                context_completion_tokens=None,
            ),
            520,
            id="final-request-estimate-fallback",
        ),
    ],
)
async def test_non_streaming_handle_response_persists_context_without_changing_cost(
    usage: TokenUsage,
    context_input_token_estimate: int,
):
    response = SimpleNamespace(
        completion=Completion(
            text="ok",
            context_input_token_estimate=context_input_token_estimate,
        ),
        total_token_count=1020,
        usage=usage,
        extended_logging=None,
    )
    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    from eneo.assistants.assistant_service import AssistantService

    with patch("eneo.assistants.assistant_service.count_tokens", return_value=40):
        answer = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=SimpleNamespace(info_blobs=[], no_duplicate_chunks=[]),
            question="hello?",
            files=[],
            completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
            session=_make_session_in_db(),
            stream=False,
            assistant_id=uuid4(),
            question_id=uuid4(),
            **_skill_runtime_args(final_skill_context_tokens=37),
        )

    assert answer == "ok"
    persisted = session_service_mock.complete_question_with_answer.await_args.kwargs
    assert persisted["num_tokens_question"] == 1020
    assert persisted["num_tokens_answer"] == 60
    assert persisted["context_prompt_tokens"] == 520
    assert persisted["context_completion_tokens"] == 40
    assert persisted["skill_context_tokens"] == 37


@pytest.mark.asyncio
async def test_streaming_handle_response_keeps_distinct_refs_with_same_uri():
    first_ref = McpToolReference(
        id=uuid4(),
        tool_call_id="call_1",
        mcp_tool_name="server__tool",
        uri="https://example.test/shared",
        mime_type="text/plain",
        content="first",
        meta={},
        order=0,
    )
    second_ref = McpToolReference(
        id=uuid4(),
        tool_call_id="call_2",
        mcp_tool_name="server__tool",
        uri="https://example.test/shared",
        mime_type="text/plain",
        content="second",
        meta={},
        order=1,
    )

    async def fake_completion_stream():
        for ref in (first_ref, second_ref):
            yield Completion(
                reasoning_token_count=0,
                response_type=ResponseType.TOOL_CALL,
                mcp_tool_references=[ref],
            )
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.TEXT,
            text="ok",
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=3,
        usage=None,
        extended_logging=None,
    )
    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    from eneo.assistants.assistant_service import AssistantService

    gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
        svc,  # pyright: ignore[reportArgumentType]
        response=response,
        datastore_result=SimpleNamespace(info_blobs=[], no_duplicate_chunks=[]),
        question="hello?",
        files=[],
        completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
        session=_make_session_in_db(),
        stream=True,
        assistant_id=uuid4(),
        question_id=uuid4(),
        **_skill_runtime_args(),
    )
    async for _ in gen:
        pass

    update_kwargs = session_service_mock.complete_question_with_answer.call_args.kwargs
    assert update_kwargs["mcp_tool_references"] == [first_ref, second_ref]


@pytest.mark.asyncio
async def test_streaming_handle_response_persists_reasoning_separately_from_answer():
    """REASONING chunks must accumulate into the persisted `reasoning` field, never
    into the answer text."""

    async def fake_completion_stream():
        for reasoning in ["let me ", "think"]:
            yield Completion(
                reasoning_token_count=0,
                response_type=ResponseType.REASONING,
                reasoning_content=reasoning,
            )
        yield Completion(
            reasoning_token_count=2,
            response_type=ResponseType.TEXT,
            text="ok",
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=3,
        usage=None,
        extended_logging=None,
    )
    datastore_result = SimpleNamespace(info_blobs=[], no_duplicate_chunks=[])

    session_service_mock = AsyncMock()
    session_service_mock.complete_question_with_answer = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    from eneo.assistants.assistant_service import AssistantService

    gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
        svc,  # pyright: ignore[reportArgumentType]
        response=response,
        datastore_result=datastore_result,
        question="hello?",
        files=[],
        completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
        session=_make_session_in_db(),
        stream=True,
        assistant_id=uuid4(),
        question_id=uuid4(),
        **_skill_runtime_args(),
    )

    async for _ in gen:
        pass

    session_service_mock.complete_question_with_answer.assert_awaited_once()
    update_kwargs = session_service_mock.complete_question_with_answer.call_args.kwargs
    assert update_kwargs["answer"] == "ok"
    assert update_kwargs["reasoning"] == "let me think"


@pytest.mark.asyncio
async def test_streaming_handle_response_partial_save_keeps_reasoning_on_abort():
    """Aborting while the model is still thinking (no TEXT yet) must still schedule
    a partial save carrying the streamed reasoning — the trace is part of the
    transparency record even for interrupted turns."""

    async def fake_completion_stream():
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.REASONING,
            reasoning_content="thinking hard",
        )
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.TEXT,
            text="never reached",
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=0,
        usage=None,
        extended_logging=None,
    )
    datastore_result = SimpleNamespace(info_blobs=[], no_duplicate_chunks=[])

    session_service_mock = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    persist_calls: list[dict[str, object]] = []

    async def tracking_persist(**kwargs: object) -> None:
        persist_calls.append(kwargs)

    with patch.object(
        session_service_module,
        "persist_partial_question_answer",
        tracking_persist,
    ):
        from eneo.assistants.assistant_service import AssistantService

        gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=datastore_result,
            question="hello?",
            files=[],
            completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
            session=_make_session_in_db(),
            stream=True,
            assistant_id=uuid4(),
            question_id=uuid4(),
            **_skill_runtime_args(),
        )

        chunks = await _drain_until(gen, 1)
        assert chunks[0].response_type == ResponseType.REASONING

        await gen.aclose()
        await asyncio.sleep(0)

    assert len(persist_calls) == 1
    assert persist_calls[0]["answer"] == ""
    assert persist_calls[0]["reasoning"] == "thinking hard"

    session_service_mock.complete_question_with_answer.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_handle_response_skips_partial_save_when_no_content():
    """When the stream is aborted *before* any TEXT chunk arrives — or the LLM
    raises before producing output — `response_string` is empty and an UPDATE
    setting answer='' would be a no-op against the placeholder. The finally must
    skip the redundant background save in that case."""

    async def empty_then_error_stream():
        # Mimic an LLM that errors before the first chunk is yielded.
        if False:  # pragma: no cover - keeps it an async generator
            yield None
        raise RuntimeError("upstream LLM unreachable")

    response = SimpleNamespace(
        completion=empty_then_error_stream(),
        total_token_count=0,
        usage=None,
        extended_logging=None,
    )
    datastore_result = SimpleNamespace(info_blobs=[], no_duplicate_chunks=[])

    session_service_mock = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    persist_calls: list[dict[str, object]] = []

    async def tracking_persist(**kwargs: object) -> None:
        persist_calls.append(kwargs)

    with patch.object(
        session_service_module,
        "persist_partial_question_answer",
        tracking_persist,
    ):
        from eneo.assistants.assistant_service import AssistantService

        gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=datastore_result,
            question="hello?",
            files=[],
            completion_model=SimpleNamespace(id=uuid4(), name="gpt-4"),
            session=_make_session_in_db(),
            stream=True,
            assistant_id=uuid4(),
            question_id=uuid4(),
            **_skill_runtime_args(),
        )

        with pytest.raises(RuntimeError, match="upstream LLM unreachable"):
            async for _ in gen:
                pass

        await asyncio.sleep(0)

    assert persist_calls == [], (
        "no partial-save should be scheduled when no content was streamed; "
        "the placeholder row already captures the user's question"
    )


@pytest.mark.asyncio
async def test_streaming_handle_response_count_tokens_failure_still_persists_partial():
    """The pre-fix code computed count_tokens inline inside `finally` — if tiktoken
    raised on an exotic model name, the asyncio.create_task call was never reached
    and the partial save collapsed silently. Verify the safe wrapper now lets the
    save through with num_tokens_answer=0."""

    async def fake_completion_stream():
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.TEXT,
            text="partial",
        )
        # Hang on the next chunk — the consumer will aclose() in between.
        await asyncio.sleep(10)
        yield Completion(
            reasoning_token_count=0,
            response_type=ResponseType.TEXT,
            text="lost",
        )

    response = SimpleNamespace(
        completion=fake_completion_stream(),
        total_token_count=2,
        usage=None,
        extended_logging=None,
    )
    datastore_result = SimpleNamespace(info_blobs=[], no_duplicate_chunks=[])

    session_service_mock = AsyncMock()
    svc = _make_assistant_service_for_streaming(session_service_mock)

    persist_calls: list[dict[str, object]] = []

    async def tracking_persist(**kwargs: object) -> None:
        persist_calls.append(kwargs)

    def boom(*_: object, **__: object) -> int:
        raise KeyError("unknown model")

    with (
        patch.object(
            session_service_module,
            "persist_partial_question_answer",
            tracking_persist,
        ),
        patch.object(session_service_module, "count_tokens", side_effect=boom),
    ):
        from eneo.assistants.assistant_service import AssistantService

        gen = await AssistantService._handle_response(  # pyright: ignore[reportPrivateUsage]
            svc,  # pyright: ignore[reportArgumentType]
            response=response,
            datastore_result=datastore_result,
            question="hi",
            files=[],
            completion_model=SimpleNamespace(id=uuid4(), name="exotic-model"),
            session=_make_session_in_db(),
            stream=True,
            assistant_id=uuid4(),
            question_id=uuid4(),
            **_skill_runtime_args(),
        )

        first = await _drain_until(gen, 1)
        assert [c.text for c in first] == ["partial"]

        await gen.aclose()
        await asyncio.sleep(0)

    assert len(persist_calls) == 1, (
        "partial save must still fire even when count_tokens raises"
    )
    assert persist_calls[0]["answer"] == "partial"
    assert persist_calls[0]["num_tokens_answer"] == 0


# ----- _schedule_background_save strong-ref invariant -----------------------


@pytest.mark.asyncio
async def test_schedule_background_save_holds_strong_reference_until_done():
    """asyncio.create_task internally holds only a weak reference — without
    `_background_save_tasks` keeping a strong one, the GC can collect the task
    mid-flight and silently drop the persistence write."""
    started = asyncio.Event()
    finish = asyncio.Event()
    ran_to_completion = False

    async def slow_coro() -> None:
        nonlocal ran_to_completion
        started.set()
        await finish.wait()
        ran_to_completion = True

    task = session_service_module.schedule_background_save(slow_coro())

    await started.wait()
    # The task should be tracked while in-flight.
    assert task in session_service_module._background_save_tasks

    finish.set()
    await task

    # And removed after completion via the add_done_callback.
    assert task not in session_service_module._background_save_tasks
    assert ran_to_completion is True

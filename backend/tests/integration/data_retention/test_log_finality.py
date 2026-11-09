"""A removed question leaves nothing readable in any log.

The answer path logs the whole request body, so the log of a later turn holds
every earlier turn of its conversation. Removing a question must leave none of
its text in any log, also when the next answer was generated from it, a log
must not outlive the question it was written for, and a question answered
while logging was off has no log at all.
"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.data_retention.application.conversation_retention import (
    ConversationRootKind,
)
from eneo.data_retention.infrastructure.conversation_unit_repo import (
    ConversationUnitRepository,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.logging.logging import LoggingDetails
from eneo.questions.question import QuestionAdd
from eneo.users.user import UserInDB
from tests.integration.data_retention.copy_support import auth, create_assistant
from tests.integration.data_retention.retention_support import (
    run_registered_retention,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def owner_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def _space(client: AsyncClient, token: str) -> str:
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"logs-{uuid4().hex[:6]}"},
        headers=auth(token),
    )
    assert space.status_code == 201, space.text
    return space.json()["id"]


async def _insight_assistant(client: AsyncClient, token: str) -> UUID:
    assistant_id = await create_assistant(client, token, await _space(client, token))
    enabled = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"insight_enabled": True},
        headers=auth(token),
    )
    assert enabled.status_code == 200, enabled.text
    return assistant_id


async def _askable_assistant(
    client: AsyncClient,
    db_container,
    completion_model_factory,
    token: str,
    *,
    logging_enabled: bool,
) -> UUID:
    space_id = await _space(client, token)
    assistant_id = await create_assistant(client, token, space_id)
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session, f"logs-{uuid4().hex[:8]}", is_default=True
        )
        model_id = str(model.id)
        session.add(
            SpacesCompletionModels(
                space_id=UUID(space_id), completion_model_id=model.id
            )
        )
    updated = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"completion_model": {"id": model_id}, "logging_enabled": logging_enabled},
        headers=auth(token),
    )
    assert updated.status_code == 200, updated.text
    return assistant_id


async def _logged_conversation(
    db_container,
    owner: UserInDB,
    *,
    assistant_id: UUID,
    turns: list[tuple[str, str]],
) -> list[UUID]:
    """A conversation logged the way the answer path logs one: each turn's
    request body holds every earlier turn and its own question. The turns
    are a minute apart, the last one now."""
    history: list[dict[str, str]] = []
    question_ids: list[UUID] = []
    first_asked = datetime.now(timezone.utc) - timedelta(minutes=len(turns))
    async with db_container() as container:
        session = await container.session_service().create_session(
            name="logged", assistant_id=assistant_id
        )
        for index, (question, answer) in enumerate(turns, start=1):
            history.append({"role": "user", "content": question})
            added = await container.question_repo().add(
                QuestionAdd(
                    question=question,
                    answer=answer,
                    num_tokens_question=1,
                    num_tokens_answer=1,
                    tenant_id=owner.tenant_id,
                    session_id=session.id,
                    assistant_id=assistant_id,
                    logging_details=LoggingDetails(
                        model_kwargs={"temperature": 0.2},
                        json_body=json.dumps(history),
                    ),
                )
            )
            await container.session().execute(
                sa.update(Questions)
                .where(Questions.id == added.id)
                .values(created_at=first_asked + timedelta(minutes=index))
            )
            history.append({"role": "assistant", "content": answer})
            question_ids.append(added.id)
    return question_ids


async def _logs_containing(text: str) -> int:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.text(
                "SELECT count(*) FROM logging WHERE concat_ws(' ', context, "
                "model_kwargs::text, json_body::text) LIKE :pattern"
            ),
            {"pattern": f"%{text}%"},
        )


async def _all_logs() -> int:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(sa.text("SELECT count(*) FROM logging"))


async def _question_log(question_id: UUID) -> UUID | None:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.select(Questions.logging_details_id).where(Questions.id == question_id)
        )


async def _delete_question(question_id: UUID) -> None:
    async with sessionmanager.session() as session, session.begin():
        await session.execute(sa.delete(Questions).where(Questions.id == question_id))


async def _remove_by_retention(
    session: AsyncSession, assistant_id: UUID, question_id: UUID
) -> None:
    long_ago = datetime.now(timezone.utc) - timedelta(days=10)
    await session.execute(
        sa.update(Assistants)
        .where(Assistants.id == assistant_id)
        .values(data_retention_days=1)
    )
    await session.execute(
        sa.update(Questions)
        .where(Questions.id == question_id)
        .values(created_at=long_ago)
    )
    await session.commit()
    report = await run_registered_retention(session)
    assert report.counts["questions.questions_deleted"] == 1


async def _remove_directly(
    session: AsyncSession, _assistant_id: UUID, question_id: UUID
) -> None:
    await session.execute(sa.delete(Questions).where(Questions.id == question_id))
    await session.commit()


QuestionRemoval = Callable[[AsyncSession, UUID, UUID], Awaitable[None]]
QUESTION_REMOVALS: dict[str, QuestionRemoval] = {
    "by retention": _remove_by_retention,
    "deleted directly": _remove_directly,
}


@pytest.mark.parametrize(
    "removal", QUESTION_REMOVALS.values(), ids=QUESTION_REMOVALS.keys()
)
async def test_a_removed_question_leaves_no_text_in_the_later_logs_of_its_conversation(
    client: AsyncClient,
    db_container,
    admin_user: UserInDB,
    owner_token: str,
    retention_session: AsyncSession,
    removal: QuestionRemoval,
):
    """A later log that held the removed turn reads as not logged. Mutants:
    removal deletes only the question's own log; it clears logs of other
    conversations; it removes the later question with the log."""
    removed = f"removed-{uuid4().hex}"
    other = f"other-{uuid4().hex}"
    assistant_id = await _insight_assistant(client, owner_token)
    first, second = await _logged_conversation(
        db_container,
        admin_user,
        assistant_id=assistant_id,
        turns=[
            (f"first question {removed}", f"first answer {removed}"),
            ("second question", "second answer"),
        ],
    )
    await _logged_conversation(
        db_container,
        admin_user,
        assistant_id=assistant_id,
        turns=[(f"other question {other}", "other answer")],
    )
    before = await client.get(f"/api/v1/logging/{second}/", headers=auth(owner_token))
    assert before.status_code == 200, before.text
    assert removed in before.text  # the later turn's log carries the earlier turn

    await removal(retention_session, assistant_id, first)

    async with sessionmanager.session() as session, session.begin():
        assert await session.get(Questions, second) is not None
    after = await client.get(f"/api/v1/logging/{second}/", headers=auth(owner_token))
    assert after.status_code == 400, after.text
    assert "Question was not logged" in after.text
    assert await _logs_containing(removed) == 0
    assert await _logs_containing(other) == 1


async def test_removing_a_question_keeps_the_logs_of_the_turns_before_it(
    client: AsyncClient,
    db_container,
    admin_user: UserInDB,
    owner_token: str,
):
    """An earlier turn's log holds nothing of a later turn. Mutant: removal
    clears every log of the conversation."""
    earlier = f"earlier-{uuid4().hex}"
    assistant_id = await _insight_assistant(client, owner_token)
    first, second, third = await _logged_conversation(
        db_container,
        admin_user,
        assistant_id=assistant_id,
        turns=[
            (f"earlier question {earlier}", "earlier answer"),
            ("removed question", "removed answer"),
            ("later question", "later answer"),
        ],
    )

    await _delete_question(second)

    kept = await client.get(f"/api/v1/logging/{first}/", headers=auth(owner_token))
    assert kept.status_code == 200, kept.text
    assert earlier in kept.text
    cleared = await client.get(f"/api/v1/logging/{third}/", headers=auth(owner_token))
    assert cleared.status_code == 400, cleared.text


async def test_a_question_is_charged_for_each_log_its_removal_clears(
    client: AsyncClient,
    db_container,
    admin_user: UserInDB,
    owner_token: str,
):
    """The retention unit pays for the logs the removal trigger writes: the
    question's own log and each later log that still holds a request body,
    once. Mutant: the later logs are not charged, or a cleared log is charged
    again."""
    assistant_id = await _insight_assistant(client, owner_token)
    first, second, _ = await _logged_conversation(
        db_container,
        admin_user,
        assistant_id=assistant_id,
        turns=[("first", "first"), ("second", "second"), ("third", "third")],
    )

    async def cost(question_id: UUID) -> int:
        async with sessionmanager.session() as session, session.begin():
            unit = ConversationUnitRepository(
                session,
                kind=ConversationRootKind.QUESTION,
                now=datetime.now(timezone.utc),
            )
            return await unit.cascade_cost(question_id, ceiling=100)

    assert await cost(first) == 3
    await _delete_question(first)
    assert await cost(second) == 1


@pytest.mark.parametrize("removed", [None, "conversation", "question"])
async def test_an_answer_completed_after_its_question_went_leaves_no_log(
    client: AsyncClient,
    db_container,
    owner_token: str,
    removed: str | None,
):
    """The question is removed between its placeholder and its answer: the
    answer's log must not be stored without a question to remove it with.
    Mutant for the first case: no answer is logged at all."""
    marker = f"racing-{uuid4().hex}"
    assistant_id = await create_assistant(
        client, owner_token, await _space(client, owner_token)
    )
    async with db_container() as container:
        service = container.session_service()
        conversation = await service.create_session(
            name="racing", assistant_id=assistant_id
        )
        question_id, _ = await service.create_question_placeholder(
            question=f"asked {marker}",
            session=conversation,
            assistant_id=assistant_id,
        )
    if removed == "conversation":
        async with sessionmanager.session() as session, session.begin():
            await session.execute(
                sa.delete(Sessions).where(Sessions.id == conversation.id)
            )
    elif removed == "question":
        await _delete_question(question_id)

    async with db_container() as container:
        await container.session_service().complete_question_with_answer(
            question_id=question_id,
            answer=f"answer {marker}",
            num_tokens_question=1,
            num_tokens_answer=1,
            info_blob_chunks=[],
            logging_details=LoggingDetails(
                model_kwargs={},
                json_body=json.dumps([{"role": "user", "content": f"asked {marker}"}]),
            ),
            history_revision=conversation.history_revision,
        )

    assert await _logs_containing(marker) == (1 if removed is None else 0)


@dataclass
class LoggingModel:
    """A model that logs its request the way the adapter does, history
    included, and only when the Assistant asked for a log."""

    during_answer: Callable[[], Awaitable[None]] | None = None
    requests: list[str] = field(default_factory=list)


@pytest.fixture
def logging_model(monkeypatch) -> LoggingModel:
    model = LoggingModel()

    async def fake_get_response(self: CompletionService, **kwargs: Any):
        conversation = kwargs.get("session")
        messages: list[dict[str, str]] = []
        for turn in conversation.questions if conversation is not None else []:
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": turn.answer})
        messages.append({"role": "user", "content": kwargs["text_input"]})
        model.requests.append(json.dumps(messages))
        if model.during_answer is not None:
            await model.during_answer()
        details = (
            LoggingDetails(model_kwargs={}, json_body=json.dumps(messages))
            if kwargs.get("extended_logging")
            else None
        )

        async def chunks() -> AsyncGenerator[Completion, None]:
            yield Completion(response_type=ResponseType.TEXT, text="answer")

        return CompletionModelResponse(
            completion=chunks()
            if kwargs.get("stream")
            else Completion(text="answer", response_type=ResponseType.TEXT),
            model=kwargs["model"],
            extended_logging=details,
            total_token_count=1,
            usage=None,
        )

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)
    return model


@pytest.mark.parametrize("stream", [False, True], ids=["answer", "stream"])
async def test_a_question_removed_while_the_next_answer_is_generated_is_not_in_its_log(
    client: AsyncClient,
    db_container,
    completion_model_factory,
    admin_user: UserInDB,
    owner_token: str,
    logging_model: LoggingModel,
    stream: bool,
):
    """The next turn loaded the conversation's history, then the earlier
    question was removed before the answer was stored. Mutant: the answer
    is dropped along with its log."""
    removed = f"removed-{uuid4().hex}"
    assistant_id = await _askable_assistant(
        client,
        db_container,
        completion_model_factory,
        owner_token,
        logging_enabled=True,
    )
    [first] = await _logged_conversation(
        db_container,
        admin_user,
        assistant_id=assistant_id,
        turns=[(f"first question {removed}", f"first answer {removed}")],
    )
    async with sessionmanager.session() as session, session.begin():
        session_id = await session.scalar(
            sa.select(Questions.session_id).where(Questions.id == first)
        )
    logging_model.during_answer = lambda: _delete_question(first)

    asked = await client.post(
        "/api/v1/conversations/",
        json={
            "question": "next question",
            "session_id": str(session_id),
            "stream": stream,
        },
        headers=auth(owner_token),
    )

    assert asked.status_code == 200, asked.text
    [request] = logging_model.requests
    assert removed in request  # the answer was generated from the removed turn
    async with sessionmanager.session() as session, session.begin():
        answers = list(
            await session.scalars(
                sa.select(Questions.answer).where(Questions.session_id == session_id)
            )
        )
    assert answers == ["answer"]
    assert await _logs_containing(removed) == 0


@pytest.mark.parametrize("stream", [False, True], ids=["answer", "stream"])
@pytest.mark.parametrize("logging_enabled", [False, True], ids=["off", "on"])
async def test_an_assistant_logs_an_answer_only_when_logging_is_on(
    client: AsyncClient,
    db_container,
    completion_model_factory,
    owner_token: str,
    logging_model: LoggingModel,
    logging_enabled: bool,
    stream: bool,
):
    """Mutant for the on cases: answers are never logged."""
    assistant_id = await _askable_assistant(
        client,
        db_container,
        completion_model_factory,
        owner_token,
        logging_enabled=logging_enabled,
    )
    logs_before = await _all_logs()

    asked = await client.post(
        "/api/v1/conversations/",
        json={"question": "Hej", "assistant_id": str(assistant_id), "stream": stream},
        headers=auth(owner_token),
    )

    assert asked.status_code == 200, asked.text
    async with sessionmanager.session() as session, session.begin():
        [question_id] = await session.scalars(
            sa.select(Questions.id).where(Questions.assistant_id == assistant_id)
        )
    if logging_enabled:
        assert await _question_log(question_id) is not None
        assert await _all_logs() == logs_before + 1
    else:
        assert await _question_log(question_id) is None
        assert await _all_logs() == logs_before

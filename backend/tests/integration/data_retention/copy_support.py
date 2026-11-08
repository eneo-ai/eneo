"""A copy of a conversation and the paths that remove its source."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.derivations import register_derivations
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.questions_table import Questions
from eneo.questions.question import QuestionAdd
from eneo.users.user import UserInDB
from tests.integration.data_retention.retention_support import (
    run_registered_retention,
)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_assistant(client: AsyncClient, token: str, space_id: str) -> UUID:
    created = await client.post(
        "/api/v1/assistants/",
        json={"name": f"copy-{uuid4().hex[:6]}", "space_id": space_id},
        headers=auth(token),
    )
    assert created.status_code == 200, created.text
    return UUID(created.json()["id"])


async def conversation(
    db_container, owner: UserInDB, *, assistant_id: UUID, turns: int
) -> tuple[UUID, list[UUID]]:
    async with db_container() as container:
        session = await container.session_service().create_session(
            name="conversation", assistant_id=assistant_id
        )
        questions = [
            (
                await container.question_repo().add(
                    QuestionAdd(
                        question=f"question {index}",
                        answer=f"answer {index}",
                        num_tokens_question=1,
                        num_tokens_answer=1,
                        tenant_id=owner.tenant_id,
                        session_id=session.id,
                        assistant_id=assistant_id,
                    )
                )
            ).id
            for index in range(turns)
        ]
    return session.id, questions


@dataclass(frozen=True)
class Copy:
    space_id: str
    source_assistant: UUID
    source_session: UUID
    source_question: UUID
    copy_assistant: UUID
    copy_session: UUID
    copy_questions: list[UUID]


async def make_copy(
    client: AsyncClient, db_container, admin_user: UserInDB, owner_token: str
) -> Copy:
    """A space with a source conversation of one question and a copy of two
    questions in another Assistant, its edge to the source registered."""
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"copies-{uuid4().hex[:6]}"},
        headers=auth(owner_token),
    )
    assert space.status_code == 201, space.text
    space_id = space.json()["id"]
    source_assistant = await create_assistant(client, owner_token, space_id)
    copy_assistant = await create_assistant(client, owner_token, space_id)
    source_session, [source_question] = await conversation(
        db_container, admin_user, assistant_id=source_assistant, turns=1
    )
    copy_session, copy_questions = await conversation(
        db_container, admin_user, assistant_id=copy_assistant, turns=2
    )
    await register_derivations(
        tenant_id=admin_user.tenant_id,
        copy_session_id=copy_session,
        source_question_ids=[source_question],
    )
    return Copy(
        space_id,
        source_assistant,
        source_session,
        source_question,
        copy_assistant,
        copy_session,
        copy_questions,
    )


async def remove_by_user(client: AsyncClient, token: str, copy: Copy, _) -> None:
    deleted = await client.delete(
        f"/api/v1/conversations/{copy.source_session}/", headers=auth(token)
    )
    assert deleted.status_code in (200, 204), deleted.text


async def remove_with_assistant(client: AsyncClient, token: str, copy: Copy, _) -> None:
    deleted = await client.delete(
        f"/api/v1/assistants/{copy.source_assistant}/", headers=auth(token)
    )
    assert deleted.status_code in (200, 204), deleted.text


async def remove_by_retention(
    client: AsyncClient, token: str, copy: Copy, retention_session: AsyncSession
) -> None:
    long_ago = datetime.now(timezone.utc) - timedelta(days=10)
    await retention_session.execute(
        sa.update(Assistants)
        .where(Assistants.id == copy.source_assistant)
        .values(data_retention_days=1)
    )
    await retention_session.execute(
        sa.update(Questions)
        .where(Questions.id == copy.source_question)
        .values(created_at=long_ago)
    )
    await retention_session.commit()
    report = await run_registered_retention(retention_session)
    assert report.counts["questions.questions_deleted"] == 1


Removal = Callable[[AsyncClient, str, Copy, AsyncSession], Awaitable[None]]
REMOVALS: dict[str, Removal] = {
    "by a user": remove_by_user,
    "with its assistant": remove_with_assistant,
    "by retention": remove_by_retention,
}

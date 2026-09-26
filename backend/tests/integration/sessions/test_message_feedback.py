"""Per-answer feedback through the HTTP API, and how insights report it.

Each answer (question row) holds at most one rating from the conversation's
owner. It is separate from the conversation-level rating on the session:
setting one never changes the other, and insights count only answer ratings.
"""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.database import sessionmanager
from eneo.database.tables.questions_table import QuestionFeedback
from eneo.main.models import ModelId
from eneo.questions.question import QuestionAdd
from eneo.users.user import UserAdd, UserInDB, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def owner_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def other_user_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    """A second user in the same tenant, with the same roles as the owner."""
    async with db_container() as container:
        other = await container.user_repo().add(
            UserAdd(
                email=f"feedback-other-{uuid4().hex[:8]}@example.com",
                username=f"feedback_other_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id) for role in admin_user.roles],
            )
        )
        return container.auth_service().create_access_token_for_user(other)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _assistant(client: AsyncClient, token: str) -> UUID:
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"feedback-space-{uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    assert space.status_code == 201, space.text
    created = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"feedback-assistant-{uuid4().hex[:8]}",
            "space_id": space.json()["id"],
        },
        headers=_auth(token),
    )
    assert created.status_code == 200, created.text
    assistant_id = created.json()["id"]
    updated = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"insight_enabled": True},
        headers=_auth(token),
    )
    assert updated.status_code == 200, updated.text
    return UUID(assistant_id)


async def _conversation(
    db_container, owner: UserInDB, assistant_id: UUID, questions: list[str]
) -> tuple[UUID, list[UUID]]:
    async with db_container() as container:
        session = await container.session_service().create_session(
            name=questions[0], assistant_id=assistant_id
        )
    message_ids: list[UUID] = []
    # One transaction per turn: each gets its own created_at, so "the first
    # answer of the conversation" is well defined.
    for question in questions:
        async with db_container() as container:
            added = await container.question_repo().add(
                QuestionAdd(
                    question=question,
                    answer=f"Svar på: {question}",
                    num_tokens_question=0,
                    num_tokens_answer=0,
                    tenant_id=owner.tenant_id,
                    session_id=session.id,
                    assistant_id=assistant_id,
                )
            )
            assert added is not None
            message_ids.append(added.id)
    return session.id, message_ids


def _feedback_url(session_id: UUID, message_id: UUID) -> str:
    return f"/api/v1/conversations/{session_id}/messages/{message_id}/feedback/"


async def _stored_rows(message_id: UUID) -> int:
    async with sessionmanager.session() as session, session.begin():
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(QuestionFeedback)
            .where(QuestionFeedback.question_id == message_id)
        )
    return int(count or 0)


async def test_owner_rates_replaces_and_clears_an_answer(
    client, db_container, admin_user, owner_token
):
    assistant_id = await _assistant(client, owner_token)
    session_id, (first, second) = await _conversation(
        db_container, admin_user, assistant_id, ["Vad gäller?", "Och sedan?"]
    )
    url = _feedback_url(session_id, second)

    rated = await client.put(
        url, json={"value": 1, "text": "  Tydligt svar  "}, headers=_auth(owner_token)
    )
    assert rated.status_code == 200, rated.text
    assert rated.json() == {"value": 1, "text": "Tydligt svar"}

    replaced = await client.put(url, json={"value": -1}, headers=_auth(owner_token))
    assert replaced.status_code == 200, replaced.text
    assert replaced.json() == {"value": -1, "text": None}
    assert await _stored_rows(second) == 1

    # The rating comes back with the conversation, on its own answer only.
    reloaded = await client.get(
        f"/api/v1/conversations/{session_id}/", headers=_auth(owner_token)
    )
    assert reloaded.status_code == 200, reloaded.text
    messages = {message["id"]: message for message in reloaded.json()["messages"]}
    assert messages[str(first)]["feedback"] is None
    assert messages[str(second)]["feedback"] == {"value": -1, "text": None}
    assert reloaded.json()["feedback"] is None

    cleared = await client.delete(url, headers=_auth(owner_token))
    assert cleared.status_code == 204, cleared.text
    assert await _stored_rows(second) == 0
    # Clearing an answer without a rating succeeds too.
    assert (await client.delete(url, headers=_auth(owner_token))).status_code == 204

    reloaded = await client.get(
        f"/api/v1/conversations/{session_id}/", headers=_auth(owner_token)
    )
    assert [message["feedback"] for message in reloaded.json()["messages"]] == [
        None,
        None,
    ]


async def test_answer_and_conversation_feedback_are_kept_apart(
    client, db_container, admin_user, owner_token
):
    assistant_id = await _assistant(client, owner_token)
    session_id, (message_id,) = await _conversation(
        db_container, admin_user, assistant_id, ["Vilken gräns gäller?"]
    )
    headers = _auth(owner_token)

    await client.put(
        _feedback_url(session_id, message_id), json={"value": 1}, headers=headers
    )
    conversation_rating = await client.post(
        f"/api/v1/conversations/{session_id}/feedback/",
        json={"value": -1, "text": "Långsamt"},
        headers=headers,
    )
    assert conversation_rating.status_code == 200, conversation_rating.text

    reloaded = (
        await client.get(f"/api/v1/conversations/{session_id}/", headers=headers)
    ).json()
    assert reloaded["feedback"] == {"value": -1, "text": "Långsamt"}
    assert reloaded["messages"][0]["feedback"] == {"value": 1, "text": None}

    await client.delete(_feedback_url(session_id, message_id), headers=headers)
    reloaded = (
        await client.get(f"/api/v1/conversations/{session_id}/", headers=headers)
    ).json()
    assert reloaded["feedback"] == {"value": -1, "text": "Långsamt"}
    assert reloaded["messages"][0]["feedback"] is None


async def test_only_the_conversation_owner_can_rate_its_answers(
    client, db_container, admin_user, owner_token, other_user_token
):
    assistant_id = await _assistant(client, owner_token)
    session_id, (message_id,) = await _conversation(
        db_container, admin_user, assistant_id, ["Vem får se detta?"]
    )
    other_session_id, _ = await _conversation(
        db_container, admin_user, assistant_id, ["Ett annat samtal"]
    )
    url = _feedback_url(session_id, message_id)
    await client.put(url, json={"value": 1}, headers=_auth(owner_token))

    # Another user cannot rate or clear it, and cannot tell that it exists.
    foreign_put = await client.put(
        url, json={"value": -1}, headers=_auth(other_user_token)
    )
    assert foreign_put.status_code == 404, foreign_put.text
    foreign_delete = await client.delete(url, headers=_auth(other_user_token))
    assert foreign_delete.status_code == 404, foreign_delete.text

    # A message is addressed through its own conversation only.
    wrong_session = await client.put(
        _feedback_url(other_session_id, message_id),
        json={"value": -1},
        headers=_auth(owner_token),
    )
    assert wrong_session.status_code == 404, wrong_session.text
    unknown = await client.put(
        _feedback_url(session_id, uuid4()), json={"value": 1}, headers=_auth(owner_token)
    )
    assert unknown.status_code == 404, unknown.text

    invalid = await client.put(url, json={"value": 0}, headers=_auth(owner_token))
    assert invalid.status_code == 422, invalid.text

    reloaded = (
        await client.get(
            f"/api/v1/conversations/{session_id}/", headers=_auth(owner_token)
        )
    ).json()
    assert reloaded["messages"][0]["feedback"] == {"value": 1, "text": None}


async def test_deleting_a_conversation_removes_its_answer_ratings(
    client, db_container, admin_user, owner_token
):
    assistant_id = await _assistant(client, owner_token)
    session_id, (message_id,) = await _conversation(
        db_container, admin_user, assistant_id, ["Ta bort mig"]
    )
    headers = _auth(owner_token)
    await client.put(
        _feedback_url(session_id, message_id), json={"value": -1}, headers=headers
    )

    deleted = await client.delete(f"/api/v1/conversations/{session_id}/", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert await _stored_rows(message_id) == 0


async def test_insights_count_and_list_answer_ratings(
    client, db_container, admin_user, owner_token
):
    assistant_id = await _assistant(client, owner_token)
    headers = _auth(owner_token)
    rated_session, (opening, follow_up) = await _conversation(
        db_container, admin_user, assistant_id, ["Första frågan", "Följdfrågan"]
    )
    second_session, (second_opening,) = await _conversation(
        db_container, admin_user, assistant_id, ["Andra samtalet"]
    )
    await _conversation(db_container, admin_user, assistant_id, ["Obetygsatt"])

    for session_id, message_id, body in (
        (rated_session, opening, {"value": 1}),
        (rated_session, follow_up, {"value": -1, "text": "Fel paragraf"}),
        (second_session, second_opening, {"value": 1}),
    ):
        response = await client.put(
            _feedback_url(session_id, message_id), json=body, headers=headers
        )
        assert response.status_code == 200, response.text
    # A conversation-level rating is not an answer rating and is not counted.
    await client.post(
        f"/api/v1/conversations/{rated_session}/feedback/",
        json={"value": -1},
        headers=headers,
    )

    stats = await client.get(
        "/api/v1/analysis/conversation-insights/",
        params={"assistant_id": str(assistant_id)},
        headers=headers,
    )
    assert stats.status_code == 200, stats.text
    assert stats.json()["total_questions"] == 4
    assert stats.json()["feedback"] == {"positive": 2, "negative": 1}

    all_answers = await client.get(
        f"/api/v1/analysis/assistants/{assistant_id}/feedback/",
        params={"include_followups": "true"},
        headers=headers,
    )
    assert all_answers.status_code == 200, all_answers.text
    assert all_answers.json() == {"positive": 2, "negative": 1}
    first_answers = await client.get(
        f"/api/v1/analysis/assistants/{assistant_id}/feedback/", headers=headers
    )
    assert first_answers.json() == {"positive": 2, "negative": 0}

    history = await client.get(
        f"/api/v1/analysis/assistants/{assistant_id}/questions/",
        params={"include_followups": "true"},
        headers=headers,
    )
    assert history.status_code == 200, history.text
    ratings = {item["id"]: item["feedback"] for item in history.json()["items"]}
    assert ratings[str(opening)] == {"value": 1, "text": None}
    assert ratings[str(follow_up)] == {"value": -1, "text": "Fel paragraf"}
    assert ratings[str(second_opening)] == {"value": 1, "text": None}
    assert sum(rating is None for rating in ratings.values()) == 1

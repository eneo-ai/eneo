"""Preflight, delete, feedback and rename decide ownership without the turns.

They read who owns a conversation and whom it is with; only a response that
returns the conversation reads its turns, once. The refusals are those of
``get_session_by_uuid``: another principal is Unauthorized (403) and a
helper-run conversation does not exist (404).
"""

import re
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.sessions_table import Sessions
from eneo.main.models import ModelId
from eneo.questions.question import QuestionAdd
from eneo.users.user import UserAdd, UserInDB, UserState
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = pytest.mark.integration

_TURNS = re.compile(r"\bFROM questions\s")


@pytest.fixture
async def owner_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def other_user_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        other = await container.user_repo().add(
            UserAdd(
                email=f"ownership-other-{uuid4().hex[:8]}@example.com",
                username=f"ownership_other_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id) for role in admin_user.roles],
            )
        )
        return container.auth_service().create_access_token_for_user(other)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _space(client: AsyncClient, token: str) -> str:
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"ownership-{uuid4().hex[:6]}"},
        headers=_auth(token),
    )
    assert space.status_code == 201, space.text
    return space.json()["id"]


async def _assistant(client: AsyncClient, token: str, space_id: str) -> UUID:
    created = await client.post(
        "/api/v1/assistants/",
        json={"name": f"ownership-{uuid4().hex[:6]}", "space_id": space_id},
        headers=_auth(token),
    )
    assert created.status_code == 200, created.text
    return UUID(created.json()["id"])


async def _conversation(
    db_container,
    owner: UserInDB,
    *,
    assistant_id: UUID | None = None,
    turns: int = 3,
) -> UUID:
    async with db_container() as container:
        session = await container.session_service().create_session(
            name="conversation", assistant_id=assistant_id
        )
        image = await container.file_service().save_image_from_bytes(
            b"\x89PNG" + b"\x00" * 64, name="photo.png", mimetype="image/png"
        )
        for index in range(turns):
            await container.question_repo().add(
                QuestionAdd(
                    question=f"question {index}",
                    answer=f"answer {index}",
                    num_tokens_question=1,
                    num_tokens_answer=1,
                    tenant_id=owner.tenant_id,
                    session_id=session.id,
                    assistant_id=assistant_id,
                ),
                files=[image] if index == 0 else [],
            )
    return session.id


def _preflight(session_id: UUID) -> dict[str, object]:
    return {"question": "hello", "session_id": str(session_id)}


async def _stored(db_container, session_id: UUID) -> tuple[str, int | None] | None:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(Sessions.name, Sessions.feedback_value).where(
                    Sessions.id == session_id
                )
            )
        ).one_or_none()
    return None if row is None else (row.name, row.feedback_value)


async def _turn_reads(db_container, request) -> tuple[int, int]:
    async with db_container() as container:
        bind = container.session().sync_session.bind
    assert bind is not None
    with capture_queries(bind.engine) as queries:
        response = await request
    return response.status_code, sum(1 for q in queries if _TURNS.search(q.sql))


async def test_the_owner_reads_the_turns_only_for_a_response_that_returns_them(
    client, db_container, admin_user, owner_token
) -> None:
    space_id = await _space(client, owner_token)
    assistant_id = await _assistant(client, owner_token, space_id)
    session_id = await _conversation(
        db_container, admin_user, assistant_id=assistant_id
    )
    url = f"/api/v1/conversations/{session_id}/"

    preflight = await _turn_reads(
        db_container,
        client.post(
            "/api/v1/conversations/preflight",
            json=_preflight(session_id),
            headers=_auth(owner_token),
        ),
    )
    rename = await _turn_reads(
        db_container,
        client.patch(
            url + "name/", json={"name": "renamed"}, headers=_auth(owner_token)
        ),
    )
    feedback = await _turn_reads(
        db_container,
        client.post(url + "feedback/", json={"value": 1}, headers=_auth(owner_token)),
    )
    assert await _stored(db_container, session_id) == ("renamed", 1)
    delete = await _turn_reads(
        db_container, client.delete(url, headers=_auth(owner_token))
    )

    assert (preflight, rename, feedback, delete) == (
        (200, 0),
        (200, 1),
        (200, 1),
        (204, 1),
    )
    assert await _stored(db_container, session_id) is None


async def test_another_user_is_refused_and_changes_nothing(
    client, db_container, admin_user, owner_token, other_user_token
) -> None:
    space_id = await _space(client, owner_token)
    assistant_id = await _assistant(client, owner_token, space_id)
    session_id = await _conversation(
        db_container, admin_user, assistant_id=assistant_id
    )
    url = f"/api/v1/conversations/{session_id}/"
    other = _auth(other_user_token)

    responses = [
        await client.post(
            "/api/v1/conversations/preflight",
            json=_preflight(session_id),
            headers=other,
        ),
        await client.patch(url + "name/", json={"name": "taken"}, headers=other),
        await client.post(url + "feedback/", json={"value": 1}, headers=other),
        await client.delete(url, headers=other),
        await client.post(
            f"/api/v1/assistants/{assistant_id}/sessions/{session_id}/feedback/",
            json={"value": 1},
            headers=other,
        ),
        await client.delete(
            f"/api/v1/assistants/{assistant_id}/sessions/{session_id}/", headers=other
        ),
    ]

    assert [r.status_code for r in responses] == [403] * len(responses), [
        r.text for r in responses
    ]
    assert await _stored(db_container, session_id) == ("conversation", None)


async def test_a_helper_run_conversation_does_not_exist(
    client, db_container, admin_user, owner_token
) -> None:
    space_id = await _space(client, owner_token)
    assistant_id = await _assistant(client, owner_token, space_id)
    session_id = await _conversation(
        db_container, admin_user, assistant_id=assistant_id
    )
    async with db_container() as container:
        await container.session().execute(
            sa.insert(HelpAssistantRuns).values(
                tenant_id=admin_user.tenant_id,
                org_space_id=UUID(space_id),
                kind="prompt_guide",
                assistant_id=assistant_id,
                target_type="assistant",
                target_id=assistant_id,
                session_id=session_id,
                actor_user_id=admin_user.id,
            )
        )
    url = f"/api/v1/conversations/{session_id}/"
    owner = _auth(owner_token)

    responses = [
        await client.post(
            "/api/v1/conversations/preflight",
            json=_preflight(session_id),
            headers=owner,
        ),
        await client.patch(url + "name/", json={"name": "renamed"}, headers=owner),
        await client.post(url + "feedback/", json={"value": 1}, headers=owner),
        await client.delete(url, headers=owner),
        await client.post(
            f"/api/v1/assistants/{assistant_id}/sessions/{session_id}/feedback/",
            json={"value": 1},
            headers=owner,
        ),
        await client.delete(
            f"/api/v1/assistants/{assistant_id}/sessions/{session_id}/", headers=owner
        ),
    ]

    assert [r.status_code for r in responses] == [404] * len(responses), [
        r.text for r in responses
    ]
    assert await _stored(db_container, session_id) == ("conversation", None)


async def test_the_owners_api_key_acts_as_the_owner(
    client, db_container, admin_user, owner_token, admin_user_api_key
) -> None:
    space_id = await _space(client, owner_token)
    assistant_id = await _assistant(client, owner_token, space_id)
    session_id = await _conversation(
        db_container, admin_user, assistant_id=assistant_id
    )
    url = f"/api/v1/conversations/{session_id}/"
    key = {"X-API-Key": admin_user_api_key.key}

    preflight = await client.post(
        "/api/v1/conversations/preflight", json=_preflight(session_id), headers=key
    )
    rename = await client.patch(url + "name/", json={"name": "by key"}, headers=key)
    feedback = await client.post(url + "feedback/", json={"value": 1}, headers=key)

    assert preflight.status_code == 200, preflight.text
    assert rename.status_code == 200, rename.text
    assert feedback.status_code == 200, feedback.text
    assert await _stored(db_container, session_id) == ("by key", 1)
    assert (await client.delete(url, headers=key)).status_code == 204
    assert await _stored(db_container, session_id) is None

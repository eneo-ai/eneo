"""The conversation history list reads the conversations, not their turns."""

from uuid import UUID, uuid4

import pytest

from eneo.questions.question import QuestionAdd
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = pytest.mark.integration


@pytest.fixture
async def owner_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _assistant_with_conversations(client, db_container, admin_user, token):
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"history-{uuid4().hex[:6]}"},
        headers=_auth(token),
    )
    assert space.status_code == 201, space.text
    created = await client.post(
        "/api/v1/assistants/",
        json={"name": "history", "space_id": space.json()["id"]},
        headers=_auth(token),
    )
    assert created.status_code == 200, created.text
    assistant_id = UUID(created.json()["id"])
    names = []
    for index in range(3):
        async with db_container() as container:
            session = await container.session_service().create_session(
                name=f"conversation {index}", assistant_id=assistant_id
            )
            image = await container.file_service().save_image_from_bytes(
                b"\x89PNG" + bytes([index]) * 64,
                name=f"a-{index}.png",
                mimetype="image/png",
            )
            await container.question_repo().add(
                QuestionAdd(
                    question="question",
                    answer="answer",
                    num_tokens_question=1,
                    num_tokens_answer=1,
                    tenant_id=admin_user.tenant_id,
                    session_id=session.id,
                    assistant_id=assistant_id,
                ),
                files=[image],
            )
        names.append(f"conversation {index}")
    return assistant_id, names


async def test_history_list_reads_no_turns_and_keeps_its_cursors(
    client, db_container, admin_user, owner_token
) -> None:
    assistant_id, names = await _assistant_with_conversations(
        client, db_container, admin_user, owner_token
    )
    base = f"/api/v1/conversations/?assistant_id={assistant_id}"

    async with db_container() as container:
        bind = container.session().sync_session.bind
    assert bind is not None
    with capture_queries(bind.engine) as queries:
        first = await client.get(base + "&limit=2", headers=_auth(owner_token))

    assert first.status_code == 200, first.text
    page = first.json()
    assert [item["name"] for item in page["items"]] == names[::-1][:2]
    assert all(
        set(item) == {"id", "name", "created_at", "updated_at"}
        for item in page["items"]
    )
    assert page["total_count"] == 3
    assert page["limit"] == 2
    assert page["next_cursor"] is not None
    assert not [q.sql for q in queries if "FROM questions" in q.sql]

    second = await client.get(
        base + f"&limit=2&cursor={page['next_cursor']}", headers=_auth(owner_token)
    )
    assert second.status_code == 200, second.text
    assert [item["name"] for item in second.json()["items"]] == [names[0]]

    back = await client.get(
        base
        + f"&limit=2&previous=true&cursor={second.json()['items'][0]['created_at']}",
        headers=_auth(owner_token),
    )
    assert back.status_code == 200, back.text
    assert [item["name"] for item in back.json()["items"]] == names[::-1][:2]

    with capture_queries(bind.engine) as queries:
        by_route = await client.get(
            f"/api/v1/assistants/{assistant_id}/sessions/?limit=2",
            headers=_auth(owner_token),
        )
    assert by_route.status_code == 200, by_route.text
    assert by_route.json()["items"] == page["items"]
    assert not [q.sql for q in queries if "FROM questions" in q.sql]

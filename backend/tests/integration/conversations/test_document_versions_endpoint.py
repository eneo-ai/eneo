"""Saving a reader's edit of a conversation document over the HTTP API.

The new version is a Markdown file that revises the one edited from and joins
that turn's generated files, so the conversation shows it and export knows
it. Unchanged text makes no version.
"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.questions.question import QuestionAdd
from eneo.users.user import UserInDB

MARKDOWN = "# Plan\n\nFas ett startar i maj.\n"
EDITED = "# Plan\n\nFas ett startar i juni.\n"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _token(db_container, patch_auth_service_jwt, user: UserInDB) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(user)


async def _assistant(client: AsyncClient, token: str) -> UUID:
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"versions-space-{uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    assert space.status_code == 201, space.text
    created = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"versions-assistant-{uuid4().hex[:8]}",
            "space_id": space.json()["id"],
        },
        headers=_auth(token),
    )
    assert created.status_code == 200, created.text
    return UUID(created.json()["id"])


async def _conversation_with_document(
    db_container, owner: UserInDB, assistant_id: UUID
) -> tuple[UUID, UUID]:
    """A conversation whose one turn made a document; returns (session, file)."""
    async with db_container() as container:
        document = await container.file_service().save_generated_document(
            MARKDOWN.encode(), name="Plan.md", mimetype="text/markdown"
        )
        session = await container.session_service().create_session(
            name="plan", assistant_id=assistant_id
        )
        await container.question_repo().add(
            QuestionAdd(
                question="skriv en plan",
                answer="här",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=owner.tenant_id,
                session_id=session.id,
                assistant_id=assistant_id,
            ),
            generated_files=[document],
        )
    return session.id, document.id


def _url(session_id: UUID, file_id: UUID) -> str:
    return f"/api/v1/conversations/{session_id}/documents/{file_id}/versions/"


async def _file_count() -> int:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(sa.select(sa.func.count()).select_from(Files))


async def test_saved_edit_is_a_new_version_on_the_documents_turn(
    client, db_container, admin_user, patch_auth_service_jwt
):
    token = await _token(db_container, patch_auth_service_jwt, admin_user)
    assistant_id = await _assistant(client, token)
    session_id, base = await _conversation_with_document(
        db_container, admin_user, assistant_id
    )

    response = await client.post(
        _url(session_id, base), json={"content": EDITED}, headers=_auth(token)
    )

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["revises_file_id"] == str(base)
    assert version["name"] == "Plan.md"
    assert version["mimetype"] == "text/markdown"

    conversation = await client.get(
        f"/api/v1/conversations/{session_id}/", headers=_auth(token)
    )
    assert conversation.status_code == 200, conversation.text
    generated = conversation.json()["messages"][0]["generated_files"]
    assert {file["id"] for file in generated} == {str(base), version["id"]}
    saved = next(file for file in generated if file["id"] == version["id"])
    assert saved["revises_file_id"] == str(base)

    # The version is exportable like the document it revises: availability
    # answers for it instead of refusing the file (no provider in tests).
    availability = await client.get(
        f"/api/v1/conversations/{session_id}/documents/{version['id']}/export/",
        headers=_auth(token),
    )
    assert availability.status_code == 200, availability.text


async def test_a_second_save_is_a_version_of_the_readers_first(
    client, db_container, admin_user, patch_auth_service_jwt
):
    token = await _token(db_container, patch_auth_service_jwt, admin_user)
    assistant_id = await _assistant(client, token)
    session_id, base = await _conversation_with_document(
        db_container, admin_user, assistant_id
    )
    first = await client.post(
        _url(session_id, base), json={"content": EDITED}, headers=_auth(token)
    )
    assert first.status_code == 201, first.text
    files_after_first = await _file_count()

    second = await client.post(
        _url(session_id, UUID(first.json()["id"])),
        json={"content": EDITED + "\nEn rad till.\n"},
        headers=_auth(token),
    )

    assert second.status_code == 201, second.text
    # The versions stack: the second stands on the first, which stays.
    assert second.json()["revises_file_id"] == first.json()["id"]
    assert await _file_count() == files_after_first + 1
    conversation = await client.get(
        f"/api/v1/conversations/{session_id}/", headers=_auth(token)
    )
    generated = {f["id"] for f in conversation.json()["messages"][0]["generated_files"]}
    assert generated == {str(base), first.json()["id"], second.json()["id"]}


async def test_unchanged_text_makes_no_version(
    client, db_container, admin_user, patch_auth_service_jwt
):
    token = await _token(db_container, patch_auth_service_jwt, admin_user)
    assistant_id = await _assistant(client, token)
    session_id, base = await _conversation_with_document(
        db_container, admin_user, assistant_id
    )
    before = await _file_count()

    response = await client.post(
        _url(session_id, base), json={"content": MARKDOWN}, headers=_auth(token)
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(base)
    assert await _file_count() == before


async def test_a_file_outside_the_conversation_takes_no_version(
    client, db_container, admin_user, patch_auth_service_jwt
):
    token = await _token(db_container, patch_auth_service_jwt, admin_user)
    assistant_id = await _assistant(client, token)
    session_id, _ = await _conversation_with_document(
        db_container, admin_user, assistant_id
    )

    unknown = await client.post(
        _url(session_id, uuid4()), json={"content": EDITED}, headers=_auth(token)
    )

    assert unknown.status_code == 404, unknown.text

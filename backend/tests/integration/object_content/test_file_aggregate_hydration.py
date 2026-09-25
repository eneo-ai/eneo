from __future__ import annotations

import re
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.files.file_content_loader import FileContentLoader


async def _create_space(client, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"hydration-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_persisted_aggregate_files_reload_through_object_content(
    client,
    db_container,
    admin_user_api_key,
    transcription_model_factory,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    space_id = await _create_space(client, headers)

    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("policy.txt", b"durable policy", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    file_id = upload.json()["id"]
    attachment = [{"id": file_id}]

    assistant = await client.post(
        "/api/v1/assistants/",
        json={"name": "Hydrated assistant", "space_id": space_id},
        headers=headers,
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = assistant.json()["id"]
    updated_assistant = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"attachments": attachment},
        headers=headers,
    )
    assert updated_assistant.status_code == 200, updated_assistant.text

    async with db_container() as container:
        await transcription_model_factory(
            container.session(),
            "fixture-whisper",
            is_default=True,
        )

    app = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": "Hydrated app"},
        headers=headers,
    )
    assert app.status_code == 201, app.text
    app_id = app.json()["id"]
    updated_app = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"attachments": attachment},
        headers=headers,
    )
    assert updated_app.status_code == 200, updated_app.text

    reloaded_assistant = await client.get(
        f"/api/v1/assistants/{assistant_id}/",
        headers=headers,
    )
    reloaded_app = await client.get(
        f"/api/v1/apps/{app_id}/",
        headers=headers,
    )
    reloaded_space = await client.get(
        f"/api/v1/spaces/{space_id}/",
        headers=headers,
    )
    assert reloaded_assistant.status_code == 200, reloaded_assistant.text
    assert reloaded_app.status_code == 200, reloaded_app.text
    assert reloaded_space.status_code == 200, reloaded_space.text
    assert reloaded_assistant.json()["attachments"][0]["id"] == file_id
    assert reloaded_app.json()["attachments"][0]["id"] == file_id

    async with db_container() as container:
        file = await container.file_service().get_file_content(UUID(file_id))
        (
            session,
            question_id,
            _question_created_at,
        ) = await container.session_service().create_session_with_question_placeholder(
            name="Hydrated history",
            question="Use the attached policy",
            files=[file],
        )
        reloaded_session = await container.session_service().get_session_by_uuid(
            session.id
        )
        reloaded_question = await container.question_repo().get(question_id)

    assert reloaded_session.questions[0].files[0].text == "durable policy"
    assert reloaded_question is not None
    assert reloaded_question.files[0].text == "durable policy"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_applications_view_does_not_read_attachment_content(
    client,
    db_container,
    admin_user_api_key,
    admin_user,
    completion_model_factory,
    service_factory,
    transcription_model_factory,
    monkeypatch,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    space_id = await _create_space(client, headers)

    audio_upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("meeting.mp3", b"audio", "audio/mpeg")},
        headers=headers,
    )
    assert audio_upload.status_code == 200, audio_upload.text
    audio_file_id = UUID(audio_upload.json()["id"])

    async with db_container() as container:
        saved = await container.file_service().save_transcription(
            audio_file_id,
            "persisted sparse transcript",
        )
        assert saved == "persisted sparse transcript"

    reloaded_file = await client.get(f"/api/v1/files/{audio_file_id}/", headers=headers)
    assert reloaded_file.status_code == 200, reloaded_file.text
    assert reloaded_file.json()["transcription"] == "persisted sparse transcript"

    attachment_upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("policy.txt", b"durable policy", "text/plain")},
        headers=headers,
    )
    assert attachment_upload.status_code == 200, attachment_upload.text
    attachment = [{"id": attachment_upload.json()["id"]}]

    assistant = await client.post(
        "/api/v1/assistants/",
        json={"name": "Sparse assistant", "space_id": space_id},
        headers=headers,
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = assistant.json()["id"]
    updated_assistant = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"attachments": attachment},
        headers=headers,
    )
    assert updated_assistant.status_code == 200, updated_assistant.text

    async with db_container() as container:
        await transcription_model_factory(
            container.session(),
            "sparse-fixture-whisper",
            is_default=True,
        )

    app = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": "Sparse app"},
        headers=headers,
    )
    assert app.status_code == 201, app.text
    app_id = app.json()["id"]
    updated_app = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"attachments": attachment},
        headers=headers,
    )
    assert updated_app.status_code == 200, updated_app.text

    async with db_container() as container:
        session = container.session()
        completion_model = await completion_model_factory(
            session,
            f"sparse-completion-{uuid4().hex[:8]}",
            is_default=True,
        )
        session.add(
            SpacesCompletionModels(
                space_id=UUID(space_id),
                completion_model_id=completion_model.id,
            )
        )
        for number in range(2):
            session.add(
                GroupChatsTable(
                    name=f"Sparse group chat {number}",
                    space_id=UUID(space_id),
                    user_id=admin_user.id,
                )
            )
            await service_factory(
                session,
                f"Sparse service {number}",
                completion_model.id,
                space_id=UUID(space_id),
            )
        await session.flush()

    async with db_container() as container:
        session = container.session()
        assert session.bind is not None
        sync_engine = session.bind.sync_engine

    byte_loads = 0
    original_load_attachment_groups = FileContentLoader.load_attachment_groups

    async def count_attachment_byte_loads(self, groups):
        nonlocal byte_loads
        byte_loads += 1
        return await original_load_attachment_groups(self, groups)

    monkeypatch.setattr(
        FileContentLoader,
        "load_attachment_groups",
        count_attachment_byte_loads,
    )

    attachment_queries: list[str] = []
    matched_attachment_tables: set[str] = set()
    attachment_tables = (
        "files",
        "assistants_files",
        "apps_files",
        "file_content_references",
        "object_contents",
        "inline_content_payloads",
        "object_store_objects",
    )

    def capture_attachment_query(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = statement.lower()
        matched = {
            table
            for table in attachment_tables
            if re.search(rf"\b{re.escape(table)}\b", normalized)
        }
        if matched:
            matched_attachment_tables.update(matched)
            attachment_queries.append(statement)

    sa.event.listen(sync_engine, "before_cursor_execute", capture_attachment_query)
    try:
        full_space = await client.get(
            f"/api/v1/spaces/{space_id}/",
            headers=headers,
        )
        assert full_space.status_code == 200, full_space.text
        expected_applications = full_space.json()["applications"]
        assert byte_loads > 0
        assert attachment_queries
        assert "files" in matched_attachment_tables
        assert len(expected_applications["group_chats"]["items"]) == 2

        byte_loads = 0
        attachment_queries.clear()
        matched_attachment_tables.clear()
        applications = await client.get(
            f"/api/v1/spaces/{space_id}/applications/",
            headers=headers,
        )
    finally:
        sa.event.remove(
            sync_engine,
            "before_cursor_execute",
            capture_attachment_query,
        )

    assert applications.status_code == 200, applications.text
    assert applications.json() == expected_applications
    assert (byte_loads, attachment_queries, matched_attachment_tables) == (0, [], set())

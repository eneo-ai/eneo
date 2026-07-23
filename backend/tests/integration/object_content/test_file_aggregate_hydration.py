from __future__ import annotations

from uuid import UUID, uuid4

import pytest


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

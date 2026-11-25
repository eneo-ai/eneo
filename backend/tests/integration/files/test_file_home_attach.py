"""A file gets its home when it is attached, and is not attached anywhere else.

Through the API, the way a client does it: an upload is a draft, attaching it
to an assistant, an app, an app run or a question places it in that space, and
using the same file id in another space is refused.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.files.file_home import FileHomeConflictError, FileHomes
from eneo.main.models import ModelId
from eneo.questions.question import QuestionAdd
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState


@pytest.fixture
async def two_spaces(
    client,
    db_container,
    admin_user_api_key,
    completion_model_factory,
    transcription_model_factory,
):
    """Two spaces that can hold assistants and apps and answer questions."""
    headers = {"X-API-Key": admin_user_api_key.key}
    space_ids: list[str] = []
    for name in ("meetings", "economy"):
        space = await client.post(
            "/api/v1/spaces/",
            json={"name": f"{name}-{uuid4().hex[:8]}"},
            headers=headers,
        )
        assert space.status_code == 201, space.text
        space_ids.append(space.json()["id"])
    async with db_container() as container:
        session = container.session()
        await transcription_model_factory(session, "home-whisper", is_default=True)
        model = await completion_model_factory(
            session, f"home-{uuid4().hex[:8]}", is_default=True
        )
        for space_id in space_ids:
            session.add(
                SpacesCompletionModels(
                    space_id=UUID(space_id), completion_model_id=model.id
                )
            )
        model_id = str(model.id)
    return headers, space_ids[0], space_ids[1], model_id


@pytest.fixture
def answered(monkeypatch) -> None:
    async def fake_get_response(self: CompletionService, **kwargs: Any):
        return CompletionModelResponse(
            completion=Completion(text="answer", response_type=ResponseType.TEXT),
            model=kwargs["model"],
            extended_logging=None,
            total_token_count=1,
            usage=None,
        )

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)


async def _upload(client, headers) -> str:
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": (f"{uuid4().hex[:6]}.txt", b"minutes", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    return upload.json()["id"]


async def _assistant(client, headers, space_id: str, model_id: str) -> str:
    assistant = await client.post(
        "/api/v1/assistants/",
        json={"name": f"a-{uuid4().hex[:6]}", "space_id": space_id},
        headers=headers,
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = assistant.json()["id"]
    configured = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"completion_model": {"id": model_id}},
        headers=headers,
    )
    assert configured.status_code == 200, configured.text
    return assistant_id


async def _attach(client, headers, assistant_id: str, file_ids: list[str]):
    return await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"attachments": [{"id": file_id} for file_id in file_ids]},
        headers=headers,
    )


async def _home(db_container, file_id: str) -> str | None:
    async with db_container() as container:
        homes = await FileHomes(container.session()).homes_of([UUID(file_id)])
    home = homes[UUID(file_id)]
    return None if home is None else str(home)


async def test_an_upload_is_a_draft_until_it_is_attached(
    client, db_container, two_spaces
) -> None:
    headers, meetings, _, model_id = two_spaces
    file_id = await _upload(client, headers)
    assert await _home(db_container, file_id) is None
    assistant_id = await _assistant(client, headers, meetings, model_id)

    attached = await _attach(client, headers, assistant_id, [file_id])

    assert attached.status_code == 200, attached.text
    assert await _home(db_container, file_id) == meetings


async def test_a_file_is_not_attached_in_another_space_than_its_home(
    client, db_container, two_spaces
) -> None:
    headers, meetings, economy, model_id = two_spaces
    file_id = await _upload(client, headers)
    at_home = await _assistant(client, headers, meetings, model_id)
    elsewhere = await _assistant(client, headers, economy, model_id)
    assert (await _attach(client, headers, at_home, [file_id])).status_code == 200

    refused = await _attach(client, headers, elsewhere, [file_id])

    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "file_home_conflict"
    assert "Upload" in refused.json()["message"]
    # The file stays where it lives, and the other assistant got nothing.
    assert await _home(db_container, file_id) == meetings
    async with db_container() as container:
        attached_to = (
            await container.session().scalars(
                sa.select(AssistantsFiles.assistant_id).where(
                    AssistantsFiles.file_id == UUID(file_id)
                )
            )
        ).all()
    assert [str(assistant_id) for assistant_id in attached_to] == [at_home]


async def test_an_assistant_can_be_saved_with_what_it_already_had_attached(
    client, db_container, two_spaces
) -> None:
    """A file from before homes existed may be attached in two spaces. Saving
    either assistant again, with its attachments unchanged, must keep working."""
    headers, meetings, economy, model_id = two_spaces
    file_id = await _upload(client, headers)
    first = await _assistant(client, headers, meetings, model_id)
    second = await _assistant(client, headers, economy, model_id)
    assert (await _attach(client, headers, first, [file_id])).status_code == 200
    async with db_container() as container:
        session = container.session()
        # As earlier releases left it: no home, attached in both spaces.
        await session.execute(
            sa.text("UPDATE files SET home_space_id = NULL WHERE id = :id"),
            {"id": file_id},
        )
        session.add(AssistantsFiles(assistant_id=UUID(second), file_id=UUID(file_id)))

    saved = await _attach(client, headers, second, [file_id])

    assert saved.status_code == 200, saved.text
    assert await _home(db_container, file_id) is None
    # A new attachment of the same file is still held to the rule.
    third = await _assistant(client, headers, economy, model_id)
    refused = await _attach(client, headers, third, [file_id])
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "file_in_use_elsewhere"


async def test_a_file_attached_to_an_app_lives_in_the_apps_space(
    client, db_container, two_spaces
) -> None:
    headers, meetings, economy, _ = two_spaces
    file_id = await _upload(client, headers)
    apps = []
    for space_id in (meetings, economy):
        app = await client.post(
            f"/api/v1/spaces/{space_id}/applications/apps/",
            json={"name": f"app-{uuid4().hex[:6]}"},
            headers=headers,
        )
        assert app.status_code == 201, app.text
        apps.append(app.json()["id"])

    attached = await client.patch(
        f"/api/v1/apps/{apps[0]}/",
        json={"attachments": [{"id": file_id}]},
        headers=headers,
    )
    refused = await client.patch(
        f"/api/v1/apps/{apps[1]}/",
        json={"attachments": [{"id": file_id}]},
        headers=headers,
    )

    assert attached.status_code == 200, attached.text
    assert await _home(db_container, file_id) == meetings
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "file_home_conflict"


async def test_the_input_of_an_app_run_lives_in_the_apps_space(
    client, db_container, admin_user, two_spaces, app_factory
) -> None:
    headers, meetings, economy, model_id = two_spaces
    file_id = await _upload(client, headers)

    async def run_with_input(space_id: str) -> None:
        async with db_container() as container:
            session = container.session()
            app = await app_factory(
                session, "Transcriber", UUID(model_id), space_id=UUID(space_id)
            )
            run = AppRuns(
                tenant_id=admin_user.tenant_id,
                app_id=app.id,
                user_id=admin_user.id,
                completion_model_id=UUID(model_id),
                input_text="",
                output_text="",
            )
            session.add(run)
            await session.flush()
            # The step of the repository that ties the input to the run.
            await container.app_run_repo()._set_input_files(  # pyright: ignore[reportPrivateUsage]
                run, [SimpleNamespace(id=UUID(file_id))]
            )

    await run_with_input(meetings)

    assert await _home(db_container, file_id) == meetings
    with pytest.raises(FileHomeConflictError):
        await run_with_input(economy)
    assert await _home(db_container, file_id) == meetings


async def test_a_file_asked_about_lives_in_the_space_of_the_assistant(
    client, db_container, two_spaces, answered
) -> None:
    headers, meetings, economy, model_id = two_spaces
    file_id = await _upload(client, headers)
    at_home = await _assistant(client, headers, meetings, model_id)
    elsewhere = await _assistant(client, headers, economy, model_id)

    asked = await client.post(
        "/api/v1/conversations/",
        json={
            "question": "Summarise",
            "assistant_id": at_home,
            "stream": False,
            "files": [{"id": file_id}],
        },
        headers=headers,
    )
    again = await client.post(
        "/api/v1/conversations/",
        json={
            "question": "And the decisions?",
            "session_id": asked.json().get("session_id"),
            "stream": False,
            "files": [{"id": file_id}],
        },
        headers=headers,
    )
    refused = await client.post(
        "/api/v1/conversations/",
        json={
            "question": "Summarise",
            "assistant_id": elsewhere,
            "stream": False,
            "files": [{"id": file_id}],
        },
        headers=headers,
    )

    assert asked.status_code == 200, asked.text
    assert await _home(db_container, file_id) == meetings
    # The same file in the same space is used as often as wanted.
    assert again.status_code == 200, again.text
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "file_home_conflict"
    async with db_container() as container:
        still_there = await container.session().scalar(
            sa.select(sa.func.count()).select_from(Files).where(Files.id == file_id)
        )
    assert still_there == 1


async def test_an_upload_that_names_its_space_lives_there_from_the_start(
    client, db_container, two_spaces
) -> None:
    headers, meetings, _, _ = two_spaces

    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("minutes.txt", b"minutes", "text/plain")},
        data={"space_id": meetings},
        headers=headers,
    )

    # The response is the one an upload has always given.
    assert upload.status_code == 200, upload.text
    assert "home_space_id" not in upload.json()
    assert await _home(db_container, upload.json()["id"]) == meetings


async def test_an_upload_cannot_name_a_space_the_uploader_cannot_read(
    client, db_container, admin_user, patch_auth_service_jwt, two_spaces
) -> None:
    _, meetings, _, _ = two_spaces
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"file-home-{uuid4().hex[:8]}",
                permissions=[p for p in Permission if p is not Permission.ADMIN],
                tenant_id=admin_user.tenant_id,
            )
        )
        outsider = await container.user_repo().add(
            UserAdd(
                email=f"file-home-{uuid4().hex[:8]}@example.com",
                username=f"file_home_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        token = container.auth_service().create_access_token_for_user(outsider)
        outsider_id = outsider.id
    headers = {"Authorization": f"Bearer {token}"}

    async def stored() -> int:
        async with db_container() as container:
            return await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(Files)
                .where(Files.owner_user_id == outsider_id)
            )

    for space_id, status in ((meetings, 403), (str(uuid4()), 404)):
        refused = await client.post(
            "/api/v1/files/",
            files={"upload_file": ("minutes.txt", b"minutes", "text/plain")},
            data={"space_id": space_id},
            headers=headers,
        )
        assert refused.status_code == status, refused.text
    # Refused before anything was stored.
    assert await stored() == 0

    # The same person uploads a draft as before.
    draft = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("minutes.txt", b"minutes", "text/plain")},
        headers=headers,
    )
    assert draft.status_code == 200, draft.text
    assert await stored() == 1


async def test_a_file_made_for_a_question_lives_in_the_questions_space(
    client, db_container, admin_user, two_spaces
) -> None:
    headers, meetings, _, model_id = two_spaces
    assistant_id = UUID(await _assistant(client, headers, meetings, model_id))
    async with db_container() as container:
        conversation = await container.session_service().create_session(
            name="plan", assistant_id=assistant_id
        )
        question = await container.question_repo().add(
            QuestionAdd(
                question="skriv en plan",
                answer="",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                session_id=conversation.id,
                assistant_id=assistant_id,
            )
        )
        files = container.file_service()

        image = await files.save_image_from_bytes(
            b"\x89PNG-chart",
            name="chart.png",
            mimetype="image/png",
            for_question_id=question.id,
        )
        document = await files.save_generated_document(
            b"# Plan\n",
            name="Plan.md",
            mimetype="text/markdown",
            for_question_id=question.id,
        )
        # A reader's edit of the document is a file of its own, in the same home.
        version = await files.save_generated_document(
            b"# Plan\n\nPhase one.\n",
            name="Plan.md",
            mimetype="text/markdown",
            revises_file_id=document.id,
        )
        # Made for nothing in particular: a draft.
        loose = await files.save_image_from_bytes(b"\x89PNG-loose")
        made = [str(file.id) for file in (image, document, version, loose)]

    assert [await _home(db_container, file_id) for file_id in made] == [
        meetings,
        meetings,
        meetings,
        None,
    ]

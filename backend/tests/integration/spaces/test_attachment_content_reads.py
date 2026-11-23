"""A space read carries no attachment content; asking one assistant reads its own.

Attachment bytes went through PostgreSQL or the object store for every assistant
and app in a space on every read, a typing pause's preflight included, and were
thrown away. The responses only show facts about the files.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.files.file_models import FileContentNotLoadedError, FileWithoutContent
from eneo.object_content.content_service import ObjectContentService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _attached_assistant(client, headers, space_id: str, text: bytes) -> str:
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": (f"{uuid4().hex[:6]}.txt", text, "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    assistant = await client.post(
        "/api/v1/assistants/",
        json={"name": f"a-{uuid4().hex[:6]}", "space_id": space_id},
        headers=headers,
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = assistant.json()["id"]
    updated = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"attachments": [{"id": upload.json()["id"]}]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    return assistant_id


@pytest.fixture
async def space_with_assistants(
    client, admin_user_api_key, transcription_model_factory, db_container
):
    async with db_container() as container:
        await transcription_model_factory(
            container.session(), "fixture-whisper", is_default=True
        )
    headers = {"X-API-Key": admin_user_api_key.key}
    space = await client.post(
        "/api/v1/spaces/",
        json={"name": f"attachments-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert space.status_code == 201, space.text
    space_id = space.json()["id"]
    first = await _attached_assistant(client, headers, space_id, b"first policy")
    second = await _attached_assistant(client, headers, space_id, b"second policy")
    return headers, space_id, first, second


@pytest.fixture
def read_contents(monkeypatch) -> list[UUID]:
    reads: list[UUID] = []
    original = ObjectContentService.read_content_bytes

    async def spy(self, grants):
        reads.extend(grant.content_id for grant in grants)
        return await original(self, grants)

    monkeypatch.setattr(ObjectContentService, "read_content_bytes", spy)
    return reads


@pytest.mark.parametrize(
    "route",
    [
        "/api/v1/spaces/{space}/",
        "/api/v1/dashboard/",
        "/api/v1/spaces/?include_applications=true",
    ],
)
async def test_space_reads_load_no_attachment_content(
    client, space_with_assistants, read_contents, route
) -> None:
    headers, space_id, _, _ = space_with_assistants

    response = await client.get(route.format(space=space_id), headers=headers)

    assert response.status_code == 200, response.text
    assert read_contents == []


async def test_a_preflight_reads_the_attachments_of_its_assistant_only(
    client, space_with_assistants, read_contents
) -> None:
    headers, _, first, _ = space_with_assistants

    response = await client.post(
        "/api/v1/conversations/preflight",
        json={"question": "Hej", "assistant_id": first},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["assistant_attachment_tokens"] > 0
    assert len(read_contents) == 1


async def test_only_the_named_assistants_have_content(
    db_container, space_with_assistants
) -> None:
    _, space_id, first, second = space_with_assistants
    async with db_container() as container:
        repo = container.space_repo()
        space = await repo.get_space_by_assistant(UUID(first))
        with_tool = await repo.get_space_by_assistant(
            UUID(first), tool_assistant_id=UUID(second)
        )

    assert space.id == UUID(space_id)
    assert space.get_assistant(UUID(first)).attachments[0].text == "first policy"
    [other] = space.get_assistant(UUID(second)).attachments
    assert isinstance(other, FileWithoutContent)
    with pytest.raises(FileContentNotLoadedError):
        _ = other.text
    assert other.size == len(b"second policy")
    assert with_tool.get_assistant(UUID(second)).attachments[0].text == "second policy"


async def test_an_app_read_loads_that_apps_content_only(
    client, db_container, space_with_assistants
) -> None:
    headers, space_id, first, _ = space_with_assistants
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("app.txt", b"app policy", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    app = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"app-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert app.status_code == 201, app.text
    app_id = UUID(app.json()["id"])
    updated = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"attachments": [{"id": upload.json()["id"]}]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text

    async with db_container() as container:
        space = await container.space_repo().get_space_by_app(app_id)

    assert space.get_app(app_id).attachments[0].text == "app policy"
    assert isinstance(
        space.get_assistant(UUID(first)).attachments[0], FileWithoutContent
    )


@pytest.fixture
def prompt_file_texts(monkeypatch) -> list[list[str]]:
    """What each completion was sent, read the way the context builder reads it."""
    sent: list[list[str]] = []

    async def fake_get_response(self: CompletionService, **kwargs: Any):
        sent.append([file.text for file in kwargs.get("prompt_files") or []])
        return CompletionModelResponse(
            completion=Completion(text="answer", response_type=ResponseType.TEXT),
            model=kwargs["model"],
            extended_logging=None,
            total_token_count=1,
            usage=None,
        )

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)
    return sent


@pytest.fixture
async def askable_space(
    client, db_container, completion_model_factory, space_with_assistants
):
    headers, space_id, first, second = space_with_assistants
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session, f"ask-{uuid4().hex[:8]}", is_default=True
        )
        model_id = str(model.id)
        session.add(
            SpacesCompletionModels(
                space_id=UUID(space_id), completion_model_id=model.id
            )
        )
    for assistant_id in (first, second):
        response = await client.post(
            f"/api/v1/assistants/{assistant_id}/",
            json={"completion_model": {"id": model_id}},
            headers=headers,
        )
        assert response.status_code == 200, response.text
    return headers, space_id, first, second


async def test_an_ask_sends_the_assistants_own_attachments(
    client, askable_space, prompt_file_texts
) -> None:
    headers, _, first, _ = askable_space

    response = await client.post(
        "/api/v1/conversations/",
        json={"question": "Hej", "assistant_id": first, "stream": False},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert prompt_file_texts == [["first policy"]]


async def test_a_tool_assistant_ask_sends_the_tool_assistants_attachments(
    client, askable_space, prompt_file_texts
) -> None:
    headers, space_id, _, second = askable_space
    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)
    assert space.status_code == 200, space.text

    response = await client.post(
        "/api/v1/conversations/",
        json={
            "question": "Hej",
            "assistant_id": space.json()["default_assistant"]["id"],
            "stream": False,
            "tools": {"assistants": [{"id": second, "handle": "second"}]},
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert prompt_file_texts == [["second policy"]]


async def test_an_app_run_sends_the_apps_attachments(
    client, db_container, askable_space, prompt_file_texts
) -> None:
    headers, space_id, _, _ = askable_space
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("app.txt", b"app policy", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    app = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"app-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert app.status_code == 201, app.text
    app_id = UUID(app.json()["id"])
    updated = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"attachments": [{"id": upload.json()["id"]}]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text

    async with db_container() as container:
        await container.app_service().run_app(app_id, file_ids=[], text="Hej")

    assert prompt_file_texts == [["app policy"]]

"""A file created for a flow records its space and flow on the File row.

An upload to a published step (by a user or a service key), a Word template
uploaded to a draft and a template from a package import each record where the
file came from. A file uploaded through the ordinary file endpoint records no
origin, also when a flow uses it later. The origin grants no access and is not
in any response.
"""

from __future__ import annotations

import base64
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.responses import JSONResponse

from eneo.database.tables.flow_tables import FlowTemplateAssets
from eneo.files.file_models import FileMetadata
from eneo.flow_packages.api import flow_package_router
from eneo.flow_packages.infrastructure.flow_package_zip_writer import (
    write_flow_package,
)
from eneo.main.container.container import Container
from eneo.server.dependencies.container import load_container_upload_admission
from tests.docx_template_fixtures import control_template_bytes
from tests.integration.flows import test_flow_package_import_data_model as imports
from tests.integration.flows.test_flow_consumer_api_contract import (
    _create_flow_service_key,
    _create_published_required_runtime_input_flow,
    _create_space,
    _upload_runtime_document,
)
from tests.unittests.flow_packages.test_flow_package_templates import (
    _template_envelope,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ORIGIN_KEYS = {"origin_space_id", "origin_flow_id", "origin_flow_run_id"}


async def _stored(db_container, file_id: UUID | str) -> FileMetadata:
    async with db_container() as container:
        stored = await container.file_repo().get_by_id_for_lifecycle(UUID(str(file_id)))
    assert stored is not None
    return stored


def _origin(file: FileMetadata) -> tuple[UUID | None, UUID | None, UUID | None]:
    return (file.origin_space_id, file.origin_flow_id, file.origin_flow_run_id)


async def _create_flow(client, *, token: str, space_id: str) -> str:
    response = await client.post(
        "/api/v1/flows/",
        json={"space_id": space_id, "name": f"origin-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("uploader", ["user", "service_key"])
async def test_an_upload_to_a_published_step_records_space_and_flow(
    client, db_container, flow_process_auth_headers, admin_user, uploader
):
    token = flow_process_auth_headers.token
    space_id = await _create_space(client, token=token)
    flow = await _create_published_required_runtime_input_flow(
        client, token=token, space_id=space_id
    )
    headers = (
        {"Authorization": f"Bearer {token}"}
        if uploader == "user"
        else {"X-API-Key": await _create_flow_service_key(client, token=token)}
    )

    uploaded = await _upload_runtime_document(
        client, flow_id=flow["id"], step_id=flow["steps"][0]["id"], headers=headers
    )

    stored = await _stored(db_container, uploaded["id"])
    assert _origin(stored) == (UUID(space_id), UUID(flow["id"]), None)
    assert stored.owner_type.value == uploader
    assert (stored.owner_user_id == admin_user.id) is (uploader == "user")
    # The response is the same as before: the origin is not part of it.
    assert ORIGIN_KEYS.isdisjoint(uploaded)


async def test_an_ordinary_upload_records_no_origin(
    client, db_container, flow_process_auth_headers
):
    token = flow_process_auth_headers.token
    headers = dict(flow_process_auth_headers)
    response = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("note.txt", b"An ordinary file.", "text/plain")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert ORIGIN_KEYS.isdisjoint(response.json())
    file_id = response.json()["id"]

    # A user then attaches the file to a step of a flow: to the step's assistant.
    space_id = await _create_space(client, token=token)
    flow_id = await _create_flow(client, token=token, space_id=space_id)
    assistant = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"origin-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert assistant.status_code == 201, assistant.text
    assistant_id = assistant.json()["id"]
    with_step = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "steps": [
                {
                    "assistant_id": assistant_id,
                    "step_order": 1,
                    "user_description": "Answer with the attached note",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                }
            ]
        },
        headers=headers,
    )
    assert with_step.status_code == 200, with_step.text
    attached = await client.patch(
        f"/api/v1/flows/{flow_id}/assistants/{assistant_id}/",
        json={"attachments": [{"id": file_id}]},
        headers=headers,
    )
    assert attached.status_code == 200, attached.text

    flow = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)
    assert flow.status_code == 200, flow.text
    step_assistant = await client.get(
        f"/api/v1/flows/{flow_id}/assistants/{assistant_id}/", headers=headers
    )
    assert step_assistant.status_code == 200, step_assistant.text
    assert [step["assistant_id"] for step in flow.json()["steps"]] == [assistant_id]
    assert [file["id"] for file in step_assistant.json()["attachments"]] == [file_id]

    stored = await _stored(db_container, file_id)
    assert _origin(stored) == (None, None, None)


async def test_a_template_uploaded_to_a_draft_records_space_and_flow(
    client, db_container, flow_process_auth_headers
):
    token = flow_process_auth_headers.token
    space_id = await _create_space(client, token=token)
    flow_id = await _create_flow(client, token=token, space_id=space_id)

    upload = await client.post(
        f"/api/v1/flows/{flow_id}/template-files/",
        files={
            "upload_file": (
                "mall.docx",
                control_template_bytes(text=["case_id"]),
                DOCX_MIME,
            )
        },
        headers=dict(flow_process_auth_headers),
    )
    assert upload.status_code == 201, upload.text

    async with db_container() as container:
        file_id = await container.session().scalar(
            sa.select(FlowTemplateAssets.file_id).where(
                FlowTemplateAssets.id == UUID(upload.json()["id"])
            )
        )
    stored = await _stored(db_container, file_id)
    assert _origin(stored) == (UUID(space_id), UUID(flow_id), None)


async def test_a_template_from_a_package_import_records_space_and_flow(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
):
    package = write_flow_package(_template_envelope())
    async with db_container() as container:
        await load_container_upload_admission(container)
        session = container.session()
        space = await imports._create_space(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )
        space_id = space.id
        await imports._add_space_membership(
            session=session, space_id=space_id, user_id=admin_user.id
        )
        imports._patch_import_access(monkeypatch, target_space_id=space_id)

        imported = await flow_package_router.import_flow_package_as_draft(
            id=space_id,
            import_request=imports._import_request(base64.b64encode(package).decode()),
            request=imports._request(),
            container=cast(Container, container),
        )
        assert not isinstance(imported, JSONResponse)
        file_ids = list(
            await session.scalars(
                sa.select(FlowTemplateAssets.file_id).where(
                    FlowTemplateAssets.flow_id == imported.flow_id
                )
            )
        )

    assert len(file_ids) == 1
    stored = await _stored(db_container, file_ids[0])
    assert _origin(stored) == (space_id, imported.flow_id, None)

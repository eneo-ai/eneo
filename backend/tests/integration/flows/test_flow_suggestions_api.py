"""``GET /flows/{id}/suggestions/``: the draft's suggestions, for the people
who may edit the flow, inside their tenant."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.flows.domain.flow import FlowStep
from eneo.main.models import ModelId
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate
from tests.integration.flows.flow_seed_support import flow_space

_PROMPT_READ = "Sammanfatta.\n{{ step_1.output.text }}"


@dataclass(frozen=True)
class Tracer:
    """Two steps; step 2 reads step 1 as ``previous_step`` and, when the
    fixture says so, again in its assistant's prompt."""

    space_id: UUID
    flow_id: UUID
    step_ids: list[UUID]
    headers: dict[str, str]


async def _tracer(client, db_container, admin_user, *, prompt: str) -> Tracer:
    space_id = await flow_space(client, db_container, admin_user)
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_id(admin_user.id)
        headers = {
            "Authorization": "Bearer "
            + container.auth_service().create_access_token_for_user(admin)
        }
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id, name="Dubbel läsning", description=None, steps=[]
        )
        steps: list[FlowStep] = []
        for order, text in ((1, "Läs brevet."), (2, prompt)):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg{order}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(prompt=PromptCreate(text=text)),
            )
            steps.append(
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    input_source="flow_input" if order == 1 else "previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                )
            )
        saved = await service.update_flow(flow_id=flow.id, steps=steps)
    return Tracer(
        space_id=space_id,
        flow_id=saved.id,
        step_ids=[
            step.id
            for step in sorted(saved.steps, key=lambda item: item.step_order)
            if step.id is not None
        ],
        headers=headers,
    )


@pytest.fixture
async def tracer(client, db_container, admin_user, patch_auth_service_jwt) -> Tracer:
    return await _tracer(client, db_container, admin_user, prompt=_PROMPT_READ)


async def test_a_prompt_read_of_the_input_step_is_one_suggestion(
    client: AsyncClient, tracer: Tracer
):
    response = await client.get(
        f"/api/v1/flows/{tracer.flow_id}/suggestions/", headers=tracer.headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["flow_id"] == str(tracer.flow_id)
    assert body["draft_revision"] >= 1
    (item,) = body["items"]
    assert item["code"] == "duplicate_read"
    assert item["steps"] == [str(tracer.step_ids[1]), str(tracer.step_ids[0])]
    assert item["params"]["producer_step_order"] == 1
    assert item["params"]["producer_step_id"] == str(tracer.step_ids[0])
    assert item["params"]["contained"] is False
    assert [read["site"] for read in item["params"]["reads"]] == [
        "input_source",
        "assistant_prompt:step_1.output.text",
    ]
    assert item["impact"] == {"basis": "definition", "level": "high"}
    assert item["fix"]["kind"] == "patch"
    assert item["message"].startswith("Step 2 reads step 1 twice")


async def test_the_patch_is_the_editor_update_that_removes_the_prompt_read(
    client: AsyncClient, tracer: Tracer
):
    response = await client.get(
        f"/api/v1/flows/{tracer.flow_id}/suggestions/", headers=tracer.headers
    )

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    patch = item["fix"]["patch"]
    assert set(patch) == {"definition", "assistants"}
    assert patch["definition"] == {}
    (change,) = patch["assistants"]
    # Named by the step, so a shared assistant would be copied for it.
    assert change["step_id"] == str(tracer.step_ids[1])
    assert change["changes"] == {
        "prompt": {"text": "Sammanfatta.", "description": None}
    }


async def test_no_suggestion_without_the_prompt_read(
    client: AsyncClient, db_container, admin_user, patch_auth_service_jwt
):
    tracer = await _tracer(client, db_container, admin_user, prompt="Sammanfatta.")

    response = await client.get(
        f"/api/v1/flows/{tracer.flow_id}/suggestions/", headers=tracer.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


async def test_a_viewer_of_the_space_is_refused(
    client: AsyncClient, db_container, admin_user, user_factory, tracer: Tracer
):
    async with db_container() as container:
        session = container.session()
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-viewer-{uuid4().hex[:8]}",
                permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_MANAGE],
                tenant_id=admin_user.tenant_id,
            )
        )
        viewer = await user_factory(session)
        await session.execute(
            sa.insert(users_roles_table).values(user_id=viewer.id, role_id=role.id)
        )
        session.add(
            SpacesUsers(space_id=tracer.space_id, user_id=viewer.id, role="viewer")
        )
        await session.flush()
        in_db = await container.user_repo().get_user_by_id(viewer.id)
        token = container.auth_service().create_access_token_for_user(in_db)

    response = await client.get(
        f"/api/v1/flows/{tracer.flow_id}/suggestions/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "insufficient_space_permission"


async def test_a_flow_of_another_tenant_is_not_found(
    client: AsyncClient,
    db_container,
    user_factory,
    tenant_factory,
    tracer: Tracer,
):
    async with db_container() as container:
        session = container.session()
        tenant = await tenant_factory(session)
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-author-{uuid4().hex[:8]}",
                permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_MANAGE],
                tenant_id=tenant.id,
            )
        )
        outsider = await user_factory(session, tenant_id=tenant.id)
        await session.flush()
        updated = await container.user_repo().update(
            UserUpdate(id=outsider.id, roles=[ModelId(id=role.id)])
        )
        assert updated is not None
        token = container.auth_service().create_access_token_for_user(updated)

    response = await client.get(
        f"/api/v1/flows/{tracer.flow_id}/suggestions/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404, response.text

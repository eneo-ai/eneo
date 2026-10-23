"""``GET /flows/{id}/suggestions/``: the draft's suggestions, for the people
who may edit the flow, inside their tenant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
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


# --- Applying suggestions ---------------------------------------------------


@dataclass(frozen=True)
class StepSpec:
    prompt: str = "Gör så här."
    input_source: str = "previous_step"
    output_mode: str = "pass_through"
    input_type: str = "text"
    output_type: str = "text"


async def _seeded(client, db_container, admin_user, specs: list[StepSpec]) -> Tracer:
    """A flow with a step per spec, each with its own assistant; the first
    reads the run."""
    space_id = await flow_space(client, db_container, admin_user)
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_id(admin_user.id)
        headers = {
            "Authorization": "Bearer "
            + container.auth_service().create_access_token_for_user(admin)
        }
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id, name="Förslag", description=None, steps=[]
        )
        steps: list[FlowStep] = []
        for order, spec in enumerate(specs, start=1):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg{order}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(prompt=PromptCreate(text=spec.prompt)),
            )
            steps.append(
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    input_source="flow_input" if order == 1 else spec.input_source,
                    input_type=spec.input_type,
                    output_mode=spec.output_mode,
                    output_type=spec.output_type,
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


async def _suggestions(client: AsyncClient, flow: Tracer) -> dict[str, Any]:
    response = await client.get(
        f"/api/v1/flows/{flow.flow_id}/suggestions/", headers=flow.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _apply(
    client: AsyncClient,
    flow: Tracer,
    fingerprints: list[str],
    revision: int,
    headers: dict[str, str] | None = None,
):
    return await client.post(
        f"/api/v1/flows/{flow.flow_id}/suggestions/apply/",
        json={"expected_revision": revision, "fingerprints": fingerprints},
        headers=headers or flow.headers,
    )


async def _prompt_of(db_container, flow: Tracer, step_id: UUID) -> str:
    async with db_container() as container:
        service = container.flow_service()
        saved = await service.get_flow(flow.flow_id)
        prompts = await service.get_flow_assistant_prompts(saved)
    step = next(step for step in saved.steps if step.id == step_id)
    return prompts[step.assistant_id].text


def _record_audit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    log_async = AuditService.log_async

    async def record(self: AuditService, **kwargs: Any) -> Any:
        entries.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return entries


async def _viewer_token(db_container, admin_user, user_factory, space_id) -> str:
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
        session.add(SpacesUsers(space_id=space_id, user_id=viewer.id, role="viewer"))
        await session.flush()
        in_db = await container.user_repo().get_user_by_id(viewer.id)
        return container.auth_service().create_access_token_for_user(in_db)


async def test_applying_the_duplicate_removes_the_prompt_read_and_audits_it(
    client: AsyncClient,
    db_container,
    tracer: Tracer,
    monkeypatch: pytest.MonkeyPatch,
):
    listed = await _suggestions(client, tracer)
    (item,) = listed["items"]
    audited = _record_audit(monkeypatch)

    response = await _apply(
        client, tracer, [item["fingerprint"]], listed["draft_revision"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == [item["fingerprint"]]
    assert body["skipped"] == []
    assert body["flow"]["id"] == str(tracer.flow_id)
    assert body["flow"]["draft_revision"] > listed["draft_revision"]
    assert await _prompt_of(db_container, tracer, tracer.step_ids[1]) == "Sammanfatta."
    after = await _suggestions(client, tracer)
    assert after["items"] == []
    assert after["draft_revision"] == body["flow"]["draft_revision"]
    assert audited
    for entry in audited:
        extra = entry["metadata"]["extra"]
        assert extra["origin"] == "suggestion"
        assert extra["suggestion_code"] == "duplicate_read"
        assert extra["suggestion_fingerprint"] == item["fingerprint"]
    assert ActionType.FLOW_UPDATED in [entry["action"] for entry in audited]

    again = await _apply(
        client, tracer, [item["fingerprint"]], body["flow"]["draft_revision"]
    )

    assert again.status_code == 409, again.text
    assert again.json()["code"] == "flow_suggestion_stale"


async def test_a_stale_revision_is_the_editors_conflict(
    client: AsyncClient, tracer: Tracer
):
    listed = await _suggestions(client, tracer)
    (item,) = listed["items"]

    response = await _apply(
        client, tracer, [item["fingerprint"]], listed["draft_revision"] - 1
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "stale_revision"


async def test_a_stale_fingerprint_changes_nothing_of_the_batch(
    client: AsyncClient, db_container, tracer: Tracer
):
    listed = await _suggestions(client, tracer)
    (item,) = listed["items"]

    response = await _apply(
        client, tracer, [item["fingerprint"], "0" * 64], listed["draft_revision"]
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "flow_suggestion_stale"
    assert response.json()["context"]["fingerprints"] == ["0" * 64]
    assert await _suggestions(client, tracer) == listed
    assert await _prompt_of(db_container, tracer, tracer.step_ids[1]) == _PROMPT_READ


async def test_two_fixes_of_one_prompt_both_land(
    client: AsyncClient, db_container, admin_user, patch_auth_service_jwt
):
    # Step 3 reads step 2 as its input and again in its prompt, and step 1
    # twice in its prompt: both fixes rewrite the same prompt.
    flow = await _seeded(
        client,
        db_container,
        admin_user,
        [
            StepSpec(),
            StepSpec(),
            StepSpec(
                prompt=(
                    "Skriv.\n{{ step_2.output.text }}\n"
                    "{{ step_1.output.text }}\n{{ step_1.output.text }}"
                )
            ),
        ],
    )
    listed = await _suggestions(client, flow)
    fingerprints = [item["fingerprint"] for item in listed["items"]]
    assert len(fingerprints) == 2
    assert {item["fix"]["kind"] for item in listed["items"]} == {"patch"}

    response = await _apply(
        client, flow, list(reversed(fingerprints)), listed["draft_revision"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == fingerprints
    assert body["skipped"] == []
    assert (
        await _prompt_of(db_container, flow, flow.step_ids[2])
        == "Skriv.\n{{ step_1.output.text }}"
    )
    assert (await _suggestions(client, flow))["items"] == []


async def test_fixing_all_removes_a_chain_of_relays(
    client: AsyncClient, db_container, admin_user, patch_auth_service_jwt
):
    # Steps 2 and 3 each only pass on the step before. Removing step 2
    # renumbers step 3, which stays the same relay and is removed too.
    flow = await _seeded(
        client,
        db_container,
        admin_user,
        [
            StepSpec(output_type="json"),
            StepSpec(output_mode="copy_input", input_type="json", output_type="json"),
            StepSpec(output_mode="copy_input", input_type="json", output_type="json"),
            StepSpec(input_type="json"),
        ],
    )
    listed = await _suggestions(client, flow)
    relays = [item for item in listed["items"] if item["code"] == "relay_step"]
    assert [item["steps"][0] for item in relays] == [
        str(flow.step_ids[1]),
        str(flow.step_ids[2]),
    ]
    fingerprints = [item["fingerprint"] for item in relays]

    response = await _apply(client, flow, fingerprints, listed["draft_revision"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == fingerprints
    assert body["skipped"] == []
    assert [step["id"] for step in body["flow"]["steps"]] == [
        str(flow.step_ids[0]),
        str(flow.step_ids[3]),
    ]
    after = await _suggestions(client, flow)
    assert [item for item in after["items"] if item["code"] == "relay_step"] == []


async def test_a_viewer_may_not_apply_a_suggestion(
    client: AsyncClient, db_container, admin_user, user_factory, tracer: Tracer
):
    listed = await _suggestions(client, tracer)
    (item,) = listed["items"]
    token = await _viewer_token(db_container, admin_user, user_factory, tracer.space_id)

    response = await _apply(
        client,
        tracer,
        [item["fingerprint"]],
        listed["draft_revision"],
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403, response.text


async def test_a_suggestion_of_another_tenants_flow_is_not_found(
    client: AsyncClient,
    db_container,
    user_factory,
    tenant_factory,
    tracer: Tracer,
):
    listed = await _suggestions(client, tracer)
    (item,) = listed["items"]
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

    response = await _apply(
        client,
        tracer,
        [item["fingerprint"]],
        listed["draft_revision"],
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404, response.text


async def test_a_published_flow_must_be_unpublished_first(
    client: AsyncClient, tracer: Tracer
):
    published = await client.post(
        f"/api/v1/flows/{tracer.flow_id}/publish/", headers=tracer.headers
    )
    assert published.status_code == 200, published.text
    listed = await _suggestions(client, tracer)
    (item,) = listed["items"]

    response = await _apply(
        client, tracer, [item["fingerprint"]], listed["draft_revision"]
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "flow_unpublish_required"

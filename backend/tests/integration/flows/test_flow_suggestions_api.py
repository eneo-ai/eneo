"""``GET /flows/{id}/suggestions/``: the draft's suggestions, for the people
who may edit the flow, inside their tenant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowProviderCalls,
    FlowRuns,
    Flows,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.forwarding_facts import ForwardingEdgeFacts, ForwardingFacts
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdges,
    FlowResolvedInputJsonPath,
    FlowResolvedInputStepResultSource,
    build_resolved_input_edge,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
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
    assert item["impact"] == {
        "basis": "definition",
        "level": "high",
        "tokens_per_run": None,
        "run_count": None,
        "version": None,
        "step_changed_since": None,
    }
    assert body["runs"] is None
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


# --- Measured from recent runs ----------------------------------------------

_INPUT_TEXT = "Brevet i sin helhet. " * 50


async def _publish(client: AsyncClient, flow: Tracer) -> None:
    response = await client.post(
        f"/api/v1/flows/{flow.flow_id}/publish/", headers=flow.headers
    )
    assert response.status_code == 200, response.text


async def _token_with(
    db_container, user_id: UUID, tenant_id: UUID, permissions: list[Permission]
) -> str:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-trace-{uuid4().hex[:8]}",
                permissions=permissions,
                tenant_id=tenant_id,
            )
        )
        updated = await container.user_repo().update(
            UserUpdate(id=user_id, roles=[ModelId(id=role.id)])
        )
        assert updated is not None
        return container.auth_service().create_access_token_for_user(updated)


_TRACE_AUTHOR = [
    Permission.ASSISTANTS,
    Permission.SHARED_SPACES,
    Permission.FLOWS_VIEW,
    Permission.FLOWS_MANAGE,
    Permission.FLOWS_TRACE,
]


_TRACER_READS = ("input_source", "assistant_prompt:step_1.output.text")


async def _seed_run(
    db_container,
    flow: Tracer,
    *,
    principal_user_id: UUID,
    tokens: int,
    binding_refs: tuple[str, ...] = _TRACER_READS,
    output_tokens: int = 20,
    facts: ForwardingFacts | None = None,
) -> UUID:
    """A completed run of version 1 in which step 2 got step 1's text at
    each of ``binding_refs`` (by default as its input and again in its
    prompt), all edges sent in one call billed ``tokens`` input tokens, and
    with ``facts`` the forwarding facts the worker recorded for it."""
    now = datetime.now(timezone.utc)
    async with db_container() as container:
        session = container.session()
        tenant_id = container.user().tenant_id
        run = FlowRuns(
            flow_id=flow.flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=principal_user_id,
            tenant_id=tenant_id,
            trace_id=uuid4(),
            status="completed",
            input_payload_json={"text": "Ett brev."},
            evidence_classification_level=0,
        )
        session.add(run)
        await session.flush()
        attempts: list[FlowStepAttempts] = []
        for order, step_id in enumerate(flow.step_ids, start=1):
            session.add(
                FlowStepResults(
                    flow_run_id=run.id,
                    flow_id=flow.flow_id,
                    tenant_id=tenant_id,
                    step_id=step_id,
                    step_order=order,
                    current_attempt_no=1,
                    status="completed",
                )
            )
            attempt = FlowStepAttempts(
                flow_run_id=run.id,
                flow_id=flow.flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=order,
                attempt_no=1,
                status="completed",
                started_at=now,
                finished_at=now,
            )
            session.add(attempt)
            attempts.append(attempt)
        await session.flush()
        source = FlowResolvedInputStepResultSource(
            kind="step_result",
            source_step_id=flow.step_ids[0],
            source_attempt_no=1,
            selector=FlowResolvedInputJsonPath(
                kind="json_path", path=("output", "text")
            ),
        )
        edges = FlowResolvedInputEdges(
            schema_version=1,
            edges=tuple(
                build_resolved_input_edge(
                    binding_ref=binding_ref, source=source, selected_value=_INPUT_TEXT
                )
                for binding_ref in binding_refs
            ),
        )
        reader = attempts[1]
        session.add(
            FlowStepAttemptResolvedInputs(
                flow_step_attempt_id=reader.id,
                resolved_input_edges_jsonb=edges.model_dump(mode="json"),
            )
        )
        await session.flush()
        session.add(
            FlowProviderCalls(
                flow_step_attempt_id=reader.id,
                resolved_inputs_attempt_id=reader.id,
                ordinal=1,
                call_kind="completion",
                status="completed",
                request_schema_version=2,
                provider_request_hash="0" * 64,
                requested_model="modell",
                response_format="none",
                requested_capabilities=[],
                resolved_input_edge_indexes=list(range(len(binding_refs))),
                call_reason="initial",
                num_tokens_input=tokens,
                num_tokens_output=output_tokens,
                input_source="provider",
                output_source="provider",
                requested_at=now,
                finished_at=now,
            )
        )
        await session.flush()
        if facts is not None:
            assert await FlowRunRepository(session=session).record_forwarding_facts(
                run_id=run.id,
                step_id=flow.step_ids[1],
                attempt_no=1,
                tenant_id=tenant_id,
                facts=facts,
            )
        return run.id


async def _measured(client: AsyncClient, flow: Tracer, headers, runs: int = 5):
    return await client.get(
        f"/api/v1/flows/{flow.flow_id}/suggestions/",
        params={"runs": runs},
        headers=headers,
    )


async def _evidence_audits(db_container, flow_id: UUID) -> list[dict[str, Any]]:
    async with db_container() as container:
        rows = await container.session().scalars(
            sa.select(AuditLog.log_metadata)
            .where(AuditLog.entity_id == flow_id)
            .where(AuditLog.action == ActionType.FLOW_EVIDENCE_VIEWED.value)
        )
        return [dict(row) for row in rows]


async def test_measured_runs_give_the_duplicate_its_tokens_and_one_audit_entry(
    client: AsyncClient, db_container, admin_user, tracer: Tracer
):
    await _publish(client, tracer)
    token = await _token_with(
        db_container, admin_user.id, admin_user.tenant_id, _TRACE_AUTHOR
    )
    headers = {"Authorization": f"Bearer {token}"}
    run_ids = [
        await _seed_run(
            db_container, tracer, principal_user_id=admin_user.id, tokens=tokens
        )
        for tokens in (600, 800)
    ]

    response = await _measured(client, tracer, headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runs"] == {"requested": 5, "counted": 2, "left_out": 0}
    (item,) = body["items"]
    assert item["code"] == "duplicate_read"
    # The prompt read is half of each call's input bytes: 300 and 400 tokens.
    assert item["impact"] == {
        "basis": "runs",
        "level": "high",
        "tokens_per_run": 350,
        "run_count": 2,
        "version": 1,
        "step_changed_since": False,
    }
    static = await _suggestions(client, tracer)
    assert static["runs"] is None
    assert static["items"][0]["fingerprint"] == item["fingerprint"]
    (audit,) = await _evidence_audits(db_container, tracer.flow_id)
    extra = audit["extra"]
    assert extra["evidence_detail"] == "suggestion_measurements"
    assert extra["flow_id"] == str(tracer.flow_id)
    assert sorted(extra["run_ids"]) == sorted(str(run_id) for run_id in run_ids)
    assert extra["left_out_run_count"] == 0
    assert extra["requested_runs"] == 5


async def test_measuring_runs_needs_the_trace_permission(
    client: AsyncClient, db_container, tracer: Tracer
):
    response = await _measured(client, tracer, tracer.headers)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "insufficient_tenant_permission"
    assert await _evidence_audits(db_container, tracer.flow_id) == []


async def test_a_run_the_caller_may_not_see_is_left_out_and_counted(
    client: AsyncClient, db_container, admin_user, user_factory, tracer: Tracer
):
    await _publish(client, tracer)
    # An editor of the space who owns the draft sees the evidence of their
    # own runs, not of the space owner's.
    async with db_container() as container:
        session = container.session()
        editor = await user_factory(session)
        session.add(
            SpacesUsers(space_id=tracer.space_id, user_id=editor.id, role="editor")
        )
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == tracer.flow_id)
            .values(owner_user_id=editor.id)
        )
        await session.flush()
        editor_id = editor.id
    token = await _token_with(
        db_container, editor_id, admin_user.tenant_id, _TRACE_AUTHOR
    )
    own = await _seed_run(db_container, tracer, principal_user_id=editor_id, tokens=600)
    await _seed_run(db_container, tracer, principal_user_id=admin_user.id, tokens=800)

    response = await _measured(client, tracer, {"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runs"] == {"requested": 5, "counted": 1, "left_out": 1}
    (item,) = body["items"]
    assert item["impact"]["tokens_per_run"] == 300
    assert item["impact"]["run_count"] == 1
    (audit,) = await _evidence_audits(db_container, tracer.flow_id)
    assert audit["extra"]["run_ids"] == [str(own)]
    assert audit["extra"]["left_out_run_count"] == 1


async def test_measuring_another_tenants_flow_is_not_found(
    client: AsyncClient,
    db_container,
    admin_user,
    user_factory,
    tenant_factory,
    tracer: Tracer,
):
    await _publish(client, tracer)
    await _seed_run(db_container, tracer, principal_user_id=admin_user.id, tokens=600)
    async with db_container() as container:
        tenant = await tenant_factory(container.session())
        outsider = await user_factory(container.session(), tenant_id=tenant.id)
        await container.session().flush()
        outsider_id, tenant_id = outsider.id, tenant.id
    token = await _token_with(db_container, outsider_id, tenant_id, _TRACE_AUTHOR)

    response = await _measured(client, tracer, {"Authorization": f"Bearer {token}"})

    assert response.status_code == 404, response.text
    assert await _evidence_audits(db_container, tracer.flow_id) == []


# --- Measured from the forwarding facts ---------------------------------------

_INPUT_BYTES = len(_INPUT_TEXT.encode("utf-8"))


def _relay_facts(copied: float = 0.8) -> ForwardingFacts:
    """Step 2's call: ``copied`` of its 1000-byte output was found in the
    edge from step 1."""
    return ForwardingFacts(
        schema_version=1,
        measured=True,
        call_count=1,
        edges=(
            ForwardingEdgeFacts(
                edge_index=0,
                byte_size=_INPUT_BYTES,
                shingle_count=193,
                sample_every=1,
                repeated_bytes=0,
                copied_to_output_ratio=copied,
            ),
        ),
        output_byte_size=1000,
        output_shingle_count=150,
        output_verbatim_ratio=copied,
    )


async def _relay_flow(client, db_container, admin_user) -> Tracer:
    """Step 2 reads step 1 as its input; step 3 reads step 2."""
    flow = await _seeded(client, db_container, admin_user, [StepSpec()] * 3)
    await _publish(client, flow)
    return flow


async def _seed_relay_run(db_container, flow: Tracer, admin_user) -> UUID:
    return await _seed_run(
        db_container,
        flow,
        principal_user_id=admin_user.id,
        tokens=400,
        binding_refs=("input_source",),
        output_tokens=300,
        facts=_relay_facts(),
    )


async def test_a_step_that_copies_its_input_on_is_a_measured_relay(
    client: AsyncClient, db_container, admin_user, patch_auth_service_jwt
):
    flow = await _relay_flow(client, db_container, admin_user)
    run_id = await _seed_relay_run(db_container, flow, admin_user)
    token = await _token_with(
        db_container, admin_user.id, admin_user.tenant_id, _TRACE_AUTHOR
    )

    response = await _measured(
        client, flow, {"Authorization": f"Bearer {token}"}, runs=1
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runs"] == {"requested": 1, "counted": 1, "left_out": 0}
    (item,) = [item for item in body["items"] if item["code"] == "model_relay"]
    second, first, third = flow.step_ids[1], flow.step_ids[0], flow.step_ids[2]
    assert item["steps"] == [str(second), str(first), str(third)]
    assert item["params"]["producer_step_id"] == str(flow.step_ids[0])
    assert item["params"]["copied_share"] == 0.8
    assert (item["params"]["run_count"], item["params"]["held_runs"]) == (1, 1)
    # 80 % of the call's 300 output tokens.
    assert item["impact"] == {
        "basis": "runs",
        "level": "high",
        "tokens_per_run": 240,
        "run_count": 1,
        "version": 1,
        "step_changed_since": False,
    }
    assert item["fix"] == {"kind": "assisted", "patch": None}
    static = await _suggestions(client, flow)
    assert [item for item in static["items"] if item["code"] == "model_relay"] == []
    (audit,) = await _evidence_audits(db_container, flow.flow_id)
    assert audit["extra"]["run_ids"] == [str(run_id)]
    assert audit["extra"]["forwarding_facts_attempt_count"] == 1


async def test_a_relay_is_not_measured_without_the_trace_permission(
    client: AsyncClient, db_container, admin_user, patch_auth_service_jwt
):
    flow = await _relay_flow(client, db_container, admin_user)
    await _seed_relay_run(db_container, flow, admin_user)

    response = await _measured(client, flow, flow.headers, runs=1)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "insufficient_tenant_permission"
    assert await _evidence_audits(db_container, flow.flow_id) == []


async def test_the_forwarding_facts_of_another_tenant_are_never_read(
    client: AsyncClient,
    db_container,
    admin_user,
    user_factory,
    tenant_factory,
    patch_auth_service_jwt,
):
    flow = await _relay_flow(client, db_container, admin_user)
    run_id = await _seed_relay_run(db_container, flow, admin_user)
    async with db_container() as container:
        tenant = await tenant_factory(container.session())
        outsider = await user_factory(container.session(), tenant_id=tenant.id)
        await container.session().flush()
        outsider_id, tenant_id = outsider.id, tenant.id
    token = await _token_with(db_container, outsider_id, tenant_id, _TRACE_AUTHOR)

    response = await _measured(
        client, flow, {"Authorization": f"Bearer {token}"}, runs=1
    )

    assert response.status_code == 404, response.text
    assert await _evidence_audits(db_container, flow.flow_id) == []
    # The evidence statement reads the facts with the attempt, in the tenant
    # it is asked for and no other.
    async with db_container() as container:
        repo = container.flow_suggestion_evidence_repo()
        own = await repo.read_attempts(
            flow_id=flow.flow_id, run_ids=[run_id], tenant_id=admin_user.tenant_id
        )
        other = await repo.read_attempts(
            flow_id=flow.flow_id, run_ids=[run_id], tenant_id=tenant_id
        )
    reader = next(
        attempt for attempt in own[run_id] if attempt.step_id == flow.step_ids[1]
    )
    assert reader.forwarding == _relay_facts()
    assert other == {}

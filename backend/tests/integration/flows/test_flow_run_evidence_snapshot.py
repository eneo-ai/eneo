from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import FlowStepAttempts
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.users_table import users_roles_table
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.domain.flow import Flow
from eneo.flows.domain.provider_call import ProviderCallEvidencePage
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallRepository,
)
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    StepAttemptProvenanceSize,
)
from eneo.flows.published_definition import build_published_definition_json
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceRoleValue


@dataclass(frozen=True, slots=True)
class _SnapshotSeed:
    flow_id: UUID
    run_id: UUID
    step_id: UUID
    tenant_id: UUID


def _attempt(seed: _SnapshotSeed, *, attempt_no: int) -> FlowStepAttempts:
    now = datetime.now(timezone.utc)
    return FlowStepAttempts(
        flow_run_id=seed.run_id,
        flow_id=seed.flow_id,
        tenant_id=seed.tenant_id,
        step_id=seed.step_id,
        step_order=1,
        attempt_no=attempt_no,
        status="completed",
        provenance_json={"schema_version": 1, "llm": None, "rag": None},
        started_at=now,
        finished_at=now,
    )


async def _seed_snapshot_run(
    *,
    session: AsyncSession,
    space_factory,
    admin_user,
) -> _SnapshotSeed:
    space = await space_factory(session, "Evidence snapshot", [])
    await session.execute(
        sa.text(
            """
            INSERT INTO spaces_users (space_id, user_id, role)
            VALUES (:space_id, :user_id, :role)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "space_id": str(space.id),
            "user_id": str(admin_user.id),
            "role": SpaceRoleValue.ADMIN.value,
        },
    )
    flow_repo = FlowRepository(session=session)
    flow = await flow_repo.create(
        Flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            name="Evidence snapshot",
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
        ),
        tenant_id=admin_user.tenant_id,
    )
    flow_id = flow.require_persisted_id()
    await FlowVersionRepository(session=session).create(
        flow_id=flow_id,
        version=1,
        definition_json=build_published_definition_json(
            flow_id=flow_id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[],
        ),
        tenant_id=admin_user.tenant_id,
    )
    run = await FlowRunRepository(session=session).create(
        flow_id=flow_id,
        flow_version=1,
        principal_type="user",
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={},
        preseed_steps=[],
    )
    seed = _SnapshotSeed(
        flow_id=flow_id,
        run_id=run.id,
        step_id=uuid4(),
        tenant_id=admin_user.tenant_id,
    )
    session.add(_attempt(seed, attempt_no=1))
    return seed


def _summary_attempt_count(payload: dict[str, object]) -> int:
    debug_export = payload["debug_export"]
    assert isinstance(debug_export, dict)
    debug_run = debug_export["run"]
    assert isinstance(debug_run, dict)
    summary = debug_run["summary"]
    assert isinstance(summary, dict)
    attempt_count = summary["attempts_count"]
    assert isinstance(attempt_count, int)
    return attempt_count


async def _admin_token(*, db_container, patch_auth_service_jwt, admin_user) -> str:
    _ = patch_auth_service_jwt
    async with db_container() as container:
        session = container.session()
        role = Roles(
            name=f"Evidence snapshot {uuid4().hex[:8]}",
            permissions=[
                Permission.ADMIN.value,
                Permission.FLOWS_VIEW.value,
                Permission.FLOWS_TRACE.value,
            ],
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(
                user_id=admin_user.id,
                role_id=role.id,
            )
        )
        user = await container.user_repo().get_user_by_email(admin_user.email)
        return container.auth_service().create_access_token_for_user(user)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_evidence_view_route_uses_one_repeatable_read_snapshot(
    client,
    db_container,
    patch_auth_service_jwt,
    setup_database,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as seed_session, seed_session.begin():
        seed = await _seed_snapshot_run(
            session=seed_session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )
    endpoint = f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/"
    headers = {"Authorization": f"Bearer {token}"}

    preflight_attempt_counts: list[int] = []
    observed_isolation: list[str] = []
    original_measure = FlowRunRepository.measure_step_attempt_provenance

    async def measure_then_mutate(
        repository: FlowRunRepository, *, run_id: UUID, tenant_id: UUID
    ) -> StepAttemptProvenanceSize:
        measurement = await original_measure(
            repository,
            run_id=run_id,
            tenant_id=tenant_id,
        )
        preflight_attempt_counts.append(measurement.attempt_count)
        isolation = await repository.session.scalar(
            sa.text("SHOW transaction_isolation")
        )
        assert isinstance(isolation, str)
        observed_isolation.append(isolation)
        if len(preflight_attempt_counts) == 1:
            async with (
                sessionmanager.session() as mutation_session,
                mutation_session.begin(),
            ):
                mutation_session.add(_attempt(seed, attempt_no=2))
        return measurement

    monkeypatch.setattr(
        FlowRunRepository,
        "measure_step_attempt_provenance",
        measure_then_mutate,
    )

    before_response = await client.get(endpoint, headers=headers)
    after_response = await client.get(endpoint, headers=headers)

    assert before_response.status_code == 200, before_response.text
    assert after_response.status_code == 200, after_response.text
    before_payload = before_response.json()
    after_payload = after_response.json()
    assert observed_isolation == ["repeatable read", "repeatable read"]
    assert preflight_attempt_counts == [1, 2]
    assert [attempt["attempt_no"] for attempt in before_payload["step_attempts"]] == [1]
    assert _summary_attempt_count(before_payload) == 1
    assert [attempt["attempt_no"] for attempt in after_payload["step_attempts"]] == [
        1,
        2,
    ]
    assert _summary_attempt_count(after_payload) == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_call_and_export_routes_enter_repeatable_read_before_service(
    client,
    db_container,
    patch_auth_service_jwt,
    setup_database,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as seed_session, seed_session.begin():
        seed = await _seed_snapshot_run(
            session=seed_session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )
    headers = {"Authorization": f"Bearer {token}"}
    active_route = ""
    observed_isolation: dict[str, str] = {}
    original_measure = FlowRunRepository.measure_step_attempt_provenance
    original_provider_page = FlowProviderCallRepository.list_evidence_page

    async def capture_export_isolation(
        repository: FlowRunRepository, *, run_id: UUID, tenant_id: UUID
    ) -> StepAttemptProvenanceSize:
        isolation = await repository.session.scalar(
            sa.text("SHOW transaction_isolation")
        )
        assert isinstance(isolation, str)
        observed_isolation[active_route] = isolation
        return await original_measure(
            repository,
            run_id=run_id,
            tenant_id=tenant_id,
        )

    async def capture_provider_isolation(
        repository: FlowProviderCallRepository,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int,
        after_event_id: UUID | None = None,
        attempt_id: UUID | None = None,
    ) -> ProviderCallEvidencePage:
        isolation = await repository.session.scalar(
            sa.text("SHOW transaction_isolation")
        )
        assert isinstance(isolation, str)
        observed_isolation[active_route] = isolation
        return await original_provider_page(
            repository,
            run_id=run_id,
            tenant_id=tenant_id,
            limit=limit,
            after_event_id=after_event_id,
            attempt_id=attempt_id,
        )

    monkeypatch.setattr(
        FlowRunRepository,
        "measure_step_attempt_provenance",
        capture_export_isolation,
    )
    monkeypatch.setattr(
        FlowProviderCallRepository,
        "list_evidence_page",
        capture_provider_isolation,
    )

    active_route = "provider_calls"
    provider_response = await client.get(
        f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/provider-calls/",
        headers=headers,
    )
    active_route = "export"
    export_response = await client.get(
        f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/export",
        headers=headers,
    )

    assert provider_response.status_code == 200, provider_response.text
    assert export_response.status_code == 200, export_response.text
    assert observed_isolation == {
        "provider_calls": "repeatable read",
        "export": "repeatable read",
    }

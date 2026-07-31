from __future__ import annotations

import gc
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowProviderCalls,
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
    FlowVersions,
)
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.users_table import users_roles_table
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.application import flow_run_evidence_service
from eneo.flows.application.flow_run_evidence_service import (
    EVIDENCE_EXPORT_DEFAULT_FAN_OUT_ROW_CEILING,
    EVIDENCE_EXPORT_MEASURED_PEAK_MEMORY_MULTIPLIER,
    EVIDENCE_EXPORT_REQUEST_MEMORY_BUDGET_BYTES,
    EVIDENCE_EXPORT_SERIALIZED_ROW_FLOOR_BYTES,
)
from eneo.flows.domain.flow import Flow
from eneo.flows.domain.provider_call import ProviderCallEvidencePage
from eneo.flows.flow_retention_tombstone import (
    FlowAttemptRetentionMarker,
    FlowRetentionTombstone,
    RunDebugAttemptRetentionCounts,
)
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallRepository,
)
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    StepAttemptEvidenceSize,
    _bounded_step_result_evidence_count_statement,
    _bounded_step_result_evidence_size_statement,
)
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
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


async def _add_provider_call(
    *,
    session: AsyncSession,
    seed: _SnapshotSeed,
    mapped_source_id: str,
) -> None:
    await session.flush()
    attempt_id = await session.scalar(
        sa.select(FlowStepAttempts.id).where(
            FlowStepAttempts.flow_run_id == seed.run_id
        )
    )
    assert attempt_id is not None
    session.add(
        FlowStepAttemptResolvedInputs(
            flow_step_attempt_id=attempt_id,
            resolved_input_edges_jsonb={"schema_version": 1, "edges": []},
        )
    )
    await session.flush()
    session.add(
        FlowProviderCalls(
            flow_step_attempt_id=attempt_id,
            ordinal=1,
            status="started",
            request_schema_version=2,
            provider_request_hash="a" * 64,
            requested_model="model",
            provider="provider",
            response_format="none",
            requested_capabilities=[],
            resolved_input_edge_indexes=[],
            call_reason="initial",
            mapped_execution_mode="per_source",
            mapped_source_index=1,
            mapped_source_id=mapped_source_id,
            requested_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()


async def _add_rerun_operations_with_overrides(
    *,
    session: AsyncSession,
    seed: _SnapshotSeed,
    admin_user,
    operation_count: int,
    overrides_per_operation: int,
) -> None:
    rows: list[tuple[UUID, UUID, int, int]] = []
    for operation_index in range(operation_count):
        operation_id = uuid4()
        step_id = uuid4()
        attempt_no = operation_index + 1
        session.add(
            FlowRunRerunOperations(
                id=operation_id,
                tenant_id=seed.tenant_id,
                flow_id=seed.flow_id,
                flow_run_id=seed.run_id,
                rerun_step_id=step_id,
                rerun_step_order=attempt_no,
                root_attempt_no=attempt_no,
                status="completed",
                request_fingerprint=f"{operation_index + 1:064x}",
                expected_run_revision=operation_index + 1,
                accepted_run_revision=operation_index + 1,
                reason="memory-bounded rerun",
                root_step_input_override_requested=True,
                requested_by_principal_type="user",
                requested_by_user_id=admin_user.id,
            )
        )
        for override_index in range(overrides_per_operation):
            file_id = uuid4()
            row_index = operation_index * overrides_per_operation + override_index
            session.add_all(
                [
                    Files(
                        id=file_id,
                        tenant_id=seed.tenant_id,
                        name=f"override-{row_index}.txt",
                        checksum=f"{row_index + 1:064x}",
                        size=1,
                        mimetype="text/plain",
                        file_type="text",
                        owner_type="user",
                        owner_user_id=admin_user.id,
                        owner_service_id=None,
                    ),
                    FlowRuntimeUploadedFiles(
                        file_id=file_id,
                        flow_id=seed.flow_id,
                        tenant_id=seed.tenant_id,
                        uploaded_for_step_id=step_id,
                        owner_type="user",
                        owner_user_id=admin_user.id,
                        owner_service_id=None,
                    ),
                ]
            )
            rows.append((step_id, file_id, attempt_no, override_index))
    await session.flush()
    session.add_all(
        [
            FlowRunStepInputFiles(
                flow_run_id=seed.run_id,
                flow_id=seed.flow_id,
                tenant_id=seed.tenant_id,
                step_id=step_id,
                step_order=attempt_no,
                attempt_no=attempt_no,
                file_id=file_id,
                ordinal=ordinal,
            )
            for step_id, file_id, attempt_no, ordinal in rows
        ]
    )
    await session.flush()


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
    original_measure = FlowRunRepository.measure_step_attempt_evidence

    async def measure_then_mutate(
        repository: FlowRunRepository,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> StepAttemptEvidenceSize:
        measurement = await original_measure(
            repository,
            run_id=run_id,
            tenant_id=tenant_id,
            candidate_limit=candidate_limit,
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
        "measure_step_attempt_evidence",
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
async def test_evidence_view_lineage_does_not_mix_pre_purge_and_purged_state(
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
        attempt_id = await seed_session.scalar(
            sa.select(FlowStepAttempts.id).where(
                FlowStepAttempts.flow_run_id == seed.run_id
            )
        )
        trace_id = await seed_session.scalar(
            sa.select(FlowRuns.trace_id).where(FlowRuns.id == seed.run_id)
        )
        assert attempt_id is not None
        assert trace_id is not None
        seed_session.add(
            FlowStepAttemptResolvedInputs(
                flow_step_attempt_id=attempt_id,
                resolved_input_edges_jsonb={"schema_version": 1, "edges": []},
            )
        )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )
    endpoint = f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/"
    headers = {"Authorization": f"Bearer {token}"}

    original_measure = FlowRunRepository.measure_step_attempt_evidence
    measurement_count = 0

    async def measure_then_purge(
        repository: FlowRunRepository,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> StepAttemptEvidenceSize:
        nonlocal measurement_count
        measurement = await original_measure(
            repository,
            run_id=run_id,
            tenant_id=tenant_id,
            candidate_limit=candidate_limit,
        )
        measurement_count += 1
        if measurement_count == 1:
            now = datetime.now(timezone.utc)
            marker = FlowAttemptRetentionMarker(
                tombstone=FlowRetentionTombstone(
                    tenant_id=str(seed.tenant_id),
                    run_id=str(seed.run_id),
                    trace_id=str(trace_id),
                    data_class="run_debug_evidence",
                    object_type="flow_step_attempt",
                    object_id=str(attempt_id),
                    policy_source="tenant_policy",
                    cutoff=now,
                    counts=RunDebugAttemptRetentionCounts(
                        cleared_field_count=1,
                        provider_call_count=0,
                        resolved_input_aggregate_count=1,
                        resolved_input_edge_count=0,
                    ),
                    timestamp=now,
                    retention_state="retention_purged",
                )
            )
            async with (
                sessionmanager.session() as mutation_session,
                mutation_session.begin(),
            ):
                await mutation_session.execute(
                    sa.delete(FlowStepAttemptResolvedInputs).where(
                        FlowStepAttemptResolvedInputs.flow_step_attempt_id == attempt_id
                    )
                )
                await mutation_session.execute(
                    sa.update(FlowStepAttempts)
                    .where(FlowStepAttempts.id == attempt_id)
                    .values(provenance_json=marker.to_payload())
                )
        return measurement

    monkeypatch.setattr(
        FlowRunRepository,
        "measure_step_attempt_evidence",
        measure_then_purge,
    )

    before_response = await client.get(endpoint, headers=headers)
    after_response = await client.get(endpoint, headers=headers)

    assert before_response.status_code == 200, before_response.text
    assert after_response.status_code == 200, after_response.text
    before_lineage = before_response.json()["step_attempts"][0][
        "resolved_input_lineage"
    ]
    after_lineage = after_response.json()["step_attempts"][0]["resolved_input_lineage"]
    assert before_lineage == {"status": "tracked", "schema_version": 1, "edges": []}
    assert after_lineage == {
        "status": "retention_purged",
        "resolved_input_aggregate_count": 1,
        "resolved_input_edge_count": 0,
    }


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
    original_measure = FlowRunRepository.measure_step_attempt_evidence
    original_provider_page = FlowProviderCallRepository.list_evidence_page

    async def capture_export_isolation(
        repository: FlowRunRepository,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> StepAttemptEvidenceSize:
        isolation = await repository.session.scalar(
            sa.text("SHOW transaction_isolation")
        )
        assert isinstance(isolation, str)
        observed_isolation[active_route] = isolation
        return await original_measure(
            repository,
            run_id=run_id,
            tenant_id=tenant_id,
            candidate_limit=candidate_limit,
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
        "measure_step_attempt_evidence",
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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_provider_call_repository_represents_zero_byte_admission(
    setup_database,
    space_factory,
    admin_user,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        await _add_provider_call(
            session=session,
            seed=seed,
            mapped_source_id="first-row-exceeds-budget",
        )

        page = await FlowProviderCallRepository(session=session).list_evidence_page(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            limit=100,
            total_count_limit=101,
            logical_byte_budget=1,
        )

    assert page.items == ()
    assert page.count == 0
    assert page.total_count == 1
    assert page.total_count_truncated is False
    assert page.has_more is False
    assert page.next_after_event_id is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_evidence_view_reports_first_oversized_provider_call(
    client,
    db_container,
    patch_auth_service_jwt,
    setup_database,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        await _add_provider_call(
            session=session,
            seed=seed,
            mapped_source_id="first-row-exceeds-budget",
        )
    monkeypatch.setattr(
        flow_run_evidence_service,
        "RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES",
        1,
    )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )

    response = await client.get(
        f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider_calls"] == {
        "items": [],
        "count": 0,
        "total_count": 1,
        "total_count_truncated": False,
        "has_more": False,
        "next_after_event_id": None,
    }
    assert payload["debug_export"]["run"]["summary"]["omissions"] == [
        {
            "reason": "logical_bytes",
            "section": "provider_calls",
            "rows_omitted": 1,
            "count_truncated": False,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_export_logical_ceiling_catches_toast_compressible_json(
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
        await seed_session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == seed.run_id)
            .values(input_payload_json={"repetitive": "x" * 250_000})
        )
        measurement = await FlowRunRepository(
            session=seed_session
        ).measure_step_attempt_evidence(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
        )
        assert measurement.stored_json_bytes < 100_000
        assert measurement.logical_json_bytes > 200_000

    monkeypatch.setattr(
        flow_run_evidence_service,
        "EVIDENCE_EXPORT_MAX_AGGREGATE_STORED_JSON_BYTES",
        100_000,
    )
    monkeypatch.setattr(
        flow_run_evidence_service,
        "EVIDENCE_EXPORT_MAX_AGGREGATE_LOGICAL_JSON_BYTES",
        200_000,
    )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )

    response = await client.get(
        f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/export",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 413, response.text
    error = response.json()
    assert error["context"]["section"] == "whole_bundle"
    assert error["context"]["limit"] == "aggregate_logical_json_bytes"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_export_row_preflight_plan_limits_candidates_before_counting(
    setup_database,
    space_factory,
    admin_user,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        session.add_all(
            [
                FlowStepResults(
                    flow_run_id=seed.run_id,
                    flow_id=seed.flow_id,
                    tenant_id=seed.tenant_id,
                    step_id=uuid4(),
                    step_order=step_order,
                    status="completed",
                    output_payload_json={"step": step_order},
                )
                for step_order in range(1, 51)
            ]
        )
        await session.flush()
        ceiling = 5
        count_statement = _bounded_step_result_evidence_count_statement(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            ceiling=ceiling,
        )
        size_statement = _bounded_step_result_evidence_size_statement(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            candidate_limit=ceiling + 1,
        )
        bind = session.get_bind()
        count_sql = str(
            count_statement.compile(
                dialect=bind.dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        size_sql = str(
            size_statement.compile(
                dialect=bind.dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        count_plan_rows = await session.execute(
            sa.text(f"EXPLAIN (ANALYZE, BUFFERS) {count_sql}")
        )
        count_plan = "\n".join(str(row[0]) for row in count_plan_rows)
        size_plan_value = (
            await session.execute(
                sa.text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {size_sql}")
            )
        ).scalar_one()

    assert "Limit" in count_plan
    assert "Aggregate" in count_plan
    size_plan = size_plan_value[0]["Plan"]
    scan_rows: list[int] = []

    def collect_scan_rows(node: dict[str, object]) -> None:
        if "Scan" in str(node.get("Node Type")):
            scan_rows.append(int(node["Actual Rows"]))
        for child in node.get("Plans", []):
            assert isinstance(child, dict)
            collect_scan_rows(child)

    collect_scan_rows(size_plan)
    assert scan_rows
    assert max(scan_rows) <= ceiling + 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_measurements_cover_every_variable_width_evidence_projection(
    client,
    db_container,
    patch_auth_service_jwt,
    setup_database,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = setup_database
    large = "projection-marker-" + ("x" * 50_000)
    control_heavy = '\n\t"\\\b\f\r' * 10_000
    payload = {"marker": large}
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        await session.flush()
        result_id = uuid4()
        operation_id = uuid4()
        file_id = uuid4()
        session.add_all(
            [
                FlowStepResults(
                    id=result_id,
                    flow_run_id=seed.run_id,
                    flow_id=seed.flow_id,
                    tenant_id=seed.tenant_id,
                    step_id=seed.step_id,
                    step_order=1,
                    current_attempt_no=1,
                    input_payload_json=payload,
                    output_payload_json=payload,
                    model_parameters_json=payload,
                    effective_prompt=large,
                    error_message=large,
                    status="completed",
                ),
                Files(
                    id=file_id,
                    tenant_id=seed.tenant_id,
                    name=large,
                    checksum="a" * 64,
                    size=1,
                    mimetype=large,
                    file_type="text",
                    owner_type="user",
                    owner_user_id=admin_user.id,
                    owner_service_id=None,
                ),
                FlowRuntimeUploadedFiles(
                    file_id=file_id,
                    flow_id=seed.flow_id,
                    tenant_id=seed.tenant_id,
                    uploaded_for_step_id=seed.step_id,
                    owner_type="user",
                    owner_user_id=admin_user.id,
                    owner_service_id=None,
                ),
                FlowRunRerunOperations(
                    id=operation_id,
                    tenant_id=seed.tenant_id,
                    flow_id=seed.flow_id,
                    flow_run_id=seed.run_id,
                    rerun_step_id=seed.step_id,
                    rerun_step_order=1,
                    root_attempt_no=1,
                    status="completed",
                    request_fingerprint="b" * 64,
                    expected_run_revision=1,
                    accepted_run_revision=1,
                    reason=large,
                    input_payload_json=payload,
                    root_step_input_override_requested=True,
                    changed_input_paths=[large],
                    prior_input_payload_json=payload,
                    requested_by_principal_type="user",
                    requested_by_user_id=admin_user.id,
                    failure_message=large,
                ),
                FlowRunReviewCheckpoints(
                    tenant_id=seed.tenant_id,
                    flow_id=seed.flow_id,
                    flow_run_id=seed.run_id,
                    step_id=seed.step_id,
                    step_order=1,
                    attempt_no=1,
                    state="cancelled",
                    original_payload_json=payload,
                    current_payload_json=payload,
                    step_label=large,
                    review_mode="view",
                    output_type="json",
                    output_contract_json=payload,
                    next_step_ids_json=[large],
                    requester_principal_type="user",
                    requester_user_id=admin_user.id,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                FlowRunStepInputFiles(
                    flow_run_id=seed.run_id,
                    flow_id=seed.flow_id,
                    tenant_id=seed.tenant_id,
                    step_id=seed.step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=file_id,
                    ordinal=0,
                ),
                FlowRunStepResultFiles(
                    flow_run_id=seed.run_id,
                    flow_id=seed.flow_id,
                    tenant_id=seed.tenant_id,
                    step_result_id=result_id,
                    step_id=seed.step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=file_id,
                    ordinal=0,
                    source="generated_output",
                ),
                FlowRunRerunInvalidatedSteps(
                    operation_id=operation_id,
                    tenant_id=seed.tenant_id,
                    flow_id=seed.flow_id,
                    flow_run_id=seed.run_id,
                    step_id=seed.step_id,
                    step_order=1,
                    invalidation_order=0,
                    role="root",
                    dependency_sources_json=[large],
                    prior_step_result_id=result_id,
                ),
            ]
        )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == seed.run_id)
            .values(
                provenance_json=payload,
                input_payload_json=payload,
                output_payload_json=payload,
                celery_task_id=large,
                error_code=large,
                error_message=control_heavy,
                requested_model=large,
                response_model=large,
                provider=large,
                finish_reason=large,
                provider_response_id=large,
                flow_step_execution_hash=large,
            )
        )
        attempt_id = await session.scalar(
            sa.select(FlowStepAttempts.id).where(
                FlowStepAttempts.flow_run_id == seed.run_id
            )
        )
        assert attempt_id is not None
        session.add(
            FlowStepAttemptResolvedInputs(
                flow_step_attempt_id=attempt_id,
                resolved_input_edges_jsonb={"schema_version": 1, "edges": []},
            )
        )
        await session.flush()
        session.add(
            FlowProviderCalls(
                flow_step_attempt_id=attempt_id,
                ordinal=1,
                status="started",
                request_schema_version=2,
                provider_request_hash="c" * 64,
                requested_model="model",
                provider="provider",
                response_format="none",
                requested_capabilities=[],
                resolved_input_edge_indexes=[],
                call_reason="initial",
                mapped_execution_mode="per_source",
                mapped_source_index=1,
                mapped_source_id=control_heavy,
                requested_at=datetime.now(timezone.utc),
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == seed.run_id)
            .values(
                dispatch_last_error=payload,
                input_payload_json=payload,
                output_payload_json=payload,
                error_json=payload,
            )
        )
        await session.execute(
            sa.update(FlowVersions)
            .where(FlowVersions.flow_id == seed.flow_id)
            .values(definition_json=payload)
        )
        await session.flush()

        run_repo = FlowRunRepository(session=session)
        run_measurement = await run_repo.measure_evidence_sections(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            candidate_limit=10_001,
        )
        attempt_measurement = await run_repo.measure_step_attempt_evidence(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            candidate_limit=10_001,
        )
        rerun_measurement = await FlowRunRerunRepository(
            session=session
        ).measure_evidence_sections(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            candidate_limit=10_001,
        )
        checkpoint_measurement = await FlowRunReviewCheckpointRepository(
            session=session,
            audit_outbox_repo=FlowRunAuditOutboxRepository(session=session),
        ).measure_evidence(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            candidate_limit=10_001,
        )
        version_measurement = await FlowVersionRepository(
            session=session
        ).measure_definition_evidence(
            flow_id=seed.flow_id,
            version=1,
            tenant_id=seed.tenant_id,
        )
        provider_measurement = await FlowProviderCallRepository(
            session=session
        ).measure_evidence(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            candidate_limit=10_001,
        )

    assert run_measurement.run_logical_json_bytes > 200_000
    assert run_measurement.step_result_logical_json_bytes > 250_000
    assert run_measurement.result_file_logical_json_bytes > 100_000
    assert run_measurement.runtime_input_file_logical_json_bytes > 100_000
    assert attempt_measurement.logical_json_bytes > 500_000
    assert attempt_measurement.logical_json_bytes > len(control_heavy.encode("utf-8"))
    assert rerun_measurement.operation_row_count == 1
    assert rerun_measurement.operation_nested_override_row_count == 1
    assert rerun_measurement.operation_logical_json_bytes > 250_000
    assert rerun_measurement.invalidated_step_logical_json_bytes > 50_000
    assert checkpoint_measurement.logical_json_bytes > 200_000
    assert version_measurement.logical_json_bytes > 50_000
    assert provider_measurement.logical_json_bytes > len(control_heavy.encode("utf-8"))

    async def evidence_load_must_not_run(*args: object, **kwargs: object):
        raise AssertionError("projection rows loaded before oversized export refusal")

    monkeypatch.setattr(
        flow_run_evidence_service,
        "EVIDENCE_EXPORT_MAX_AGGREGATE_LOGICAL_JSON_BYTES",
        1,
    )
    monkeypatch.setattr(
        FlowRunRepository,
        "list_step_results",
        evidence_load_must_not_run,
    )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )
    response = await client.get(
        f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/export",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 413, response.text
    assert response.json()["context"]["limit"] == "aggregate_logical_json_bytes"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rerun_view_read_returns_the_ordered_500_operation_prefix(
    setup_database,
    space_factory,
    admin_user,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        session.add_all(
            [
                FlowRunRerunOperations(
                    tenant_id=seed.tenant_id,
                    flow_id=seed.flow_id,
                    flow_run_id=seed.run_id,
                    rerun_step_id=seed.step_id,
                    rerun_step_order=1,
                    root_attempt_no=1,
                    status="completed",
                    request_fingerprint=f"{revision:064x}",
                    expected_run_revision=revision,
                    accepted_run_revision=revision,
                    reason="retry",
                    root_step_input_override_requested=False,
                    requested_by_principal_type="user",
                    requested_by_user_id=admin_user.id,
                )
                for revision in range(1, 502)
            ]
        )
        await session.flush()

        operations = await FlowRunRerunRepository(
            session=session
        ).list_rerun_operations_for_run(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            limit=500,
            logical_byte_budget=16 * 1024 * 1024,
        )

    assert len(operations) == 500
    assert operations[0].accepted_run_revision == 1
    assert operations[-1].accepted_run_revision == 500


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rerun_view_read_keeps_safe_rows_before_a_large_late_row(
    setup_database,
    space_factory,
    admin_user,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        session.add_all(
            [
                FlowRunRerunOperations(
                    tenant_id=seed.tenant_id,
                    flow_id=seed.flow_id,
                    flow_run_id=seed.run_id,
                    rerun_step_id=seed.step_id,
                    rerun_step_order=1,
                    root_attempt_no=1,
                    status="completed",
                    request_fingerprint=f"{revision:064x}",
                    expected_run_revision=revision,
                    accepted_run_revision=revision,
                    reason="retry" if revision < 3 else "x" * 20_000,
                    root_step_input_override_requested=False,
                    requested_by_principal_type="user",
                    requested_by_user_id=admin_user.id,
                )
                for revision in range(1, 4)
            ]
        )
        await session.flush()

        operations = await FlowRunRerunRepository(
            session=session
        ).list_rerun_operations_for_run(
            run_id=seed.run_id,
            tenant_id=seed.tenant_id,
            limit=500,
            logical_byte_budget=1_000,
        )

    assert [item.accepted_run_revision for item in operations] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_evidence_view_reports_rerun_override_row_saturation(
    client,
    db_container,
    patch_auth_service_jwt,
    setup_database,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = setup_database
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        await _add_rerun_operations_with_overrides(
            session=session,
            seed=seed,
            admin_user=admin_user,
            operation_count=3,
            overrides_per_operation=2,
        )
    monkeypatch.setattr(
        flow_run_evidence_service,
        "RUN_VIEW_MAX_LOADED_SECTION_ROWS",
        4,
    )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )

    response = await client.get(
        f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [
        operation["accepted_run_revision"] for operation in payload["rerun_operations"]
    ] == [1, 2]
    assert payload["debug_export"]["run"]["summary"]["omissions"] == [
        {
            "reason": "row_limit",
            "section": "rerun_operations",
            "rows_omitted": 1,
            "count_truncated": False,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_complete_export_routes_stay_within_the_measured_memory_budget(
    client,
    db_container,
    patch_auth_service_jwt,
    setup_database,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = setup_database
    test_logical_ceiling = 5 * 1024 * 1024
    retained_memory_tolerance = 4 * 1024 * 1024
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == seed.run_id)
            .values(input_payload_json={"near_ceiling": "x" * (4 * 1024 * 1024)})
        )
    monkeypatch.setattr(
        flow_run_evidence_service,
        "EVIDENCE_EXPORT_MAX_AGGREGATE_LOGICAL_JSON_BYTES",
        test_logical_ceiling,
    )
    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )
    headers = {"Authorization": f"Bearer {token}"}
    base_url = f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/export"

    peaks: list[int] = []
    tracemalloc.start()
    try:
        warmup_response = await client.get(
            f"{base_url}?detail=redacted", headers=headers
        )
        assert warmup_response.status_code == 200, warmup_response.text
        del warmup_response
        gc.collect()
        baseline_current = tracemalloc.get_traced_memory()[0]
        for query in ("?detail=redacted", "?detail=raw&reason=memory-test"):
            gc.collect()
            tracemalloc.reset_peak()
            response = await client.get(f"{base_url}{query}", headers=headers)
            assert response.status_code == 200, response.text
            peaks.append(tracemalloc.get_traced_memory()[1])
            del response
        gc.collect()
        post_loop_current = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()

    assert max(peaks) < EVIDENCE_EXPORT_REQUEST_MEMORY_BUDGET_BYTES
    assert max(peaks) < (
        test_logical_ceiling * EVIDENCE_EXPORT_MEASURED_PEAK_MEMORY_MULTIPLIER
    )
    assert post_loop_current <= baseline_current + retained_memory_tolerance


@pytest.mark.asyncio
@pytest.mark.integration
async def test_high_row_count_exports_stay_within_the_serialized_row_floor_budget(
    client,
    db_container,
    patch_auth_service_jwt,
    setup_database,
    space_factory,
    admin_user,
) -> None:
    _ = setup_database
    rerun_count = EVIDENCE_EXPORT_DEFAULT_FAN_OUT_ROW_CEILING - 500
    async with sessionmanager.session() as session, session.begin():
        seed = await _seed_snapshot_run(
            session=session,
            space_factory=space_factory,
            admin_user=admin_user,
        )
        await session.execute(
            sa.insert(FlowRunRerunOperations),
            [
                {
                    "tenant_id": seed.tenant_id,
                    "flow_id": seed.flow_id,
                    "flow_run_id": seed.run_id,
                    "rerun_step_id": seed.step_id,
                    "rerun_step_order": 1,
                    "root_attempt_no": 1,
                    "status": "completed",
                    "request_fingerprint": f"{revision:064x}",
                    "expected_run_revision": revision,
                    "accepted_run_revision": revision,
                    "reason": "r",
                    "root_step_input_override_requested": False,
                    "requested_by_principal_type": "user",
                    "requested_by_user_id": admin_user.id,
                }
                for revision in range(1, rerun_count + 1)
            ],
        )

    token = await _admin_token(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        admin_user=admin_user,
    )
    headers = {"Authorization": f"Bearer {token}"}
    base_url = f"/api/v1/flows/{seed.flow_id}/runs/{seed.run_id}/evidence/export"
    charged_projection_bytes = rerun_count * EVIDENCE_EXPORT_SERIALIZED_ROW_FLOOR_BYTES

    peaks: list[int] = []
    tracemalloc.start()
    try:
        for query in ("?detail=redacted", "?detail=raw&reason=high-row-memory"):
            gc.collect()
            tracemalloc.reset_peak()
            response = await client.get(f"{base_url}{query}", headers=headers)
            assert response.status_code == 200, response.text
            peaks.append(tracemalloc.get_traced_memory()[1])
            del response
    finally:
        tracemalloc.stop()

    assert max(peaks) < EVIDENCE_EXPORT_REQUEST_MEMORY_BUDGET_BYTES
    assert max(peaks) < (
        charged_projection_bytes * EVIDENCE_EXPORT_MEASURED_PEAK_MEMORY_MULTIPLIER
    )

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import (
    BuilderClientErrors,
    BuilderSessions,
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCategory,
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    AIBuilderPublicError,
)
from eneo.flows.ai_builder.ai_builder_failure_ledger import (
    MAX_FAMILIES,
    collect_failure_summary,
)
from eneo.flows.flow_run_error import FlowRunError, dump_flow_run_error
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate

pytestmark = pytest.mark.integration


async def _token_with_permissions(
    db_container, admin_user, permissions: list[Permission]
) -> str:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"ai-builder-client-error-{uuid4().hex[:8]}",
                permissions=permissions,
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert user is not None
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    return await _token_with_permissions(
        db_container,
        admin_user,
        [Permission.FLOWS_MANAGE, Permission.FLOWS_AI_BUILDER],
    )


def _report(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "client_event_id": str(uuid4()),
        "phase": "client",
        "category": "network",
        "code": "stream_aborted",
        "request_id": "9ffea2154b4dacfa7728a7d5c1d977b8",
    }
    payload.update(overrides)
    return payload


async def _post(client, token: str, payload: dict[str, object]):
    return await client.post(
        "/api/v1/flows/ai-builder/client-errors",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


@pytest.mark.asyncio
async def test_report_client_error_persists_row_and_one_audit_log(
    client,
    bearer_token: str,
    db_container,
) -> None:
    response = await _post(client, bearer_token, _report(code="persists_case"))

    assert response.status_code == 204

    async with db_container() as container:
        session = container.session()
        user = container.user()
        row = (
            await session.execute(
                select(BuilderClientErrors).where(
                    BuilderClientErrors.tenant_id == user.tenant_id,
                    BuilderClientErrors.code == "persists_case",
                )
            )
        ).scalar_one()
        assert row.user_id == user.id
        assert row.session_id is None
        assert row.phase == "client"
        assert row.category == "network"
        assert row.request_id == "9ffea2154b4dacfa7728a7d5c1d977b8"

        audit_rows = (
            (
                await session.execute(
                    select(AuditLogTable).where(
                        AuditLogTable.tenant_id == user.tenant_id,
                        AuditLogTable.action
                        == ActionType.AI_BUILDER_CLIENT_ERROR_REPORTED.value,
                        AuditLogTable.entity_type
                        == EntityType.AI_BUILDER_CLIENT_ERROR.value,
                        AuditLogTable.entity_id == row.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [audit.description for audit in audit_rows] == [
            "Client reported AI builder error (persists_case)"
        ]


@pytest.mark.asyncio
async def test_replaying_a_client_event_is_a_no_op(
    client,
    bearer_token: str,
    db_container,
) -> None:
    payload = _report(code="replayed_case")

    first = await _post(client, bearer_token, payload)
    second = await _post(client, bearer_token, payload)

    assert first.status_code == 204
    assert second.status_code == 204

    async with db_container() as container:
        session = container.session()
        user = container.user()
        rows = (
            (
                await session.execute(
                    select(BuilderClientErrors).where(
                        BuilderClientErrors.tenant_id == user.tenant_id,
                        BuilderClientErrors.code == "replayed_case",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

        audit_count = (
            (
                await session.execute(
                    select(AuditLogTable).where(
                        AuditLogTable.entity_id == rows[0].id,
                        AuditLogTable.action
                        == ActionType.AI_BUILDER_CLIENT_ERROR_REPORTED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_count) == 1


@pytest.mark.asyncio
async def test_report_client_error_nulls_an_unknown_session_id_in_row_and_audit(
    client,
    bearer_token: str,
    db_container,
) -> None:
    # The failure report must never fail because the thing that failed is gone,
    # and the audit records what was stored, never the client's claim.
    response = await _post(
        client,
        bearer_token,
        _report(code="session_gone", session_id=str(uuid4())),
    )

    assert response.status_code == 204

    async with db_container() as container:
        session = container.session()
        user = container.user()
        row = (
            await session.execute(
                select(BuilderClientErrors).where(
                    BuilderClientErrors.tenant_id == user.tenant_id,
                    BuilderClientErrors.code == "session_gone",
                )
            )
        ).scalar_one()
        assert row.session_id is None

        audit = (
            await session.execute(
                select(AuditLogTable).where(
                    AuditLogTable.entity_id == row.id,
                    AuditLogTable.action
                    == ActionType.AI_BUILDER_CLIENT_ERROR_REPORTED.value,
                )
            )
        ).scalar_one()
        assert audit.log_metadata["extra"]["session_id"] is None


@pytest.mark.asyncio
async def test_report_client_error_requires_builder_permission(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
) -> None:
    token = await _token_with_permissions(
        db_container, admin_user, [Permission.ASSISTANTS]
    )

    response = await _post(client, token, _report(code="denied_case"))

    assert response.status_code == 403

    async with db_container() as container:
        rows = (
            (
                await container.session().execute(
                    select(BuilderClientErrors).where(
                        BuilderClientErrors.code == "denied_case"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def _create_space_and_session(
    container, space: Spaces | None = None
) -> tuple[Spaces, BuilderSessions]:
    session = container.session()
    user = container.user()
    if space is None:
        # One space per test: spaces.user_id is unique per user.
        space = Spaces(
            name=f"client-error-{uuid4().hex[:8]}",
            tenant_id=user.tenant_id,
            user_id=user.id,
        )
        session.add(space)
        await session.flush()
    builder_session = BuilderSessions(
        tenant_id=user.tenant_id,
        space_id=space.id,
        target_kind="create",
        actor_user_id=user.id,
        conversation=[],
    )
    session.add(builder_session)
    await session.flush()
    return space, builder_session


@pytest.mark.asyncio
async def test_client_error_rows_die_with_their_session(
    client,
    bearer_token: str,
    db_container,
) -> None:
    # Retention is the schema, not a job: deleting the session deletes its
    # error rows through the composite (session_id, tenant_id) CASCADE.
    async with db_container() as container:
        _, builder_session = await _create_space_and_session(container)
        session_id = builder_session.id

    response = await _post(
        client,
        bearer_token,
        _report(code="dies_with_session", session_id=str(session_id)),
    )
    assert response.status_code == 204

    async with db_container() as container:
        session = container.session()
        stored = (
            await session.execute(
                select(BuilderClientErrors).where(
                    BuilderClientErrors.code == "dies_with_session"
                )
            )
        ).scalar_one()
        assert stored.session_id == session_id

        await session.execute(
            delete(BuilderSessions).where(BuilderSessions.id == session_id)
        )

    async with db_container() as container:
        remaining = (
            (
                await container.session().execute(
                    select(BuilderClientErrors).where(
                        BuilderClientErrors.code == "dies_with_session"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []


@pytest.mark.asyncio
async def test_failure_summary_groups_all_three_stores(
    client,
    bearer_token: str,
    db_container,
) -> None:
    # Behavioral proof for every section: seed a builder-session failure
    # snapshot, a failed and a cancelled flow run with error_json, and one
    # client report — each must appear as a family, not merely not crash.
    async with db_container() as container:
        session = container.session()
        user = container.user()
        space, failed_session = await _create_space_and_session(container)
        failed_session.latest_turn_id = uuid4()
        failed_session.latest_turn_request_fingerprint = "f" * 64
        failed_session.latest_turn_request_jsonb = {}
        failed_session.latest_turn_state = "failed_before_provider"
        failed_session.latest_turn_message_id = str(uuid4())

        _, committed_session = await _create_space_and_session(container, space)
        committed_session.latest_turn_id = uuid4()
        committed_session.latest_turn_request_fingerprint = "c" * 64
        committed_session.latest_turn_request_jsonb = {}
        committed_session.latest_turn_state = "committed"
        committed_session.latest_turn_message_id = str(uuid4())
        committed_session.latest_turn_error_jsonb = AIBuilderPublicError(
            code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
            category=AIBuilderErrorCategory.UPSTREAM,
            message="The planner upstream call failed.",
            phase=AIBuilderErrorPhase.PLANNER,
            eneo_error_code=9024,
            request_id="req-ledger-1",
        ).model_dump(mode="json")

        flow = Flows(
            name="ledger flow",
            tenant_id=user.tenant_id,
            space_id=space.id,
        )
        session.add(flow)
        await session.flush()
        session.add(
            FlowVersions(
                flow_id=flow.id,
                version=1,
                tenant_id=user.tenant_id,
                definition_checksum="0" * 64,
                definition_json={},
            )
        )
        await session.flush()
        run_error = FlowRunError(
            code="flow_definition_invalid",
            message="The published definition is invalid.",
            retryable=False,
        )
        for status_value, error in (("failed", run_error), ("cancelled", None)):
            session.add(
                FlowRuns(
                    flow_id=flow.id,
                    flow_version=1,
                    principal_type="user",
                    principal_user_id=user.id,
                    tenant_id=user.tenant_id,
                    trace_id=uuid4(),
                    status=status_value,
                    error_json=dump_flow_run_error(error),
                )
            )
        await session.flush()

    response = await _post(client, bearer_token, _report(code="grouped_case"))
    assert response.status_code == 204

    async with db_container() as container:
        summary = await collect_failure_summary(
            container.session(),
            since=datetime.now(timezone.utc) - timedelta(days=1),
        )

    snapshot = {
        (family.group, family.detail)
        for family in summary.builder_turn_failure_snapshot.families
    }
    assert ("failed_before_provider", "none") in snapshot
    assert ("committed_with_error", "planner_upstream_error") in snapshot

    runs = {
        (family.group, family.detail) for family in summary.flow_run_failures.families
    }
    assert ("failed", "flow_definition_invalid") in runs
    assert ("cancelled", "unknown") in runs

    clients = {
        (family.group, family.detail) for family in summary.client_errors.families
    }
    assert ("network", "grouped_case") in clients


@pytest.mark.asyncio
async def test_failure_summary_truncation_is_explicit(
    client,
    bearer_token: str,
    db_container,
) -> None:
    for index in range(MAX_FAMILIES + 1):
        response = await _post(
            client, bearer_token, _report(code=f"family_{index:02d}")
        )
        assert response.status_code == 204

    async with db_container() as container:
        summary = await collect_failure_summary(
            container.session(),
            since=datetime.now(timezone.utc) - timedelta(days=1),
        )

    section = summary.client_errors
    assert len(section.families) == MAX_FAMILIES
    assert section.total_families == MAX_FAMILIES + 1
    assert section.truncated is True
    # Equal counts break ties deterministically by label.
    labels = [family.detail for family in section.families]
    assert labels == sorted(labels)


@pytest.mark.asyncio
async def test_report_client_error_rejects_unknown_phase_and_category(
    client,
    bearer_token: str,
) -> None:
    for field, value in (
        ("phase", "made_up"),
        ("category", "made_up"),
        # code is an open set but must stay a machine identifier.
        ("code", "Not An Identifier!"),
    ):
        response = await _post(client, bearer_token, _report(**{field: value}))
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_expired_client_errors_are_deleted_in_batches(
    client,
    bearer_token: str,
    db_container,
) -> None:
    from sqlalchemy import update

    from eneo.data_retention.infrastructure.data_retention_service import (
        DataRetentionService,
    )
    from eneo.flows.ai_builder.ai_builder_failure_ledger import MAX_WINDOW_DAYS

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_WINDOW_DAYS)
    ages = {
        "ttl_expired_a": cutoff - timedelta(days=2),
        "ttl_expired_b": cutoff - timedelta(days=1),
        "ttl_boundary": cutoff,
        "ttl_fresh": cutoff + timedelta(days=1),
    }
    for code in ages:
        response = await _post(client, bearer_token, _report(code=code))
        assert response.status_code == 204

    async with db_container() as container:
        session = container.session()
        for code, created_at in ages.items():
            await session.execute(
                update(BuilderClientErrors)
                .where(BuilderClientErrors.code == code)
                .values(created_at=created_at)
            )

    async with db_container() as container:
        session = container.session()
        service = DataRetentionService(session=session)
        # limit=1 forces one row per call: proves the batch contract.
        first = await service.delete_expired_builder_client_errors_batch(
            now=now, limit=1
        )
        second = await service.delete_expired_builder_client_errors_batch(
            now=now, limit=1
        )
        drained = await service.delete_expired_builder_client_errors_batch(
            now=now, limit=1
        )
        assert (first, second, drained) == (1, 1, 0)

        remaining = {
            row.code
            for row in (
                await session.execute(
                    select(BuilderClientErrors).where(
                        BuilderClientErrors.code.in_(list(ages))
                    )
                )
            ).scalars()
        }
    # The boundary row (created_at == cutoff) is not older than the window.
    assert remaining == {"ttl_boundary", "ttl_fresh"}

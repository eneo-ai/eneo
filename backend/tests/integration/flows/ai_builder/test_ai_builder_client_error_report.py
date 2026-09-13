from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text

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


async def _stored(db_container, code: str) -> SimpleNamespace:
    # A snapshot: the ORM row expires with the container's session.
    async with db_container() as container:
        row = (
            await container.session().execute(
                select(BuilderClientErrors).where(BuilderClientErrors.code == code)
            )
        ).scalar_one()
        return SimpleNamespace(
            id=row.id,
            user_id=row.user_id,
            surface=row.surface,
            presented_as=row.presented_as,
            first_action=row.first_action,
            first_action_received_at=row.first_action_received_at,
        )


async def _audit_actions(db_container, error_id) -> list[str]:
    async with db_container() as container:
        rows = (
            (
                await container.session().execute(
                    select(AuditLogTable)
                    .where(
                        AuditLogTable.entity_id == error_id,
                        AuditLogTable.action.in_(
                            [
                                ActionType.AI_BUILDER_CLIENT_ERROR_REPORTED.value,
                                ActionType.AI_BUILDER_CLIENT_ERROR_OUTCOME_RECORDED.value,
                            ]
                        ),
                    )
                    .order_by(AuditLogTable.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [row.action for row in rows]


@pytest.mark.asyncio
async def test_observation_report_stores_where_and_as_what_it_was_displayed(
    client,
    bearer_token: str,
    db_container,
) -> None:
    response = await _post(
        client,
        bearer_token,
        _report(code="displayed_case", surface="generation", presented_as="other"),
    )
    assert response.status_code == 204

    row = await _stored(db_container, "displayed_case")
    assert (row.surface, row.presented_as) == ("generation", "other")
    assert row.first_action is None
    assert row.first_action_received_at is None


@pytest.mark.asyncio
async def test_first_action_is_stored_once_with_a_server_receipt_time(
    client,
    bearer_token: str,
    db_container,
) -> None:
    # The same client_event_id carries the observation, then the user's
    # first explicit selection. A replay and a conflicting later action
    # change nothing; each stored fact is audited once.
    payload = _report(code="acted_case", surface="generation", presented_as="other")
    assert (await _post(client, bearer_token, payload)).status_code == 204
    before = datetime.now(timezone.utc)

    acted = await _post(
        client, bearer_token, {**payload, "first_action": "retry_requested"}
    )
    assert acted.status_code == 204
    replayed = await _post(
        client, bearer_token, {**payload, "first_action": "retry_requested"}
    )
    assert replayed.status_code == 204
    conflicting = await _post(
        client, bearer_token, {**payload, "first_action": "conversation_opened"}
    )
    assert conflicting.status_code == 204

    row = await _stored(db_container, "acted_case")
    assert row.first_action == "retry_requested"
    assert row.first_action_received_at is not None
    assert row.first_action_received_at >= before - timedelta(seconds=5)
    assert await _audit_actions(db_container, row.id) == [
        ActionType.AI_BUILDER_CLIENT_ERROR_REPORTED.value,
        ActionType.AI_BUILDER_CLIENT_ERROR_OUTCOME_RECORDED.value,
    ]


@pytest.mark.asyncio
async def test_an_action_reported_before_the_observation_keeps_both(
    client,
    bearer_token: str,
    db_container,
) -> None:
    # Telemetry is fire-and-forget on the client, so the action can land
    # first. It inserts the row; the late initial report fills only the
    # presentation facts and never touches the action.
    payload = _report(code="action_first_case")
    assert (
        await _post(client, bearer_token, {**payload, "first_action": "dismissed"})
    ).status_code == 204
    assert (
        await _post(
            client,
            bearer_token,
            {**payload, "surface": "chat", "presented_as": "provider_rejected"},
        )
    ).status_code == 204

    row = await _stored(db_container, "action_first_case")
    assert (row.surface, row.presented_as) == ("chat", "provider_rejected")
    assert row.first_action == "dismissed"
    assert row.first_action_received_at is not None


@pytest.mark.asyncio
async def test_another_reporter_cannot_change_a_stored_observation(
    client,
    bearer_token: str,
    db_container,
) -> None:
    # The first reporter owns the observation. A report under the same
    # event id from another user in the tenant is ignored, not rejected:
    # telemetry never fails its caller.
    payload = _report(code="other_reporter_case")
    assert (await _post(client, bearer_token, payload)).status_code == 204

    async with db_container() as container:
        user = container.user()
        record = await container.ai_builder_repo().record_client_error(
            tenant_id=user.tenant_id,
            user_id=uuid4(),
            client_event_id=UUID(str(payload["client_event_id"])),
            session_id=None,
            phase="client",
            category="network",
            code="other_reporter_case",
            request_id=None,
            first_action="retry_requested",
        )
    assert record is None

    row = await _stored(db_container, "other_reporter_case")
    assert row.first_action is None


@pytest.mark.asyncio
async def test_a_reused_event_id_with_another_identity_fills_nothing(
    client,
    bearer_token: str,
    db_container,
) -> None:
    # The immutable identity must match before any gap is filled: a report
    # that names a different failure under the same event id is a no-op.
    payload = _report(code="identity_case")
    assert (await _post(client, bearer_token, payload)).status_code == 204

    other = await _post(
        client,
        bearer_token,
        {
            **payload,
            "code": "identity_case_other",
            "surface": "generation",
            "first_action": "retry_requested",
        },
    )
    assert other.status_code == 204

    row = await _stored(db_container, "identity_case")
    assert (row.surface, row.first_action) == (None, None)
    async with db_container() as container:
        others = (
            (
                await container.session().execute(
                    select(BuilderClientErrors).where(
                        BuilderClientErrors.code == "identity_case_other"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert others == []


@pytest.mark.asyncio
async def test_a_later_report_fills_only_the_gap_and_audits_what_was_kept(
    client,
    bearer_token: str,
    db_container,
) -> None:
    payload = _report(code="gap_case")
    assert (
        await _post(
            client, bearer_token, {**payload, "first_action": "retry_requested"}
        )
    ).status_code == 204

    # A conflicting action beside a new surface: the surface fills, the
    # stored action stays, and the audit names the stored action.
    later = await _post(
        client,
        bearer_token,
        {**payload, "surface": "chat", "first_action": "dismissed"},
    )
    assert later.status_code == 204

    row = await _stored(db_container, "gap_case")
    assert (row.surface, row.first_action) == ("chat", "retry_requested")
    async with db_container() as container:
        audits = (
            (
                await container.session().execute(
                    select(AuditLogTable)
                    .where(
                        AuditLogTable.entity_id == row.id,
                        AuditLogTable.action
                        == ActionType.AI_BUILDER_CLIENT_ERROR_OUTCOME_RECORDED.value,
                    )
                    .order_by(AuditLogTable.created_at)
                )
            )
            .scalars()
            .all()
        )
        extras = [audit.log_metadata["extra"] for audit in audits]
    assert [(extra["surface"], extra["first_action"]) for extra in extras] == [
        ("chat", "retry_requested")
    ]


@pytest.mark.asyncio
async def test_report_client_error_rejects_unknown_presentation_values(
    client,
    bearer_token: str,
) -> None:
    for field, value in (
        ("surface", "toast"),
        ("presented_as", "prose"),
        ("first_action", "gave_up"),
    ):
        response = await _post(client, bearer_token, _report(**{field: value}))
        assert response.status_code == 422, field


@pytest.mark.asyncio
async def test_presented_as_by_first_action_counts_are_one_bounded_query(
    client,
    bearer_token: str,
    db_container,
) -> None:
    """The query an operator runs to see how users respond to each failure
    class. A null first_action means nothing was selected while the failure
    was displayed; it is not abandonment, and no action means recovery
    succeeded. The window and the limit keep it bounded."""
    for presented_as, first_action in (
        ("provider_rejected", "retry_requested"),
        ("provider_rejected", "retry_requested"),
        ("provider_rejected", None),
        ("request_budget_exhausted", "conversation_opened"),
    ):
        payload = _report(
            code="counts_case", surface="generation", presented_as=presented_as
        )
        if first_action is not None:
            payload["first_action"] = first_action
        assert (await _post(client, bearer_token, payload)).status_code == 204

    async with db_container() as container:
        user = container.user()
        rows = (
            await container.session().execute(
                text(
                    """
                    SELECT presented_as, first_action, count(*) AS reports
                    FROM builder_client_errors
                    WHERE tenant_id = :tenant_id
                      AND code = :code
                      AND created_at >= :since
                    GROUP BY presented_as, first_action
                    ORDER BY reports DESC, presented_as, first_action
                    LIMIT 100
                    """
                ),
                {
                    "tenant_id": user.tenant_id,
                    "code": "counts_case",
                    "since": datetime.now(timezone.utc) - timedelta(days=1),
                },
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("provider_rejected", "retry_requested", 2),
        ("provider_rejected", None, 1),
        ("request_budget_exhausted", "conversation_opened", 1),
    ]

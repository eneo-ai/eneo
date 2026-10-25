from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
)
from eneo.flows.application.flow_run_audit_outbox_delivery import (
    FlowRunAuditOutboxDeliveryService,
    FlowRunAuditOutboxGenerationConflictError,
    FlowRunAuditOutboxNotFoundError,
    FlowRunAuditOutboxStateConflictError,
)
from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.enums import FlowRunLifecycleSource, FlowRunStatus
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime import tasks as flow_runtime_tasks
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from tests.flow_snapshot_fixtures import assistant_snapshot


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Audit Outbox Delivery Flow",
        description="Flow used for audit outbox delivery tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Step one",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                input_config=None,
                output_config=None,
            )
        ],
    )


async def _create_flow_and_run(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    model = await completion_model_factory(session, f"gpt-4o-mini-{uuid4().hex}")
    space = await space_factory(session, "Audit outbox delivery space", [model.id])
    assistant = await assistant_factory(
        session,
        "Audit Outbox Delivery Assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session)
    version_repo = FlowVersionRepository(session=session)
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        ),
        tenant_id=admin_user.tenant_id,
    )
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        definition_json={
            "steps": [
                {
                    "step_id": str(flow.steps[0].id),
                    "assistant_id": str(flow.steps[0].assistant_id),
                    "assistant_snapshot": assistant_snapshot(
                        flow.steps[0].assistant_id
                    ),
                    "step_order": 1,
                }
            ]
        },
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    run_repo = FlowRunRepository(session=session)
    run = await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"question": "What happened?"},
        preseed_steps=[
            {
                "step_id": flow.steps[0].id,
                "assistant_id": flow.steps[0].assistant_id,
                "step_order": 1,
            }
        ],
    )
    return flow, run


async def _insert_completed_outbox(
    *,
    outbox_repo: FlowRunAuditOutboxRepository,
    run,
    actor_id: UUID,
) -> UUID:
    return await outbox_repo.insert_terminal_audit_outbox(
        run=run,
        action=ActionType.FLOW_RUN_COMPLETED,
        principal=FlowPrincipal(
            principal_type=PrincipalType.USER, principal_user_id=actor_id
        ),
        source=FlowRunLifecycleSource.EXECUTOR_COMPLETED,
        target_status=FlowRunStatus.COMPLETED,
        error_code=None,
        error_message=None,
    )


def _delivery_service(session) -> FlowRunAuditOutboxDeliveryService:
    return FlowRunAuditOutboxDeliveryService(
        audit_outbox_repo=FlowRunAuditOutboxRepository(session=session),
        audit_log_repo=AuditLogRepositoryImpl(session),
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_delivery_creates_audit_log_and_marks_delivered(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_repo = FlowRunAuditOutboxRepository(session=session)
        outbox_id = await _insert_completed_outbox(
            outbox_repo=outbox_repo,
            run=run,
            actor_id=admin_user.id,
        )
        run_id = run.id
        now = datetime.now(timezone.utc)

        result = await _delivery_service(session).deliver_due(now=now)

        outbox_state = (
            await session.execute(
                sa.select(
                    FlowRunAuditOutbox.delivery_status,
                    FlowRunAuditOutbox.delivery_attempts,
                    FlowRunAuditOutbox.delivered_at,
                ).where(FlowRunAuditOutbox.id == outbox_id)
            )
        ).one()
        audit_state = (
            await session.execute(
                sa.select(
                    AuditLogTable.description,
                    AuditLogTable.log_metadata,
                ).where(AuditLogTable.id == outbox_id)
            )
        ).one()

    assert result.delivered_count == 1
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 0
    assert outbox_state.delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
    assert outbox_state.delivery_attempts == 1
    assert outbox_state.delivered_at is not None
    assert audit_state.description == "Flow run completed by executor_completed."
    assert audit_state.log_metadata["flow_run_id"] == str(run_id)
    assert audit_state.log_metadata["outbox_description"] == (
        "flow_run_completed:executor_completed"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_delivery_reuses_existing_audit_log_id(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_repo = FlowRunAuditOutboxRepository(session=session)
        outbox_id = await _insert_completed_outbox(
            outbox_repo=outbox_repo,
            run=run,
            actor_id=admin_user.id,
        )
        service = _delivery_service(session)

        await service.deliver_due(now=datetime.now(timezone.utc))
        await session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                delivery_attempts=0,
                next_delivery_at=datetime.now(timezone.utc),
                delivered_at=None,
            )
        )
        result = await service.deliver_due(now=datetime.now(timezone.utc))
        audit_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(AuditLogTable.id == outbox_id)
        )

    assert result.delivered_count == 1
    assert audit_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_dead_letter_listing_is_bounded_and_stable(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        dead_lettered_at_values = [
            datetime(2026, 7, 22, 8, minute, tzinfo=timezone.utc) for minute in range(3)
        ]
        outbox_ids: list[UUID] = []
        run_ids: list[UUID] = []
        for dead_lettered_at in dead_lettered_at_values:
            _flow, run = await _create_flow_and_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
            )
            outbox_id = await _insert_completed_outbox(
                outbox_repo=FlowRunAuditOutboxRepository(session=session),
                run=run,
                actor_id=admin_user.id,
            )
            await session.execute(
                sa.update(FlowRunAuditOutbox)
                .where(FlowRunAuditOutbox.id == outbox_id)
                .values(
                    delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
                    delivery_attempts=5,
                    next_delivery_at=None,
                    dead_lettered_at=dead_lettered_at,
                    delivery_last_error=(
                        "POST https://operator:password@example.com/audit?token=top-secret "
                        "failed with Bearer bearer-secret"
                        if len(outbox_ids) == 0
                        else "audit store unavailable"
                    ),
                )
            )
            outbox_ids.append(outbox_id)
            run_ids.append(run.id)

        service = _delivery_service(session)
        first_page = await service.list_dead_letters(limit=2, offset=0)
        second_page = await service.list_dead_letters(limit=2, offset=2)

    assert [row.outbox_id for row in first_page.items] == outbox_ids[:2]
    assert [row.flow_run_id for row in first_page.items] == run_ids[:2]
    assert [row.dead_lettered_at for row in first_page.items] == (
        dead_lettered_at_values[:2]
    )
    listed_error = first_page.items[0].delivery_last_error
    assert listed_error is not None
    assert "operator" not in listed_error
    assert "password" not in listed_error
    assert "top-secret" not in listed_error
    assert "bearer-secret" not in listed_error
    assert "https://example.com/audit?token=%5BREDACTED%5D" in listed_error
    assert "Bearer [REDACTED]" in listed_error
    assert first_page.has_more is True
    assert [row.outbox_id for row in second_page.items] == outbox_ids[2:]
    assert second_page.has_more is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_redrive_resets_budget_and_writes_operator_audit(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_id = await _insert_completed_outbox(
            outbox_repo=FlowRunAuditOutboxRepository(session=session),
            run=run,
            actor_id=admin_user.id,
        )
        dead_lettered_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        await session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
                delivery_attempts=5,
                next_delivery_at=None,
                dead_lettered_at=dead_lettered_at,
                delivery_last_error=(
                    "POST https://operator:password@example.com/audit?token=top-secret "
                    "failed with Bearer bearer-secret"
                ),
            )
        )
        redriven_at = datetime.now(timezone.utc)

        delivery_service = _delivery_service(session)
        inspection = await delivery_service.inspect_redrive(
            outbox_id=outbox_id,
            expected_dead_lettered_at=dead_lettered_at,
        )
        inspection_state = await session.scalar(
            sa.select(FlowRunAuditOutbox.delivery_status).where(
                FlowRunAuditOutbox.id == outbox_id
            )
        )
        inspection_audit_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(AuditLogTable.id == outbox_id)
        )
        result = await delivery_service.redrive_dead_lettered(
            outbox_id=outbox_id,
            expected_dead_lettered_at=dead_lettered_at,
            reason="Audit storage recovered; password=operator-secret",
            now=redriven_at,
            operator_identity="on-call@example.invalid",
        )

        outbox_state = (
            await session.execute(
                sa.select(
                    FlowRunAuditOutbox.delivery_status,
                    FlowRunAuditOutbox.delivery_attempts,
                    FlowRunAuditOutbox.next_delivery_at,
                    FlowRunAuditOutbox.delivered_at,
                    FlowRunAuditOutbox.dead_lettered_at,
                    FlowRunAuditOutbox.delivery_last_error,
                ).where(FlowRunAuditOutbox.id == outbox_id)
            )
        ).one()
        operator_audit = (
            await session.execute(
                sa.select(
                    AuditLogTable.tenant_id,
                    AuditLogTable.actor_type,
                    AuditLogTable.action,
                    AuditLogTable.entity_id,
                    AuditLogTable.log_metadata,
                ).where(AuditLogTable.id == result.operator_audit_id)
            )
        ).one()
        first_delivery = await delivery_service.deliver_due(now=redriven_at)
        repeated_delivery = await delivery_service.deliver_due(now=redriven_at)
        final_delivery_status = await session.scalar(
            sa.select(FlowRunAuditOutbox.delivery_status).where(
                FlowRunAuditOutbox.id == outbox_id
            )
        )
        lifecycle_audit_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(AuditLogTable.id == outbox_id)
            .where(AuditLogTable.action == ActionType.FLOW_RUN_COMPLETED.value)
        )
        run_id = run.id
        run_tenant_id = run.tenant_id
        flow_id = run.flow_id

    assert result.outbox_id == outbox_id
    assert inspection.outbox_id == outbox_id
    assert inspection.dead_lettered_at == dead_lettered_at
    assert inspection_state == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    assert inspection_audit_count == 0
    assert result.flow_run_id == run_id
    assert result.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert result.delivery_attempts == 0
    assert result.next_delivery_at == redriven_at
    assert outbox_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert outbox_state.delivery_attempts == 0
    assert outbox_state.next_delivery_at == redriven_at
    assert outbox_state.delivered_at is None
    assert outbox_state.dead_lettered_at is None
    assert outbox_state.delivery_last_error is None
    assert first_delivery.delivered_count == 1
    assert repeated_delivery.attempted_count == 0
    assert final_delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
    assert lifecycle_audit_count == 1
    assert operator_audit.tenant_id == run_tenant_id
    assert operator_audit.actor_type == ActorType.SYSTEM.value
    assert operator_audit.action == ActionType.FLOW_RUN_AUDIT_DELIVERY_REDRIVEN.value
    assert operator_audit.entity_id == run_id
    assert operator_audit.log_metadata == {
        "actor": {"type": "system", "via": "operator_redrive"},
        "flow_id": str(flow_id),
        "flow_run_id": str(run_id),
        "outbox_id": str(outbox_id),
        "reason": "Audit storage recovered; password=[REDACTED]",
        "operator_identity": "on-call@example.invalid",
        "prior_delivery_attempts": 5,
        "prior_dead_lettered_at": dead_lettered_at.isoformat(),
        "prior_delivery_last_error": (
            "POST https://example.com/audit?token=%5BREDACTED%5D "
            "failed with Bearer [REDACTED]"
        ),
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_redrive_distinguishes_missing_and_wrong_state(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_id = await _insert_completed_outbox(
            outbox_repo=FlowRunAuditOutboxRepository(session=session),
            run=run,
            actor_id=admin_user.id,
        )
        service = _delivery_service(session)
        now = datetime.now(timezone.utc)

        with pytest.raises(FlowRunAuditOutboxNotFoundError):
            await service.inspect_redrive(
                outbox_id=uuid4(),
                expected_dead_lettered_at=now,
            )
        with pytest.raises(FlowRunAuditOutboxNotFoundError):
            await service.redrive_dead_lettered(
                outbox_id=uuid4(),
                expected_dead_lettered_at=now,
                reason="Investigated missing row.",
                now=now,
                operator_identity="test-operator",
            )
        with pytest.raises(FlowRunAuditOutboxStateConflictError):
            await service.inspect_redrive(
                outbox_id=outbox_id,
                expected_dead_lettered_at=now,
            )
        with pytest.raises(FlowRunAuditOutboxStateConflictError) as conflict:
            await service.redrive_dead_lettered(
                outbox_id=outbox_id,
                expected_dead_lettered_at=now,
                reason="Attempted a duplicate redrive.",
                now=now,
                operator_identity="test-operator",
            )

        operator_audit_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(
                AuditLogTable.action
                == ActionType.FLOW_RUN_AUDIT_DELIVERY_REDRIVEN.value
            )
        )
        delivery_status = await session.scalar(
            sa.select(FlowRunAuditOutbox.delivery_status).where(
                FlowRunAuditOutbox.id == outbox_id
            )
        )

    assert conflict.value.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert operator_audit_count == 0
    assert delivery_status == FlowOutboxDeliveryStatus.PENDING.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_redrive_rejects_stale_dead_letter_generation(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_id = await _insert_completed_outbox(
            outbox_repo=FlowRunAuditOutboxRepository(session=session),
            run=run,
            actor_id=admin_user.id,
        )
        stale_generation = datetime.now(timezone.utc) - timedelta(minutes=5)
        current_generation = datetime.now(timezone.utc)
        await session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
                delivery_attempts=5,
                next_delivery_at=None,
                dead_lettered_at=current_generation,
                delivery_last_error="second delivery generation failed",
            )
        )

        with pytest.raises(FlowRunAuditOutboxGenerationConflictError):
            await _delivery_service(session).inspect_redrive(
                outbox_id=outbox_id,
                expected_dead_lettered_at=stale_generation,
            )
        with pytest.raises(FlowRunAuditOutboxGenerationConflictError) as conflict:
            await _delivery_service(session).redrive_dead_lettered(
                outbox_id=outbox_id,
                expected_dead_lettered_at=stale_generation,
                reason="Using an obsolete operator listing.",
                now=datetime.now(timezone.utc),
                operator_identity="test-operator",
            )

        state = (
            await session.execute(
                sa.select(
                    FlowRunAuditOutbox.delivery_status,
                    FlowRunAuditOutbox.delivery_attempts,
                    FlowRunAuditOutbox.dead_lettered_at,
                    FlowRunAuditOutbox.delivery_last_error,
                ).where(FlowRunAuditOutbox.id == outbox_id)
            )
        ).one()
        audit_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(
                AuditLogTable.action
                == ActionType.FLOW_RUN_AUDIT_DELIVERY_REDRIVEN.value
            )
        )

    assert conflict.value.current_dead_lettered_at == current_generation
    assert state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    assert state.delivery_attempts == 5
    assert state.dead_lettered_at == current_generation
    assert state.delivery_last_error == "second delivery generation failed"
    assert audit_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_redrive_rolls_back_when_operator_audit_fails(
    monkeypatch: pytest.MonkeyPatch,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_id = await _insert_completed_outbox(
            outbox_repo=FlowRunAuditOutboxRepository(session=session),
            run=run,
            actor_id=admin_user.id,
        )
        dead_lettered_at = datetime.now(timezone.utc)
        await session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
                delivery_attempts=5,
                next_delivery_at=None,
                dead_lettered_at=dead_lettered_at,
                delivery_last_error="audit store unavailable",
            )
        )
        audit_repo = AuditLogRepositoryImpl(session)

        async def _fail_create(_audit_log):
            raise RuntimeError("operator audit insert failed")

        monkeypatch.setattr(audit_repo, "create", _fail_create)
        service = FlowRunAuditOutboxDeliveryService(
            audit_outbox_repo=FlowRunAuditOutboxRepository(session=session),
            audit_log_repo=audit_repo,
        )

        with pytest.raises(RuntimeError, match="operator audit insert failed"):
            await service.redrive_dead_lettered(
                outbox_id=outbox_id,
                expected_dead_lettered_at=dead_lettered_at,
                reason="Audit storage recovered.",
                now=datetime.now(timezone.utc),
                operator_identity="test-operator",
            )

        state = (
            await session.execute(
                sa.select(
                    FlowRunAuditOutbox.delivery_status,
                    FlowRunAuditOutbox.delivery_attempts,
                    FlowRunAuditOutbox.dead_lettered_at,
                    FlowRunAuditOutbox.delivery_last_error,
                ).where(FlowRunAuditOutbox.id == outbox_id)
            )
        ).one()

    assert state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    assert state.delivery_attempts == 5
    assert state.dead_lettered_at == dead_lettered_at
    assert state.delivery_last_error == "audit store unavailable"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_flow_audit_outbox_redrives_allow_one_transition(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_id = await _insert_completed_outbox(
            outbox_repo=FlowRunAuditOutboxRepository(session=session),
            run=run,
            actor_id=admin_user.id,
        )
        await session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
                delivery_attempts=5,
                next_delivery_at=None,
                dead_lettered_at=datetime.now(timezone.utc),
                delivery_last_error="audit store unavailable",
            )
        )
        run_id = run.id
        dead_lettered_at = await session.scalar(
            sa.select(FlowRunAuditOutbox.dead_lettered_at).where(
                FlowRunAuditOutbox.id == outbox_id
            )
        )
        assert dead_lettered_at is not None

    async def _redrive(reason: str):
        async with sessionmanager.session() as session, session.begin():
            return await _delivery_service(session).redrive_dead_lettered(
                outbox_id=outbox_id,
                expected_dead_lettered_at=dead_lettered_at,
                reason=reason,
                now=datetime.now(timezone.utc),
                operator_identity="test-operator",
            )

    outcomes = await asyncio.gather(
        _redrive("Operator A investigated."),
        _redrive("Operator B investigated."),
        return_exceptions=True,
    )

    async with sessionmanager.session() as session, session.begin():
        delivery_status = await session.scalar(
            sa.select(FlowRunAuditOutbox.delivery_status).where(
                FlowRunAuditOutbox.id == outbox_id
            )
        )
        operator_audit_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(
                AuditLogTable.action
                == ActionType.FLOW_RUN_AUDIT_DELIVERY_REDRIVEN.value
            )
            .where(AuditLogTable.entity_id == run_id)
        )

    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert (
        sum(
            isinstance(outcome, FlowRunAuditOutboxStateConflictError)
            for outcome in outcomes
        )
        == 1
    )
    assert delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert operator_audit_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_delivery_dead_letters_bad_row_and_delivers_neighbors(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        outbox_ids: list[UUID] = []
        for _ in range(3):
            _flow, run = await _create_flow_and_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
            )
            outbox_ids.append(
                await _insert_completed_outbox(
                    outbox_repo=FlowRunAuditOutboxRepository(session=session),
                    run=run,
                    actor_id=admin_user.id,
                )
            )
        await session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_ids[1])
            .values(
                action="unsupported_flow_action",
                description="unsupported_flow_action:executor_completed",
            )
        )

        result = await _delivery_service(session).deliver_due(
            now=datetime.now(timezone.utc)
        )
        statuses = [
            await session.scalar(
                sa.select(FlowRunAuditOutbox.delivery_status).where(
                    FlowRunAuditOutbox.id == outbox_id
                )
            )
            for outbox_id in outbox_ids
        ]

    assert result.delivered_count == 2
    assert result.dead_lettered_count == 1
    assert statuses == [
        FlowOutboxDeliveryStatus.DELIVERED.value,
        FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
        FlowOutboxDeliveryStatus.DELIVERED.value,
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_delivery_retries_then_dead_letters_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_id = await _insert_completed_outbox(
            outbox_repo=FlowRunAuditOutboxRepository(session=session),
            run=run,
            actor_id=admin_user.id,
        )
        audit_repo = AuditLogRepositoryImpl(session)

        async def _fail_create_if_absent(_audit_log):
            raise RuntimeError("audit store unavailable")

        monkeypatch.setattr(audit_repo, "create_if_absent", _fail_create_if_absent)
        service = FlowRunAuditOutboxDeliveryService(
            audit_outbox_repo=FlowRunAuditOutboxRepository(session=session),
            audit_log_repo=audit_repo,
        )
        now = datetime.now(timezone.utc)

        first = await service.deliver_due(now=now)
        retry_state = (
            await session.execute(
                sa.select(
                    FlowRunAuditOutbox.delivery_status,
                    FlowRunAuditOutbox.delivery_attempts,
                    FlowRunAuditOutbox.next_delivery_at,
                ).where(FlowRunAuditOutbox.id == outbox_id)
            )
        ).one()
        await session.execute(
            sa.update(FlowRunAuditOutbox)
            .where(FlowRunAuditOutbox.id == outbox_id)
            .values(
                delivery_attempts=4,
                next_delivery_at=now - timedelta(seconds=1),
            )
        )
        second = await service.deliver_due(now=now)
        dead_letter_state = (
            await session.execute(
                sa.select(
                    FlowRunAuditOutbox.delivery_status,
                    FlowRunAuditOutbox.dead_lettered_at,
                ).where(FlowRunAuditOutbox.id == outbox_id)
            )
        ).one()

    assert first.retry_scheduled_count == 1
    assert retry_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert retry_state.delivery_attempts == 1
    assert retry_state.next_delivery_at is not None
    assert second.dead_lettered_count == 1
    assert (
        dead_letter_state.delivery_status
        == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert dead_letter_state.dead_lettered_at is not None


@pytest.mark.parametrize(
    "invalid_update",
    [
        {
            "delivery_status": FlowOutboxDeliveryStatus.DELIVERED.value,
            "delivered_at": None,
        },
        {"delivery_status": "unsupported"},
        {"delivery_attempts": -1},
    ],
)
@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_delivery_constraints_reject_impossible_state(
    invalid_update: dict[str, object],
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_id = await _insert_completed_outbox(
            outbox_repo=FlowRunAuditOutboxRepository(session=session),
            run=run,
            actor_id=admin_user.id,
        )

        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    sa.update(FlowRunAuditOutbox)
                    .where(FlowRunAuditOutbox.id == outbox_id)
                    .values(**invalid_update)
                )
                await session.flush()


async def _seed_due_outbox_rows(
    *,
    row_count: int,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
) -> list[UUID]:
    """Commit ``row_count`` due audit rows, one per revision of one run."""
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        _flow, run = await _create_flow_and_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        outbox_repo = FlowRunAuditOutboxRepository(session=session)
        outbox_ids = [
            await _insert_completed_outbox(
                outbox_repo=outbox_repo,
                run=run.model_copy(update={"revision": revision}),
                actor_id=admin_user.id,
            )
            for revision in range(1, row_count + 1)
        ]
        await session.commit()
    return outbox_ids


async def _delivery_statuses() -> dict[str, int]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.execute(
            sa.select(FlowRunAuditOutbox.delivery_status, sa.func.count()).group_by(
                FlowRunAuditOutbox.delivery_status
            )
        )
        return {status: count for status, count in rows.all()}


async def _audit_log_count() -> int:
    async with sessionmanager.session() as session, session.begin():
        return await session.scalar(
            sa.select(sa.func.count())
            .select_from(AuditLogTable)
            .where(AuditLogTable.action == ActionType.FLOW_RUN_COMPLETED.value)
        )


def _record_claims(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record how many rows each delivery batch claims."""
    claims: list[int] = []
    real_list_due = FlowRunAuditOutboxRepository.list_due_delivery_rows

    async def _list_due(self, *, now, limit):
        rows = await real_list_due(self, now=now, limit=limit)
        claims.append(len(rows))
        return rows

    monkeypatch.setattr(
        FlowRunAuditOutboxRepository, "list_due_delivery_rows", _list_due
    )
    return claims


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_job_drains_more_than_one_batch(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    await _seed_due_outbox_rows(
        row_count=2 * FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE + 50,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )

    payload = await flow_runtime_tasks.deliver_flow_audit_outbox()

    row_count = 2 * FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE + 50
    assert payload == {
        "status": "ok",
        "attempted": row_count,
        "delivered": row_count,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "batches": 3,
    }
    assert await _delivery_statuses() == {
        FlowOutboxDeliveryStatus.DELIVERED.value: row_count
    }
    assert await _audit_log_count() == row_count


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_job_ends_on_a_partly_attempted_batch(
    monkeypatch: pytest.MonkeyPatch,
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """A batch that claims fewer rows than its limit means nothing more is
    due: the job stops there instead of asking again."""
    await _seed_due_outbox_rows(
        row_count=3,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    claims = _record_claims(monkeypatch)

    payload = await flow_runtime_tasks._deliver_flow_audit_outbox(limit=2)

    assert claims == [2, 1]
    assert payload["delivered"] == 3
    assert payload["batches"] == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_job_goes_on_after_a_full_batch_with_a_retry(
    monkeypatch: pytest.MonkeyPatch,
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """A full claim means more may be due even when a row in it failed: the
    job stops on what it attempted, not on what it delivered."""
    await _seed_due_outbox_rows(
        row_count=3,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    claims = _record_claims(monkeypatch)
    real_create_if_absent = AuditLogRepositoryImpl.create_if_absent
    audit_writes = 0

    async def _create_if_absent(self, audit_log):
        nonlocal audit_writes
        audit_writes += 1
        if audit_writes == 1:
            raise RuntimeError("audit log unavailable")
        return await real_create_if_absent(self, audit_log)

    monkeypatch.setattr(AuditLogRepositoryImpl, "create_if_absent", _create_if_absent)

    payload = await flow_runtime_tasks._deliver_flow_audit_outbox(limit=2)

    assert claims == [2, 1]
    assert payload == {
        "status": "ok",
        "attempted": 3,
        "delivered": 2,
        "retry_scheduled": 1,
        "dead_lettered": 0,
        "batches": 2,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_job_stops_at_its_drain_time(
    monkeypatch: pytest.MonkeyPatch,
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    row_count = FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE + 1
    await _seed_due_outbox_rows(
        row_count=row_count,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    monkeypatch.setattr(
        flow_runtime_tasks, "flow_audit_outbox_drain_seconds", lambda: 0
    )

    payload = await flow_runtime_tasks.deliver_flow_audit_outbox()

    assert payload["delivered"] == FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE
    assert payload["batches"] == 1
    assert await _delivery_statuses() == {
        FlowOutboxDeliveryStatus.DELIVERED.value: FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
        FlowOutboxDeliveryStatus.PENDING.value: 1,
    }


@pytest.mark.parametrize("interruption", ["failure", "cancellation"])
@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_audit_outbox_job_interrupted_in_a_later_batch_keeps_earlier_batches(
    interruption: str,
    monkeypatch: pytest.MonkeyPatch,
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """Each batch commits on its own. A batch that fails or is cancelled after
    delivering its rows rolls back; the batch before it stays delivered, and the
    rolled-back rows stay due for the next job."""
    row_count = 2 * FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE + 50
    await _seed_due_outbox_rows(
        row_count=row_count,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    real_deliver_due = FlowRunAuditOutboxDeliveryService.deliver_due
    batches_started = 0
    second_batch_delivered = asyncio.Event()

    async def _deliver_due(self, *, now, limit=None):
        nonlocal batches_started
        batches_started += 1
        result = await real_deliver_due(self, now=now, limit=limit)
        if batches_started == 2:
            assert result.delivered_count == FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE
            if interruption == "failure":
                raise RuntimeError("database went away")
            second_batch_delivered.set()
            await asyncio.Event().wait()
        return result

    monkeypatch.setattr(FlowRunAuditOutboxDeliveryService, "deliver_due", _deliver_due)

    job = asyncio.create_task(flow_runtime_tasks.deliver_flow_audit_outbox())
    if interruption == "failure":
        with pytest.raises(RuntimeError, match="database went away"):
            await job
    else:
        await asyncio.wait_for(second_batch_delivered.wait(), timeout=30)
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job

    assert batches_started == 2
    assert await _delivery_statuses() == {
        FlowOutboxDeliveryStatus.DELIVERED.value: FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
        FlowOutboxDeliveryStatus.PENDING.value: row_count
        - FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
    }
    assert await _audit_log_count() == FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE

    monkeypatch.setattr(
        FlowRunAuditOutboxDeliveryService, "deliver_due", real_deliver_due
    )
    recovered = await flow_runtime_tasks.deliver_flow_audit_outbox()

    assert recovered["delivered"] == row_count - FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE
    assert await _delivery_statuses() == {
        FlowOutboxDeliveryStatus.DELIVERED.value: row_count
    }
    assert await _audit_log_count() == row_count

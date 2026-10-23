from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.exc import IntegrityError

from eneo.audit.domain.outcome import Outcome
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRuns,
    FlowRunWebhookDeliveries,
    FlowStepAttempts,
    FlowStepResults,
    FlowVersions,
)
from eneo.flows.application import flow_webhook_delivery_policy as webhook_policy
from eneo.flows.application.flow_run_retry_service import FlowRunRetryService
from eneo.flows.application.flow_run_service import FlowRunService
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_CONCURRENCY,
    FLOW_WEBHOOK_MAX_ATTEMPTS,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepResultStatus,
)
from eneo.flows.domain.flow_webhook_delivery import (
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from eneo.flows.enums import FlowRunLifecycleSource, FlowStepAttemptStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
    FlowRunWebhookDeliveryRow,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import (
    build_published_definition_json,
    published_definition_checksum,
)
from eneo.flows.runtime.flow_webhook_delivery import FlowRunWebhookDeliveryService
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.container.container import Container
from eneo.main.exceptions import ConflictException, TypedIOValidationException
from tests.flow_snapshot_fixtures import assistant_snapshot
from tests.unittests.flows.egress.egress_test_support import recording_server


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
    output_config: dict[str, object] | None = None,
    include_prior_step: bool = False,
) -> Flow:
    webhook_step_order = 2 if include_prior_step else 1
    steps = (
        [
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Prepare webhook content",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings={"question": "{{flow.input.question}}"},
                output_config=None,
                output_classification_override=None,
                input_config=None,
            )
        ]
        if include_prior_step
        else []
    )
    steps.append(
        FlowStep(
            id=None,
            flow_id=uuid4(),
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            step_order=webhook_step_order,
            user_description="Send webhook",
            input_source="previous_step" if include_prior_step else "flow_input",
            input_type="text",
            input_contract=None,
            output_mode="http_post",
            output_type="text",
            output_contract=None,
            input_bindings={"question": "{{flow.input.question}}"},
            output_config=output_config
            or {
                "url": "https://example.org/hook/{{flow_input.case_id}}",
                "auth": {"mode": "none"},
                "timeout_seconds": 5,
            },
            output_classification_override=None,
            input_config=None,
        )
    )
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Webhook Outbox Delivery Flow",
        description="Flow used for webhook outbox delivery tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=steps,
    )


async def _create_running_webhook_run(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    output_config: dict[str, object] | None = None,
    prior_output_payload: dict[str, object] | None = None,
    model_name: str = "gpt-4o-mini",
):
    model = await completion_model_factory(session, model_name)
    space = await space_factory(session, "Webhook outbox delivery space", [model.id])
    assistant = await assistant_factory(
        session,
        "Webhook Outbox Delivery Assistant",
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
            output_config=output_config,
            include_prior_step=prior_output_payload is not None,
        ),
        tenant_id=admin_user.tenant_id,
    )
    assert flow.id is not None
    step = flow.steps[-1]
    assert step.id is not None
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        definition_json=build_published_definition_json(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[
                {
                    "step_id": str(published_step.id),
                    "assistant_id": str(published_step.assistant_id),
                    "assistant_snapshot": assistant_snapshot(
                        published_step.assistant_id
                    ),
                    "step_order": published_step.step_order,
                    "user_description": published_step.user_description,
                    "input_source": published_step.input_source,
                    "input_type": published_step.input_type,
                    "input_bindings": published_step.input_bindings,
                    "output_mode": published_step.output_mode,
                    "output_type": published_step.output_type,
                    "output_config": published_step.output_config,
                }
                for published_step in flow.steps
            ],
        ),
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
        input_payload_json={"question": "What happened?", "case_id": "case-123"},
        preseed_steps=[
            {
                "step_id": published_step.id,
                "assistant_id": published_step.assistant_id,
                "step_order": published_step.step_order,
            }
            for published_step in flow.steps
        ],
    )
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == run.id)
        .values(
            status=FlowRunStatus.RUNNING.value,
            execution_heartbeat_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    output_payloads = (
        [prior_output_payload, {"text": "done"}]
        if prior_output_payload is not None
        else [{"text": "done"}]
    )
    for published_step, output_payload in zip(flow.steps, output_payloads, strict=True):
        assert published_step.id is not None
        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=published_step.id,
            step_order=published_step.step_order,
            attempt_no=1,
            dispatch_task_id=f"webhook-outbox-fixture-{published_step.step_order}",
        )
        pending_result = await run_repo.get_step_result(
            run_id=run.id,
            step_id=published_step.id,
            tenant_id=admin_user.tenant_id,
        )
        assert pending_result is not None
        completed_result = pending_result.model_copy(
            update={
                "status": FlowStepResultStatus.COMPLETED,
                "current_attempt_no": 1,
                "input_payload_json": {"text": "hello"},
                "output_payload_json": output_payload,
                "effective_prompt": "prompt",
                "model_parameters_json": {},
                "num_tokens_input": 1,
                "num_tokens_output": 1,
                "flow_step_execution_hash": "hash",
            },
            deep=True,
        )
        await run_repo.save_step_result(
            run.id,
            completed_result,
            tenant_id=admin_user.tenant_id,
            attempt_no=1,
        )
        await run_repo.finish_attempt(
            run_id=run.id,
            step_id=published_step.id,
            attempt_no=1,
            tenant_id=admin_user.tenant_id,
            status=FlowStepAttemptStatus.COMPLETED,
            requested_model="gpt-4o-mini",
            response_model="gpt-4o-mini",
            provider="openai",
            finish_reason="stop",
            num_tokens_input=1,
            num_tokens_output=1,
        )
    return flow, run, step


def _intent(
    *,
    run_id: UUID,
    step_id: UUID,
    step_order: int = 1,
) -> WebhookDeliveryIntent:
    return WebhookDeliveryIntent(
        flow_run_id=run_id,
        step_id=step_id,
        step_order=step_order,
        attempt_no=1,
        idempotency_key=f"{run_id}:{step_id}:1:webhook",
        payload=WebhookPayloadRef(
            value=f"flow_run:{run_id}:step:{step_id}:attempt:1",
        ),
    )


def _intent_for_attempt(
    *,
    run_id: UUID,
    step_id: UUID,
    attempt_no: int,
) -> WebhookDeliveryIntent:
    return WebhookDeliveryIntent(
        flow_run_id=run_id,
        step_id=step_id,
        step_order=1,
        attempt_no=attempt_no,
        idempotency_key=f"{run_id}:{step_id}:{attempt_no}:webhook",
        payload=WebhookPayloadRef(
            value=f"flow_run:{run_id}:step:{step_id}:attempt:{attempt_no}",
        ),
    )


class _TestEncryptionService:
    _PREFIX = "enc:fernet:v1:"

    def is_encrypted(self, value: str) -> bool:
        return value.startswith(self._PREFIX)

    def can_decrypt(self, value: str) -> bool:
        return value.startswith(self._PREFIX)

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext.startswith(self._PREFIX):
            return ciphertext
        return ciphertext[len(self._PREFIX) :]


class _CasFailingWebhookDeliveryRepository(FlowRunWebhookDeliveryRepository):
    async def mark_delivery_succeeded(self, **kwargs):
        return False


class _FailureCasFailingWebhookDeliveryRepository(FlowRunWebhookDeliveryRepository):
    async def record_delivery_failure(self, **kwargs):
        return False


class _FailureCasFailingOnceWebhookDeliveryRepository(FlowRunWebhookDeliveryRepository):
    fail_next_failure = False

    async def record_delivery_failure(self, **kwargs):
        if self.fail_next_failure:
            self.fail_next_failure = False
            return False
        return await super().record_delivery_failure(**kwargs)


class _SuccessCasFailingOnceWebhookDeliveryRepository(FlowRunWebhookDeliveryRepository):
    fail_next_success = False

    async def mark_delivery_succeeded(self, **kwargs):
        if self.fail_next_success:
            self.fail_next_success = False
            return False
        return await super().mark_delivery_succeeded(**kwargs)


def _delivery_service(
    *,
    session,
    container: Container,
    webhook_repo: FlowRunWebhookDeliveryRepository,
    audit_service=None,
    encryption_service=None,
) -> FlowRunWebhookDeliveryService:
    flow_run_repo = FlowRunRepository(session=session)
    audit_outbox_repo = FlowRunAuditOutboxRepository(session=session)
    review_checkpoint_repo = FlowRunReviewCheckpointRepository(
        session=session,
        audit_outbox_repo=audit_outbox_repo,
    )
    return FlowRunWebhookDeliveryService(
        webhook_delivery_repo=webhook_repo,
        flow_repo=FlowRepository(session=session),
        flow_run_repo=flow_run_repo,
        flow_version_repo=FlowVersionRepository(
            session=session,
        ),
        flow_run_terminalizer=FlowRunTerminalizer(
            flow_run_repo,
            audit_outbox_repo,
            review_checkpoint_repo,
        ),
        encryption_service=encryption_service or container.encryption_service(),
        audit_service=audit_service,
        user_repo=container.user_repo(),
        api_key_repo=container.api_key_v2_repo(),
        tenant_repo=container.tenant_repo(),
        http_runtime=FlowHttpRuntimeHelper(
            variable_resolver=FlowVariableResolver(),
            request_timeout_seconds=5.0,
            max_timeout_seconds=5.0,
            allow_private_networks=False,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_public_projection_is_tenant_scoped_and_ordered(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        flow, run, webhook_step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            prior_output_payload={"text": "prepared"},
        )
        first_step = flow.steps[0]
        assert flow.id is not None
        assert first_step.id is not None
        assert webhook_step.id is not None
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        second_delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(
                run_id=run.id,
                step_id=webhook_step.id,
                step_order=webhook_step.step_order,
            ),
        )
        await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(
                run_id=run.id,
                step_id=first_step.id,
                step_order=first_step.step_order,
            ),
        )
        delivered_at = datetime.now(timezone.utc)
        await session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == second_delivery_id)
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
                delivery_attempts=2,
                next_delivery_at=None,
                delivered_at=delivered_at,
            )
        )

        deliveries = await webhook_repo.list_run_delivery_statuses(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
        )
        other_tenant_deliveries = await webhook_repo.list_run_delivery_statuses(
            run_id=run.id,
            tenant_id=uuid4(),
        )

    assert [(item.step_order, item.attempt_no) for item in deliveries] == [
        (1, 1),
        (2, 1),
    ]
    assert deliveries[1].delivery_status is FlowOutboxDeliveryStatus.DELIVERED
    assert deliveries[1].delivery_attempts == 2
    assert deliveries[1].delivered_at == delivered_at
    assert other_tenant_deliveries == []
    assert not hasattr(deliveries[1], "idempotency_key")
    assert not hasattr(deliveries[1], "payload_ref")
    assert not hasattr(deliveries[1], "delivery_last_error")
    assert not hasattr(deliveries[1], "claim_token")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_claims_pending_rows_and_skips_stale_reconciler(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )

        stale_runs = await FlowRunRepository(
            session=session,
        ).list_recovery_candidates(
            tenant_id=admin_user.tenant_id,
        )
        claimed = await webhook_repo.claim_due_delivery_rows(
            now=datetime.now(timezone.utc),
            limit=10,
            claim_ttl_seconds=120,
            max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
        )
        second_claim = await webhook_repo.claim_due_delivery_rows(
            now=datetime.now(timezone.utc),
            limit=10,
            claim_ttl_seconds=120,
            max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
        )

    assert stale_runs == []
    assert [item.id for item in claimed] == [delivery_id]
    assert second_claim == []
    assert all(item.id != run.id for item in stale_runs)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_claim_charges_attempt_before_outcome(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        now = datetime.now(timezone.utc)

        claimed = await webhook_repo.claim_due_delivery_rows(
            now=now,
            limit=1,
            claim_ttl_seconds=120,
            max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
        )
        await session.commit()

        async with sessionmanager.session() as check_session:
            async with check_session.begin():
                committed_attempts = await check_session.scalar(
                    sa.select(FlowRunWebhookDeliveries.delivery_attempts).where(
                        FlowRunWebhookDeliveries.id == delivery_id
                    )
                )

        assert claimed[0].delivery_attempts == 1
        assert committed_attempts == 1

        did_record = await webhook_repo.record_delivery_failure(
            delivery_id=delivery_id,
            claim_token=claimed[0].claim_token,
            error_message="retryable failure",
            next_delivery_at=now,
            dead_lettered_at=None,
        )
        attempts_after_outcome = await session.scalar(
            sa.select(FlowRunWebhookDeliveries.delivery_attempts).where(
                FlowRunWebhookDeliveries.id == delivery_id
            )
        )

    assert did_record is True
    assert attempts_after_outcome == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_batch_claim_is_distinct_across_competing_sessions(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as setup_session:
        enable_autobegin_for_flow_task_session(setup_session)
        delivery_ids: list[UUID] = []
        for row_no in range(2):
            flow, run, step = await _create_running_webhook_run(
                session=setup_session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                model_name=f"webhook-batch-model-{row_no}",
            )
            delivery_ids.append(
                await FlowRunWebhookDeliveryRepository(
                    session=setup_session
                ).insert_pending_delivery(
                    flow_id=flow.id,
                    tenant_id=admin_user.tenant_id,
                    intent=_intent(run_id=run.id, step_id=step.id),
                )
            )
        await setup_session.commit()

    now = datetime.now(timezone.utc)

    async def _claim_batch():
        async with sessionmanager.session() as claim_session:
            enable_autobegin_for_flow_task_session(claim_session)
            rows = await FlowRunWebhookDeliveryRepository(
                session=claim_session
            ).claim_due_delivery_rows(
                now=now,
                limit=2,
                claim_ttl_seconds=120,
                max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
            )
            await claim_session.commit()
            return rows

    competing_claims = await asyncio.gather(_claim_batch(), _claim_batch())
    claimed_rows = [row for batch in competing_claims for row in batch]

    async with sessionmanager.session() as check_session:
        enable_autobegin_for_flow_task_session(check_session)
        attempts = (
            await check_session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.id,
                    FlowRunWebhookDeliveries.delivery_attempts,
                ).where(FlowRunWebhookDeliveries.id.in_(delivery_ids))
            )
        ).all()

    assert {row.id for row in claimed_rows} == set(delivery_ids)
    assert len(claimed_rows) == len(delivery_ids)
    assert {row.delivery_attempts for row in claimed_rows} == {1}
    assert {attempt.id: attempt.delivery_attempts for attempt in attempts} == {
        delivery_id: 1 for delivery_id in delivery_ids
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_reclaims_expired_claim_after_pre_send_crash(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        now = datetime.now(timezone.utc)

        first_claim = (
            await webhook_repo.claim_due_delivery_rows(
                now=now,
                limit=1,
                claim_ttl_seconds=120,
                max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
            )
        )[0]
        await session.commit()

        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")
        send_http_request = AsyncMock(return_value=httpx.Response(200, request=request))
        service.http_runtime.send_request = send_http_request

        recovered = await service.deliver_due(now=now + timedelta(seconds=121))
        recorded_by = datetime.now(timezone.utc)
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.idempotency_key,
                    FlowRunWebhookDeliveries.delivered_at,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()

    assert first_claim.delivery_attempts == 1
    assert recovered.attempted_count == 1
    assert recovered.delivered_count == 1
    assert send_http_request.await_count == 1
    assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
    assert delivery_state.delivery_attempts == 2
    assert delivery_state.idempotency_key == first_claim.idempotency_key
    # Recorded when it happened, not at the (here future) claim time.
    assert delivery_state.delivered_at <= recorded_by


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_reposts_after_expired_success_claim_with_stable_key(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = _SuccessCasFailingOnceWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        webhook_repo.fail_next_success = True
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")
        sent_idempotency_keys: list[str] = []

        async def _send_http_request(**kwargs):
            sent_idempotency_keys.append(kwargs["headers"]["Idempotency-Key"])
            return httpx.Response(200, request=request)

        service.http_runtime.send_request = _send_http_request
        now = datetime.now(timezone.utc)

        outcome_commit_lost = await service.deliver_due(now=now)
        recovered = await service.deliver_due(
            now=now
            + timedelta(
                seconds=webhook_policy.flow_webhook_delivery_budget().claim_ttl_seconds
                + 1
            )
        )
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()

    assert outcome_commit_lost.attempted_count == 1
    assert outcome_commit_lost.delivered_count == 0
    assert recovered.attempted_count == 1
    assert recovered.delivered_count == 1
    assert len(sent_idempotency_keys) == 2
    assert sent_idempotency_keys[0] == sent_idempotency_keys[1]
    assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
    assert delivery_state.delivery_attempts == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_requires_matching_step_attempt(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)

        with pytest.raises(IntegrityError) as exc_info:
            await webhook_repo.insert_pending_delivery(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                intent=_intent_for_attempt(
                    run_id=run.id, step_id=step.id, attempt_no=99
                ),
            )
        assert "fk_flow_run_webhook_deliveries_step_attempt" in str(exc_info.value)
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_blocks_attempt_deletion(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )

        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                sa.delete(FlowStepAttempts)
                .where(FlowStepAttempts.flow_run_id == run.id)
                .where(FlowStepAttempts.step_id == step.id)
                .where(FlowStepAttempts.attempt_no == 1)
                .where(FlowStepAttempts.tenant_id == admin_user.tenant_id)
            )
        assert "fk_flow_run_webhook_deliveries_step_attempt" in str(exc_info.value)
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_sends_outside_transaction_and_completes_run(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )

        async def _log_audit(**_kwargs: object) -> UUID:
            await session.execute(sa.select(1))
            return uuid4()

        audit_log = AsyncMock(side_effect=_log_audit)
        audit_service = type(
            "AuditServiceStub",
            (),
            {"log_async": audit_log},
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
            audit_service=audit_service,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")

        async def _send_http_request(**kwargs):
            assert not session.in_transaction()
            async with sessionmanager.session() as check_session:
                enable_autobegin_for_flow_task_session(check_session)
                committed_claim = (
                    await check_session.execute(
                        sa.select(
                            FlowRunWebhookDeliveries.claim_token,
                            FlowRunWebhookDeliveries.delivery_attempts,
                        ).where(FlowRunWebhookDeliveries.id == delivery_id)
                    )
                ).one()
            assert committed_claim.claim_token is not None
            assert committed_claim.delivery_attempts == 1
            assert kwargs["url"] == "https://example.org/hook/case-123"
            assert kwargs["body_bytes"] == b"done"
            assert len(kwargs["headers"]["Idempotency-Key"]) == 64
            return httpx.Response(200, request=request)

        service.http_runtime.send_request = _send_http_request

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.delivered_at,
                    FlowRunWebhookDeliveries.delivery_last_error,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status).where(FlowRuns.id == run.id)
            )
        ).scalar_one()
        result_payload = (
            await session.execute(
                sa.select(FlowStepResults.output_payload_json).where(
                    FlowStepResults.flow_run_id == run.id,
                    FlowStepResults.step_id == step.id,
                )
            )
        ).scalar_one()

    assert result.delivered_count == 1, delivery_state.delivery_last_error
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 0
    assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
    assert delivery_state.delivery_attempts == 1
    assert delivery_state.delivered_at is not None
    assert run_state == FlowRunStatus.COMPLETED.value
    assert result_payload == {"text": "done"}
    audit_log.assert_awaited_once()
    audit_args = audit_log.await_args
    assert audit_args is not None
    assert audit_args.kwargs["outcome"] == Outcome.SUCCESS


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_rejects_file_backed_preview_without_http(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run.id,
                FlowStepResults.step_id == step.id,
            )
            .values(
                output_payload_json={
                    "text": "preview",
                    "text_overflow": {
                        "generated_file_ids": [str(uuid4())],
                        "inline_text_bytes": 7,
                        "full_text_bytes": 20,
                    },
                }
            )
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        send_http_request = AsyncMock()
        service.http_runtime.send_request = send_http_request

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_last_error,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()

    assert result.dead_lettered_count == 1
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert "complete text is stored in a generated output file" in (
        delivery_state.delivery_last_error
    )
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("output_config", "expected_in_error"),
    [
        pytest.param(
            {
                "url": "https://example.org/hook",
                "auth": {"mode": "bearer_token", "token": "{{step_1.output.text}}"},
                "timeout_seconds": 5,
            },
            "auth.token",
            id="templated-credential",
        ),
        pytest.param(
            {"url": "https://example.org/hook", "timeout_seconds": 5},
            "authored HTTP config",
            id="missing-auth",
        ),
        pytest.param(
            {
                "url": "https://example.org/hook",
                "auth": {"mode": "bogus"},
                "timeout_seconds": 5,
            },
            "output_config.auth",
            id="bogus-auth-mode",
        ),
        pytest.param(
            {"url": "not a url", "auth": {"mode": "none"}, "timeout_seconds": 5},
            "output_config.url",
            id="malformed-url",
        ),
        pytest.param(
            {
                "url": "https://alice:secret@{{step_1.output.text}}/hook",
                "auth": {"mode": "none"},
                "timeout_seconds": 5,
            },
            "output_config.url",
            id="templated-userinfo",
        ),
        pytest.param(
            {
                "url": "ftp://example.org/{{step_1.output.text}}",
                "auth": {"mode": "none"},
                "timeout_seconds": 5,
            },
            "output_config.url",
            id="fixed-non-http-scheme-before-a-template",
        ),
    ],
)
async def test_flow_webhook_delivery_dead_letters_a_config_the_runtime_rejects_without_retry(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    output_config,
    expected_in_error,
):
    # A version published before the config was validated. Compiling the
    # request never changes between attempts, so retrying it five times only
    # delays the run's failure.
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            output_config=output_config,
            prior_output_payload={"text": "classified-text"},
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(
                run_id=run.id,
                step_id=step.id,
                step_order=step.step_order,
            ),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        send_http_request = AsyncMock()
        service.http_runtime.send_request = send_http_request
        now = datetime.now(timezone.utc)

        result = await service.deliver_due(now=now)
        repeated = await service.deliver_due(now=now + timedelta(hours=1))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.delivery_last_error,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()

    assert result.attempted_count == 1
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 1
    assert repeated.attempted_count == 0
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == 1
    assert expected_in_error in delivery_state.delivery_last_error
    assert "classified-text" not in delivery_state.delivery_last_error
    assert "alice:secret" not in delivery_state.delivery_last_error
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_dead_letters_file_backed_template_reference_once(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    file_id = uuid4()
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            output_config={
                "url": "https://example.org/hook/{{step_1.output.text}}",
                "auth": {"mode": "none"},
                "timeout_seconds": 5,
            },
            prior_output_payload={
                "text": "preview",
                "text_overflow": {
                    "generated_file_ids": [str(file_id)],
                    "inline_text_bytes": 7,
                    "full_text_bytes": 20,
                },
            },
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(
                run_id=run.id,
                step_id=step.id,
                step_order=step.step_order,
            ),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        send_http_request = AsyncMock()
        service.http_runtime.send_request = send_http_request
        now = datetime.now(timezone.utc)

        result = await service.deliver_due(now=now)
        repeated = await service.deliver_due(now=now)
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.delivery_last_error,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()

    assert result.attempted_count == 1
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 1
    assert repeated.attempted_count == 0
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == 1
    assert "generated output file" in delivery_state.delivery_last_error
    assert "preview" not in delivery_state.delivery_last_error
    assert str(file_id) not in delivery_state.delivery_last_error
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_audits_failed_http_response(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )

        async def _log_audit(**_kwargs: object) -> UUID:
            await session.execute(sa.select(1))
            return uuid4()

        audit_log = AsyncMock(side_effect=_log_audit)
        audit_service = type(
            "AuditServiceStub",
            (),
            {"log_async": audit_log},
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
            audit_service=audit_service,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")

        async def _send_http_request(**kwargs):
            assert not session.in_transaction()
            return httpx.Response(503, request=request)

        service.http_runtime.send_request = _send_http_request

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.delivery_last_error,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()

    assert result.delivered_count == 0
    assert result.retry_scheduled_count == 1
    assert result.dead_lettered_count == 0
    assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert delivery_state.delivery_attempts == 1
    assert "status 503" in delivery_state.delivery_last_error
    audit_log.assert_awaited_once()
    audit_args = audit_log.await_args
    assert audit_args is not None
    assert audit_args.kwargs["outcome"] == Outcome.FAILURE


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_decrypts_encrypted_headers(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            output_config={
                "url": "https://example.org/hook/{{flow_input.case_id}}",
                "auth": {"mode": "none"},
                "timeout_seconds": 5,
                "custom_headers": [
                    {
                        "name": "Authorization",
                        "value": "enc:fernet:v1:Bearer top-secret",
                        "secret": True,
                    },
                    {"name": "X-Plain", "value": "visible", "secret": False},
                ],
            },
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
            encryption_service=_TestEncryptionService(),
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")

        async def _send_http_request(**kwargs):
            assert kwargs["headers"]["Authorization"] == "Bearer top-secret"
            assert kwargs["headers"]["X-Plain"] == "visible"
            return httpx.Response(200, request=request)

        service.http_runtime.send_request = _send_http_request

        result = await service.deliver_due(now=datetime.now(timezone.utc))

    assert result.delivered_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_rolls_back_step_result_when_success_claim_lost(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = _CasFailingWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")

        async def _send_http_request(**kwargs):
            return httpx.Response(200, request=request)

        service.http_runtime.send_request = _send_http_request

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.claim_token,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        result_payload = (
            await session.execute(
                sa.select(FlowStepResults.output_payload_json).where(
                    FlowStepResults.flow_run_id == run.id,
                    FlowStepResults.step_id == step.id,
                )
            )
        ).scalar_one()

    assert result.delivered_count == 0
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 0
    assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert delivery_state.claim_token is not None
    assert result_payload == {"text": "done"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_dead_letters_cancelled_run_without_http(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(status=FlowRunStatus.CANCELLED.value)
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        send_http_request = AsyncMock()
        service.http_runtime.send_request = send_http_request

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.dead_lettered_at,
                    FlowRunWebhookDeliveries.delivery_last_error,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status).where(FlowRuns.id == run.id)
            )
        ).scalar_one()

    assert result.attempted_count == 1
    assert result.delivered_count == 0
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 1
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == 1
    assert delivery_state.dead_lettered_at is not None
    assert "no longer running" in delivery_state.delivery_last_error
    assert run_state == FlowRunStatus.CANCELLED.value
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_dead_letters_checksum_drift_without_http(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        definition_json = await session.scalar(
            sa.select(FlowVersions.definition_json).where(
                FlowVersions.flow_id == flow.id,
                FlowVersions.version == run.flow_version,
            )
        )
        assert isinstance(definition_json, dict)
        await session.execute(
            sa.update(FlowVersions)
            .where(
                FlowVersions.flow_id == flow.id,
                FlowVersions.version == run.flow_version,
            )
            .values(definition_json={**definition_json, "name": "Corrupt snapshot"})
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        send_http_request = AsyncMock(
            side_effect=AssertionError("checksum drift must fail before HTTP")
        )
        service.http_runtime.send_request = send_http_request
        now = datetime.now(timezone.utc)

        result = await service.deliver_due(now=now)
        second_result = await service.deliver_due(now=now)
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.dead_lettered_at,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.error_json).where(
                    FlowRuns.id == run.id
                )
            )
        ).one()

    assert result.attempted_count == 1
    assert result.delivered_count == 0
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 1
    assert second_result.attempted_count == 0
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == 1
    assert delivery_state.dead_lettered_at is not None
    assert run_state.status == FlowRunStatus.FAILED.value
    run_error = FlowRunError.model_validate(run_state.error_json)
    assert run_error.code is FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH
    assert run_error.source is FlowRunLifecycleSource.DEFINITION_CHECKSUM_MISMATCH
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_dead_letters_malformed_definition_without_http(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        definition_json = await session.scalar(
            sa.select(FlowVersions.definition_json).where(
                FlowVersions.flow_id == flow.id,
                FlowVersions.version == run.flow_version,
            )
        )
        assert isinstance(definition_json, dict)
        malformed_definition = {**definition_json, "steps": "not-an-array"}
        await session.execute(
            sa.update(FlowVersions)
            .where(
                FlowVersions.flow_id == flow.id,
                FlowVersions.version == run.flow_version,
            )
            .values(
                definition_json=malformed_definition,
                definition_checksum=published_definition_checksum(malformed_definition),
            )
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        send_http_request = AsyncMock(
            side_effect=AssertionError("malformed definition must fail before HTTP")
        )
        service.http_runtime.send_request = send_http_request
        now = datetime.now(timezone.utc)

        result = await service.deliver_due(now=now)
        second_result = await service.deliver_due(now=now)
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.dead_lettered_at,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.error_json).where(
                    FlowRuns.id == run.id
                )
            )
        ).one()

    assert result.attempted_count == 1
    assert result.delivered_count == 0
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 1
    assert second_result.attempted_count == 0
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == 1
    assert delivery_state.dead_lettered_at is not None
    assert run_state.status == FlowRunStatus.FAILED.value
    run_error = FlowRunError.model_validate(run_state.error_json)
    assert run_error.code is FlowApiErrorCode.DEFINITION_STEPS_INVALID
    assert run_error.source is FlowRunLifecycleSource.INVALID_FLOW_DEFINITION
    send_http_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_rolls_back_step_result_when_failure_claim_lost(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = _FailureCasFailingWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        await session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .values(delivery_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS - 1)
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")

        async def _send_http_request(**kwargs):
            return httpx.Response(503, request=request)

        service.http_runtime.send_request = _send_http_request

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.claim_token,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status).where(FlowRuns.id == run.id)
            )
        ).scalar_one()
        result_payload = (
            await session.execute(
                sa.select(FlowStepResults.output_payload_json).where(
                    FlowStepResults.flow_run_id == run.id,
                    FlowStepResults.step_id == step.id,
                )
            )
        ).scalar_one()

    assert result.attempted_count == 1
    assert result.delivered_count == 0
    assert result.retry_scheduled_count == 0
    assert result.dead_lettered_count == 0
    assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert delivery_state.claim_token is not None
    assert run_state == FlowRunStatus.RUNNING.value
    assert result_payload == {"text": "done"}


@pytest.mark.parametrize(
    ("error_code", "message", "expected_retry", "expected_dead_letter"),
    [
        ("typed_io_http_ssrf_blocked", "HTTP URL blocked by SSRF policy.", 0, 1),
        ("typed_io_http_invalid_url", "HTTP URL is not valid.", 0, 1),
        (
            "typed_io_http_connection_error",
            "Unable to resolve HTTP host 'hook.example.test'.",
            1,
            0,
        ),
    ],
)
@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_does_not_retry_a_destination_the_sender_refuses(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    error_code: str,
    message: str,
    expected_retry: int,
    expected_dead_letter: int,
):
    # A refused destination (policy or URL) is refused the same way on every
    # attempt, so it is dead-lettered on the first; a name that did not resolve
    # may resolve later and is retried.
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        service.http_runtime.send_request = AsyncMock(
            side_effect=TypedIOValidationException(message, code=error_code)
        )

        now = datetime.now(timezone.utc)
        result = await service.deliver_due(now=now)
        repeated = await service.deliver_due(now=now + timedelta(seconds=1))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_status = await session.scalar(
            sa.select(FlowRuns.status).where(FlowRuns.id == run.id)
        )

    assert result.attempted_count == 1
    assert result.retry_scheduled_count == expected_retry
    assert result.dead_lettered_count == expected_dead_letter
    if expected_dead_letter:
        assert repeated.attempted_count == 0
        assert delivery_state.delivery_attempts == 1
        assert (
            delivery_state.delivery_status
            == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
        )
        assert run_status == FlowRunStatus.FAILED.value
    else:
        assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
        assert run_status == FlowRunStatus.RUNNING.value


@pytest.mark.parametrize(
    ("status_code", "expected_retry", "expected_dead_letter"),
    # A redirect is never followed; it retries, since it can be temporary.
    [(302, 1, 0), (308, 1, 0), (408, 1, 0), (429, 1, 0), (422, 0, 1)],
)
@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_applies_http_status_retry_policy(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    status_code: int,
    expected_retry: int,
    expected_dead_letter: int,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")
        service.http_runtime.send_request = AsyncMock(
            return_value=httpx.Response(status_code, request=request)
        )

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_status = await session.scalar(
            sa.select(FlowRuns.status).where(FlowRuns.id == run.id)
        )

    assert result.retry_scheduled_count == expected_retry
    assert result.dead_lettered_count == expected_dead_letter
    assert delivery_state.delivery_attempts == 1
    if expected_dead_letter:
        assert (
            delivery_state.delivery_status
            == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
        )
        assert run_status == FlowRunStatus.FAILED.value
    else:
        assert delivery_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
        assert run_status == FlowRunStatus.RUNNING.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_five_claims_then_converges_without_sixth_post(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = _FailureCasFailingOnceWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")
        send_http_request = AsyncMock(return_value=httpx.Response(503, request=request))
        service.http_runtime.send_request = send_http_request
        now = datetime.now(timezone.utc)

        for delivery_attempt in range(1, FLOW_WEBHOOK_MAX_ATTEMPTS + 1):
            if delivery_attempt == FLOW_WEBHOOK_MAX_ATTEMPTS:
                webhook_repo.fail_next_failure = True
            result = await service.deliver_due(now=now)
            assert result.attempted_count == 1
            now += timedelta(seconds=2_000)

        attempts_after_lost_outcome = await session.scalar(
            sa.select(FlowRunWebhookDeliveries.delivery_attempts).where(
                FlowRunWebhookDeliveries.id == delivery_id
            )
        )
        converged = await service.deliver_due(now=now)
        recorded_by = datetime.now(timezone.utc)
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                    FlowRunWebhookDeliveries.delivery_last_error,
                    FlowRunWebhookDeliveries.dead_lettered_at,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.error_json).where(
                    FlowRuns.id == run.id
                )
            )
        ).one()

    assert attempts_after_lost_outcome == FLOW_WEBHOOK_MAX_ATTEMPTS
    assert send_http_request.await_count == FLOW_WEBHOOK_MAX_ATTEMPTS
    assert converged.attempted_count == 0
    assert converged.dead_lettered_count == 1
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == FLOW_WEBHOOK_MAX_ATTEMPTS
    # Recorded when it happened, not at the (here future) claim time.
    assert delivery_state.dead_lettered_at <= recorded_by
    assert "outcome is unknown" in delivery_state.delivery_last_error
    assert "may have been delivered" in delivery_state.delivery_last_error
    assert run_state.status == FlowRunStatus.FAILED.value
    run_error = FlowRunError.model_validate(run_state.error_json)
    assert "may have been delivered" in run_error.message


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_redacts_url_secrets_from_persisted_error(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")
        service.http_runtime.send_request = AsyncMock(
            side_effect=httpx.ConnectError(
                "POST https://user:pass@example.org/hook?token=secret-value failed; "
                "X-Partner-Proof: dummy-credential-outside-url",
                request=request,
            )
        )

        result = await service.deliver_due(now=datetime.now(timezone.utc))
        persisted_error = await session.scalar(
            sa.select(FlowRunWebhookDeliveries.delivery_last_error).where(
                FlowRunWebhookDeliveries.id == delivery_id
            )
        )

    assert result.retry_scheduled_count == 1
    assert persisted_error is not None
    assert "user:pass" not in persisted_error
    assert "secret-value" not in persisted_error
    assert "dummy-credential-outside-url" not in persisted_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_outbox_reaches_but_never_exceeds_invocation_concurrency(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
):
    """One task invocation runs at most FLOW_WEBHOOK_DELIVERY_CONCURRENCY sends.

    The cron's fixed job id runs one invocation at a time, so this is the
    ceiling a webhook receiver sees; it has to be observed rather than assumed.
    Claiming more rows than the ceiling is what makes the observation
    meaningful.
    """
    from eneo.flows.runtime import tasks as tasks_module

    row_count = FLOW_WEBHOOK_DELIVERY_CONCURRENCY + 2
    async with sessionmanager.session() as setup_session:
        enable_autobegin_for_flow_task_session(setup_session)
        for row_no in range(row_count):
            flow, run, step = await _create_running_webhook_run(
                session=setup_session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                model_name=f"webhook-ceiling-model-{row_no}",
            )
            assert flow.id is not None and step.id is not None
            await FlowRunWebhookDeliveryRepository(
                session=setup_session
            ).insert_pending_delivery(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                intent=_intent(run_id=run.id, step_id=step.id),
            )
        await setup_session.commit()

    in_flight = 0
    peak_in_flight = 0
    sent_idempotency_keys: list[str] = []
    ceiling_reached = asyncio.Event()

    async def _send_http_request(_self, *, headers, **_kwargs):
        nonlocal in_flight, peak_in_flight
        sent_idempotency_keys.append(headers["Idempotency-Key"])
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        if in_flight >= FLOW_WEBHOOK_DELIVERY_CONCURRENCY:
            ceiling_reached.set()
        try:
            # Hold every send until a full cohort is simultaneously in flight,
            # so the peak is observed and not a scheduling accident.
            await asyncio.wait_for(ceiling_reached.wait(), timeout=30)
        finally:
            in_flight -= 1
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.org/hook/case-123"),
        )

    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _send_http_request)

    result = await tasks_module._deliver_flow_webhook_outbox(
        budget=webhook_policy.flow_webhook_delivery_budget(), limit=row_count
    )

    assert peak_in_flight == FLOW_WEBHOOK_DELIVERY_CONCURRENCY
    assert in_flight == 0
    assert result["attempted"] == row_count
    assert result["delivered"] == row_count
    # No duplicate while a claim is valid: one send per claim, and the counts
    # above cannot detect a second send inside one attempt.
    assert len(sent_idempotency_keys) == row_count
    assert len(set(sent_idempotency_keys)) == row_count


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_claim_replaces_only_after_expiry_and_voids_stale_token(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """The claim token is the whole overlap contract, against the real predicates.

    Four phases: no competing claim while a claim is valid; reclaim after it
    expires; the new claimant's outcome persists; the displaced claimant can
    write nothing. Sibling tests force the CAS result through repository
    doubles, so the SQL predicates themselves are otherwise unproven.
    """
    async with sessionmanager.session() as setup_session:
        enable_autobegin_for_flow_task_session(setup_session)
        flow, run, step = await _create_running_webhook_run(
            session=setup_session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            model_name="webhook-claim-replacement-model",
        )
        assert flow.id is not None and step.id is not None
        delivery_id = await FlowRunWebhookDeliveryRepository(
            session=setup_session
        ).insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        await setup_session.commit()

    now = datetime.now(timezone.utc)

    async def _claim() -> list[FlowRunWebhookDeliveryRow]:
        async with sessionmanager.session() as claim_session:
            enable_autobegin_for_flow_task_session(claim_session)
            rows = await FlowRunWebhookDeliveryRepository(
                session=claim_session
            ).claim_due_delivery_rows(
                now=now,
                limit=5,
                claim_ttl_seconds=(
                    webhook_policy.flow_webhook_delivery_budget().claim_ttl_seconds
                ),
                max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
            )
            await claim_session.commit()
            return rows

    displaced_rows = await _claim()
    assert [row.id for row in displaced_rows] == [delivery_id]
    displaced = displaced_rows[0]

    # Phase 1: the claim is valid, so nothing else may take it.
    assert await _claim() == []

    # Phase 2: expire the claim, then a second deliverer may take it.
    async with sessionmanager.session() as expiry_session:
        enable_autobegin_for_flow_task_session(expiry_session)
        await expiry_session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .values(claim_expires_at=now - timedelta(seconds=1))
        )
        await expiry_session.commit()

    current_rows = await _claim()
    assert [row.id for row in current_rows] == [delivery_id]
    current = current_rows[0]
    assert current.claim_token != displaced.claim_token
    assert current.delivery_attempts == displaced.delivery_attempts + 1
    # Redelivery keeps the sender-side key receivers deduplicate on.
    assert current.idempotency_key == displaced.idempotency_key

    # Phase 3: the displaced deliverer returns while the row is STILL PENDING
    # and the replacement claim is outstanding. Only the claim-token predicate
    # can reject these writes here — after a terminal outcome the status
    # predicate would reject them on its own, and the test would pass with the
    # token guard deleted.
    async with sessionmanager.session() as stale_session:
        enable_autobegin_for_flow_task_session(stale_session)
        stale_repo = FlowRunWebhookDeliveryRepository(session=stale_session)
        assert (
            await stale_repo.mark_delivery_succeeded(
                delivery_id=delivery_id,
                claim_token=displaced.claim_token,
                delivered_at=now + timedelta(seconds=9),
            )
            is False
        )
        assert (
            await stale_repo.record_delivery_failure(
                delivery_id=delivery_id,
                claim_token=displaced.claim_token,
                error_message="late failure from the displaced deliverer",
                next_delivery_at=now + timedelta(seconds=30),
                dead_lettered_at=None,
            )
            is False
        )
        assert (
            await stale_repo.release_unsent_claim(
                delivery_id=delivery_id, claim_token=displaced.claim_token
            )
            is False
        )
        await stale_session.commit()

    async with sessionmanager.session() as intact_session:
        enable_autobegin_for_flow_task_session(intact_session)
        intact = (
            await intact_session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.claim_token,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
    assert intact.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert intact.claim_token == current.claim_token

    # Phase 4: the current claimant still owns the row and records the outcome.
    delivered_at = now + timedelta(seconds=5)
    async with sessionmanager.session() as outcome_session:
        enable_autobegin_for_flow_task_session(outcome_session)
        assert (
            await FlowRunWebhookDeliveryRepository(
                session=outcome_session
            ).mark_delivery_succeeded(
                delivery_id=delivery_id,
                claim_token=current.claim_token,
                delivered_at=delivered_at,
            )
            is True
        )
        await outcome_session.commit()

    async with sessionmanager.session() as check_session:
        enable_autobegin_for_flow_task_session(check_session)
        stored = (
            await check_session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivered_at,
                    FlowRunWebhookDeliveries.delivery_last_error,
                    FlowRunWebhookDeliveries.claim_token,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()

    assert stored.delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
    assert stored.delivered_at == delivered_at
    assert stored.delivery_last_error is None
    assert stored.claim_token is None


async def _insert_due_webhook_rows(
    *,
    row_count: int,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
) -> list[UUID]:
    delivery_ids: list[UUID] = []
    async with sessionmanager.session() as setup_session:
        enable_autobegin_for_flow_task_session(setup_session)
        for row_no in range(row_count):
            flow, run, step = await _create_running_webhook_run(
                session=setup_session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                model_name=f"webhook-budget-model-{row_no}",
            )
            assert flow.id is not None and step.id is not None
            delivery_ids.append(
                await FlowRunWebhookDeliveryRepository(
                    session=setup_session
                ).insert_pending_delivery(
                    flow_id=flow.id,
                    tenant_id=admin_user.tenant_id,
                    intent=_intent(run_id=run.id, step_id=step.id),
                )
            )
        await setup_session.commit()
    return delivery_ids


async def _delivery_states(delivery_ids: list[UUID]) -> dict[UUID, sa.Row]:
    async with sessionmanager.session() as check_session:
        async with check_session.begin():
            rows = (
                await check_session.execute(
                    sa.select(
                        FlowRunWebhookDeliveries.id,
                        FlowRunWebhookDeliveries.flow_run_id,
                        FlowRunWebhookDeliveries.delivery_status,
                        FlowRunWebhookDeliveries.delivery_attempts,
                        FlowRunWebhookDeliveries.claim_token,
                        FlowRunWebhookDeliveries.next_delivery_at,
                        FlowRunWebhookDeliveries.delivery_last_error,
                    ).where(FlowRunWebhookDeliveries.id.in_(delivery_ids))
                )
            ).all()
    return {row.id: row for row in rows}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_release_returns_the_claimed_attempt_and_frees_the_row(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """Kills: a released row keeps its claim, or keeps the attempt it was
    charged at claim although nothing was sent."""
    [delivery_id] = await _insert_due_webhook_rows(
        row_count=1,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    due_at = (await _delivery_states([delivery_id]))[delivery_id].next_delivery_at
    now = datetime.now(timezone.utc)
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        [claimed] = await webhook_repo.claim_due_delivery_rows(
            now=now,
            limit=1,
            claim_ttl_seconds=120,
            max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
        )
        released = await webhook_repo.release_unsent_claim(
            delivery_id=delivery_id, claim_token=claimed.claim_token
        )
        await session.commit()
    released_state = (await _delivery_states([delivery_id]))[delivery_id]

    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        reclaimed = await FlowRunWebhookDeliveryRepository(
            session=session
        ).claim_due_delivery_rows(
            now=now,
            limit=1,
            claim_ttl_seconds=120,
            max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
        )
        await session.commit()

    assert claimed.delivery_attempts == 1
    assert released is True
    assert released_state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert released_state.delivery_attempts == 0
    assert released_state.claim_token is None
    assert released_state.next_delivery_at == due_at
    assert [row.delivery_attempts for row in reclaimed] == [1]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_delivery_releases_a_row_whose_preparation_outlasts_the_send_deadline(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
):
    """Kills: a claim made after the deadline stopped covering a whole delivery;
    an unsent row that loses an attempt when the job deadline fires during its
    preparation (here inside a database query); and a preparation that runs
    past the job deadline."""
    from eneo.flows.application import flow_webhook_delivery_policy as policy

    [delivery_id] = await _insert_due_webhook_rows(
        row_count=1,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    send_http_request = AsyncMock()
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", send_http_request)
    budget = policy.FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=0.1,
        preparation_margin_seconds=0.1,
        persistence_margin_seconds=0.1,
        finish_margin_seconds=0.1,
        cancel_margin_seconds=0.1,
        claim_window_seconds=0.1,
    )
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        service = container.flow_run_webhook_delivery_service()
        prepare = service._prepare_delivery_payload

        async def _slow_prepare(**kwargs):
            await session.execute(sa.text("SELECT pg_sleep(5)"))
            return await prepare(**kwargs)

        monkeypatch.setattr(service, "_prepare_delivery_payload", _slow_prepare)
        loop = asyncio.get_running_loop()
        spent = budget.deadline(started_at=loop.time() - budget.job_deadline_seconds)
        async with session.begin():
            refused = await service.claim_due_batch(
                now=datetime.now(timezone.utc), limit=1, deadline=spent
            )
        assert refused.claimed_rows == []
        deadline = budget.deadline(started_at=loop.time())
        async with session.begin():
            batch = await service.claim_due_batch(
                now=datetime.now(timezone.utc), limit=1, deadline=deadline
            )
        [row] = batch.claimed_rows
        result = await asyncio.wait_for(
            service.deliver_claimed(row=row, deadline=deadline),
            timeout=budget.job_timeout_seconds,
        )

    state = (await _delivery_states([delivery_id]))[delivery_id]
    assert result.to_task_payload()["released"] == 1
    assert result.attempted_count == 0
    send_http_request.assert_not_awaited()
    assert state.delivery_attempts == 0
    assert state.claim_token is None
    assert state.delivery_status == FlowOutboxDeliveryStatus.PENDING.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_outbox_job_claims_only_what_its_deadline_can_send(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
):
    """A receiver that never answers, with more due rows than one wave, and a
    claim on its last attempt that expires while the wave is out.

    Kills: a wave claimed without the budget (rows beyond the first wave are
    claimed and must be handed back); a send not bounded by the send deadline
    (it runs into the time kept to record it); a cut send that is not the
    typed timeout failure; a claim session opened after the last wave (it
    dead-letters the expired claim after the sends ended); a backoff counted
    from the batch start instead of the failure."""
    from eneo.flows.application import flow_webhook_delivery_policy as policy
    from eneo.flows.runtime import tasks as tasks_module

    *delivery_ids, last_attempt_id = await _insert_due_webhook_rows(
        row_count=FLOW_WEBHOOK_DELIVERY_CONCURRENCY + 3,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    send_stopped_at: list[datetime] = []

    async def _unanswered_send(_self, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            send_stopped_at.append(datetime.now(timezone.utc))

    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _unanswered_send)
    # The sends end 1.5 s after the start; the margins after them only bound
    # the test, they are not waited for.
    budget = policy.FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=0.1,
        preparation_margin_seconds=1.2,
        persistence_margin_seconds=2.0,
        finish_margin_seconds=2.0,
        claim_window_seconds=0.2,
    )
    sends_end_after = timedelta(
        seconds=budget.job_deadline_seconds - budget.persistence_margin_seconds
    )
    started_at = datetime.now(timezone.utc)
    async with sessionmanager.session() as session:
        async with session.begin():
            # Held by another job; it expires halfway to the end of the sends.
            await session.execute(
                sa.update(FlowRunWebhookDeliveries)
                .where(FlowRunWebhookDeliveries.id == last_attempt_id)
                .values(
                    delivery_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
                    claim_token=uuid4(),
                    claimed_at=started_at,
                    claim_expires_at=started_at + sends_end_after / 2,
                )
            )

    result = await asyncio.wait_for(
        tasks_module._deliver_flow_webhook_outbox(budget=budget),
        timeout=budget.job_timeout_seconds,
    )

    states = await _delivery_states(delivery_ids)
    last_attempt = (await _delivery_states([last_attempt_id]))[last_attempt_id]
    sent = [state for state in states.values() if state.delivery_attempts == 1]
    unsent = [state for state in states.values() if state.delivery_attempts == 0]
    # One wave only. A row of it whose preparation outlasted the deadline on a
    # busy host is released, not charged.
    assert result["attempted"] + result["released"] == (
        FLOW_WEBHOOK_DELIVERY_CONCURRENCY
    )
    assert result["attempted"] >= 1
    assert result["retry_scheduled"] == result["attempted"]
    assert result["dead_lettered"] == 0
    assert last_attempt.delivery_status == FlowOutboxDeliveryStatus.PENDING.value
    assert len(send_stopped_at) == len(sent) == result["attempted"]
    # Half the persistence margin absorbs a late timer on a busy host.
    assert max(send_stopped_at) - started_at <= sends_end_after + timedelta(
        seconds=budget.persistence_margin_seconds / 2
    )
    assert all("timed out" in state.delivery_last_error for state in sent)
    assert len(sent) + len(unsent) == len(delivery_ids)
    assert all(state.claim_token is None for state in states.values())
    first_backoff = timedelta(seconds=policy.FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS[0])
    assert all(
        state.next_delivery_at is not None
        and state.next_delivery_at >= min(send_stopped_at) + first_backoff
        for state in sent
    )


def _capture_logs(monkeypatch, caplog, logger: logging.Logger) -> None:
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "handlers", [caplog.handler])


async def _answer_200(_self, **_kwargs):
    return httpx.Response(
        200, request=httpx.Request("POST", "https://example.org/hook/case-123")
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_outbox_records_a_200_whose_audit_never_returns(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
    caplog,
):
    """Kills: an outbound audit with no bound (the hard stop then cuts the
    delivery and the 200 is sent again later), and an audit cut that turns the
    known HTTP result into a delivery failure."""
    from eneo.audit.application.audit_service import AuditService
    from eneo.flows.runtime import flow_webhook_delivery as flow_webhook_delivery_module
    from eneo.flows.runtime import tasks as tasks_module

    [delivery_id] = await _insert_due_webhook_rows(
        row_count=1,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    audit_entered = asyncio.Event()

    async def _audit_that_never_returns(_self, **_kwargs):
        audit_entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(AuditService, "log_async", _audit_that_never_returns)
    monkeypatch.setattr(FlowHttpRuntimeHelper, "send_request", _answer_200)
    _capture_logs(monkeypatch, caplog, flow_webhook_delivery_module.logger)
    budget = webhook_policy.FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=0.2,
        preparation_margin_seconds=1.0,
        persistence_margin_seconds=0.3,
        finish_margin_seconds=0.5,
        cancel_margin_seconds=1.0,
        claim_window_seconds=0.1,
    )
    loop = asyncio.get_running_loop()
    started_at = loop.time()

    result = await asyncio.wait_for(
        tasks_module._deliver_flow_webhook_outbox(budget=budget),
        timeout=budget.job_timeout_seconds,
    )

    state = (await _delivery_states([delivery_id]))[delivery_id]
    assert audit_entered.is_set()
    assert loop.time() - started_at < budget.hard_stop_seconds
    assert (result["status"], result["delivered"]) == ("ok", 1)
    assert state.delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
    assert [
        record.levelno
        for record in caplog.records
        if record.exc_info is not None and record.exc_info[0] is TimeoutError
    ] == [logging.WARNING]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_outbox_keeps_the_claim_when_recording_blocks_to_the_hard_stop(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    monkeypatch,
    caplog,
):
    """A 200 whose outcome cannot be recorded: another session holds the
    delivery row's lock.

    Kills: recording with no bound (the job runs on until ARQ cancels it), and
    a cut delivery or a cut job that is not logged."""
    from eneo.flows.runtime import tasks as tasks_module

    [delivery_id] = await _insert_due_webhook_rows(
        row_count=1,
        admin_user=admin_user,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
    )
    send_started = asyncio.Event()
    lock_held = asyncio.Event()
    release_lock = asyncio.Event()

    async def _hold_the_row_lock() -> None:
        await send_started.wait()
        async with sessionmanager.session() as lock_session, lock_session.begin():
            await lock_session.execute(
                sa.select(FlowRunWebhookDeliveries.id)
                .where(FlowRunWebhookDeliveries.id == delivery_id)
                .with_for_update()
            )
            lock_held.set()
            await release_lock.wait()

    async def _send_once_the_row_is_locked(_self, **kwargs):
        send_started.set()
        await lock_held.wait()
        return await _answer_200(_self, **kwargs)

    monkeypatch.setattr(
        FlowHttpRuntimeHelper, "send_request", _send_once_the_row_is_locked
    )
    _capture_logs(monkeypatch, caplog, tasks_module.logger)
    budget = webhook_policy.FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=0.2,
        preparation_margin_seconds=1.0,
        persistence_margin_seconds=0.3,
        finish_margin_seconds=0.3,
        cancel_margin_seconds=1.0,
        claim_window_seconds=0.1,
    )
    loop = asyncio.get_running_loop()
    lock_holder = asyncio.create_task(_hold_the_row_lock())
    started_at = loop.time()
    try:
        result = await asyncio.wait_for(
            tasks_module._deliver_flow_webhook_outbox(budget=budget),
            timeout=budget.job_timeout_seconds,
        )
        returned_after = loop.time() - started_at
    finally:
        release_lock.set()
        # A job that ends before its send (for example a released row) never
        # wakes the helper; cancel it so the job's own failure is reported
        # instead of a hang.
        if not send_started.is_set():
            lock_holder.cancel()
        await asyncio.gather(lock_holder, return_exceptions=True)

    state = (await _delivery_states([delivery_id]))[delivery_id]
    assert budget.hard_stop_seconds <= returned_after < budget.job_timeout_seconds
    assert (result["status"], result["unfinished"], result["delivered"]) == (
        "hard_stopped",
        1,
        0,
    )
    assert state.claim_token is not None
    assert state.delivery_attempts == 1
    assert state.delivery_status != FlowOutboxDeliveryStatus.DELIVERED.value
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert [
        (getattr(record, "delivery_id", None), getattr(record, "flow_run_id", None))
        for record in errors
    ] == [(str(delivery_id), str(state.flow_run_id)), (None, None)]
    assert getattr(errors[1], "unfinished", None) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_webhook_outbox_cuts_a_blocked_claim_session_at_the_hard_stop(
    setup_database,
    monkeypatch,
):
    """Kills: claim sessions that run outside the hard stop."""
    from eneo.flows.runtime import tasks as tasks_module

    async def _blocked_dead_letter_lock(self, **_kwargs):
        await self.session.execute(sa.text("SELECT pg_sleep(30)"))
        return []

    monkeypatch.setattr(
        FlowRunWebhookDeliveryRepository,
        "lock_expired_at_budget_delivery_rows",
        _blocked_dead_letter_lock,
    )
    budget = webhook_policy.FlowWebhookDeliveryBudget(
        max_request_timeout_seconds=0.1,
        preparation_margin_seconds=0.1,
        persistence_margin_seconds=0.1,
        finish_margin_seconds=0.1,
        cancel_margin_seconds=1.0,
        claim_window_seconds=0.1,
    )
    loop = asyncio.get_running_loop()
    started_at = loop.time()

    result = await asyncio.wait_for(
        tasks_module._deliver_flow_webhook_outbox(budget=budget),
        timeout=budget.job_timeout_seconds,
    )

    assert loop.time() - started_at < budget.job_timeout_seconds
    assert (result["status"], result["attempted"], result["unfinished"]) == (
        "hard_stopped",
        0,
        0,
    )


@pytest.mark.parametrize(
    "url_template",
    [
        "http://127.0.0.1:{port}/hook",
        "http://localhost:{port}/hook",
        "http://[::ffff:127.0.0.1]:{port}/hook",
        "http://2130706433:{port}/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fd00:ec2::254]/latest/meta-data/",
    ],
)
async def test_flow_webhook_delivery_refuses_internal_destinations_without_connecting(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    url_template: str,
):
    # The real sender, with its destination policy, is the one the outbox job
    # uses: a loopback, metadata or IPv4-mapped destination in any spelling is
    # refused before a connection exists, and refused once, not retried.
    async with recording_server() as internal:
        async with sessionmanager.session() as session:
            enable_autobegin_for_flow_task_session(session)
            container = Container(
                session=providers.Object(session),
                user=providers.Object(admin_user),
            )
            flow, run, step = await _create_running_webhook_run(
                session=session,
                admin_user=admin_user,
                completion_model_factory=completion_model_factory,
                space_factory=space_factory,
                assistant_factory=assistant_factory,
                output_config={
                    "url": url_template.format(port=internal.port),
                    "auth": {"mode": "none"},
                    "timeout_seconds": 5,
                },
            )
            webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
            delivery_id = await webhook_repo.insert_pending_delivery(
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                intent=_intent(run_id=run.id, step_id=step.id),
            )
            service = _delivery_service(
                session=session,
                container=container,
                webhook_repo=webhook_repo,
            )

            now = datetime.now(timezone.utc)
            result = await service.deliver_due(now=now)
            repeated = await service.deliver_due(now=now + timedelta(hours=1))
            delivery_state = (
                await session.execute(
                    sa.select(
                        FlowRunWebhookDeliveries.delivery_status,
                        FlowRunWebhookDeliveries.delivery_attempts,
                    ).where(FlowRunWebhookDeliveries.id == delivery_id)
                )
            ).one()
            run_state = (
                await session.execute(
                    sa.select(FlowRuns.status, FlowRuns.error_json).where(
                        FlowRuns.id == run.id
                    )
                )
            ).one()

        assert internal.connections == 0
        assert bytes(internal.received) == b""

    assert (result.attempted_count, result.dead_lettered_count) == (1, 1)
    assert result.retry_scheduled_count == 0
    assert repeated.attempted_count == 0
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == 1
    assert run_state.status == FlowRunStatus.FAILED.value
    assert (
        FlowRunError.model_validate(run_state.error_json).code
        == FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED
    )


class _RunServiceARefusedRetryNeverUses:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"A refused retry reached the run service: {name}")


@pytest.mark.parametrize(
    "lost_answer",
    [
        httpx.ReadTimeout("no answer after the request was sent"),
        httpx.RemoteProtocolError("connection closed without a response"),
    ],
    ids=["timeout_after_send", "reset_after_send"],
)
async def test_a_webhook_whose_outcome_stays_unknown_is_reposted_only_under_its_key(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    test_tenant,
    object_content_runtime_ready,
    lost_answer: httpx.HTTPError,
):
    # A request that went out and lost its answer may have been received. The
    # outbox repeats it only under the same idempotency key, within the attempt
    # budget, and then stops. The failed run cannot be retried from its last
    # step: the delivering step completed, so a retry would only repeat the
    # same POST under a new key that the receiver cannot match.
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        sent_idempotency_keys: list[str] = []

        async def _send_http_request(**kwargs):
            sent_idempotency_keys.append(kwargs["headers"]["Idempotency-Key"])
            raise lost_answer

        service.http_runtime.send_request = _send_http_request
        now = datetime.now(timezone.utc)
        results = []
        for _ in range(FLOW_WEBHOOK_MAX_ATTEMPTS + 1):
            results.append(await service.deliver_due(now=now))
            now += timedelta(seconds=2_000)

        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivery_attempts,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_state = (
            await session.execute(
                sa.select(FlowRuns.status, FlowRuns.error_json).where(
                    FlowRuns.id == run.id
                )
            )
        ).one()
        step_state = (
            await session.execute(
                sa.select(
                    FlowStepResults.status,
                    FlowStepResults.current_attempt_no,
                    FlowStepResults.output_payload_json,
                ).where(
                    FlowStepResults.flow_run_id == run.id,
                    FlowStepResults.step_id == step.id,
                )
            )
        ).one()
        attempt_states = (
            await session.execute(
                sa.select(FlowStepAttempts.attempt_no, FlowStepAttempts.status).where(
                    FlowStepAttempts.flow_run_id == run.id,
                    FlowStepAttempts.step_id == step.id,
                )
            )
        ).all()
        await session.commit()

        retry_service = FlowRunRetryService(
            user=admin_user,
            run_service=cast(FlowRunService, _RunServiceARefusedRetryNeverUses()),
            access_policy=container.flow_run_access_policy(),
            run_repo=FlowRunRepository(session=session),
            flow_repo=FlowRepository(session=session),
            checkpoint_repo=container.flow_run_review_checkpoint_repo(),
            audit_service=container.audit_service(),
        )
        with pytest.raises(ConflictException) as refused:
            await retry_service.retry_from_failed_step(
                flow_id=flow.id,
                run_id=run.id,
                idempotency_key=f"retry-after-unknown-webhook:{uuid4()}",
            )
        run_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuns)
            .where(FlowRuns.flow_id == flow.id)
        )
        delivery_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.flow_id == flow.id)
        )

    assert [result.attempted_count for result in results] == [1] * 5 + [0]
    assert [result.retry_scheduled_count for result in results] == [1] * 4 + [0, 0]
    assert results[FLOW_WEBHOOK_MAX_ATTEMPTS - 1].dead_lettered_count == 1
    assert len(sent_idempotency_keys) == FLOW_WEBHOOK_MAX_ATTEMPTS
    assert set(sent_idempotency_keys) == {
        hashlib.sha256(f"{run.id}:{step.id}:1:webhook".encode()).hexdigest()
    }
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivery_attempts == FLOW_WEBHOOK_MAX_ATTEMPTS
    assert run_state.status == FlowRunStatus.FAILED.value
    assert (
        FlowRunError.model_validate(run_state.error_json).code
        == FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED
    )
    # The delivering step keeps its completed attempt and its output.
    assert step_state.status == FlowStepResultStatus.COMPLETED.value
    assert step_state.current_attempt_no == 1
    assert step_state.output_payload_json == {"text": "done"}
    assert attempt_states == [(1, FlowStepAttemptStatus.COMPLETED.value)]
    assert refused.value.code == FlowApiErrorCode.RUN_RETRY_PREFIX_UNSUPPORTED.value
    assert refused.value.context == {"step_order": 1, "reason": "no_unfinished_step"}
    assert run_count == 1
    assert delivery_count == 1


async def test_a_run_cancelled_while_its_webhook_is_in_flight_is_not_reposted(
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    # The POST that was in flight when the run was cancelled is not recorded
    # as delivered, and the expired claim it leaves behind ends the delivery
    # without a second request.
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
        )
        flow, run, step = await _create_running_webhook_run(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        webhook_repo = FlowRunWebhookDeliveryRepository(session=session)
        delivery_id = await webhook_repo.insert_pending_delivery(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            intent=_intent(run_id=run.id, step_id=step.id),
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")
        sends = 0

        async def _cancel_during_send(**_kwargs):
            nonlocal sends
            sends += 1
            async with sessionmanager.session() as other, other.begin():
                other_run_repo = FlowRunRepository(session=other)
                audit_outbox_repo = FlowRunAuditOutboxRepository(session=other)
                cancelled = await FlowRunTerminalizer(
                    other_run_repo,
                    audit_outbox_repo,
                    FlowRunReviewCheckpointRepository(
                        session=other, audit_outbox_repo=audit_outbox_repo
                    ),
                ).terminalize_run(
                    run_id=run.id,
                    tenant_id=admin_user.tenant_id,
                    target_status=FlowRunStatus.CANCELLED,
                    source=FlowRunLifecycleSource.USER_CANCEL,
                    error=FlowRunError.from_source(
                        FlowRunLifecycleSource.USER_CANCEL,
                        code=FlowApiErrorCode.RUN_USER_CANCELLED,
                        message="Run cancelled by user.",
                    ),
                    cancelled_at=datetime.now(timezone.utc),
                )
                assert cancelled.did_transition
            return httpx.Response(200, request=request)

        service.http_runtime.send_request = _cancel_during_send
        now = datetime.now(timezone.utc)
        in_flight = await service.deliver_due(now=now)
        after_claim_expiry = await service.deliver_due(
            now=now
            + timedelta(
                seconds=webhook_policy.flow_webhook_delivery_budget().claim_ttl_seconds
                + 1
            )
        )
        later = await service.deliver_due(now=now + timedelta(hours=2))
        delivery_state = (
            await session.execute(
                sa.select(
                    FlowRunWebhookDeliveries.delivery_status,
                    FlowRunWebhookDeliveries.delivered_at,
                ).where(FlowRunWebhookDeliveries.id == delivery_id)
            )
        ).one()
        run_status = await session.scalar(
            sa.select(FlowRuns.status).where(FlowRuns.id == run.id)
        )

    assert sends == 1
    assert (in_flight.attempted_count, in_flight.delivered_count) == (1, 0)
    assert after_claim_expiry.dead_lettered_count == 1
    assert later.attempted_count == 0
    assert (
        delivery_state.delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
    )
    assert delivery_state.delivered_at is None
    assert run_status == FlowRunStatus.CANCELLED.value

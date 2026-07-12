from __future__ import annotations

from datetime import datetime, timezone
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
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_MAX_ATTEMPTS,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepResultStatus,
)
from eneo.flows.enums import FlowRunLifecycleSource, FlowStepAttemptStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_factory import FlowFactory
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import (
    build_published_definition_json,
    published_definition_checksum,
)
from eneo.flows.runtime.flow_webhook_delivery import FlowRunWebhookDeliveryService
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.step_execution_result import (
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.container.container import Container


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
    output_config: dict[str, object] | None = None,
) -> Flow:
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
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Send webhook",
                input_source="flow_input",
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
        ],
    )


async def _create_running_webhook_run(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    output_config: dict[str, object] | None = None,
):
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Webhook outbox delivery space", [model.id])
    assistant = await assistant_factory(
        session,
        "Webhook Outbox Delivery Assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session, factory=FlowFactory())
    version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
            output_config=output_config,
        ),
        tenant_id=admin_user.tenant_id,
    )
    assert flow.id is not None
    step = flow.steps[0]
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
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": 1,
                    "user_description": step.user_description,
                    "input_source": step.input_source,
                    "input_type": step.input_type,
                    "input_bindings": step.input_bindings,
                    "output_mode": step.output_mode,
                    "output_type": step.output_type,
                    "output_config": step.output_config,
                }
            ],
        ),
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    run_repo = FlowRunRepository(session=session, factory=FlowFactory())
    run = await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"question": "What happened?", "case_id": "case-123"},
        preseed_steps=[
            {
                "step_id": step.id,
                "assistant_id": step.assistant_id,
                "step_order": 1,
            }
        ],
    )
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == run.id)
        .values(
            status=FlowRunStatus.RUNNING.value,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    await run_repo.create_or_get_attempt_started(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        step_id=step.id,
        step_order=step.step_order,
        attempt_no=1,
        celery_task_id="webhook-outbox-fixture",
    )
    pending_result = await run_repo.get_step_result(
        run_id=run.id,
        step_id=step.id,
        tenant_id=admin_user.tenant_id,
    )
    assert pending_result is not None
    completed_result = pending_result.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "current_attempt_no": 1,
            "input_payload_json": {"text": "hello"},
            "output_payload_json": {"text": "done"},
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
        step_id=step.id,
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


def _intent(*, run_id: UUID, step_id: UUID) -> WebhookDeliveryIntent:
    return WebhookDeliveryIntent(
        flow_run_id=run_id,
        step_id=step_id,
        step_order=1,
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


def _delivery_service(
    *,
    session,
    container: Container,
    webhook_repo: FlowRunWebhookDeliveryRepository,
    audit_service=None,
    encryption_service=None,
) -> FlowRunWebhookDeliveryService:
    flow_run_repo = FlowRunRepository(session=session, factory=FlowFactory())
    audit_outbox_repo = FlowRunAuditOutboxRepository(session=session)
    review_checkpoint_repo = FlowRunReviewCheckpointRepository(
        session=session,
        factory=FlowFactory(),
        audit_outbox_repo=audit_outbox_repo,
    )
    return FlowRunWebhookDeliveryService(
        webhook_delivery_repo=webhook_repo,
        flow_repo=FlowRepository(session=session, factory=FlowFactory()),
        flow_run_repo=flow_run_repo,
        flow_version_repo=FlowVersionRepository(
            session=session,
            factory=FlowFactory(),
        ),
        flow_run_terminalizer=FlowRunTerminalizer(
            flow_run_repo,
            FlowRunRerunRepository(
                session=flow_run_repo.session,
                factory=flow_run_repo.factory,
            ),
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
            factory=FlowFactory(),
        ).list_stale_running_runs(
            tenant_id=admin_user.tenant_id,
            stale_before=datetime.now(timezone.utc),
        )
        claimed = await webhook_repo.claim_due_delivery_rows(
            now=datetime.now(timezone.utc),
            limit=10,
            claim_ttl_seconds=120,
        )
        second_claim = await webhook_repo.claim_due_delivery_rows(
            now=datetime.now(timezone.utc),
            limit=10,
            claim_ttl_seconds=120,
        )

    assert stale_runs == []
    assert [item.id for item in claimed] == [delivery_id]
    assert second_claim == []
    assert all(item.id != run.id for item in stale_runs)


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
        audit_service = type(
            "AuditServiceStub",
            (),
            {"log_async": AsyncMock(return_value=uuid4())},
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
            audit_service=audit_service,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")

        async def _send_http_request(**kwargs):
            async with sessionmanager.session() as check_session:
                enable_autobegin_for_flow_task_session(check_session)
                committed_claim_token = await check_session.scalar(
                    sa.select(FlowRunWebhookDeliveries.claim_token).where(
                        FlowRunWebhookDeliveries.id == delivery_id
                    )
                )
            assert committed_claim_token is not None
            assert kwargs["url"] == "https://example.org/hook/case-123"
            assert kwargs["body_bytes"] == b"done"
            assert len(kwargs["headers"]["Idempotency-Key"]) == 64
            return httpx.Response(200, request=request)

        service._send_http_request = _send_http_request

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
    audit_service.log_async.assert_awaited_once()
    assert audit_service.log_async.await_args.kwargs["outcome"] == Outcome.SUCCESS


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
        audit_service = type(
            "AuditServiceStub",
            (),
            {"log_async": AsyncMock(return_value=uuid4())},
        )
        service = _delivery_service(
            session=session,
            container=container,
            webhook_repo=webhook_repo,
            audit_service=audit_service,
        )
        request = httpx.Request("POST", "https://example.org/hook/case-123")

        async def _send_http_request(**kwargs):
            return httpx.Response(503, request=request)

        service._send_http_request = _send_http_request

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
    audit_service.log_async.assert_awaited_once()
    assert audit_service.log_async.await_args.kwargs["outcome"] == Outcome.FAILURE


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

        service._send_http_request = _send_http_request

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

        service._send_http_request = _send_http_request

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
        service._send_http_request = send_http_request

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
        service._send_http_request = send_http_request
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
        service._send_http_request = send_http_request
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

        service._send_http_request = _send_http_request

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

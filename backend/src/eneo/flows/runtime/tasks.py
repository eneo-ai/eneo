from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, assert_never
from uuid import UUID

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.flows.application.flow_dispatch import (
    FlowRunDispatchAccepted,
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_BATCH_SIZE,
    FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS,
    FLOW_WEBHOOK_DELIVERY_CONCURRENCY,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.flow_run_recovery_policy import (
    flow_stale_running_reconcile_after_seconds,
)
from eneo.flows.domain.mapped_execution_policy import (
    resolve_flow_mapped_execution_policy,
)
from eneo.flows.domain.provider_call import ProviderCallUnknownReason
from eneo.flows.domain.rag_evidence_policy import resolve_flow_rag_evidence_policy
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_document_limits import resolve_flow_document_render_limits
from eneo.flows.flow_input_limits import resolve_flow_input_limits
from eneo.flows.flow_run_dispatch_request import (
    FlowRunDispatchMalformedPayload,
    FlowRunServiceKeyDispatchRequest,
    FlowRunUserDispatchRequest,
    parse_flow_run_dispatch_task_kwargs,
)
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_runtime_policy import resolve_flow_runtime_policy
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRow,
)
from eneo.flows.runtime.diarizing_transcription import DiarizingFlowTranscriber
from eneo.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from eneo.flows.runtime.flow_run_actor import (
    FlowRunActor,
    FlowRunActorError,
    FlowRunServicePrincipalInactiveError,
)
from eneo.flows.runtime.flow_runtime_trace import FlowRunSpanContext, trace_flow_run
from eneo.flows.runtime.flow_webhook_delivery import FlowWebhookDeliveryResult
from eneo.flows.runtime.remote_transcription import build_remote_flow_transcriber
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.main.request_context import clear_request_context, set_request_context
from eneo.object_content.deployment_policy import load_upload_admission_snapshot
from eneo.object_content.runtime import object_content_runtime
from eneo.users.user_repo import UsersRepository

if TYPE_CHECKING:
    from eneo.files.transcriber import Transcriber
    from eneo.flows.runtime.transcription import FlowStepTranscriber

logger = get_logger(__name__)


def enable_autobegin_for_flow_task_session(session: AsyncSession) -> None:
    """Flow runtime uses commit-heavy repos; enable autobegin for this task session."""
    session.sync_session.autobegin = True


@contextmanager
def _flow_run_logging_context(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    run_trace_id: UUID,
    task_id: str | None,
) -> Generator[None]:
    context_values = {
        "flow.run.id": str(run_id),
        "flow.run.trace_id": str(run_trace_id),
        "flow.id": str(flow_id),
        "flow.tenant.id": str(tenant_id),
        "flow.task.id": task_id,
    }
    set_request_context(**context_values)
    try:
        yield
    finally:
        clear_request_context()


async def _resolve_flow_run_actor(
    *,
    container: Container,
    user_repo: UsersRepository,
    run: object,
    expected_principal_type: PrincipalType,
    expected_principal_user_id: UUID | None,
    expected_principal_service_id: UUID | None,
) -> FlowRunActor:
    raw_principal_type = getattr(run, "principal_type")
    run_principal_type = (
        raw_principal_type
        if isinstance(raw_principal_type, PrincipalType)
        else PrincipalType(str(raw_principal_type))
    )
    if run_principal_type != expected_principal_type:
        raise FlowRunActorError("task principal type does not match run principal")

    if expected_principal_type == PrincipalType.USER:
        run_user_id = getattr(run, "principal_user_id", None)
        if run_user_id is None or run_user_id != expected_principal_user_id:
            raise FlowRunActorError("task user principal does not match run principal")
        user = await user_repo.get_user_by_id_and_tenant_id(
            id=run_user_id,
            tenant_id=getattr(run, "tenant_id"),
        )
        if user is None:
            raise FlowRunActorError("run user principal is missing")
        return FlowRunActor.from_user_run(run=run, user=user)

    run_service_id = getattr(run, "principal_service_id", None)
    if run_service_id is None or run_service_id != expected_principal_service_id:
        raise FlowRunActorError("task service principal does not match run principal")
    service_principal = await container.api_key_v2_repo().get_service_principal(
        service_principal_id=run_service_id,
        tenant_id=getattr(run, "tenant_id"),
    )
    if service_principal is None:
        raise FlowRunActorError("run service principal is missing")
    try:
        return FlowRunActor.from_service_principal_run(
            run=run,
            service_principal=service_principal,
        )
    except FlowRunServicePrincipalInactiveError:
        raise
    except ValueError as exc:
        raise FlowRunActorError(str(exc)) from exc


async def _terminalize_actor_resolution_failure(
    *,
    container: Container,
    session: AsyncSession,
    run_id: UUID,
    tenant_id: UUID,
    code: FlowApiErrorCode,
    message: str,
) -> None:
    await container.flow_run_terminalizer().terminalize_run(
        run_id=run_id,
        tenant_id=tenant_id,
        target_status=FlowRunStatus.FAILED,
        source=FlowRunLifecycleSource.MISSING_PRINCIPAL,
        error=FlowRunError.from_source(
            FlowRunLifecycleSource.MISSING_PRINCIPAL,
            code=code,
            message=message,
        ),
    )
    await session.commit()


async def _execute_flow_run_async(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    run_revision: int,
    principal_type: PrincipalType,
    principal_user_id: UUID | None,
    principal_service_id: UUID | None,
    task_id: str | None,
    retry_count: int,
) -> dict[str, str]:
    with trace_flow_run(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        task_id=task_id,
        retry_count=retry_count,
    ) as flow_span:
        return await _execute_flow_run_async_traced(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            run_revision=run_revision,
            principal_type=principal_type,
            principal_user_id=principal_user_id,
            principal_service_id=principal_service_id,
            task_id=task_id,
            retry_count=retry_count,
            flow_span=flow_span,
        )


async def _execute_flow_run_async_traced(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    run_revision: int,
    principal_type: PrincipalType,
    principal_user_id: UUID | None,
    principal_service_id: UUID | None,
    task_id: str | None,
    retry_count: int,
    flow_span: FlowRunSpanContext,
) -> dict[str, str]:
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        bootstrap_container = Container(session=providers.Object(session))
        user_repo = UsersRepository(session=session)
        tenant = await bootstrap_container.tenant_repo().get(tenant_id)
        if tenant is None:
            flow_span.set_result(status="failed", reason="tenant_not_found")
            raise RuntimeError("Flow execution task tenant not found.")
        runtime_container = Container(
            session=providers.Object(session),
            tenant=providers.Object(tenant),
        )

        flow_run_repo = runtime_container.flow_run_repo()
        run = await flow_run_repo.get(
            run_id=run_id,
            tenant_id=tenant_id,
            flow_id=flow_id,
        )
        flow_span.set_run_trace_id(run.trace_id)
        with _flow_run_logging_context(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            run_trace_id=run.trace_id,
            task_id=task_id,
        ):
            can_run = await flow_run_repo.mark_running_if_claimable(
                run_id=run_id,
                tenant_id=tenant_id,
                expected_revision=run_revision,
            )
            await session.commit()
            if not can_run:
                latest = await flow_run_repo.get(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    flow_id=flow_id,
                )
                result = {
                    "status": "skipped",
                    "reason": f"run_{latest.status.value}_or_revision_changed",
                }
                flow_span.set_result_from_mapping(result)
                return result

            try:
                run_actor = await _resolve_flow_run_actor(
                    container=runtime_container,
                    user_repo=user_repo,
                    run=run,
                    expected_principal_type=principal_type,
                    expected_principal_user_id=principal_user_id,
                    expected_principal_service_id=principal_service_id,
                )
            except FlowRunServicePrincipalInactiveError as exc:
                await _terminalize_actor_resolution_failure(
                    container=runtime_container,
                    session=session,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    code=FlowApiErrorCode.RUN_SERVICE_PRINCIPAL_DISABLED,
                    message=f"flow_service_principal_disabled: {exc}",
                )
                result = {"status": "failed", "reason": "service_principal_disabled"}
                flow_span.set_result_from_mapping(result)
                return result
            except FlowRunActorError as exc:
                await _terminalize_actor_resolution_failure(
                    container=runtime_container,
                    session=session,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    code=FlowApiErrorCode.RUN_RUNTIME_ACTOR_INVALID,
                    message=f"flow_runtime_actor_invalid: {exc}",
                )
                result = {"status": "failed", "reason": "runtime_actor_invalid"}
                flow_span.set_result_from_mapping(result)
                return result

            upload_admission = await load_upload_admission_snapshot(
                session,
                inline_maximum_bytes=object_content_runtime.inline_maximum_bytes,
                object_store_maximum_bytes=(
                    object_content_runtime.object_store_maximum_bytes
                ),
            )
            flow_limits = resolve_flow_input_limits(
                tenant.flow_settings,
                defaults=upload_admission,
            )
            document_render_limits = resolve_flow_document_render_limits(
                tenant.flow_settings
            )
            runtime_policy = resolve_flow_runtime_policy(tenant.flow_settings)
            mapped_execution_policy = resolve_flow_mapped_execution_policy(
                tenant.flow_settings
            )
            rag_evidence_policy = resolve_flow_rag_evidence_policy(tenant.flow_settings)
            runtime_file_service = runtime_container.file_service(
                user=None,
                owner=run_actor.principal.file_owner(tenant_id=tenant_id),
            )

            executor = FlowRunExecutor(
                runtime_actor=run_actor,
                session=session,
                flow_repo=runtime_container.flow_repo(),
                flow_run_repo=flow_run_repo,
                flow_run_review_checkpoint_repo=runtime_container.flow_run_review_checkpoint_repo(),
                flow_run_terminalizer=runtime_container.flow_run_terminalizer(),
                flow_version_repo=runtime_container.flow_version_repo(),
                space_repo=runtime_container.tenant_scoped_space_repo(),
                completion_service=runtime_container.completion_service(
                    user=run_actor.user
                ),
                file_repo=runtime_container.file_repo(),
                file_content_loader=runtime_container.file_content_loader(),
                file_service=runtime_file_service,
                template_asset_repo=runtime_container.flow_template_asset_repo(),
                encryption_service=runtime_container.encryption_service(),
                audit_service=runtime_container.audit_service(),
                references_service=runtime_container.references_service(),
                transcriber=_build_flow_transcriber(
                    runtime_container.transcriber(file_service=runtime_file_service)
                ),
                transcript_words_repo=runtime_container.flow_transcript_words_repo(),
                config=FlowRunExecutorConfig.from_settings(
                    max_inline_text_bytes=get_settings().flow_max_inline_text_bytes,
                    max_audio_files=flow_limits.audio_max_files_per_run,
                    max_generic_files=flow_limits.max_files_per_run,
                    document_render_limits=document_render_limits,
                    runtime_policy=runtime_policy,
                    mapped_execution_policy=mapped_execution_policy,
                    rag_evidence_policy=rag_evidence_policy,
                ),
            )
            result = await executor.execute_claimed(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                dispatch_task_id=task_id,
                retry_count=retry_count,
            )
            flow_span.set_result_from_mapping(result)
            return {key: str(value) for key, value in result.items()}


async def terminalize_flow_run_failure(
    *,
    run_id: UUID,
    tenant_id: UUID,
    source: FlowRunLifecycleSource,
    error: FlowRunError,
) -> None:
    async with sessionmanager.session() as session:
        async with session.begin():
            container = Container(session=providers.Object(session))
            terminalizer = container.flow_run_terminalizer()
            await terminalizer.terminalize_run(
                run_id=run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=source,
                error=error,
            )


async def _terminalize_flow_run_failure_from_task(
    *,
    run_id: UUID,
    tenant_id: UUID,
    task_id: str | None,
    source: FlowRunLifecycleSource,
    error: FlowRunError,
) -> None:
    try:
        async with asyncio.timeout(10):
            await terminalize_flow_run_failure(
                run_id=run_id,
                tenant_id=tenant_id,
                source=source,
                error=error,
            )
    except Exception:
        logger.exception(
            "Flow run task terminalization failed",
            extra={
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
                "task_id": task_id,
                "source": source.value,
            },
        )


async def execute_flow_run_task(
    *,
    run_id: str,
    flow_id: str,
    tenant_id: str,
    run_revision: int,
    principal_type: str | None = None,
    principal_user_id: str | None = None,
    principal_service_id: str | None = None,
    task_id: str | None,
    retry_count: int,
) -> dict[str, str]:
    logger.info(
        "Received flow execution task",
        extra={
            "task_id": task_id,
            "retries": retry_count,
            "run_id": run_id,
            "flow_id": flow_id,
            "tenant_id": tenant_id,
            "principal_type": principal_type,
            "principal_user_id": principal_user_id,
            "principal_service_id": principal_service_id,
        },
    )

    dispatch_request = parse_flow_run_dispatch_task_kwargs(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        run_revision=run_revision,
        principal_type=principal_type,
        principal_user_id=principal_user_id,
        principal_service_id=principal_service_id,
    )
    match dispatch_request:
        case FlowRunUserDispatchRequest() as user_dispatch:
            run_id_uuid = user_dispatch.run_id
            flow_id_uuid = user_dispatch.flow_id
            tenant_id_uuid = user_dispatch.tenant_id
            expected_run_revision = user_dispatch.run_revision
            resolved_principal_type = PrincipalType.USER
            resolved_principal_user_id = user_dispatch.principal_user_id
            resolved_principal_service_id = None
        case FlowRunServiceKeyDispatchRequest() as service_dispatch:
            run_id_uuid = service_dispatch.run_id
            flow_id_uuid = service_dispatch.flow_id
            tenant_id_uuid = service_dispatch.tenant_id
            expected_run_revision = service_dispatch.run_revision
            resolved_principal_type = PrincipalType.SERVICE_KEY
            resolved_principal_user_id = service_dispatch.principal_user_id
            resolved_principal_service_id = service_dispatch.principal_service_id
        case FlowRunDispatchMalformedPayload(reason=reason):
            logger.error(
                "Flow run execution task has malformed dispatch payload",
                extra={
                    "task_id": task_id,
                    "retries": retry_count,
                    "run_id": run_id,
                    "flow_id": flow_id,
                    "tenant_id": tenant_id,
                    "principal_type": principal_type,
                    "principal_user_id": principal_user_id,
                    "principal_service_id": principal_service_id,
                    "parse_reason": reason.value,
                },
            )
            return {"status": "failed", "reason": "invalid_dispatch_payload"}
        case _:
            assert_never(dispatch_request)

    try:
        async with asyncio.timeout(get_settings().task_execution_timeout_seconds):
            return await _execute_flow_run_async(
                run_id=run_id_uuid,
                flow_id=flow_id_uuid,
                tenant_id=tenant_id_uuid,
                run_revision=expected_run_revision,
                principal_type=resolved_principal_type,
                principal_user_id=resolved_principal_user_id,
                principal_service_id=resolved_principal_service_id,
                task_id=task_id,
                retry_count=retry_count,
            )
    except TimeoutError:
        error_message = (
            "flow_task_timeout: Flow execution timed out before task completion."
        )
        logger.exception(
            "Flow execution task timed out",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        await _terminalize_flow_run_failure_from_task(
            run_id=run_id_uuid,
            tenant_id=tenant_id_uuid,
            task_id=task_id,
            source=FlowRunLifecycleSource.TASK_TIMEOUT,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.TASK_TIMEOUT,
                code=FlowApiErrorCode.RUN_TASK_TIMEOUT,
                message=error_message,
            ),
        )
        return {"status": "failed", "reason": "timeout"}
    except Exception:
        error_message = (
            "flow_task_failure: Flow execution task failed before run completion."
        )
        logger.exception(
            "Flow execution task failed",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        await _terminalize_flow_run_failure_from_task(
            run_id=run_id_uuid,
            tenant_id=tenant_id_uuid,
            task_id=task_id,
            source=FlowRunLifecycleSource.TASK_FAILURE,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.TASK_FAILURE,
                code=FlowApiErrorCode.RUN_TASK_FAILURE,
                message=error_message,
            ),
        )
        return {"status": "failed", "reason": "task_failure"}


class FlowTenantSweepPartialFailure(RuntimeError):
    """A maintenance sweep visited every tenant but could not serve them all."""


def _log_tenant_sweep_failure(*, task_name: str, tenant_id: UUID) -> None:
    logger.exception(
        "Flow maintenance sweep skipped a tenant after a failure",
        extra={"task_name": task_name, "tenant_id": str(tenant_id)},
    )


def _fail_task_if_tenants_were_skipped(
    *, task_name: str, skipped_tenant_ids: list[UUID]
) -> None:
    """Fail the task after visiting every tenant, rather than at the first one.

    Aborting mid-sweep starved every tenant listed after the failing one, and
    tenants arrive oldest-first, so that starvation was deterministic and
    permanent. Visiting the rest first and only then failing keeps the task
    failure an operator already watches, without the starvation. The same
    per-tenant isolation is applied to the tenant sweep in
    `eneo.worker.usage_stats_tasks.recalculate_all_tenants_usage_stats`.
    """
    if not skipped_tenant_ids:
        return
    raise FlowTenantSweepPartialFailure(
        f"{task_name} skipped {len(skipped_tenant_ids)} tenant(s) after failures"
    )


async def _reconcile_stale_running_runs_all_tenants(
    *, limit: int = 100
) -> dict[str, int | str]:
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=flow_stale_running_reconcile_after_seconds(
            task_timeout_seconds=get_settings().task_execution_timeout_seconds
        )
    )
    reconciled = 0
    skipped_tenant_ids: list[UUID] = []
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        run_repo = container.flow_run_repo()
        provider_call_repo = container.flow_provider_call_repo()
        terminalizer = container.flow_run_terminalizer()
        tenant_repo = container.tenant_repo()
        async with session.begin():
            tenants = await tenant_repo.get_all_tenants()
        for tenant in tenants:
            try:
                async with session.begin():
                    stale_runs = await run_repo.list_stale_running_runs(
                        tenant_id=tenant.id,
                        stale_before=stale_before,
                        limit=limit,
                    )
                for run in stale_runs:
                    async with session.begin():
                        result = await terminalizer.terminalize_stale_running_run(
                            run_id=run.id,
                            tenant_id=run.tenant_id,
                            stale_before=stale_before,
                            error=FlowRunError.from_source(
                                FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                                code=FlowApiErrorCode.RUN_WORKER_STALLED,
                                message=(
                                    "flow_worker_stalled: Flow run exceeded the execution timeout and was reconciled as failed."
                                ),
                            ),
                        )
                        if result.did_transition:
                            await provider_call_repo.mark_started_calls_outcome_unknown_for_run(
                                run_id=run.id,
                                tenant_id=run.tenant_id,
                                reason=ProviderCallUnknownReason.STALE_STARTED,
                            )
                            reconciled += 1
            except Exception:
                skipped_tenant_ids.append(tenant.id)
                _log_tenant_sweep_failure(
                    task_name="flows.reconcile_running", tenant_id=tenant.id
                )
    _fail_task_if_tenants_were_skipped(
        task_name="flows.reconcile_running", skipped_tenant_ids=skipped_tenant_ids
    )
    return {"status": "ok", "reconciled": reconciled}


async def _reconcile_expired_review_checkpoints_all_tenants(
    *, limit: int = 100
) -> dict[str, int | str]:
    reconciled = 0
    skipped_tenant_ids: list[UUID] = []
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        tenant_repo = container.tenant_repo()
        async with session.begin():
            tenants = await tenant_repo.get_all_tenants()
        for tenant in tenants:
            try:
                for _ in range(limit):
                    async with session.begin():
                        reconciler = container.flow_review_expiry_reconciler()
                        did_reconcile = (
                            await reconciler.reconcile_next_expired_checkpoint(
                                tenant_id=tenant.id,
                            )
                        )
                    if did_reconcile == 0:
                        break
                    reconciled += did_reconcile
            except Exception:
                skipped_tenant_ids.append(tenant.id)
                _log_tenant_sweep_failure(
                    task_name="flows.reconcile_review_expiry", tenant_id=tenant.id
                )
    _fail_task_if_tenants_were_skipped(
        task_name="flows.reconcile_review_expiry",
        skipped_tenant_ids=skipped_tenant_ids,
    )
    return {"status": "ok", "reconciled": reconciled}


async def _redispatch_stale_queued_runs_all_tenants(
    *, limit: int = 100
) -> dict[str, int | str]:
    """Dispatch queued epochs whose durable next-at clock is due."""

    due_at = datetime.now(timezone.utc)
    redispatched = 0
    skipped_tenant_ids: list[UUID] = []
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        run_repo = container.flow_run_repo()
        tenant_repo = container.tenant_repo()
        async with session.begin():
            tenants = await tenant_repo.get_all_tenants()
        for tenant in tenants:
            try:
                async with session.begin():
                    due_runs = await run_repo.list_dispatchable_queued_runs(
                        tenant_id=tenant.id,
                        due_at=due_at,
                        limit=limit,
                    )
                for run in due_runs:
                    result = await dispatch_flow_run_recoverably_after_commit(
                        run_id=run.id,
                        tenant_id=run.tenant_id,
                        expected_revision=run.revision,
                    )
                    if isinstance(result, FlowRunDispatchAccepted):
                        redispatched += 1
            except Exception:
                skipped_tenant_ids.append(tenant.id)
                _log_tenant_sweep_failure(
                    task_name="flows.redispatch_stale_queued", tenant_id=tenant.id
                )
    _fail_task_if_tenants_were_skipped(
        task_name="flows.redispatch_stale_queued",
        skipped_tenant_ids=skipped_tenant_ids,
    )
    return {"status": "ok", "redispatched": redispatched}


async def _deliver_flow_audit_outbox(
    *, limit: int = FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE
) -> dict[str, int | str]:
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        async with session.begin():
            container = Container(session=providers.Object(session))
            service = container.flow_run_audit_outbox_delivery_service()
            result = await service.deliver_due(
                now=datetime.now(timezone.utc),
                limit=limit,
            )
            return result.to_task_payload()


async def _deliver_flow_webhook_outbox(
    *, limit: int = FLOW_WEBHOOK_DELIVERY_BATCH_SIZE
) -> dict[str, int | str]:
    if limit <= 0:
        return FlowWebhookDeliveryResult().to_task_payload()

    now = datetime.now(timezone.utc)
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        async with session.begin():
            container = Container(session=providers.Object(session))
            service = container.flow_run_webhook_delivery_service()
            batch = await service.claim_due_batch(now=now, limit=limit)

    concurrency = min(FLOW_WEBHOOK_DELIVERY_CONCURRENCY, len(batch.claimed_rows))
    if concurrency == 0:
        return batch.result.to_task_payload()
    semaphore = asyncio.Semaphore(concurrency)

    async def _deliver_claimed(
        row: FlowRunWebhookDeliveryRow,
    ) -> FlowWebhookDeliveryResult:
        async with semaphore:
            try:
                async with sessionmanager.session() as delivery_session:
                    enable_autobegin_for_flow_task_session(delivery_session)
                    delivery_container = Container(
                        session=providers.Object(delivery_session)
                    )
                    delivery_service = (
                        delivery_container.flow_run_webhook_delivery_service()
                    )
                    return await delivery_service.deliver_claimed(row=row, now=now)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Flow webhook delivery worker failed before recording an outcome",
                    extra={"delivery_id": str(row.id)},
                )
                return FlowWebhookDeliveryResult(attempted_count=1)

    delivery_tasks: list[asyncio.Task[FlowWebhookDeliveryResult]] = []
    async with asyncio.TaskGroup() as task_group:
        for row in batch.claimed_rows:
            delivery_tasks.append(task_group.create_task(_deliver_claimed(row)))

    result = batch.result
    for delivery_task in delivery_tasks:
        result = result.combine(delivery_task.result())
    return result.to_task_payload()


async def reconcile_stale_running_runs() -> dict[str, int | str]:
    return await _reconcile_stale_running_runs_all_tenants()


async def reconcile_expired_review_checkpoints() -> dict[str, int | str]:
    return await _reconcile_expired_review_checkpoints_all_tenants()


async def redispatch_stale_queued_runs() -> dict[str, int | str]:
    return await _redispatch_stale_queued_runs_all_tenants()


async def deliver_flow_audit_outbox() -> dict[str, int | str]:
    return await _deliver_flow_audit_outbox()


async def deliver_flow_webhook_outbox() -> dict[str, int | str]:
    async with asyncio.timeout(FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS + 30):
        return await _deliver_flow_webhook_outbox()


def _build_flow_transcriber(
    registry_transcriber: "Transcriber",
) -> "FlowStepTranscriber":
    """Deployment-level engine choice for flow audio steps.

    No external service: the model-registry engine. Service in ``full`` mode: it
    replaces the engine (the flow's model stays the governance anchor). Service
    in ``diarize`` mode: the registry engine transcribes and the service only
    labels speakers.
    """
    settings = get_settings()
    if not settings.flow_transcription_service_configured:
        return registry_transcriber
    remote = build_remote_flow_transcriber(settings)
    if settings.flow_transcription_service_mode == "diarize":
        return DiarizingFlowTranscriber(registry_transcriber, remote)
    return remote

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, assert_never
from uuid import UUID

from celery.exceptions import (  # pyright: ignore[reportMissingTypeStubs]
    SoftTimeLimitExceeded,
)
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.principal_types import PrincipalType
from intric.database.database import sessionmanager
from intric.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
)
from intric.flows.application.flow_run_recovery_policy import (
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
    flow_stale_running_reconcile_after_seconds,
)
from intric.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_BATCH_SIZE,
    FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS,
)
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_document_limits import resolve_flow_document_render_limits
from intric.flows.flow_input_limits import (
    DEFAULT_MAX_AUDIO_FILES_PER_RUN,
    resolve_flow_input_limits,
)
from intric.flows.flow_run_dispatch_request import (
    FlowRunDispatchMalformedPayload,
    FlowRunDispatchMissingPrincipal,
    FlowRunServiceKeyDispatchRequest,
    FlowRunUserDispatchRequest,
    build_flow_run_dispatch_request,
    parse_flow_run_dispatch_task_kwargs,
)
from intric.flows.flow_run_error import FlowRunError
from intric.flows.flow_runtime_policy import resolve_flow_runtime_policy
from intric.flows.runtime.celery_app import celery_app
from intric.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from intric.flows.runtime.flow_run_actor import (
    FlowRunActor,
    FlowRunActorError,
    FlowRunServicePrincipalInactiveError,
)
from intric.flows.runtime.flow_runtime_trace import FlowRunSpanContext, trace_flow_run
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.request_context import clear_request_context, set_request_context
from intric.users.user_repo import UsersRepository

logger = get_logger(__name__)

_SECONDARY_TERMINALIZATION_TIMEOUT_SECONDS = 10
_FLOW_TASK_LOOP: asyncio.AbstractEventLoop | None = None
_FLOW_TASK_LOOP_THREAD: threading.Thread | None = None
_FLOW_TASK_LOOP_LOCK = threading.Lock()


def _start_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _get_flow_task_loop() -> asyncio.AbstractEventLoop:
    global _FLOW_TASK_LOOP  # pyright: ignore[reportConstantRedefinition]
    global _FLOW_TASK_LOOP_THREAD  # pyright: ignore[reportConstantRedefinition]

    with _FLOW_TASK_LOOP_LOCK:
        if _FLOW_TASK_LOOP is None or _FLOW_TASK_LOOP.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=_start_event_loop,
                args=(loop,),
                daemon=True,
                name="flow-celery-async-loop",
            )
            thread.start()
            _FLOW_TASK_LOOP = loop  # pyright: ignore[reportConstantRedefinition]
            _FLOW_TASK_LOOP_THREAD = thread  # pyright: ignore[reportConstantRedefinition]
        return _FLOW_TASK_LOOP


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
    celery_task_id: str | None,
) -> Generator[None]:
    context_values = {
        "flow.run.id": str(run_id),
        "flow.run.trace_id": str(run_trace_id),
        "flow.id": str(flow_id),
        "flow.tenant.id": str(tenant_id),
        "flow.celery.task_id": celery_task_id,
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
    principal_type: PrincipalType,
    principal_user_id: UUID | None,
    principal_service_id: UUID | None,
    celery_task_id: str | None,
    retry_count: int,
) -> dict[str, str]:
    with trace_flow_run(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        celery_task_id=celery_task_id,
        retry_count=retry_count,
    ) as flow_span:
        return await _execute_flow_run_async_traced(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            principal_type=principal_type,
            principal_user_id=principal_user_id,
            principal_service_id=principal_service_id,
            celery_task_id=celery_task_id,
            retry_count=retry_count,
            flow_span=flow_span,
        )


async def _execute_flow_run_async_traced(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    principal_type: PrincipalType,
    principal_user_id: UUID | None,
    principal_service_id: UUID | None,
    celery_task_id: str | None,
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
            celery_task_id=celery_task_id,
        ):
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

            flow_limits = resolve_flow_input_limits(tenant.flow_settings)
            document_render_limits = resolve_flow_document_render_limits(
                tenant.flow_settings
            )
            runtime_policy = resolve_flow_runtime_policy(tenant.flow_settings)

            executor = FlowRunExecutor(
                runtime_actor=run_actor,
                session=session,
                flow_repo=runtime_container.flow_repo(),
                flow_run_repo=flow_run_repo,
                flow_run_rerun_repo=runtime_container.flow_run_rerun_repo(),
                flow_run_review_checkpoint_repo=runtime_container.flow_run_review_checkpoint_repo(),
                flow_run_terminalizer=runtime_container.flow_run_terminalizer(),
                flow_version_repo=runtime_container.flow_version_repo(),
                space_repo=runtime_container.tenant_scoped_space_repo(),
                completion_service=runtime_container.completion_service(),
                file_repo=runtime_container.file_repo(),
                template_asset_repo=runtime_container.flow_template_asset_repo(),
                encryption_service=runtime_container.encryption_service(),
                audit_service=runtime_container.audit_service(),
                references_service=runtime_container.references_service(),
                transcriber=runtime_container.transcriber(),
                config=FlowRunExecutorConfig.from_settings(
                    max_inline_text_bytes=get_settings().flow_max_inline_text_bytes,
                    max_audio_files=flow_limits.audio_max_files_per_run
                    or DEFAULT_MAX_AUDIO_FILES_PER_RUN,
                    max_generic_files=flow_limits.max_files_per_run,
                    document_render_limits=document_render_limits,
                    runtime_policy=runtime_policy,
                ),
            )
            result = await executor.execute(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                celery_task_id=celery_task_id,
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


def _terminalize_flow_run_failure_from_task(
    *,
    loop: asyncio.AbstractEventLoop,
    run_id: UUID,
    tenant_id: UUID,
    task_id: str | None,
    source: FlowRunLifecycleSource,
    error: FlowRunError,
) -> None:
    try:
        asyncio.run_coroutine_threadsafe(
            terminalize_flow_run_failure(
                run_id=run_id,
                tenant_id=tenant_id,
                source=source,
                error=error,
            ),
            loop,
        ).result(timeout=_SECONDARY_TERMINALIZATION_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        logger.exception(
            "Flow run task terminalization timed out",
            extra={
                "run_id": str(run_id),
                "tenant_id": str(tenant_id),
                "task_id": task_id,
                "source": source.value,
            },
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


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="flows.execute",
    bind=True,
)
def execute_flow_run(
    self: Any,
    *,
    run_id: str,
    flow_id: str,
    tenant_id: str,
    principal_type: str | None = None,
    principal_user_id: str | None = None,
    principal_service_id: str | None = None,
) -> dict[str, str]:
    return _execute_flow_run_task(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_type=principal_type,
        principal_user_id=principal_user_id,
        principal_service_id=principal_service_id,
        task_id=self.request.id,
        retry_count=self.request.retries,
    )


def _execute_flow_run_task(
    *,
    run_id: str,
    flow_id: str,
    tenant_id: str,
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
        principal_type=principal_type,
        principal_user_id=principal_user_id,
        principal_service_id=principal_service_id,
    )
    match dispatch_request:
        case FlowRunUserDispatchRequest() as user_dispatch:
            run_id_uuid = user_dispatch.run_id
            flow_id_uuid = user_dispatch.flow_id
            tenant_id_uuid = user_dispatch.tenant_id
            resolved_principal_type = PrincipalType.USER
            resolved_principal_user_id = user_dispatch.principal_user_id
            resolved_principal_service_id = None
        case FlowRunServiceKeyDispatchRequest() as service_dispatch:
            run_id_uuid = service_dispatch.run_id
            flow_id_uuid = service_dispatch.flow_id
            tenant_id_uuid = service_dispatch.tenant_id
            resolved_principal_type = PrincipalType.SERVICE_KEY
            resolved_principal_user_id = service_dispatch.principal_user_id
            resolved_principal_service_id = service_dispatch.principal_service_id
        case FlowRunDispatchMissingPrincipal() as missing_principal:
            run_id_uuid = missing_principal.run_id
            tenant_id_uuid = missing_principal.tenant_id
            loop = _get_flow_task_loop()
            _terminalize_flow_run_failure_from_task(
                loop=loop,
                run_id=run_id_uuid,
                tenant_id=tenant_id_uuid,
                task_id=task_id,
                source=FlowRunLifecycleSource.MISSING_PRINCIPAL,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.MISSING_PRINCIPAL,
                    code=FlowApiErrorCode.RUN_MISSING_PRINCIPAL,
                    message=(
                        "flow_missing_principal: "
                        "Flow run execution skipped because run has no execution principal."
                    ),
                ),
            )
            logger.error(
                "Flow run execution skipped because run has no execution principal",
                extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
            )
            return {"status": "failed", "reason": "missing_principal"}
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

    loop = _get_flow_task_loop()
    future: concurrent.futures.Future[dict[str, str]] | None = None
    try:
        future = asyncio.run_coroutine_threadsafe(
            _execute_flow_run_async(
                run_id=run_id_uuid,
                flow_id=flow_id_uuid,
                tenant_id=tenant_id_uuid,
                principal_type=resolved_principal_type,
                principal_user_id=resolved_principal_user_id,
                principal_service_id=resolved_principal_service_id,
                celery_task_id=task_id,
                retry_count=retry_count,
            ),
            loop,
        )
        return future.result(timeout=get_settings().flow_task_timeout_seconds)
    except (concurrent.futures.TimeoutError, SoftTimeLimitExceeded):
        if future is not None:
            future.cancel()
        error_message = (
            "flow_task_timeout: Flow execution timed out before task completion."
        )
        logger.exception(
            "Flow execution task timed out",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        _terminalize_flow_run_failure_from_task(
            loop=loop,
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
        _terminalize_flow_run_failure_from_task(
            loop=loop,
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


async def _reconcile_stale_running_runs_all_tenants(
    *, limit: int = 100
) -> dict[str, int | str]:
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=flow_stale_running_reconcile_after_seconds(
            task_timeout_seconds=get_settings().flow_task_timeout_seconds
        )
    )
    reconciled = 0
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        run_repo = container.flow_run_repo()
        terminalizer = container.flow_run_terminalizer()
        tenant_repo = container.tenant_repo()
        tenants = await tenant_repo.get_all_tenants()
        for tenant in tenants:
            stale_runs = await run_repo.list_stale_running_runs(
                tenant_id=tenant.id,
                stale_before=stale_before,
                limit=limit,
            )
            for run in stale_runs:
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
                    reconciled += 1
    return {"status": "ok", "reconciled": reconciled}


async def _reconcile_expired_review_checkpoints_all_tenants(
    *, limit: int = 100
) -> dict[str, int | str]:
    reconciled = 0
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        tenant_repo = container.tenant_repo()
        async with session.begin():
            tenants = await tenant_repo.get_all_tenants()
        for tenant in tenants:
            for _ in range(limit):
                async with session.begin():
                    reconciler = container.flow_review_expiry_reconciler()
                    did_reconcile = await reconciler.reconcile_next_expired_checkpoint(
                        tenant_id=tenant.id,
                    )
                if did_reconcile == 0:
                    break
                reconciled += did_reconcile
    return {"status": "ok", "reconciled": reconciled}


async def _redispatch_stale_queued_runs_all_tenants(
    *, limit: int = 100
) -> dict[str, int | str]:
    """Re-dispatch QUEUED runs whose initial dispatch was lost.

    `dispatch_flow_run_after_commit` runs as a FastAPI BackgroundTask
    after the response is sent; if the API process exits before the
    task fires (autoreload, OOM, deploy), the run sits in QUEUED with
    no error_code and no automatic retry. This beat task is the
    safety net.

    The atomic `claim_stale_queued_run_for_redispatch` is the
    cross-process serialization point — two beat workers cannot
    redispatch the same run.
    """
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=max(1, FLOW_QUEUED_REDISPATCH_AFTER_SECONDS)
    )
    redispatched = 0
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        run_repo = container.flow_run_repo()
        backend = container.flow_execution_backend()
        tenant_repo = container.tenant_repo()
        async with session.begin():
            tenants = await tenant_repo.get_all_tenants()
        for tenant in tenants:
            async with session.begin():
                stale_runs = await run_repo.list_stale_queued_runs(
                    tenant_id=tenant.id,
                    stale_before=stale_before,
                    limit=limit,
                )
            for run in stale_runs:
                # Commit the atomic claim before dispatching: the celery
                # worker that picks up the dispatched run reads the run
                # in a fresh session, so the claim must be visible first.
                async with session.begin():
                    claimed = await run_repo.claim_stale_queued_run_for_redispatch(
                        run_id=run.id,
                        tenant_id=run.tenant_id,
                        stale_before=stale_before,
                    )
                if claimed is None:
                    continue
                try:
                    dispatch_request = build_flow_run_dispatch_request(claimed)
                except ValueError:
                    logger.warning(
                        "Skipping redispatch for run with invalid principal",
                        extra={
                            "run_id": str(claimed.id),
                            "tenant_id": str(claimed.tenant_id),
                        },
                    )
                    continue
                try:
                    await backend.dispatch(request=dispatch_request)
                    redispatched += 1
                except Exception:
                    logger.exception(
                        "Failed to redispatch stale queued flow run",
                        extra={
                            "run_id": str(claimed.id),
                            "flow_id": str(claimed.flow_id),
                            "tenant_id": str(claimed.tenant_id),
                        },
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
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        service = container.flow_run_webhook_delivery_service()
        result = await service.deliver_due(
            now=datetime.now(timezone.utc),
            limit=limit,
        )
        return result.to_task_payload()


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="flows.reconcile_running",
)
def reconcile_stale_running_runs() -> dict[str, int | str]:
    loop = _get_flow_task_loop()
    future = asyncio.run_coroutine_threadsafe(
        _reconcile_stale_running_runs_all_tenants(),
        loop,
    )
    return future.result(timeout=30)


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="flows.reconcile_review_expiry",
)
def reconcile_expired_review_checkpoints() -> dict[str, int | str]:
    loop = _get_flow_task_loop()
    future = asyncio.run_coroutine_threadsafe(
        _reconcile_expired_review_checkpoints_all_tenants(),
        loop,
    )
    return future.result(timeout=30)


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="flows.redispatch_stale_queued",
)
def redispatch_stale_queued_runs() -> dict[str, int | str]:
    loop = _get_flow_task_loop()
    future = asyncio.run_coroutine_threadsafe(
        _redispatch_stale_queued_runs_all_tenants(),
        loop,
    )
    return future.result(timeout=60)


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="flows.deliver_audit_outbox",
)
def deliver_flow_audit_outbox() -> dict[str, int | str]:
    loop = _get_flow_task_loop()
    future = asyncio.run_coroutine_threadsafe(
        _deliver_flow_audit_outbox(),
        loop,
    )
    return future.result(timeout=30)


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="flows.deliver_webhook_outbox",
)
def deliver_flow_webhook_outbox() -> dict[str, int | str]:
    loop = _get_flow_task_loop()
    future = asyncio.run_coroutine_threadsafe(
        _deliver_flow_webhook_outbox(),
        loop,
    )
    return future.result(timeout=FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS + 30)

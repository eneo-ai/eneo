from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.principal_types import PrincipalType
from intric.authentication.service_key_user import build_service_key_user
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
from intric.flows.flow_document_limits import resolve_flow_document_render_limits
from intric.flows.flow_input_limits import (
    DEFAULT_MAX_AUDIO_FILES_PER_RUN,
    resolve_flow_input_limits,
)
from intric.flows.flow_run_dispatch_request import build_flow_run_dispatch_request
from intric.flows.flow_run_error import FlowRunError
from intric.flows.flow_runtime_policy import resolve_flow_runtime_policy
from intric.flows.runtime.celery_app import celery_app
from intric.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.container.container_overrides import override_user
from intric.main.logging import get_logger
from intric.users.user_repo import UsersRepository

logger = get_logger(__name__)

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


async def _execute_flow_run_async(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    principal_type: PrincipalType,
    principal_user_id: UUID | None,
    principal_api_key_id: UUID | None,
    celery_task_id: str | None,
    retry_count: int,
) -> dict[str, str]:
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        user_repo = UsersRepository(session=session)
        tenant = await container.tenant_repo().get(tenant_id)
        if tenant is None:
            raise RuntimeError("Flow execution task tenant not found.")

        if principal_type == PrincipalType.USER:
            if principal_user_id is None:
                raise RuntimeError("Flow execution task principal_user_id is missing.")
            user = await user_repo.get_user_by_id_and_tenant_id(
                id=principal_user_id, tenant_id=tenant_id
            )
            if user is None:
                raise RuntimeError("Flow execution task user not found for tenant.")
        else:
            if principal_api_key_id is None:
                raise RuntimeError(
                    "Flow execution task principal_api_key_id is missing."
                )
            key = await container.api_key_v2_repo().get(
                key_id=principal_api_key_id,
                tenant_id=tenant_id,
            )
            if key is None:
                raise RuntimeError("Flow execution task API key not found for tenant.")
            user = build_service_key_user(key=key, tenant=tenant)

        override_user(container=container, user=user)

        flow_limits = resolve_flow_input_limits(
            tenant.flow_settings if tenant else None
        )
        document_render_limits = resolve_flow_document_render_limits(
            tenant.flow_settings if tenant else None
        )
        runtime_policy = resolve_flow_runtime_policy(
            tenant.flow_settings if tenant else None
        )

        executor = FlowRunExecutor(
            user=user,
            session=session,
            flow_repo=container.flow_repo(),
            flow_run_repo=container.flow_run_repo(),
            flow_run_terminalizer=container.flow_run_terminalizer(),
            flow_version_repo=container.flow_version_repo(),
            space_repo=container.space_repo(),
            completion_service=container.completion_service(),
            file_repo=container.file_repo(),
            template_asset_service=container.flow_template_asset_service(),
            encryption_service=container.encryption_service(),
            audit_service=container.audit_service(),
            references_service=container.references_service(),
            transcriber=container.transcriber(),
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
    principal_api_key_id: str | None = None,
) -> dict[str, str]:
    return _execute_flow_run_task(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_type=principal_type,
        principal_user_id=principal_user_id,
        principal_api_key_id=principal_api_key_id,
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
    principal_api_key_id: str | None = None,
    task_id: str | None,
    retry_count: int,
) -> dict[str, str]:
    run_id_uuid = UUID(run_id)
    tenant_id_uuid = UUID(tenant_id)
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
            "principal_api_key_id": principal_api_key_id,
        },
    )
    resolved_principal_type = (
        PrincipalType(principal_type) if principal_type is not None else None
    )
    if (
        resolved_principal_type is None
        or (resolved_principal_type == PrincipalType.USER and principal_user_id is None)
    ) or (
        resolved_principal_type == PrincipalType.SERVICE_KEY
        and principal_api_key_id is None
    ):
        loop = _get_flow_task_loop()
        asyncio.run_coroutine_threadsafe(
            terminalize_flow_run_failure(
                run_id=run_id_uuid,
                tenant_id=tenant_id_uuid,
                source=FlowRunLifecycleSource.MISSING_PRINCIPAL,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.MISSING_PRINCIPAL,
                    code="flow_missing_principal",
                    message=(
                        "flow_missing_principal: "
                        "Flow run execution skipped because run has no execution principal."
                    ),
                ),
            ),
            loop,
        ).result(timeout=10)
        logger.error(
            "Flow run execution skipped because run has no execution principal",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        return {"status": "failed", "reason": "missing_principal"}

    loop = _get_flow_task_loop()
    future: concurrent.futures.Future[dict[str, str]] | None = None
    try:
        future = asyncio.run_coroutine_threadsafe(
            _execute_flow_run_async(
                run_id=run_id_uuid,
                flow_id=UUID(flow_id),
                tenant_id=tenant_id_uuid,
                principal_type=resolved_principal_type,
                principal_user_id=(
                    UUID(principal_user_id) if principal_user_id is not None else None
                ),
                principal_api_key_id=(
                    UUID(principal_api_key_id)
                    if principal_api_key_id is not None
                    else None
                ),
                celery_task_id=task_id,
                retry_count=retry_count,
            ),
            loop,
        )
        return future.result(timeout=get_settings().flow_task_timeout_seconds)
    except concurrent.futures.TimeoutError:
        if future is not None:
            future.cancel()
        error_message = (
            "flow_task_timeout: Flow execution timed out before task completion."
        )
        logger.exception(
            "Flow execution task timed out",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        asyncio.run_coroutine_threadsafe(
            terminalize_flow_run_failure(
                run_id=run_id_uuid,
                tenant_id=tenant_id_uuid,
                source=FlowRunLifecycleSource.TASK_TIMEOUT,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.TASK_TIMEOUT,
                    code="flow_task_timeout",
                    message=error_message,
                ),
            ),
            loop,
        ).result(timeout=10)
        return {"status": "failed", "reason": "timeout"}
    except Exception:
        error_message = (
            "flow_task_failure: Flow execution task failed before run completion."
        )
        logger.exception(
            "Flow execution task failed",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        asyncio.run_coroutine_threadsafe(
            terminalize_flow_run_failure(
                run_id=run_id_uuid,
                tenant_id=tenant_id_uuid,
                source=FlowRunLifecycleSource.TASK_FAILURE,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.TASK_FAILURE,
                    code="flow_task_failure",
                    message=error_message,
                ),
            ),
            loop,
        ).result(timeout=10)
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
                        code="flow_worker_stalled",
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

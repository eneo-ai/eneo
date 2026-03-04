from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from uuid import UUID

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.database import sessionmanager
from intric.flows.flow import FlowRunStatus
from intric.flows.flow_run_repo import FlowRunRepository
from intric.flows.runtime.celery_app import celery_app
from intric.flows.runtime.executor import FlowRunExecutor
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
    global _FLOW_TASK_LOOP
    global _FLOW_TASK_LOOP_THREAD

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
            _FLOW_TASK_LOOP = loop
            _FLOW_TASK_LOOP_THREAD = thread
        return _FLOW_TASK_LOOP


def _enable_autobegin_for_flow_task_session(session: AsyncSession) -> None:
    """Flow runtime uses commit-heavy repos; enable autobegin for this task session."""
    session.sync_session.autobegin = True


async def _execute_flow_run_async(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    celery_task_id: str | None,
    retry_count: int,
) -> dict[str, str]:
    async with sessionmanager.session() as session:
        _enable_autobegin_for_flow_task_session(session)
        user_repo = UsersRepository(session=session)
        user = await user_repo.get_user_by_id_and_tenant_id(id=user_id, tenant_id=tenant_id)

        container = Container(session=providers.Object(session))
        override_user(container=container, user=user)
        executor = FlowRunExecutor(
            user=user,
            flow_repo=container.flow_repo(),
            flow_run_repo=container.flow_run_repo(),
            flow_version_repo=container.flow_version_repo(),
            space_repo=container.space_repo(),
            completion_service=container.completion_service(),
            file_repo=container.file_repo(),
            encryption_service=container.encryption_service(),
            max_inline_text_bytes=get_settings().flow_max_inline_text_bytes,
            audit_service=container.audit_service(),
        )
        result = await executor.execute(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            celery_task_id=celery_task_id,
            retry_count=retry_count,
        )
        return {key: str(value) for key, value in result.items()}


async def _mark_run_failed(
    *,
    run_id: UUID,
    tenant_id: UUID,
    error_message: str,
) -> None:
    async with sessionmanager.session() as session:
        async with session.begin():
            container = Container(session=providers.Object(session))
            run_repo: FlowRunRepository = container.flow_run_repo()
            await run_repo.mark_pending_steps_cancelled(
                run_id=run_id,
                tenant_id=tenant_id,
                error_message=error_message,
            )
            await run_repo.update_status(
                run_id=run_id,
                tenant_id=tenant_id,
                status=FlowRunStatus.FAILED,
                error_message=error_message,
                from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
            )


@celery_app.task(name="flows.execute", bind=True)
def execute_flow_run(
    self,
    *,
    run_id: str,
    flow_id: str,
    tenant_id: str,
    user_id: str | None,
) -> dict[str, str]:
    return _execute_flow_run_task(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        user_id=user_id,
        task_id=self.request.id,
        retry_count=self.request.retries,
    )


def _execute_flow_run_task(
    *,
    run_id: str,
    flow_id: str,
    tenant_id: str,
    user_id: str | None,
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
            "user_id": user_id,
        },
    )
    if user_id is None:
        loop = _get_flow_task_loop()
        asyncio.run_coroutine_threadsafe(
            _mark_run_failed(
                run_id=run_id_uuid,
                tenant_id=tenant_id_uuid,
                error_message="Flow run execution skipped because run has no user_id.",
            ),
            loop,
        ).result(timeout=10)
        logger.error(
            "Flow run execution skipped because run has no user_id",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        return {"status": "failed", "reason": "missing_user_id"}

    loop = _get_flow_task_loop()
    try:
        future = asyncio.run_coroutine_threadsafe(
            _execute_flow_run_async(
                run_id=run_id_uuid,
                flow_id=UUID(flow_id),
                tenant_id=tenant_id_uuid,
                user_id=UUID(user_id),
                celery_task_id=task_id,
                retry_count=retry_count,
            ),
            loop,
        )
        return future.result(timeout=get_settings().flow_task_timeout_seconds)
    except concurrent.futures.TimeoutError:
        future.cancel()
        error_message = "Flow execution timed out before task completion."
        logger.exception(
            "Flow execution task timed out",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        asyncio.run_coroutine_threadsafe(
            _mark_run_failed(
                run_id=run_id_uuid,
                tenant_id=tenant_id_uuid,
                error_message=error_message,
            ),
            loop,
        ).result(timeout=10)
        return {"status": "failed", "reason": "timeout"}
    except Exception as exc:
        error_message = f"Flow execution task failed: {exc}"
        logger.exception(
            "Flow execution task failed",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        asyncio.run_coroutine_threadsafe(
            _mark_run_failed(
                run_id=run_id_uuid,
                tenant_id=tenant_id_uuid,
                error_message=error_message,
            ),
            loop,
        ).result(timeout=10)
        return {"status": "failed", "reason": "task_failure"}

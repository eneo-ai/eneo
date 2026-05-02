from __future__ import annotations

import logging
from uuid import UUID

from dependency_injector import providers

from intric.database.database import sessionmanager
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.execution_backend import FlowExecutionBackend
from intric.main.container.container import Container

logger = logging.getLogger(__name__)


async def _dispatch_via_backend(
    backend: FlowExecutionBackend,
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    principal_type: str | None = None,
    principal_user_id: UUID | None = None,
    principal_api_key_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    if principal_type is None:
        await backend.dispatch(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return

    await backend.dispatch(
        run_id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        principal_type=principal_type,
        principal_user_id=principal_user_id,
        principal_api_key_id=principal_api_key_id,
    )


async def dispatch_flow_run_after_commit(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    principal_type: str | None = None,
    principal_user_id: UUID | None = None,
    principal_api_key_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    """Dispatch a newly created run; dispatch failure terminalizes it as failed."""
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        backend = container.flow_execution_backend()
        terminalizer = container.flow_run_terminalizer()
        try:
            await _dispatch_via_backend(
                backend,
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                principal_type=principal_type,
                principal_user_id=principal_user_id,
                principal_api_key_id=principal_api_key_id,
                user_id=user_id,
            )
        except Exception:
            logger.exception(
                "flow_dispatch_after_commit_failed run_id=%s flow_id=%s tenant_id=%s",
                run_id,
                flow_id,
                tenant_id,
            )
            async with session.begin():
                await terminalizer.terminalize_run(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    target_status=FlowRunStatus.FAILED,
                    source=FlowRunLifecycleSource.DISPATCH_FAILURE,
                    error_code="flow_dispatch_failed",
                    error_message=(
                        "flow_dispatch_failed: "
                        "Flow dispatch failed before execution started. "
                        "Retry creating a new run."
                    ),
                )


async def dispatch_flow_run_recoverably_after_commit(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    principal_type: str | None = None,
    principal_user_id: UUID | None = None,
    principal_api_key_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    """Dispatch an accepted operation; failures keep the queued run intact for repair."""
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        backend = container.flow_execution_backend()
        try:
            await _dispatch_via_backend(
                backend,
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                principal_type=principal_type,
                principal_user_id=principal_user_id,
                principal_api_key_id=principal_api_key_id,
                user_id=user_id,
            )
        except Exception:
            logger.exception(
                "flow_recoverable_dispatch_after_commit_failed "
                "run_id=%s flow_id=%s tenant_id=%s",
                run_id,
                flow_id,
                tenant_id,
            )

from __future__ import annotations

import logging

from dependency_injector import providers

from intric.database.database import sessionmanager
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_run_dispatch_request import FlowRunDispatchRequest
from intric.flows.flow_run_error import FlowRunError
from intric.main.container.container import Container

logger = logging.getLogger(__name__)


async def dispatch_flow_run_after_commit(
    *,
    request: FlowRunDispatchRequest,
) -> None:
    """Dispatch a newly created run; dispatch failure terminalizes it as failed."""
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        backend = container.flow_execution_backend()
        terminalizer = container.flow_run_terminalizer()
        try:
            await backend.dispatch(request=request)
        except Exception:
            logger.exception(
                "flow_dispatch_after_commit_failed run_id=%s flow_id=%s tenant_id=%s",
                request.run_id,
                request.flow_id,
                request.tenant_id,
            )
            async with session.begin():
                await terminalizer.terminalize_run(
                    run_id=request.run_id,
                    tenant_id=request.tenant_id,
                    target_status=FlowRunStatus.FAILED,
                    source=FlowRunLifecycleSource.DISPATCH_FAILURE,
                    error=FlowRunError.from_source(
                        FlowRunLifecycleSource.DISPATCH_FAILURE,
                        code=FlowApiErrorCode.RUN_DISPATCH_FAILED,
                        message=(
                            "flow_dispatch_failed: "
                            "Flow dispatch failed before execution started. "
                            "Retry creating a new run."
                        ),
                    ),
                )


async def dispatch_flow_run_recoverably_after_commit(
    *,
    request: FlowRunDispatchRequest,
) -> None:
    """Dispatch an accepted operation; failures keep the queued run intact for repair."""
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        backend = container.flow_execution_backend()
        try:
            await backend.dispatch(request=request)
        except Exception:
            logger.exception(
                "flow_recoverable_dispatch_after_commit_failed "
                "run_id=%s flow_id=%s tenant_id=%s",
                request.run_id,
                request.flow_id,
                request.tenant_id,
            )

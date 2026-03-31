from __future__ import annotations

import logging
from uuid import UUID

from dependency_injector import providers

from intric.database.database import sessionmanager
from intric.flows.domain.flow import FlowRunStatus
from intric.main.container.container import Container

logger = logging.getLogger(__name__)


async def dispatch_flow_run_after_commit(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    user_id: UUID | None,
) -> None:
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        backend = container.flow_execution_backend()
        run_repo = container.flow_run_repo()
        try:
            await backend.dispatch(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
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
                await run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.FAILED,
                    error_message=(
                        "flow_dispatch_failed: "
                        "Flow dispatch failed before execution started. "
                        "Retry creating a new run."
                    ),
                )

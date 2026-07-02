from __future__ import annotations

import logging

from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.flows.flow_run_dispatch_request import FlowRunDispatchRequest
from eneo.main.container.container import Container

logger = logging.getLogger(__name__)


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

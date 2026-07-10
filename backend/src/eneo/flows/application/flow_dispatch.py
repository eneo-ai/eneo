from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, TypeAlias
from uuid import UUID

from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_dispatch_request import build_flow_run_dispatch_request
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunDispatchErrorKind,
    FlowRunError,
)
from eneo.main.container.container import Container

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FlowRunDispatchNotClaimed:
    run: FlowRun
    kind: Literal["not_claimed"] = "not_claimed"


@dataclass(frozen=True, slots=True)
class FlowRunDispatchInvalidRequest:
    run: FlowRun
    kind: Literal["invalid_request"] = "invalid_request"


@dataclass(frozen=True, slots=True)
class FlowRunDispatchAccepted:
    run: FlowRun
    kind: Literal["accepted"] = "accepted"


@dataclass(frozen=True, slots=True)
class FlowRunDispatchFailed:
    run: FlowRun
    kind: Literal["dispatch_failed"] = "dispatch_failed"


@dataclass(frozen=True, slots=True)
class FlowRunDispatchExhausted:
    run: FlowRun
    kind: Literal["exhausted"] = "exhausted"


FlowRunDispatchResult: TypeAlias = (
    FlowRunDispatchNotClaimed
    | FlowRunDispatchInvalidRequest
    | FlowRunDispatchAccepted
    | FlowRunDispatchFailed
    | FlowRunDispatchExhausted
)


async def dispatch_flow_run_recoverably_after_commit(
    *,
    run_id: UUID,
    tenant_id: UUID,
    expected_revision: int,
) -> FlowRunDispatchResult:
    """Claim, send, and durably record one due dispatch attempt.

    The claim commits before broker I/O. Broker acceptance is not exactly-once:
    the bounded recovery deadline remains armed until a worker claims the run,
    and the worker's status-and-revision CAS rejects duplicate tasks.
    """

    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        run_repo = container.flow_run_repo()
        terminalizer = container.flow_run_terminalizer()
        now = datetime.now(timezone.utc)

        async with session.begin():
            exhausted = await run_repo.mark_dispatch_exhausted_if_due(
                run_id=run_id,
                tenant_id=tenant_id,
                expected_revision=expected_revision,
                now=now,
            )
            if exhausted is not None:
                terminalized = await terminalizer.terminalize_run(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    target_status=FlowRunStatus.FAILED,
                    source=FlowRunLifecycleSource.DISPATCH_FAILURE,
                    error=_dispatch_exhausted_error(),
                )
                return FlowRunDispatchExhausted(run=terminalized.run)

        async with session.begin():
            claimed = await run_repo.claim_queued_run_for_dispatch(
                run_id=run_id,
                tenant_id=tenant_id,
                expected_revision=expected_revision,
                now=now,
            )
        if claimed is None:
            current = await run_repo.get(run_id=run_id, tenant_id=tenant_id)
            return FlowRunDispatchNotClaimed(run=current)

        try:
            request = build_flow_run_dispatch_request(claimed)
        except ValueError:
            dispatch_error = FlowRunDispatchError.from_kind(
                FlowRunDispatchErrorKind.INVALID_REQUEST
            )
            async with session.begin():
                failed = await run_repo.record_dispatch_failure(
                    run_id=claimed.id,
                    tenant_id=claimed.tenant_id,
                    expected_revision=claimed.revision,
                    expected_attempt_count=claimed.dispatch_attempt_count,
                    error=dispatch_error,
                    now=datetime.now(timezone.utc),
                )
                if failed is None:
                    current = await run_repo.get(
                        run_id=claimed.id,
                        tenant_id=claimed.tenant_id,
                    )
                    return FlowRunDispatchNotClaimed(run=current)
                terminalized = await terminalizer.terminalize_run(
                    run_id=failed.id,
                    tenant_id=failed.tenant_id,
                    target_status=FlowRunStatus.FAILED,
                    source=FlowRunLifecycleSource.MISSING_PRINCIPAL,
                    error=FlowRunError.from_source(
                        FlowRunLifecycleSource.MISSING_PRINCIPAL,
                        code=FlowApiErrorCode.RUN_MISSING_PRINCIPAL,
                        message=dispatch_error.message,
                    ),
                )
            return FlowRunDispatchInvalidRequest(run=terminalized.run)

        backend = container.flow_execution_backend()
        try:
            await backend.dispatch(request=request)
        except Exception:
            logger.warning(
                "Flow run dispatch attempt was rejected by the execution backend",
                extra={
                    "run_id": str(claimed.id),
                    "tenant_id": str(claimed.tenant_id),
                },
            )
            dispatch_error = FlowRunDispatchError.from_kind(
                FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
            )
            async with session.begin():
                failed = await run_repo.record_dispatch_failure(
                    run_id=claimed.id,
                    tenant_id=claimed.tenant_id,
                    expected_revision=claimed.revision,
                    expected_attempt_count=claimed.dispatch_attempt_count,
                    error=dispatch_error,
                    now=datetime.now(timezone.utc),
                )
                if failed is None:
                    current = await run_repo.get(
                        run_id=claimed.id,
                        tenant_id=claimed.tenant_id,
                    )
                    return FlowRunDispatchNotClaimed(run=current)
                if failed.dispatch_exhausted_at is not None:
                    terminalized = await terminalizer.terminalize_run(
                        run_id=failed.id,
                        tenant_id=failed.tenant_id,
                        target_status=FlowRunStatus.FAILED,
                        source=FlowRunLifecycleSource.DISPATCH_FAILURE,
                        error=_dispatch_exhausted_error(),
                    )
                    failed = terminalized.run
            return FlowRunDispatchFailed(run=failed)

        async with session.begin():
            accepted = await run_repo.record_dispatch_accepted(
                run_id=claimed.id,
                tenant_id=claimed.tenant_id,
                expected_revision=claimed.revision,
                expected_attempt_count=claimed.dispatch_attempt_count,
                now=datetime.now(timezone.utc),
            )
            if accepted is None:
                accepted = await run_repo.get(
                    run_id=claimed.id,
                    tenant_id=claimed.tenant_id,
                )
        return FlowRunDispatchAccepted(run=accepted)


def _dispatch_exhausted_error() -> FlowRunError:
    return FlowRunError.from_source(
        FlowRunLifecycleSource.DISPATCH_FAILURE,
        code=FlowApiErrorCode.RUN_DISPATCH_FAILED,
        message=(
            "flow_dispatch_failed: Flow run dispatch exhausted its bounded attempts."
        ),
    )

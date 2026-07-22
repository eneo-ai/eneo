from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypeAlias
from uuid import UUID

from dependency_injector import providers

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.database import sessionmanager
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.execution_backend import FlowExecutionDispatchRejected
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_dispatch_request import build_flow_run_dispatch_request
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunDispatchErrorKind,
    FlowRunError,
)
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunDispatchRedriveGenerationConflict,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import AuditLoggingUnavailableException

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


@dataclass(frozen=True, slots=True)
class FlowRunDispatchOutcomeUnknown:
    run: FlowRun
    kind: Literal["outcome_unknown"] = "outcome_unknown"


class FlowRunDispatchExhaustionGenerationConflictError(Exception):
    def __init__(self, *, current_dispatch_exhausted_at: datetime | None):
        super().__init__(
            "Flow run dispatch exhaustion generation changed; refresh the run before "
            "redispatching."
        )
        self.current_dispatch_exhausted_at = current_dispatch_exhausted_at


FlowRunDispatchResult: TypeAlias = (
    FlowRunDispatchNotClaimed
    | FlowRunDispatchInvalidRequest
    | FlowRunDispatchAccepted
    | FlowRunDispatchFailed
    | FlowRunDispatchExhausted
    | FlowRunDispatchOutcomeUnknown
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
                if (
                    exhausted.dispatched_at is not None
                    or exhausted.dispatch_last_error is None
                ):
                    return FlowRunDispatchExhausted(run=exhausted)
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
        except FlowExecutionDispatchRejected:
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
                if (
                    failed.dispatch_exhausted_at is not None
                    and failed.dispatched_at is None
                ):
                    terminalized = await terminalizer.terminalize_run(
                        run_id=failed.id,
                        tenant_id=failed.tenant_id,
                        target_status=FlowRunStatus.FAILED,
                        source=FlowRunLifecycleSource.DISPATCH_FAILURE,
                        error=_dispatch_exhausted_error(),
                    )
                    failed = terminalized.run
            return FlowRunDispatchFailed(run=failed)
        except Exception:
            logger.warning(
                "Flow run dispatch outcome is unknown after execution backend error",
                extra={
                    "run_id": str(claimed.id),
                    "tenant_id": str(claimed.tenant_id),
                },
            )
            async with session.begin():
                outcome_unknown = await run_repo.record_dispatch_outcome_unknown(
                    run_id=claimed.id,
                    tenant_id=claimed.tenant_id,
                    expected_revision=claimed.revision,
                    expected_attempt_count=claimed.dispatch_attempt_count,
                    now=datetime.now(timezone.utc),
                )
                if outcome_unknown is None:
                    outcome_unknown = await run_repo.get(
                        run_id=claimed.id,
                        tenant_id=claimed.tenant_id,
                    )
            return FlowRunDispatchOutcomeUnknown(run=outcome_unknown)

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


async def redrive_flow_run_recoverably_after_commit(
    *,
    run_id: UUID,
    tenant_id: UUID,
    expected_revision: int,
    actor_id: UUID | None,
    actor_type: ActorType,
    actor_api_key_id: UUID | None,
    audit_metadata: dict[str, Any],
    expected_dispatch_exhausted_at: datetime | None,
) -> FlowRunDispatchResult:
    """Durably audit and rearm accepted exhaustion, then run one dispatch CAS.

    The audit and optional budget reset commit together before broker I/O.
    Automatic recovery never calls this path, so every rearmed epoch remains an
    explicit API action bounded by the standard dispatch budget.
    """

    try:
        async with sessionmanager.session() as session:
            container = Container(session=providers.Object(session))
            async with session.begin():
                rearmed = await container.flow_run_repo().rearm_exhausted_accepted_dispatch_for_redrive(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    expected_revision=expected_revision,
                    expected_dispatch_exhausted_at=expected_dispatch_exhausted_at,
                    now=datetime.now(timezone.utc),
                )
                if isinstance(rearmed, FlowRunDispatchRedriveGenerationConflict):
                    raise FlowRunDispatchExhaustionGenerationConflictError(
                        current_dispatch_exhausted_at=(
                            rearmed.current_dispatch_exhausted_at
                        )
                    )
                audit_log = await container.audit_service().log(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    actor_type=actor_type,
                    actor_api_key_id=actor_api_key_id,
                    action=ActionType.FLOW_RUN_REDISPATCHED,
                    entity_type=EntityType.FLOW_RUN,
                    entity_id=run_id,
                    description=f"Redispatch requested for flow run {run_id}",
                    metadata={
                        **audit_metadata,
                        "accepted_exhaustion_rearmed": rearmed is not None,
                    },
                )
                if audit_log is None:
                    raise AuditLoggingUnavailableException(
                        "Redispatch audit logging is unavailable.",
                        code=(FlowApiErrorCode.RUN_REDISPATCH_AUDIT_UNAVAILABLE.value),
                        context={"audit_required": True},
                    )
    except (
        AuditLoggingUnavailableException,
        FlowRunDispatchExhaustionGenerationConflictError,
    ):
        raise
    except Exception as exc:
        logger.exception(
            "Required Flow run redispatch audit transaction failed",
            extra={"run_id": str(run_id), "tenant_id": str(tenant_id)},
        )
        raise AuditLoggingUnavailableException(
            "Redispatch audit logging is unavailable.",
            code=FlowApiErrorCode.RUN_REDISPATCH_AUDIT_UNAVAILABLE.value,
            context={"audit_required": True},
        ) from exc
    return await dispatch_flow_run_recoverably_after_commit(
        run_id=run_id,
        tenant_id=tenant_id,
        expected_revision=expected_revision,
    )


def _dispatch_exhausted_error() -> FlowRunError:
    return FlowRunError.from_source(
        FlowRunLifecycleSource.DISPATCH_FAILURE,
        code=FlowApiErrorCode.RUN_DISPATCH_FAILED,
        message=(
            "flow_dispatch_failed: Flow run dispatch exhausted its bounded attempts."
        ),
    )

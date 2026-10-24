from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
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
    FLOW_WEBHOOK_DELIVERY_CONCURRENCY,
    FlowWebhookDeliveryBudget,
    FlowWebhookDeliveryDeadline,
    flow_webhook_delivery_budget,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS,
    FLOW_WORKER_SHUTDOWN_WRITE_TIMEOUT_SECONDS,
    FlowRunRecoveryKind,
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
from eneo.flows.flow_run_error import (
    FlowRunError,
    FlowRunErrorDetails,
    FlowRunRecoveryFacts,
)
from eneo.flows.flow_runtime_policy import resolve_flow_runtime_policy
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRecoveryCandidate,
    FlowRunRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRow,
)
from eneo.flows.runtime.execution_heartbeat import (
    FlowExecutionOwnershipLost,
    execution_heartbeats,
)
from eneo.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from eneo.flows.runtime.flow_run_actor import (
    FlowRunActor,
    FlowRunActorError,
    FlowRunServicePrincipalInactiveError,
)
from eneo.flows.runtime.flow_runtime_trace import FlowRunSpanContext, trace_flow_run
from eneo.flows.runtime.flow_webhook_delivery import FlowWebhookDeliveryResult
from eneo.flows.runtime.remote_transcription import connect_speaker_service
from eneo.flows.runtime.service_transcription import (
    RegistryFlowTranscriber,
    ServiceFlowTranscriber,
)
from eneo.flows.runtime.transcription import FlowTranscribers
from eneo.main.config import get_settings
from eneo.main.container.container import Container, SessionProxy
from eneo.main.logging import get_logger
from eneo.main.request_context import clear_request_context, set_request_context
from eneo.mcp_servers.application.unattended_tool_call import UnattendedToolCaller
from eneo.mcp_servers.infrastructure.repo_impl.unattended_tool_facts_reader import (
    UnattendedToolFactsReader,
)
from eneo.object_content.deployment_policy import load_upload_admission_snapshot
from eneo.object_content.runtime import object_content_runtime
from eneo.tasks.routing import FLOW_DRAIN_RETIRED_RUNS_TASK
from eneo.transcription_services.repository import (
    TranscriptionServiceConnectionRepository,
)
from eneo.users.user_repo import UsersRepository

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.files.transcriber import Transcriber
    from eneo.flows.runtime.transcription import FlowStepTranscriber
    from eneo.settings.encryption_service import EncryptionService
    from eneo.transcription_services.models import TranscriptionServiceConnection

logger = get_logger(__name__)


def enable_autobegin_for_flow_task_session(session: AsyncSession) -> None:
    """Flow runtime uses commit-heavy repos; enable autobegin for this task session."""
    session.sync_session.autobegin = True


@asynccontextmanager
async def audit_service_on_own_session(
    sessionless_container: Container,
) -> AsyncGenerator[AuditService]:
    """The audit service of a container built on SessionProxy, inside a short
    session of its own (Container.session_scope, closed when the scope ends).

    A tool or HTTP input read queues its audit record with it: a write that
    outlives its time limit is left to unwind and must not do that on the
    run's session, which the run goes on using. The scope sets the session
    only in the context of the write that opens it."""
    async with Container.session_scope():
        yield sessionless_container.audit_service()


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
    invocation_deadline: float | None,
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
            invocation_deadline=invocation_deadline,
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
    invocation_deadline: float | None,
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
            # Read before the claim stamps the lease, so its commit counts
            # against the lease the heartbeats then keep.
            leased_at = time.monotonic()
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

            async with execution_heartbeats().track(
                FlowRunExecutionOwner(run_id, tenant_id, run_revision),
                leased_at=leased_at,
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
                    result = {
                        "status": "failed",
                        "reason": "service_principal_disabled",
                    }
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
                rag_evidence_policy = resolve_flow_rag_evidence_policy(
                    tenant.flow_settings
                )
                runtime_file_service = runtime_container.file_service(
                    user=None,
                    owner=run_actor.principal.file_owner(tenant_id=tenant_id),
                )

                executor = FlowRunExecutor(
                    invocation_deadline=invocation_deadline,
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
                    read_audit_service=partial(
                        audit_service_on_own_session,
                        Container(session=providers.Object(SessionProxy())),
                    ),
                    references_service=runtime_container.references_service(
                        datastore__create_embeddings_service__user=run_actor.user
                    ),
                    transcribers=_flow_transcribers(
                        runtime_container.transcriber(
                            file_service=runtime_file_service, user=run_actor.user
                        ),
                        repository=TranscriptionServiceConnectionRepository(
                            session, tenant_id=tenant_id
                        ),
                        encryption=runtime_container.encryption_service(),
                    ),
                    transcript_words_repo=runtime_container.flow_transcript_words_repo(),
                    tool_facts_reader=UnattendedToolFactsReader(session),
                    tool_caller=UnattendedToolCaller(
                        runtime_container.mcp_proxy_session_factory()
                    ),
                    config=FlowRunExecutorConfig.from_settings(
                        max_inline_text_bytes=get_settings().flow_max_inline_text_bytes,
                        input_limits=flow_limits,
                        max_audio_files=flow_limits.audio_max_files_per_run,
                        max_generic_files=flow_limits.max_files_per_run,
                        document_render_limits=document_render_limits,
                        runtime_policy=runtime_policy,
                        mapped_execution_policy=mapped_execution_policy,
                        rag_evidence_policy=rag_evidence_policy,
                        security_classification_enabled=tenant.security_enabled,
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


# Bounds the terminal write a job timeout or a task failure makes.
FLOW_TASK_FAILURE_WRITE_TIMEOUT_SECONDS = 10


async def terminalize_flow_run_failure(
    *,
    owner: FlowRunExecutionOwner,
    source: FlowRunLifecycleSource,
    error: FlowRunError,
) -> None:
    """Fail the run this task stopped executing, behind its execution-owner
    fence: a run another worker or a redispatch took over, a user or a review
    holds, or one waiting on an outbound delivery, is left as it is.

    The owner is the run this task claimed (``claimed_run``): the heartbeat
    context reset it on the way out. As the heartbeat reaper does, a provider call the task started has no
    known outcome once the run ends here, so none is presented as finished."""
    # Ownership loss is a CancelledError: caught here, it cannot read as the
    # write itself being cancelled.
    with suppress(FlowExecutionOwnershipLost):
        async with sessionmanager.session() as session, session.begin():
            container = Container(session=providers.Object(session))
            terminalizer = container.flow_run_terminalizer()
            result = await terminalizer.terminalize_interrupted_running_run(
                owner=owner, source=source, error=error
            )
            if result.did_transition:
                provider_calls = container.flow_provider_call_repo()
                await provider_calls.mark_started_calls_outcome_unknown_for_run(
                    run_id=owner.run_id,
                    tenant_id=owner.tenant_id,
                    reason=ProviderCallUnknownReason.WORKER_INTERRUPTED,
                )


async def _terminalize_flow_run_failure_from_task(
    *,
    owner: FlowRunExecutionOwner,
    task_id: str | None,
    source: FlowRunLifecycleSource,
    error: FlowRunError,
    timeout_seconds: float = FLOW_TASK_FAILURE_WRITE_TIMEOUT_SECONDS,
) -> None:
    try:
        async with asyncio.timeout(timeout_seconds):
            await terminalize_flow_run_failure(owner=owner, source=source, error=error)
    except Exception:
        logger.exception(
            "Flow run task terminalization failed",
            extra={
                "run_id": str(owner.run_id),
                "tenant_id": str(owner.tenant_id),
                "task_id": task_id,
                "source": source.value,
                "error_code": error.code,
            },
        )


async def _fail_run_stopped_by_worker_shutdown(
    *, owner: FlowRunExecutionOwner, task_id: str | None
) -> None:
    """End at once a run whose task the worker shutdown cancelled, instead of
    leaving it running until the heartbeat reaper calls it stalled.

    The write is bounded so a slow database cannot hold the shutdown, and it
    is the execution heartbeats' task, so a second cancellation cannot cut it
    short and the worker waits for it before closing its database; a job that
    only gets here after the worker stopped waiting starts none, and the
    heartbeat reaper ends the run. The run is not requeued: a step that was
    executing may have had effects, and repeating it needs idempotency the
    steps do not promise; the user retries or reruns.
    """
    write = execution_heartbeats().run_shutdown_write(
        _terminalize_flow_run_failure_from_task(
            owner=owner,
            task_id=task_id,
            source=FlowRunLifecycleSource.TASK_FAILURE,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.TASK_FAILURE,
                code=FlowApiErrorCode.RUN_WORKER_SHUTDOWN,
                message=(
                    "flow_worker_shutdown: The worker shut down before run completion."
                ),
            ),
            timeout_seconds=FLOW_WORKER_SHUTDOWN_WRITE_TIMEOUT_SECONDS,
        )
    )
    if write is not None:
        await asyncio.shield(write)


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
    # Before anything can be cancelled: the worker's shutdown waits for this
    # job, wherever a cancellation finds it, before closing its database.
    execution_heartbeats().hold_job()
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
        async with asyncio.timeout(
            get_settings().task_execution_timeout_seconds
        ) as invocation_timeout:
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
                invocation_deadline=invocation_timeout.when(),
            )
    except FlowExecutionOwnershipLost:
        return {"status": "skipped", "reason": "execution_ownership_lost"}
    except asyncio.CancelledError:
        # Each terminal write below ends only the run this job claimed: a job
        # that never did (a duplicate delivery, or one still claiming) leaves
        # it to its claimer, the redispatch or the heartbeat reaper.
        claimed = execution_heartbeats().claimed_run()
        if claimed is not None and execution_heartbeats().worker_is_shutting_down():
            await _fail_run_stopped_by_worker_shutdown(owner=claimed, task_id=task_id)
        raise
    except TimeoutError:
        error_message = (
            "flow_task_timeout: Flow execution timed out before task completion."
        )
        logger.exception(
            "Flow execution task timed out",
            extra={"run_id": run_id, "tenant_id": tenant_id, "task_id": task_id},
        )
        if (claimed := execution_heartbeats().claimed_run()) is not None:
            await _terminalize_flow_run_failure_from_task(
                owner=claimed,
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
        if (claimed := execution_heartbeats().claimed_run()) is not None:
            await _terminalize_flow_run_failure_from_task(
                owner=claimed,
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


# Review checkpoint inspection pages every awaiting-review run, healthy ones too.
_REVIEW_RECOVERY_KINDS = frozenset({FlowRunRecoveryKind.REVIEW_CHECKPOINT_INSPECTION})
# Expired heartbeats and exhausted dispatches page apart, so a backlog of healthy
# reviews anywhere in the deployment cannot delay their recovery.
_ACTIONABLE_RECOVERY_KINDS = frozenset(
    {
        FlowRunRecoveryKind.EXECUTION_HEARTBEAT_EXPIRED,
        FlowRunRecoveryKind.EXHAUSTED_DISPATCH,
    }
)


@dataclass
class _RecoveryWindow:
    """A finite window of recovery candidates of some kinds, paged in order and
    then wrapped, so newer arrivals cannot starve older ones."""

    kinds: frozenset[FlowRunRecoveryKind]
    cursor: tuple[datetime, UUID] | None = None
    end: tuple[datetime, UUID] | None = None

    async def next_page(
        self, run_repo: FlowRunRepository, *, limit: int
    ) -> list[FlowRunRecoveryCandidate]:
        if self.cursor is None or (self.end is not None and self.cursor >= self.end):
            self.cursor = self.end = None
        if self.end is None:
            self.end = await run_repo.recovery_sweep_boundary(kinds=self.kinds)
        page = (
            await run_repo.list_recovery_candidates(
                limit=limit, after=self.cursor, through=self.end, kinds=self.kinds
            )
            if self.end is not None
            else []
        )
        if not page:
            self.cursor = self.end = None
        return page


_actionable_recovery = _RecoveryWindow(_ACTIONABLE_RECOVERY_KINDS)
_review_recovery = _RecoveryWindow(_REVIEW_RECOVERY_KINDS)


async def _reconcile_stale_running_runs_all_tenants(
    *, limit: int = 100
) -> dict[str, int | str]:
    reconciled = 0
    abandoned = 0
    review_checkpoint_invariant_violations = 0
    skipped_tenant_ids: list[UUID] = []
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        run_repo = container.flow_run_repo()
        provider_call_repo = container.flow_provider_call_repo()
        terminalizer = container.flow_run_terminalizer()
        async with session.begin():
            candidates = [
                (window, run)
                for window in (_actionable_recovery, _review_recovery)
                for run in await window.next_page(run_repo, limit=limit)
            ]
        for window, run in candidates:
            try:
                if run.kind == FlowRunRecoveryKind.REVIEW_CHECKPOINT_INSPECTION:
                    continue
                if run.kind == FlowRunRecoveryKind.MISSING_REVIEW_CHECKPOINT:
                    review_checkpoint_invariant_violations += 1
                    logger.error(
                        "Awaiting-review Flow run has no active checkpoint",
                        extra={
                            "invariant": run.kind.value,
                            "run_id": str(run.id),
                            "tenant_id": str(run.tenant_id),
                        },
                    )
                    continue
                async with session.begin():
                    if (facts := run.abandonment) is not None:
                        result = await terminalizer.terminalize_abandoned_run(
                            run_id=run.id,
                            tenant_id=run.tenant_id,
                            expected_revision=run.revision,
                            facts=facts,
                        )
                        if result.did_transition:
                            abandoned += 1
                        continue
                    result = await terminalizer.terminalize_stale_running_run(
                        run_id=run.id,
                        tenant_id=run.tenant_id,
                        expected_revision=run.revision,
                        error=FlowRunError.from_source(
                            FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                            code=FlowApiErrorCode.RUN_WORKER_STALLED,
                            message="flow_worker_stalled: Flow execution heartbeat expired.",
                            details=FlowRunErrorDetails(
                                recovery=FlowRunRecoveryFacts(
                                    reason="execution_heartbeat_expired",
                                    heartbeat_at=run.anchor_at,
                                    expires_at=run.anchor_at
                                    + timedelta(
                                        seconds=FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS
                                    ),
                                )
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
                skipped_tenant_ids.append(run.tenant_id)
                _log_tenant_sweep_failure(
                    task_name="flows.reconcile_running", tenant_id=run.tenant_id
                )
            finally:
                # Advance even after failure so one old run cannot starve other tenants.
                window.cursor = run.cursor
    _fail_task_if_tenants_were_skipped(
        task_name="flows.reconcile_running", skipped_tenant_ids=skipped_tenant_ids
    )
    return {
        "status": "ok",
        "reconciled": reconciled,
        "abandoned": abandoned,
        "review_checkpoint_invariant_violations": review_checkpoint_invariant_violations,
    }


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
            tenant_ids = await tenant_repo.get_all_tenant_ids()
        for tenant_id in tenant_ids:
            try:
                for _ in range(limit):
                    async with session.begin():
                        reconciler = container.flow_review_expiry_reconciler()
                        did_reconcile = (
                            await reconciler.reconcile_next_expired_checkpoint(
                                tenant_id=tenant_id,
                            )
                        )
                    if did_reconcile == 0:
                        break
                    reconciled += did_reconcile
            except Exception:
                skipped_tenant_ids.append(tenant_id)
                _log_tenant_sweep_failure(
                    task_name="flows.reconcile_review_expiry", tenant_id=tenant_id
                )
    _fail_task_if_tenants_were_skipped(
        task_name="flows.reconcile_review_expiry",
        skipped_tenant_ids=skipped_tenant_ids,
    )
    return {"status": "ok", "reconciled": reconciled}


async def _drain_retired_flow_runs(*, limit: int = 100) -> dict[str, int | str]:
    """Cancel the queued, running and awaiting-review runs of deleted flows.

    Deleting a flow does not wait for its runs; this sweep ends the oldest
    `limit` of them, one run per transaction. A run that reached a terminal
    state first is left as it is. A run that cannot be cancelled is rolled
    back and logged, the sweep goes on, and the task then fails so the failure
    is visible.
    """
    error = FlowRunError.from_source(
        FlowRunLifecycleSource.FLOW_DELETED,
        code=FlowApiErrorCode.FLOW_DELETED,
        message="Flow was deleted before the run finished.",
    )
    cancelled = 0
    failed = 0
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(session=providers.Object(session))
        terminalizer = container.flow_run_terminalizer()
        async with session.begin():
            runs = await container.flow_run_repo().list_active_runs_of_deleted_flows(
                limit=limit
            )
        for run_id, tenant_id in runs:
            try:
                async with session.begin():
                    result = await terminalizer.terminalize_run(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        target_status=FlowRunStatus.CANCELLED,
                        source=FlowRunLifecycleSource.FLOW_DELETED,
                        error=error,
                        cancelled_at=datetime.now(timezone.utc),
                    )
            except Exception:
                failed += 1
                logger.exception(
                    "Retired-flow run drain could not cancel a run",
                    extra={"run_id": str(run_id)},
                )
                continue
            cancelled += int(result.did_transition)
    if failed:
        raise RuntimeError(
            f"{FLOW_DRAIN_RETIRED_RUNS_TASK} could not cancel {failed} run(s)"
        )
    return {"status": "ok", "cancelled": cancelled}


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
            tenant_ids = await tenant_repo.get_all_tenant_ids()
        for tenant_id in tenant_ids:
            try:
                async with session.begin():
                    due_runs = await run_repo.list_dispatchable_queued_runs(
                        tenant_id=tenant_id,
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
                skipped_tenant_ids.append(tenant_id)
                _log_tenant_sweep_failure(
                    task_name="flows.redispatch_stale_queued", tenant_id=tenant_id
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
    *,
    budget: FlowWebhookDeliveryBudget,
    limit: int = FLOW_WEBHOOK_DELIVERY_BATCH_SIZE,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, int | str]:
    """Claim and deliver due webhooks in waves of the concurrency until a wave
    claims nothing or the job deadline no longer covers a whole delivery.
    ``clock`` is what the claims call "now"; only tests replace it.

    Claims, deliveries and their recording are all cut at the budget's hard
    stop. A delivery cut there keeps its claim; the job then returns its counts
    with the hard_stopped status and logs them once."""
    loop = asyncio.get_running_loop()
    deadline = budget.deadline(started_at=loop.time())
    result = FlowWebhookDeliveryResult()
    wave: list[asyncio.Task[FlowWebhookDeliveryResult]] = []
    hard_stop = asyncio.timeout_at(deadline.hard_stop_at)
    try:
        async with hard_stop:
            remaining = limit
            # A claim session dead-letters expired claims before it checks the
            # deadline, so none opens once a new wave no longer fits.
            while remaining > 0 and deadline.allows_new_wave(loop.time()):
                async with sessionmanager.session() as session:
                    enable_autobegin_for_flow_task_session(session)
                    async with session.begin():
                        container = Container(session=providers.Object(session))
                        service = container.flow_run_webhook_delivery_service()
                        batch = await service.claim_due_batch(
                            now=clock(),
                            limit=min(FLOW_WEBHOOK_DELIVERY_CONCURRENCY, remaining),
                            deadline=deadline,
                        )
                result = result.combine(batch.result)
                if not batch.claimed_rows:
                    break
                remaining -= len(batch.claimed_rows) + batch.result.dead_lettered_count
                async with asyncio.TaskGroup() as task_group:
                    wave = [
                        task_group.create_task(
                            _deliver_claimed_webhook(row=row, deadline=deadline)
                        )
                        for row in batch.claimed_rows
                    ]
                for delivery_task in wave:
                    result = result.combine(delivery_task.result())
                wave = []
    except TimeoutError:
        if not hard_stop.expired():
            raise
        ended = [task for task in wave if not task.cancelled()]
        for delivery_task in ended:
            result = result.combine(delivery_task.result())
        result = result.combine(
            FlowWebhookDeliveryResult(unfinished_count=len(wave) - len(ended))
        )
        payload = result.to_task_payload(status="hard_stopped")
        logger.error(
            "Flow webhook outbox job reached its hard stop; unfinished deliveries "
            "keep their claims until they expire",
            extra=payload,
        )
        return payload
    return result.to_task_payload()


async def _deliver_claimed_webhook(
    *,
    row: FlowRunWebhookDeliveryRow,
    deadline: FlowWebhookDeliveryDeadline,
) -> FlowWebhookDeliveryResult:
    try:
        async with sessionmanager.session() as delivery_session:
            enable_autobegin_for_flow_task_session(delivery_session)
            delivery_container = Container(session=providers.Object(delivery_session))
            delivery_service = delivery_container.flow_run_webhook_delivery_service()
            try:
                return await delivery_service.deliver_claimed(
                    row=row, deadline=deadline
                )
            except asyncio.CancelledError:
                logger.error(
                    "Flow webhook delivery was stopped before it ended; its claim "
                    "stays until it expires unless its outcome was already committed",
                    extra={
                        "delivery_id": str(row.id),
                        "flow_run_id": str(row.flow_run_id),
                    },
                )
                raise
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Flow webhook delivery worker failed before recording an outcome",
            extra={"delivery_id": str(row.id)},
        )
        return FlowWebhookDeliveryResult(attempted_count=1)


async def reconcile_stale_running_runs() -> dict[str, int | str]:
    return await _reconcile_stale_running_runs_all_tenants()


async def reconcile_expired_review_checkpoints() -> dict[str, int | str]:
    return await _reconcile_expired_review_checkpoints_all_tenants()


async def drain_retired_flow_runs() -> dict[str, int | str]:
    return await _drain_retired_flow_runs()


async def redispatch_stale_queued_runs() -> dict[str, int | str]:
    return await _redispatch_stale_queued_runs_all_tenants()


async def deliver_flow_audit_outbox() -> dict[str, int | str]:
    return await _deliver_flow_audit_outbox()


async def deliver_flow_webhook_outbox() -> dict[str, int | str]:
    return await _deliver_flow_webhook_outbox(budget=flow_webhook_delivery_budget())


def _flow_transcribers(
    registry_transcriber: "Transcriber",
    *,
    repository: TranscriptionServiceConnectionRepository,
    encryption: "EncryptionService",
) -> FlowTranscribers:
    """The flow's model transcribes; a step whose flow chose a transcription
    service adds the service it resolved from the flow's space."""

    async def with_speaker_service(
        connection: "TranscriptionServiceConnection",
    ) -> FlowStepTranscriber:
        return ServiceFlowTranscriber(
            registry_transcriber,
            await connect_speaker_service(
                connection.id,
                repository=repository,
                encryption=encryption,
                include_speaker_review=get_settings().flow_transcription_include_speaker_review,
            ),
        )

    return FlowTranscribers(
        model=RegistryFlowTranscriber(registry_transcriber),
        with_speaker_service=with_speaker_service,
    )

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.outcome import Outcome
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_MAX_ATTEMPTS,
    FlowWebhookDeliveryDeadline,
    flow_webhook_retry_delay_seconds,
    sanitize_webhook_delivery_error,
)
from eneo.flows.domain.flow import FlowRun, FlowRunStatus, FlowStepResult
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FlowApiErrorCode,
)
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
    FlowRunWebhookDeliveryRow,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import (
    PublishedDefinitionChecksumMismatchError,
    parse_verified_published_definition,
)
from eneo.flows.runtime.execution_state_builder import build_run_execution_state
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.http_audit import HttpAuditDeps
from eneo.flows.runtime.http_audit import (
    audit_http_outbound as audit_http_outbound_runtime,
)
from eneo.flows.runtime.http_orchestration import (
    FlowHttpOrchestrationDeps,
    WebhookDeliveryError,
    WebhookSendNotStartedError,
    deliver_webhook,
)
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.run_outcome import finalize_run_from_current_results
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import BadRequestException, TypedIOValidationException
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.tenant_repo import TenantRepository
from eneo.users.user_repo import UsersRepository

logger = logging.getLogger(__name__)

# Typed failures that repeat on every attempt, so they are not retried: compiling
# the delivery from the published definition, and a destination the sender
# refuses (the address is not allowed, or the URL is not one a flow may send to).
_PERMANENT_DELIVERY_ERROR_CODES = frozenset(
    {
        FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
        FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        FlowApiErrorCode.TYPED_IO_HTTP_INVALID_URL.value,
        FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED.value,
    }
)


@dataclass(frozen=True, slots=True)
class FlowWebhookDeliveryResult:
    attempted_count: int = 0
    delivered_count: int = 0
    retry_scheduled_count: int = 0
    dead_lettered_count: int = 0
    # Claims handed back with their attempt because the send never started.
    released_count: int = 0
    # Claimed deliveries the job's hard stop cut before they ended; they keep
    # their claim, so their outcome is unknown until it expires.
    unfinished_count: int = 0

    def combine(self, other: FlowWebhookDeliveryResult) -> FlowWebhookDeliveryResult:
        return FlowWebhookDeliveryResult(
            attempted_count=self.attempted_count + other.attempted_count,
            delivered_count=self.delivered_count + other.delivered_count,
            retry_scheduled_count=(
                self.retry_scheduled_count + other.retry_scheduled_count
            ),
            dead_lettered_count=self.dead_lettered_count + other.dead_lettered_count,
            released_count=self.released_count + other.released_count,
            unfinished_count=self.unfinished_count + other.unfinished_count,
        )

    def to_task_payload(
        self, *, status: Literal["ok", "hard_stopped"] = "ok"
    ) -> dict[str, int | str]:
        return {
            "status": status,
            "attempted": self.attempted_count,
            "delivered": self.delivered_count,
            "retry_scheduled": self.retry_scheduled_count,
            "dead_lettered": self.dead_lettered_count,
            "released": self.released_count,
            "unfinished": self.unfinished_count,
        }


@dataclass(frozen=True, slots=True)
class FlowWebhookDeliveryBatch:
    claimed_rows: list[FlowRunWebhookDeliveryRow]
    result: FlowWebhookDeliveryResult


@dataclass(frozen=True, slots=True)
class WebhookDeliveryPayload:
    run: FlowRun
    step: RuntimeStep
    step_result: FlowStepResult
    text_payload: str
    context: dict[str, Any]
    audit_actor: FlowRunActor | None


class WebhookDeliveryClaimLostError(RuntimeError):
    pass


class WebhookDeliveryAttemptBudgetExhaustedError(RuntimeError):
    pass


class FlowRunWebhookDeliveryService:
    def __init__(
        self,
        *,
        webhook_delivery_repo: FlowRunWebhookDeliveryRepository,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_version_repo: FlowVersionRepository,
        flow_run_terminalizer: FlowRunTerminalizer,
        encryption_service: EncryptionService,
        audit_service: AuditService | None,
        user_repo: UsersRepository,
        api_key_repo: ApiKeysV2Repository,
        tenant_repo: TenantRepository,
        http_runtime: FlowHttpRuntimeHelper,
    ) -> None:
        self.webhook_delivery_repo = webhook_delivery_repo
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_version_repo = flow_version_repo
        self.flow_run_terminalizer = flow_run_terminalizer
        self.encryption_service = encryption_service
        self.audit_service = audit_service
        self.user_repo = user_repo
        self.api_key_repo = api_key_repo
        self.tenant_repo = tenant_repo
        self.http_runtime = http_runtime
        self.variable_resolver = FlowVariableResolver()

    async def claim_due_batch(
        self,
        *,
        now: datetime,
        limit: int,
        deadline: FlowWebhookDeliveryDeadline,
    ) -> FlowWebhookDeliveryBatch:
        """Dead-letter claims that expired on their last attempt, then claim due
        rows if the deadline still covers a whole delivery."""
        if limit <= 0:
            return FlowWebhookDeliveryBatch(
                claimed_rows=[],
                result=FlowWebhookDeliveryResult(),
            )

        exhausted_rows = (
            await self.webhook_delivery_repo.lock_expired_at_budget_delivery_rows(
                now=now,
                limit=limit,
                max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
            )
        )
        dead_lettered = 0
        for row in exhausted_rows:
            try:
                await self._record_failure(
                    row=row,
                    error=WebhookDeliveryAttemptBudgetExhaustedError(
                        "Webhook delivery claim expired after the final allowed "
                        "attempt; the remote outcome is unknown and the payload may "
                        "have been delivered."
                    ),
                    force_dead_letter=True,
                )
            except WebhookDeliveryClaimLostError:
                continue
            dead_lettered += 1

        remaining_limit = limit - len(exhausted_rows)
        claimed_rows: list[FlowRunWebhookDeliveryRow] = []
        if remaining_limit > 0 and deadline.allows_new_wave(
            asyncio.get_running_loop().time()
        ):
            claimed_rows = await self.webhook_delivery_repo.claim_due_delivery_rows(
                now=now,
                limit=remaining_limit,
                claim_ttl_seconds=deadline.budget.claim_ttl_seconds,
                max_attempts=FLOW_WEBHOOK_MAX_ATTEMPTS,
            )
        return FlowWebhookDeliveryBatch(
            claimed_rows=claimed_rows,
            result=FlowWebhookDeliveryResult(dead_lettered_count=dead_lettered),
        )

    async def deliver_claimed(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        deadline: FlowWebhookDeliveryDeadline,
    ) -> FlowWebhookDeliveryResult:
        attempted_result = FlowWebhookDeliveryResult(attempted_count=1)
        payload_prepared = False
        try:
            payload = await self._prepare_before_sends_end(row=row, deadline=deadline)
            payload_prepared = True
            try:
                await self._deliver_payload(row=row, payload=payload, deadline=deadline)
            finally:
                # Audit policy reads share this task-scoped session. Discard
                # their read transaction before persisting the delivery outcome.
                if self.webhook_delivery_repo.session.in_transaction():
                    await self.webhook_delivery_repo.session.rollback()
        except WebhookSendNotStartedError:
            return await self._release_unsent_claim(row=row)
        except (
            BadRequestException,
            FlowPublishedDefinitionWithoutExecutableStepsError,
        ) as exc:
            failure_codes = {
                exc.code if isinstance(exc, BadRequestException) else None,
                (
                    exc.__cause__.code
                    if isinstance(exc.__cause__, TypedIOValidationException)
                    else None
                ),
            }
            permanent_failure = payload_prepared and bool(
                failure_codes & _PERMANENT_DELIVERY_ERROR_CODES
            )
            terminal_error = (
                self._terminal_error_for_definition_failure(
                    error=exc,
                    step_order=row.step_order,
                )
                if not payload_prepared
                else None
            )
            try:
                async with self.webhook_delivery_repo.session.begin():
                    did_dead_letter = await self._record_failure(
                        row=row,
                        error=exc,
                        force_dead_letter=(
                            terminal_error is not None or permanent_failure
                        ),
                        terminal_error=terminal_error,
                    )
            except WebhookDeliveryClaimLostError:
                return attempted_result
            return attempted_result.combine(
                FlowWebhookDeliveryResult(
                    dead_lettered_count=int(did_dead_letter),
                    retry_scheduled_count=int(not did_dead_letter),
                )
            )
        except ValueError as exc:
            try:
                async with self.webhook_delivery_repo.session.begin():
                    did_dead_letter = await self._record_failure(
                        row=row,
                        error=exc,
                        force_dead_letter=True,
                    )
            except WebhookDeliveryClaimLostError:
                return attempted_result
            return attempted_result.combine(
                FlowWebhookDeliveryResult(dead_lettered_count=int(did_dead_letter))
            )
        except WebhookDeliveryError as exc:
            # Only 4xx (bar 408/429) is terminal. A 3xx is not followed and
            # retries within the bounded attempts: a redirect can be temporary.
            terminal_http_failure = (
                exc.status_code is not None
                and 400 <= exc.status_code < 500
                and exc.status_code not in {408, 429}
            )
            try:
                async with self.webhook_delivery_repo.session.begin():
                    did_dead_letter = await self._record_failure(
                        row=row,
                        error=exc,
                        force_dead_letter=terminal_http_failure,
                    )
            except WebhookDeliveryClaimLostError:
                return attempted_result
            return attempted_result.combine(
                FlowWebhookDeliveryResult(
                    dead_lettered_count=int(did_dead_letter),
                    retry_scheduled_count=int(not did_dead_letter),
                )
            )
        except Exception as exc:
            try:
                async with self.webhook_delivery_repo.session.begin():
                    did_dead_letter = await self._record_failure(
                        row=row,
                        error=exc,
                        force_dead_letter=False,
                    )
            except WebhookDeliveryClaimLostError:
                return attempted_result
            return attempted_result.combine(
                FlowWebhookDeliveryResult(
                    dead_lettered_count=int(did_dead_letter),
                    retry_scheduled_count=int(not did_dead_letter),
                )
            )
        else:
            try:
                async with self.webhook_delivery_repo.session.begin():
                    did_mark = await self._record_success(
                        row=row,
                        payload=payload,
                    )
            except WebhookDeliveryClaimLostError:
                return attempted_result
            return attempted_result.combine(
                FlowWebhookDeliveryResult(delivered_count=int(did_mark))
            )

    async def _prepare_before_sends_end(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        deadline: FlowWebhookDeliveryDeadline,
    ) -> WebhookDeliveryPayload:
        preparation = asyncio.timeout_at(deadline.sends_end_at)
        try:
            async with preparation:
                async with self.webhook_delivery_repo.session.begin():
                    return await self._prepare_delivery_payload(row=row)
        except TimeoutError as exc:
            if preparation.expired():
                raise WebhookSendNotStartedError(
                    "The webhook delivery job ran out of time while preparing "
                    "the request."
                ) from exc
            raise

    async def _release_unsent_claim(
        self, *, row: FlowRunWebhookDeliveryRow
    ) -> FlowWebhookDeliveryResult:
        async with self.webhook_delivery_repo.session.begin():
            released = await self.webhook_delivery_repo.release_unsent_claim(
                delivery_id=row.id, claim_token=row.claim_token
            )
        return FlowWebhookDeliveryResult(released_count=int(released))

    @staticmethod
    def _terminal_error_for_definition_failure(
        *,
        error: BadRequestException | FlowPublishedDefinitionWithoutExecutableStepsError,
        step_order: int,
    ) -> FlowRunError:
        if isinstance(error, PublishedDefinitionChecksumMismatchError):
            return FlowRunError.from_source(
                FlowRunLifecycleSource.DEFINITION_CHECKSUM_MISMATCH,
                code=FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH,
                message=str(error),
                step_order=step_order,
            )
        if isinstance(error, FlowPublishedDefinitionWithoutExecutableStepsError):
            return FlowRunError.from_source(
                FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
                code=FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS,
                message=str(error),
                step_order=step_order,
            )
        try:
            parsed_error_code = (
                FlowApiErrorCode(error.code)
                if error.code is not None
                else FlowApiErrorCode.DEFINITION_INVALID
            )
        except ValueError:
            parsed_error_code = FlowApiErrorCode.DEFINITION_INVALID
        error_code = (
            parsed_error_code
            if parsed_error_code in FLOW_RUN_TERMINAL_ERROR_CODES
            else FlowApiErrorCode.DEFINITION_INVALID
        )
        return FlowRunError.from_source(
            FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
            code=error_code,
            message=str(error),
            step_order=step_order,
        )

    async def _prepare_delivery_payload(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
    ) -> WebhookDeliveryPayload:
        run = await self.flow_run_repo.get(
            run_id=row.flow_run_id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
        )
        if run.status != FlowRunStatus.RUNNING:
            raise ValueError("Webhook delivery run is no longer running.")
        flow_version = await self.flow_version_repo.get(
            flow_id=row.flow_id,
            version=run.flow_version,
            tenant_id=row.tenant_id,
        )
        definition = parse_verified_published_definition(
            flow_version.definition_json,
            expected_flow_id=row.flow_id,
            expected_checksum=flow_version.definition_checksum,
            flow_version=flow_version.version,
        )
        steps = definition.runtime_steps()
        step = next((item for item in steps if item.step_id == row.step_id), None)
        if step is None:
            raise ValueError(
                "Webhook delivery step is missing from published snapshot."
            )
        results = await self.flow_run_repo.list_step_results(
            run_id=row.flow_run_id,
            tenant_id=row.tenant_id,
        )
        step_result = next(
            (item for item in results if item.step_id == row.step_id),
            None,
        )
        if step_result is None:
            raise ValueError("Webhook delivery step result is missing.")
        if step_result.current_attempt_no != row.attempt_no:
            raise ValueError("Webhook delivery attempt no longer matches step result.")
        audit_actor = await self._resolve_audit_actor(run)
        payload = step_result.output_payload_json or {}
        try:
            text = interpret_step_text(payload)
        except StepOutputMetadataError as exc:
            raise ValueError(
                "Webhook delivery step result has malformed text metadata."
            ) from exc
        if isinstance(text, FileBackedStepText):
            raise ValueError(
                "Webhook delivery requires complete text, but complete text is "
                "stored in a generated output file."
            )
        text_payload = text.text

        state = build_run_execution_state(
            steps=steps,
            persisted_results=results,
        )
        context = self.variable_resolver.build_context(
            run.input_payload_json,
            state.prior_results,
            current_step_order=step.step_order + 1,
            step_names_by_order=state.step_names_by_order,
            step_ref_mapping=state.step_ref_mapping,
        )
        context["text"] = text_payload
        structured = payload.get("structured")
        if isinstance(structured, dict | list):
            context["structured"] = structured

        return WebhookDeliveryPayload(
            run=run,
            step=step,
            step_result=step_result,
            text_payload=text_payload,
            context=context,
            audit_actor=audit_actor,
        )

    async def _deliver_payload(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        payload: WebhookDeliveryPayload,
        deadline: FlowWebhookDeliveryDeadline,
    ) -> None:
        async def audit_http_outbound(
            *,
            run: FlowRun,
            step: RuntimeStep,
            url: str,
            method: str,
            call_type: str,
            outcome: Outcome,
            error_message: str | None = None,
            status_code: int | None = None,
            duration_ms: float | None = None,
        ) -> None:
            await self._audit_http_outbound(
                run=run,
                step=step,
                url=url,
                method=method,
                call_type=call_type,
                outcome=outcome,
                error_message=error_message,
                status_code=status_code,
                duration_ms=duration_ms,
                audit_actor=payload.audit_actor,
                ends_at=deadline.ends_at,
            )

        deps = FlowHttpOrchestrationDeps(
            encryption_service=self.encryption_service,
            variable_resolver=self.variable_resolver,
            resolve_timeout_seconds=self.http_runtime.resolve_timeout_seconds,
            read_response_text=self.http_runtime.read_response_text,
            send_http_request=self.http_runtime.send_request,
            audit_http_outbound=audit_http_outbound,
        )
        await deliver_webhook(
            step=payload.step,
            text_payload=payload.text_payload,
            run=payload.run,
            context=payload.context,
            deps=deps,
            idempotency_key=row.idempotency_key,
            sends_end_at=deadline.sends_end_at,
        )

    async def _record_success(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        payload: WebhookDeliveryPayload,
    ) -> bool:
        # Preserve the active-run write guard before marking delivery succeeded.
        saved_result = await self.flow_run_repo.save_step_result(
            row.flow_run_id,
            payload.step_result,
            tenant_id=row.tenant_id,
            attempt_no=row.attempt_no,
        )
        if saved_result is None:
            return False

        did_mark = await self.webhook_delivery_repo.mark_delivery_succeeded(
            delivery_id=row.id,
            claim_token=row.claim_token,
            delivered_at=datetime.now(timezone.utc),
        )
        if not did_mark:
            raise WebhookDeliveryClaimLostError(
                "Webhook delivery claim was lost before success could be recorded."
            )

        results = await self.flow_run_repo.list_step_results(
            run_id=row.flow_run_id,
            tenant_id=row.tenant_id,
        )
        await finalize_run_from_current_results(
            run_id=row.flow_run_id,
            tenant_id=row.tenant_id,
            results=results,
            terminalizer=self.flow_run_terminalizer,
        )
        return True

    async def _record_failure(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        error: Exception,
        force_dead_letter: bool,
        terminal_error: FlowRunError | None = None,
    ) -> bool:
        # The backoff counts from the failure, not from the claim: a slow
        # request must not leave the retry already due.
        failed_at = datetime.now(timezone.utc)
        retry_delay = (
            None
            if force_dead_letter
            else flow_webhook_retry_delay_seconds(
                failed_attempt_no=row.delivery_attempts
            )
        )
        dead_lettered_at = failed_at if retry_delay is None else None
        next_delivery_at = (
            None if retry_delay is None else failed_at + timedelta(seconds=retry_delay)
        )
        error_message = sanitize_webhook_delivery_error(error)

        did_record = await self.webhook_delivery_repo.record_delivery_failure(
            delivery_id=row.id,
            claim_token=row.claim_token,
            error_message=error_message,
            next_delivery_at=next_delivery_at,
            dead_lettered_at=dead_lettered_at,
        )
        if not did_record:
            raise WebhookDeliveryClaimLostError(
                "Webhook delivery claim was lost before failure could be recorded."
            )

        if dead_lettered_at is not None:
            await self.flow_run_terminalizer.terminalize_run(
                run_id=row.flow_run_id,
                tenant_id=row.tenant_id,
                target_status=FlowRunStatus.FAILED,
                source=(
                    terminal_error.source
                    if terminal_error is not None and terminal_error.source is not None
                    else FlowRunLifecycleSource.EXECUTOR_FAILED
                ),
                error=terminal_error
                or FlowRunError.from_source(
                    FlowRunLifecycleSource.EXECUTOR_FAILED,
                    code=FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED,
                    message=f"Webhook delivery failed: {error_message}",
                    step_order=row.step_order,
                ),
            )
        return dead_lettered_at is not None

    async def _resolve_audit_actor(self, run: FlowRun) -> FlowRunActor | None:
        if self.audit_service is None:
            return None

        principal_type = run.principal_type
        if principal_type == PrincipalType.USER:
            user_id = run.principal_user_id
            if user_id is None:
                raise ValueError("Webhook delivery run has no user principal.")
            user = await self.user_repo.get_user_by_id_and_tenant_id(
                id=user_id,
                tenant_id=run.tenant_id,
            )
            if user is None:
                raise ValueError("Webhook delivery audit user is missing.")
            return FlowRunActor.from_user_run(run=run, user=user)

        if principal_type == PrincipalType.SERVICE_KEY:
            if run.principal_service_id is None:
                raise ValueError("Webhook delivery run has no service-principal owner.")
            service_principal = await self.api_key_repo.get_service_principal(
                service_principal_id=run.principal_service_id,
                tenant_id=run.tenant_id,
            )
            if service_principal is None:
                raise ValueError("Webhook delivery service principal is missing.")
            return FlowRunActor.from_service_principal_run(
                run=run,
                service_principal=service_principal,
            )

        raise ValueError("Webhook delivery run has an unsupported principal type.")

    async def _audit_http_outbound(
        self,
        *,
        run: FlowRun,
        step: RuntimeStep,
        url: str,
        method: str,
        call_type: str,
        outcome: Outcome,
        error_message: str | None = None,
        status_code: int | None = None,
        duration_ms: float | None = None,
        audit_actor: FlowRunActor | None,
        ends_at: float,
    ) -> None:
        if self.audit_service is None or audit_actor is None:
            return
        # The HTTP result is known by now; an audit still waiting at the job
        # deadline is given up so the outcome can be recorded before the hard
        # stop.
        deps = HttpAuditDeps(
            audit_service=self.audit_service,
            actor=audit_actor,
            logger=logger,
            ends_at=ends_at,
        )
        await audit_http_outbound_runtime(
            run=run,
            step=step,
            url=url,
            method=method,
            call_type=call_type,
            outcome=outcome,
            error_message=error_message,
            status_code=status_code,
            duration_ms=duration_ms,
            deps=deps,
        )

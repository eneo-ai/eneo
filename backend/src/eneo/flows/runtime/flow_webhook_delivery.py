from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

import httpx

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.outcome import Outcome
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_BATCH_SIZE,
    FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS,
    FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS,
    flow_webhook_retry_delay_seconds,
    sanitize_webhook_delivery_error,
)
from eneo.flows.domain.flow import FlowRun, FlowRunStatus, FlowStepResult
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
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
    deliver_webhook,
)
from eneo.flows.runtime.http_runtime import FlowHttpRuntimeHelper
from eneo.flows.runtime.models import RuntimeStep
from eneo.flows.runtime.run_outcome import finalize_run_from_current_results
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import BadRequestException
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.tenant_repo import TenantRepository
from eneo.users.user_repo import UsersRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FlowWebhookDeliveryResult:
    attempted_count: int = 0
    delivered_count: int = 0
    retry_scheduled_count: int = 0
    dead_lettered_count: int = 0

    def to_task_payload(self) -> dict[str, int | str]:
        return {
            "status": "ok",
            "attempted": self.attempted_count,
            "delivered": self.delivered_count,
            "retry_scheduled": self.retry_scheduled_count,
            "dead_lettered": self.dead_lettered_count,
        }


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

    async def deliver_due(
        self,
        *,
        now: datetime,
        limit: int = FLOW_WEBHOOK_DELIVERY_BATCH_SIZE,
    ) -> FlowWebhookDeliveryResult:
        if limit <= 0:
            return FlowWebhookDeliveryResult()

        attempted = 0
        delivered = 0
        retry_scheduled = 0
        dead_lettered = 0
        started_at = monotonic()
        while attempted < limit:
            if (
                attempted > 0
                and monotonic() - started_at >= FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS
            ):
                break
            rows = await self.webhook_delivery_repo.claim_due_delivery_rows(
                now=now,
                limit=1,
                claim_ttl_seconds=FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS,
            )
            await self.webhook_delivery_repo.session.commit()
            if not rows:
                break

            row = rows[0]
            attempted += 1
            payload_prepared = False
            try:
                async with self.webhook_delivery_repo.session.begin():
                    payload = await self._prepare_delivery_payload(row=row)
                payload_prepared = True
                await self._deliver_payload(row=row, payload=payload)
            except (
                BadRequestException,
                FlowPublishedDefinitionWithoutExecutableStepsError,
            ) as exc:
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
                            now=now,
                            error=exc,
                            force_dead_letter=terminal_error is not None,
                            terminal_error=terminal_error,
                        )
                except WebhookDeliveryClaimLostError:
                    continue
                if did_dead_letter:
                    dead_lettered += 1
                else:
                    retry_scheduled += 1
            except ValueError as exc:
                try:
                    async with self.webhook_delivery_repo.session.begin():
                        did_dead_letter = await self._record_failure(
                            row=row,
                            now=now,
                            error=exc,
                            force_dead_letter=True,
                        )
                except WebhookDeliveryClaimLostError:
                    continue
                if did_dead_letter:
                    dead_lettered += 1
            except Exception as exc:
                try:
                    async with self.webhook_delivery_repo.session.begin():
                        did_dead_letter = await self._record_failure(
                            row=row,
                            now=now,
                            error=exc,
                            force_dead_letter=False,
                        )
                except WebhookDeliveryClaimLostError:
                    continue
                if did_dead_letter:
                    dead_lettered += 1
                else:
                    retry_scheduled += 1
            else:
                try:
                    async with self.webhook_delivery_repo.session.begin():
                        did_mark = await self._record_success(
                            row=row,
                            now=now,
                            payload=payload,
                        )
                except WebhookDeliveryClaimLostError:
                    continue
                if did_mark:
                    delivered += 1
        return FlowWebhookDeliveryResult(
            attempted_count=attempted,
            delivered_count=delivered,
            retry_scheduled_count=retry_scheduled,
            dead_lettered_count=dead_lettered,
        )

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
        text_payload = payload.get("text")
        if not isinstance(text_payload, str):
            raise ValueError("Webhook delivery step result has no text payload.")

        state = build_run_execution_state(
            steps=steps,
            persisted_results=results,
        )
        context = self.variable_resolver.build_context(
            run.input_payload_json,
            state.prior_results,
            current_step_order=step.step_order + 1,
            step_names_by_order=state.step_names_by_order,
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
            )

        deps = FlowHttpOrchestrationDeps(
            encryption_service=self.encryption_service,
            variable_resolver=self.variable_resolver,
            resolve_timeout_seconds=self.http_runtime.resolve_timeout_seconds,
            read_response_text=self.http_runtime.read_response_text,
            send_http_request=self._send_http_request,
            audit_http_outbound=audit_http_outbound,
        )
        await deliver_webhook(
            step=payload.step,
            text_payload=payload.text_payload,
            run=payload.run,
            context=payload.context,
            deps=deps,
            idempotency_key=row.idempotency_key,
        )

    async def _record_success(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        now: datetime,
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
            delivered_at=now,
            attempt_no=row.delivery_attempts + 1,
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
        now: datetime,
        error: Exception,
        force_dead_letter: bool,
        terminal_error: FlowRunError | None = None,
    ) -> bool:
        attempt_no = row.delivery_attempts + 1
        retry_delay = (
            None
            if force_dead_letter
            else flow_webhook_retry_delay_seconds(failed_attempt_no=attempt_no)
        )
        dead_lettered_at = now if retry_delay is None else None
        next_delivery_at = (
            None if retry_delay is None else now + timedelta(seconds=retry_delay)
        )
        error_message = sanitize_webhook_delivery_error(error)

        did_record = await self.webhook_delivery_repo.record_delivery_failure(
            delivery_id=row.id,
            claim_token=row.claim_token,
            attempt_no=attempt_no,
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

    async def _send_http_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        body_bytes: bytes | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        read_response_body: bool = True,
    ) -> httpx.Response:
        preflight_resolved_ips = await self.http_runtime.assert_url_allowed(url)
        return await self.http_runtime.send_request(
            method=method,
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            body_bytes=body_bytes,
            json_body=json_body,
            read_response_body=read_response_body,
            preflight_resolved_ips=preflight_resolved_ips,
            assert_connected_peer_allowed=self.http_runtime.assert_connected_peer_allowed,
        )

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
    ) -> None:
        if self.audit_service is None or audit_actor is None:
            return
        deps = HttpAuditDeps(
            audit_service=self.audit_service,
            actor=audit_actor,
            logger=logger,
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

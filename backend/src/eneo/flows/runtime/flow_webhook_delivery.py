from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileContentVariant
from eneo.files.file_repo import FileRepository
from eneo.flows.api.flow_run_contract_models import FlowRunTextDeliverablePublic
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
from eneo.flows.enums import FlowRunLifecycleSource, is_terminal_flow_run_status
from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FlowApiErrorCode,
)
from eneo.flows.flow_run_contract_service import (
    build_run_output_contract,
    project_run_deliverables,
)
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.http_transport import sends_run_result
from eneo.flows.http_transport.effective_url import parse_effective_http_url
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
from eneo.flows.runtime.run_result_body import (
    RunResultPart,
    RunResultText,
    check_run_result,
    run_result_body,
    run_result_file_ids,
    run_result_text,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.json_types import JsonValue
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    TypedIOValidationException,
)
from eneo.object_content.content import (
    ContentReadGrant,
    ObjectContentIntegrityError,
    ObjectContentStateError,
)
from eneo.object_content.content_service import ObjectContentService
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
    # The document a run_result body sends; None for a template body, which
    # is sent while its run is running. It holds content: never in a repr.
    run_result_body: JsonValue | None = field(default=None, repr=False)
    # The steps and files that body sends, for the audit row written before
    # each send.
    run_result_step_ids: tuple[UUID, ...] = ()
    run_result_file_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class _RunResultSource:
    """What a run result body is built from once the delivery's transaction
    has ended: its deliverables and a read grant for each file found."""

    parts: list[RunResultPart]
    grants: dict[UUID, ContentReadGrant]


class WebhookDeliveryClaimLostError(RuntimeError):
    pass


class RunResultAuditUnavailableError(RuntimeError):
    """The audit row a run result needs before it is sent was not written;
    nothing is sent and the delivery is tried again."""


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
        file_repo: FileRepository,
        object_content: Callable[[], ObjectContentService],
    ) -> None:
        self.file_repo = file_repo
        self.object_content = object_content
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
        result_read = False
        try:
            payload = await self._prepare_before_sends_end(row=row, deadline=deadline)
            payload_prepared = True
            result_read = payload.run_result_body is not None
            try:
                await self._deliver_payload(row=row, payload=payload, deadline=deadline)
            finally:
                # Audit policy reads share this task-scoped session. Discard
                # their read transaction before persisting the delivery outcome.
                if self.webhook_delivery_repo.session.in_transaction():
                    await self.webhook_delivery_repo.session.rollback()
        except WebhookSendNotStartedError as exc:
            if not result_read:
                return await self._release_unsent_claim(row=row)
            # Once the run's result has been read, a deadline that passes
            # before the send spends the attempt, as a cut read does: a job
            # that always gets that far would otherwise never run out of them.
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
        reading_files = False
        try:
            async with preparation:
                async with self.webhook_delivery_repo.session.begin():
                    payload, source = await self._prepare_delivery_payload(row=row)
                if source is None:
                    return payload
                # The files' bytes are read on a connection of their own, once
                # this delivery's transaction no longer holds one.
                reading_files = True
                return await self._with_run_result_body(
                    payload, source=source, tenant_id=row.tenant_id
                )
        except TimeoutError as exc:
            if not preparation.expired():
                raise
            # A slow job gives its claim back unspent, but a store that never
            # answers would then hold the delivery forever: a read cut by the
            # deadline spends the attempt and waits out the backoff.
            if reading_files:
                raise TimeoutError(
                    "The webhook delivery job ran out of time while reading the "
                    "run result's files."
                ) from exc
            raise WebhookSendNotStartedError(
                "The webhook delivery job ran out of time while preparing the request."
            ) from exc

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
    ) -> tuple[WebhookDeliveryPayload, _RunResultSource | None]:
        """The delivery's run, step, text and audit actor, read in the
        delivery's transaction. A run result also gets what its body is built
        from; its files' bytes are not read here."""
        run = await self.flow_run_repo.get(
            run_id=row.flow_run_id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
        )
        # A template body is sent while its run is running; a run result body
        # once its run has completed. Only the pinned step says which, so a
        # run in any other state is refused before the version is read.
        if run.status not in (FlowRunStatus.RUNNING, FlowRunStatus.COMPLETED):
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
        run_result = sends_run_result(step.output_mode, step.output_config)
        if run.status != (
            FlowRunStatus.COMPLETED if run_result else FlowRunStatus.RUNNING
        ):
            raise ValueError(
                "Run result delivery requires a completed run."
                if run_result
                else "Webhook delivery run is no longer running."
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

        # Headers may read run data as for any body; the address may not.
        payload = WebhookDeliveryPayload(
            run=run,
            step=step,
            step_result=step_result,
            text_payload=text_payload,
            context=context,
            audit_actor=audit_actor,
        )
        if not run_result:
            return payload, None
        # Every deliverable of the completed run, as its detail lists them,
        # each text read from its step's current result.
        result_files = await self.flow_run_repo.list_result_files_for_runs(
            run_ids=[run.id], tenant_id=row.tenant_id
        )
        results_by_step = {item.step_id: item for item in results}
        parts: list[RunResultPart] = [
            run_result_text(
                deliverable,
                step_result=results_by_step.get(deliverable.step_id),
                result_files=result_files,
            )
            if isinstance(deliverable, FlowRunTextDeliverablePublic)
            else deliverable
            for deliverable in project_run_deliverables(
                status=run.status,
                outputs=build_run_output_contract(steps),
                result_files=result_files,
            )
        ]
        if not parts:
            raise ValueError(
                "Run result delivery has nothing to send: the run delivers no "
                "text or document."
            )
        check_run_result(parts)
        return payload, _RunResultSource(
            parts=parts,
            grants=await self._content_grants(
                run_result_file_ids(parts), tenant_id=row.tenant_id
            ),
        )

    async def _with_run_result_body(
        self,
        payload: WebhookDeliveryPayload,
        *,
        source: _RunResultSource,
        tenant_id: UUID,
    ) -> WebhookDeliveryPayload:
        """The payload with its run result body. A file whose bytes cannot
        be read, or no longer match, refuses the body."""
        contents: dict[UUID, bytes] = {}
        if source.grants:
            try:
                payloads = await self.object_content().read_content_bytes(
                    list(source.grants.values())
                )
            except (ObjectContentIntegrityError, ObjectContentStateError) as exc:
                # Bytes that no longer match, or content no longer readable,
                # will not be there on a later attempt either. A store that is
                # down is left to one.
                raise ValueError(
                    f"Run result delivery could not read its files: {exc.code}."
                ) from exc
            contents = {
                file_id: payloads[grant.content_id]
                for file_id, grant in source.grants.items()
                if grant.content_id in payloads
            }
        return replace(
            payload,
            run_result_body=run_result_body(
                run=payload.run, parts=source.parts, contents=contents
            ),
            run_result_step_ids=tuple(
                part.deliverable.step_id
                if isinstance(part, RunResultText)
                else part.step_id
                for part in source.parts
            ),
            run_result_file_ids=tuple(run_result_file_ids(source.parts)),
        )

    async def _content_grants(
        self, file_ids: list[UUID], *, tenant_id: UUID
    ) -> dict[UUID, ContentReadGrant]:
        """A read grant for each file's own bytes: an upload's original or a
        generated document's artifact. A file without one is left out, which
        refuses the body."""
        if not file_ids:
            return {}
        references = await self.file_repo.get_content_references(file_ids)
        grants: dict[UUID, ContentReadGrant] = {}
        for file_id in file_ids:
            try:
                await self.file_repo.get_by_id(file_id=file_id, tenant_id=tenant_id)
            except NotFoundException:
                continue
            own = {
                reference.variant: reference
                for reference in references
                if reference.file_id == file_id and reference.ordinal == 0
            }
            reference = own.get(FileContentVariant.ORIGINAL) or own.get(
                FileContentVariant.GENERATED_ARTIFACT
            )
            if reference is not None:
                grants[file_id] = ContentReadGrant(
                    content_id=reference.content_id,
                    tenant_id=tenant_id,
                    access_class=reference.access_class,
                )
        return grants

    async def _audit_run_result_send(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        payload: WebhookDeliveryPayload,
        url: str,
    ) -> None:
        """Record, and commit, that the run's result and files are about to
        leave Eneo: after its request is compiled, before it is sent. The row
        names the steps and files by id and the receiver by the host of the
        compiled address; it holds no label, file name or content."""
        url_host = parse_effective_http_url(url).host
        actor = payload.audit_actor
        try:
            if self.audit_service is None or actor is None:
                raise RunResultAuditUnavailableError(
                    "Run result delivery audit logging is unavailable."
                )
            actor_fields = actor.audit_actor_fields()
            async with self.webhook_delivery_repo.session.begin():
                await self.audit_service.log(
                    tenant_id=row.tenant_id,
                    actor_id=actor_fields["actor_id"],
                    actor_type=actor_fields["actor_type"],
                    actor_api_key_id=actor_fields["actor_api_key_id"],
                    action=ActionType.FLOW_RUN_RESULT_SENDING,
                    entity_type=EntityType.FLOW_RUN,
                    entity_id=row.flow_run_id,
                    description=f"Sending the result of flow run {row.flow_run_id}",
                    metadata=actor.audit_metadata(
                        target=payload.run,
                        extra={
                            "flow_id": str(row.flow_id),
                            "run_id": str(row.flow_run_id),
                            "delivery_id": str(row.id),
                            "delivery_attempt": row.delivery_attempts,
                            "url_host": url_host,
                            "step_ids": [
                                str(step_id) for step_id in payload.run_result_step_ids
                            ],
                            "file_ids": [
                                str(file_id) for file_id in payload.run_result_file_ids
                            ],
                        },
                    ),
                    required=True,
                    record_client=False,
                )
        except RunResultAuditUnavailableError:
            raise
        except Exception as exc:
            raise RunResultAuditUnavailableError(
                "Run result delivery audit logging is unavailable."
            ) from exc

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

        async def audit_run_result_send(url: str) -> None:
            await self._audit_run_result_send(row=row, payload=payload, url=url)

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
            run_result_body=payload.run_result_body,
            before_send=(
                audit_run_result_send if payload.run_result_body is not None else None
            ),
        )

    async def _record_success(
        self,
        *,
        row: FlowRunWebhookDeliveryRow,
        payload: WebhookDeliveryPayload,
    ) -> bool:
        if payload.run_result_body is not None:
            # The run completed before the send: only the delivery is recorded.
            if not await self.webhook_delivery_repo.mark_delivery_succeeded(
                delivery_id=row.id,
                claim_token=row.claim_token,
                delivered_at=datetime.now(timezone.utc),
            ):
                raise WebhookDeliveryClaimLostError(
                    "Webhook delivery claim was lost before success could be recorded."
                )
            return True
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

        await finalize_run_from_current_results(
            run_id=row.flow_run_id,
            tenant_id=row.tenant_id,
            flow_run_repo=self.flow_run_repo,
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

        if dead_lettered_at is not None and not await self._run_has_ended(row):
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

    async def _run_has_ended(self, row: FlowRunWebhookDeliveryRow) -> bool:
        """A delivery for a run that has already ended never ends the run: a
        run result is sent after its run completed, and the run stays
        completed whatever the receiver does."""
        run = await self.flow_run_repo.get(
            run_id=row.flow_run_id, tenant_id=row.tenant_id, flow_id=row.flow_id
        )
        return is_terminal_flow_run_status(run.status)

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

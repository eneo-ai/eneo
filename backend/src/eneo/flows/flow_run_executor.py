"""Execute a flow run step by step with short transactions.

Each step runs in three phases:

1. claim: one committed transaction moves the step result ``pending ->
   running`` and opens an attempt;
2. prepare: a short transaction resolves models, files and knowledge into
   plain data; the provider call then runs with no transaction open;
3. persist: one committed transaction stores the outcome and closes the
   attempt.

A redelivered job skips completed steps through the claim. A step found
``running`` without being claimable means a previous worker died between
the claim and the outcome commit: the provider result is unknown, so the run
fails and the call is never repeated. A ``review`` step opens a checkpoint
and parks the run; on resume the executor finds the approved checkpoint and
completes the review step with its current payload.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

from eneo.flows.definition import (
    FlowDefinition,
    LlmStep,
    ReviewStep,
    Step,
    review_target_key,
)
from eneo.flows.flow_assembler import run_definition
from eneo.flows.flow_models import (
    FlowRunStatus,
    ReviewCheckpointState,
    StepAttemptStatus,
    StepResultStatus,
)
from eneo.flows.flow_repo import RunFileEntry
from eneo.flows.step_runners import (
    STEP_FAILED,
    STEP_TIMEOUT,
    FlowStepError,
    PreparedStep,
    RunContext,
    StepOutcome,
    signed_links_for,
)
from eneo.flows.templating import StepOutput, TemplateContext
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.flows.flow_repo import FlowRepository
    from eneo.flows.step_runners import StepRunners

logger = get_logger(__name__)

OUTCOME_UNKNOWN = "flow_step_outcome_unknown"
REVIEW_REJECTED = "flow_run_rejected_in_review"


def _now_plus(seconds: Optional[int]) -> Optional[datetime]:
    if seconds is None:
        return None
    return datetime.now(UTC) + timedelta(seconds=seconds)


class FlowRunExecutor:
    def __init__(
        self,
        repo: FlowRepository,
        runners: StepRunners,
        *,
        step_timeout_seconds: float = 900,
        audit_service: AuditService | None = None,
    ):
        self.repo = repo
        self.runners = runners
        self.step_timeout_seconds = step_timeout_seconds
        self.audit_service = audit_service
        self._tenant_id: Optional[UUID] = None

    async def _finish(
        self,
        ctx: RunContext,
        status: FlowRunStatus,
        *,
        error: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        expected_statuses: tuple[FlowRunStatus, ...] = (
            FlowRunStatus.QUEUED,
            FlowRunStatus.RUNNING,
            FlowRunStatus.AWAITING_REVIEW,
        ),
        expired: bool = False,
    ) -> bool:
        from eneo.flows.lifecycle import finish_run

        return await finish_run(
            self.repo,
            self.audit_service,
            ctx.run_id,
            ctx.tenant_id,
            status,
            error=error,
            output=output,
            expected_statuses=expected_statuses,
            expired=expired,
        )

    def _scope(self) -> AbstractAsyncContextManager[object]:
        """Short-transaction boundary.

        On a sessionless container (the worker) each block is a committed
        ``Container.session_scope()``. When the repository already holds a
        bound session (HTTP or test path) this is a no-op and the work stays
        in the ambient transaction.
        """
        try:
            self.repo.session.in_transaction()
        except RuntimeError:
            from eneo.main.container.container import Container

            return Container.session_scope()
        return contextlib.nullcontext()

    # --- Run lifecycle ---

    async def execute_run(self, run_id: UUID, tenant_id: UUID) -> None:
        async with self._scope():
            run = await self.repo.get_run(run_id, tenant_id)
            if run is None:
                raise NotFoundException("Flow run not found")
            if run.status not in (
                FlowRunStatus.QUEUED.value,
                FlowRunStatus.RUNNING.value,
            ):
                return
            flow = await self.repo.get_flow(
                run.flow_id, tenant_id, include_deleted=True
            )
            if flow is None:
                raise NotFoundException("Flow not found")
            definition = await run_definition(self.repo, run)
            files = await self.repo.list_run_files(run.id)
            ctx = RunContext(
                run_id=run.id,
                flow_id=run.flow_id,
                space_id=flow.space_id,
                tenant_id=run.tenant_id,
                principal_user_id=run.principal_user_id,
                form_values=dict(run.input_payload_json or {}),
                input_files=files,
                runtime_bindings=dict(getattr(run, "runtime_bindings", None) or {}),
            )
            if getattr(flow, "deleted_at", None) is not None:
                await self._finish(
                    ctx,
                    FlowRunStatus.CANCELLED,
                    error={"code": "flow_deleted", "message": "The flow was deleted."},
                )
                return
            await self.repo.update_run_status(
                run.id,
                FlowRunStatus.RUNNING,
                expected_statuses=(FlowRunStatus.QUEUED, FlowRunStatus.RUNNING),
            )

        self._tenant_id = ctx.tenant_id
        context = self._initial_context(ctx, definition)
        last_output: Optional[dict[str, Any]] = None

        for order, step in enumerate(definition.steps):
            assert step.id is not None
            async with self._scope():
                run = await self.repo.get_run(ctx.run_id, ctx.tenant_id)
                if run is None or run.status != FlowRunStatus.RUNNING.value:
                    # Cancelled (or reconciled) while we worked: stop here.
                    return
                flow = await self.repo.get_flow(
                    ctx.flow_id, ctx.tenant_id, include_deleted=True
                )
                if flow is None or getattr(flow, "deleted_at", None) is not None:
                    await self._finish(
                        ctx,
                        FlowRunStatus.CANCELLED,
                        error={
                            "code": "flow_deleted",
                            "message": "The flow was deleted.",
                        },
                    )
                    return
                claimed = await self.repo.claim_step_result(ctx.run_id, step.id)
                attempt_no = 0
                stored_status: Optional[str] = None
                stored_output: dict[str, Any] = {}
                if claimed:
                    attempt_no = await self.repo.open_attempt(ctx.run_id, step.id)
                else:
                    # Copy what the row says while the session is open: the
                    # commit expires the instance, so reading it later would
                    # try to refresh a detached object.
                    stored = await self.repo.get_step_result(ctx.run_id, step.id)
                    assert stored is not None
                    stored_status = stored.status
                    stored_output = dict(stored.output_payload_json or {})

            if not claimed:
                if stored_status == StepResultStatus.COMPLETED.value:
                    output = stored_output
                    self._remember(context, definition, step, output)
                    last_output = output
                    continue
                if stored_status == StepResultStatus.AWAITING_REVIEW.value:
                    resumed = await self._resume_review(ctx, definition, step)
                    if resumed is None:
                        return
                    self._remember(context, definition, step, resumed)
                    last_output = resumed
                    continue
                if stored_status in (
                    StepResultStatus.SKIPPED.value,
                    StepResultStatus.CANCELLED.value,
                    StepResultStatus.FAILED.value,
                ):
                    return
                await self._fail_outcome_unknown(ctx, step)
                return

            if isinstance(step, ReviewStep):
                await self._pause_for_review(ctx, definition, step, order, attempt_no)
                return

            try:
                async with self._scope():
                    prepared = await self.runners.prepare(step, ctx, context)
            except Exception as exc:
                await self._fail_run(ctx, step, attempt_no, exc)
                return

            try:
                async with asyncio.timeout(self.step_timeout_seconds):
                    outcome = await self._invoke(step, prepared)
            except TimeoutError:
                await self._fail_run(
                    ctx,
                    step,
                    attempt_no,
                    FlowStepError(
                        STEP_TIMEOUT,
                        f"Step '{step.name}' exceeded "
                        f"{int(self.step_timeout_seconds)} seconds.",
                    ),
                    input_payload=prepared.input_payload,
                )
                return
            except Exception as exc:
                await self._fail_run(
                    ctx, step, attempt_no, exc, input_payload=prepared.input_payload
                )
                return

            if outcome.transcription is not None:
                prepared.input_payload = {
                    **prepared.input_payload,
                    "transcription": outcome.transcription,
                }
            if outcome.documents or outcome.transcriptions:
                # Produced bytes become files of the run's principal before
                # the step is recorded, so a stored result always names
                # files that exist; a transcript is kept on its audio file.
                try:
                    async with self._scope():
                        stored = (
                            await self.runners.store_documents(outcome.documents)
                            if outcome.documents
                            else []
                        )
                        if outcome.transcriptions:
                            await self.runners.store_transcriptions(
                                outcome.transcriptions
                            )
                except Exception as exc:
                    await self._fail_run(
                        ctx,
                        step,
                        attempt_no,
                        exc,
                        input_payload=prepared.input_payload,
                    )
                    return
                outcome.output_file_ids = [*outcome.output_file_ids, *stored]
                outcome.output_payload = {
                    **outcome.output_payload,
                    "file_ids": [str(file_id) for file_id in outcome.output_file_ids],
                }

            try:
                async with self._scope():
                    current = await self.repo.get_run(
                        ctx.run_id, ctx.tenant_id, for_update=True
                    )
                    if current is None or current.status != FlowRunStatus.RUNNING.value:
                        return
                    if outcome.output_file_ids:
                        await self.repo.add_run_files(
                            ctx.run_id,
                            [
                                RunFileEntry(
                                    file_id=file_id,
                                    role="output",
                                    step_id=step.id,
                                    ordinal=index,
                                )
                                for index, file_id in enumerate(outcome.output_file_ids)
                            ],
                        )
                    await self.repo.complete_step_result(
                        ctx.run_id,
                        step.id,
                        input_payload_json=prepared.input_payload,
                        output_payload_json=outcome.output_payload,
                        num_tokens_input=outcome.num_tokens_input,
                        num_tokens_output=outcome.num_tokens_output,
                    )
                    await self.repo.finish_attempt(
                        ctx.run_id,
                        step.id,
                        attempt_no,
                        status=StepAttemptStatus.COMPLETED,
                    )
            except Exception as exc:
                await self._fail_run(ctx, step, attempt_no, exc)
                raise
            self._remember(context, definition, step, outcome.output_payload)
            last_output = outcome.output_payload

        async with self._scope():
            await self._finish(
                ctx,
                FlowRunStatus.COMPLETED,
                output=last_output or {},
                expected_statuses=(FlowRunStatus.RUNNING,),
            )

    async def _invoke(self, step: Step, prepared: PreparedStep) -> StepOutcome:
        if prepared.output_payload is not None or not prepared.io_needs_session:
            return await self.runners.invoke(step, prepared)
        # The completion service resolves its provider adapter from the
        # database inside the call, so the call itself needs a short scope;
        # the scope commits nothing of ours.
        async with self._scope():
            return await self.runners.invoke(step, prepared)

    # --- Template context ---

    @staticmethod
    def _initial_context(
        ctx: RunContext, definition: FlowDefinition
    ) -> TemplateContext:
        form: dict[str, Any] = {}
        for field in definition.form_fields:
            value = ctx.form_values.get(field.key)
            if field.type.value in ("file", "audio"):
                names = [
                    row.name
                    for row in ctx.input_files
                    if row.role == "input" and row.field_key == field.key
                ]
                form[field.key] = ", ".join(names)
            elif value is None:
                form[field.key] = None
            else:
                form[field.key] = value
        return TemplateContext(form=form)

    def _remember(
        self,
        context: TemplateContext,
        definition: FlowDefinition,
        step: Step,
        output: dict[str, Any],
    ) -> None:
        text = str(output.get("text") or "")
        raw_ids = output.get("file_ids")
        file_ids = (
            [UUID(str(item)) for item in cast(list[Any], raw_ids)]
            if isinstance(raw_ids, list)
            else []
        )
        result = StepOutput(
            text=text,
            value=output.get("value"),
            file_urls=signed_links_for(self._tenant_id, file_ids),
        )
        context.steps[step.key] = result
        if isinstance(step, ReviewStep):
            # Downstream steps read the reviewed (possibly edited) output when
            # they name the reviewed step.
            target_key = review_target_key(definition, step)
            if target_key is not None:
                context.steps[target_key] = result
        context.previous = text

    # --- Review ---

    @staticmethod
    def _review_output_type(definition: FlowDefinition, step: ReviewStep) -> str:
        target_key = review_target_key(definition, step)
        target = definition.step_by_key(target_key) if target_key else None
        if isinstance(target, LlmStep) and target.output.type == "json":
            return "json"
        return "text"

    async def _pause_for_review(
        self,
        ctx: RunContext,
        definition: FlowDefinition,
        step: ReviewStep,
        order: int,
        attempt_no: int,
    ) -> None:
        assert step.id is not None
        target_key = review_target_key(definition, step)
        async with self._scope():
            run = await self.repo.get_run(ctx.run_id, ctx.tenant_id, for_update=True)
            if run is None or run.status != FlowRunStatus.RUNNING.value:
                return
            payload: Optional[dict[str, Any]] = None
            target = definition.step_by_key(target_key) if target_key else None
            if target is not None and target.id is not None:
                target_result = await self.repo.get_step_result(ctx.run_id, target.id)
                if target_result is not None:
                    payload = target_result.output_payload_json
            await self.repo.create_checkpoint(
                run_id=ctx.run_id,
                flow_id=ctx.flow_id,
                tenant_id=ctx.tenant_id,
                step_id=step.id,
                step_order=order,
                attempt_no=attempt_no,
                review_mode=step.mode.value,
                output_type=self._review_output_type(definition, step),
                payload=payload,
                requester_principal_type="user"
                if ctx.principal_user_id is not None
                else "service",
                requester_user_id=ctx.principal_user_id,
                expires_at=_now_plus(step.expires_after_seconds),
            )
            await self.repo.set_step_awaiting_review(
                ctx.run_id, step.id, input_payload_json={"of": target_key}
            )
            await self.repo.update_run_status(
                ctx.run_id,
                FlowRunStatus.AWAITING_REVIEW,
                expected_statuses=(FlowRunStatus.RUNNING,),
            )

    async def _resume_review(
        self, ctx: RunContext, definition: FlowDefinition, step: Step
    ) -> Optional[dict[str, Any]]:
        """Complete a review step whose checkpoint was approved.

        Returns the reviewed payload, or None when the run must stay parked
        (the checkpoint is still open: a redelivered job must not push past
        it).
        """
        assert step.id is not None
        async with self._scope():
            run = await self.repo.get_run(ctx.run_id, ctx.tenant_id, for_update=True)
            if run is None or run.status != FlowRunStatus.RUNNING.value:
                return None
            checkpoint = await self.repo.get_active_checkpoint(ctx.run_id)
            if (
                checkpoint is not None
                and checkpoint.expires_at is not None
                and checkpoint.expires_at <= datetime.now(UTC)
            ):
                await self._finish(
                    ctx,
                    FlowRunStatus.FAILED,
                    error={
                        "code": "flow_review_expired",
                        "message": "The review deadline passed.",
                    },
                    expired=True,
                )
                return None
            if (
                checkpoint is None
                or checkpoint.step_id != step.id
                or checkpoint.state != ReviewCheckpointState.APPROVED.value
            ):
                await self.repo.update_run_status(
                    ctx.run_id,
                    FlowRunStatus.AWAITING_REVIEW,
                    expected_statuses=(FlowRunStatus.RUNNING,),
                )
                return None
            payload = dict(checkpoint.current_payload_json or {})
            await self.repo.complete_step_result(
                ctx.run_id,
                step.id,
                input_payload_json=None,
                output_payload_json=payload,
            )
            await self.repo.finish_attempt(
                ctx.run_id,
                step.id,
                checkpoint.attempt_no,
                status=StepAttemptStatus.COMPLETED,
            )
            await self.repo.mark_resumed(checkpoint.id)
        return payload

    # --- Failure paths ---

    async def _fail_run(
        self,
        ctx: RunContext,
        step: Step,
        attempt_no: int,
        exc: Exception,
        *,
        input_payload: Optional[dict[str, Any]] = None,
    ) -> None:
        assert step.id is not None
        if isinstance(exc, FlowStepError):
            code, message = exc.code, exc.message
        else:
            code, message = STEP_FAILED, f"{type(exc).__name__}: {exc}"
            logger.exception(
                "Flow step failed",
                extra={"run_id": str(ctx.run_id), "step_id": str(step.id)},
            )
        async with self._scope():
            run = await self.repo.get_run(ctx.run_id, ctx.tenant_id, for_update=True)
            if run is None or run.status != FlowRunStatus.RUNNING.value:
                return
            await self.repo.finish_attempt(
                ctx.run_id,
                step.id,
                attempt_no,
                status=StepAttemptStatus.FAILED,
                error=message,
            )
            await self.repo.fail_step_result(
                ctx.run_id,
                step.id,
                error_code=code,
                error_message=message,
                input_payload_json=input_payload,
            )
            await self._finish(
                ctx,
                FlowRunStatus.FAILED,
                error={
                    "code": code,
                    "message": f"Step '{step.name}' failed: {message}",
                },
                expected_statuses=(FlowRunStatus.RUNNING,),
            )

    async def _fail_outcome_unknown(self, ctx: RunContext, step: Step) -> None:
        message = (
            f"Step '{step.name}' was interrupted with an unknown provider "
            "outcome; the call is not repeated."
        )
        async with self._scope():
            run = await self.repo.get_run(ctx.run_id, ctx.tenant_id, for_update=True)
            if run is None or run.status != FlowRunStatus.RUNNING.value:
                return
            await self.repo.mark_started_attempts_outcome_unknown(ctx.run_id)
            await self.repo.fail_running_step_results(
                ctx.run_id, error_code=OUTCOME_UNKNOWN, error_message=message
            )
            await self._finish(
                ctx,
                FlowRunStatus.FAILED,
                error={"code": OUTCOME_UNKNOWN, "message": message},
                expected_statuses=(FlowRunStatus.RUNNING,),
            )

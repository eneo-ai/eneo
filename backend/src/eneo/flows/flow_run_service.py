"""Runs of a published flow: start, inspect, cancel, review.

Read access follows ``can_read_flows`` on the flow's space; starting a run
and reviewing need read; cancelling needs read plus ownership of the run or
edit rights. Execution itself lives in :class:`FlowRunExecutor`; this
service only queues the durable job and exposes state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import jsonschema

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.definition import (
    FILE_FIELD_TYPES,
    FlowDefinition,
    FormFieldType,
    LlmStep,
    ReviewStep,
    review_target_key,
)
from eneo.flows.flow_assembler import (
    checkpoint_public,
    definition_from_json,
    run_public,
    run_state_public,
    run_summary_public,
    step_public,
)
from eneo.flows.flow_models import (
    FlowRunPublic,
    FlowRunReviewCheckpointPublic,
    FlowRunReviewCheckpointResumeResponse,
    FlowRunStatePublic,
    FlowRunStatus,
    FlowRunStepPublic,
    FlowRunSummaryPublic,
    PrincipalType,
    ReviewCheckpointState,
)
from eneo.flows.flow_repo import RunFileEntry
from eneo.flows.flow_run_executor import REVIEW_REJECTED
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import FlowRunParams
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.database.tables.flow_tables import FlowRunReviewCheckpoints, FlowRuns
    from eneo.files.file_service import FileService
    from eneo.flows.flow_repo import FlowRepository
    from eneo.flows.flow_run_executor import FlowRunExecutor
    from eneo.flows.flow_service import FlowService
    from eneo.jobs.job_service import JobService
    from eneo.users.user import UserInDB

ACTIVE_RUN_STATUSES = (
    FlowRunStatus.QUEUED,
    FlowRunStatus.RUNNING,
    FlowRunStatus.AWAITING_REVIEW,
)
OPEN_CHECKPOINT_STATES = (
    ReviewCheckpointState.AWAITING_REVIEW,
    ReviewCheckpointState.EDITED,
)


class FlowRunService:
    def __init__(
        self,
        user: UserInDB,
        repo: FlowRepository,
        flow_service: FlowService,
        job_service: JobService,
        file_service: FileService,
        audit_service: AuditService,
        executor: FlowRunExecutor,
    ):
        self.user = user
        self.repo = repo
        self.flow_service = flow_service
        self.job_service = job_service
        self.file_service = file_service
        self.audit_service = audit_service
        self.executor = executor

    # --- Lookups and authorization ---

    async def _require_run(
        self, run_id: UUID, *, flow_id: Optional[UUID] = None
    ) -> FlowRuns:
        run = await self.repo.get_run(run_id, self.user.tenant_id)
        # A run is only addressable through its own flow: a valid run id
        # under another flow of the same tenant must not resolve.
        if run is None or (flow_id is not None and run.flow_id != flow_id):
            raise NotFoundException("Flow run not found")
        flow = await self.repo.get_flow(
            run.flow_id, self.user.tenant_id, include_deleted=True
        )
        if flow is None:
            raise NotFoundException("Flow run not found")
        await self.flow_service.authorize_space(flow.space_id, "read")
        return run

    async def _definition_for(self, run: FlowRuns) -> FlowDefinition:
        version = await self.repo.get_version(run.flow_id, run.flow_version)
        if version is None:
            raise NotFoundException("Published flow version not found")
        return definition_from_json(version.definition)

    def _owns(self, run: FlowRuns) -> bool:
        return run.principal_user_id == self.user.id

    async def _audit_run(
        self,
        action: ActionType,
        run: FlowRuns,
        description: str,
        *,
        channel: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=action,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run.id,
            description=description,
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=run,
                extra={
                    "channel": channel,
                    "flow_id": str(run.flow_id),
                    "flow_version": run.flow_version,
                    **(extra or {}),
                },
            ),
        )

    # --- Run creation ---

    async def _validate_run_input(
        self,
        definition: FlowDefinition,
        *,
        values: dict[str, Any],
        files: dict[str, list[UUID]],
    ) -> dict[str, Any]:
        """Check inputs against the published form; return normalized values."""
        fields_by_key = {field.key: field for field in definition.form_fields}
        problems: list[str] = []
        normalized: dict[str, Any] = {}
        for key, value in values.items():
            field = fields_by_key.get(key)
            if field is None:
                problems.append(f"unknown form field '{key}'")
                continue
            if field.type in FILE_FIELD_TYPES:
                problems.append(f"form field '{key}' takes files, not a value")
                continue
            if value is None:
                continue
            if field.type == FormFieldType.NUMBER:
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    problems.append(f"form field '{key}' must be a number")
                    continue
                try:
                    number = float(value)
                except ValueError:
                    problems.append(f"form field '{key}' must be a number")
                    continue
                normalized[key] = int(number) if number.is_integer() else number
            elif field.type == FormFieldType.SELECT:
                if field.options and str(value) not in field.options:
                    problems.append(
                        f"form field '{key}' must be one of: "
                        + ", ".join(field.options)
                    )
                    continue
                normalized[key] = str(value)
            else:
                normalized[key] = str(value)
        for key, ids in files.items():
            field = fields_by_key.get(key)
            if field is None:
                problems.append(f"unknown form field '{key}'")
                continue
            if field.type not in FILE_FIELD_TYPES:
                problems.append(f"form field '{key}' takes a value, not files")
                continue
            if ids:
                infos = await self.file_service.get_file_infos(list(set(ids)))
                if len(infos) != len(set(ids)):
                    problems.append(f"form field '{key}' references unknown files")
        for field in definition.form_fields:
            if not field.required:
                continue
            if field.type in FILE_FIELD_TYPES:
                if not files.get(field.key):
                    problems.append(
                        f"required form field '{field.key}' needs at least one file"
                    )
            elif normalized.get(field.key) in (None, ""):
                problems.append(f"required form field '{field.key}' is missing")
        if problems:
            raise BadRequestException(
                "The run inputs have problems:\n- " + "\n- ".join(problems)
            )
        return normalized

    async def _queue(self, run: FlowRuns, flow_name: str, *, name: str) -> None:
        job = await self.job_service.queue_durable_job(
            Task.RUN_FLOW,
            name=f"{name}: {flow_name}",
            task_params=FlowRunParams(
                id=run.id, flow_id=run.flow_id, user_id=self.user.id
            ),
        )
        await self.repo.set_run_job(run.id, job.id)

    async def create_run(
        self,
        flow_id: UUID,
        *,
        values: dict[str, Any],
        files: dict[str, list[UUID]],
        run_label: str | None = None,
        expected_flow_version: int | None = None,
        idempotency_key: str | None = None,
        channel: str = "api",
    ) -> FlowRunPublic:
        version, definition = await self.flow_service.get_published_definition(flow_id)
        if expected_flow_version is not None and expected_flow_version != version:
            raise BadRequestException(
                "Flow was republished since the run contract was read. "
                f"Expected version {expected_flow_version}, active version {version}."
            )
        if idempotency_key:
            existing = await self.repo.get_run_by_idempotency_key(
                flow_id, idempotency_key
            )
            if existing is not None:
                return await self._run_public(existing)
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id)
        assert flow is not None
        normalized = await self._validate_run_input(
            definition, values=values, files=files
        )
        run = await self.repo.add_run(
            flow_id=flow_id,
            flow_version=version,
            tenant_id=self.user.tenant_id,
            principal_type=PrincipalType.USER.value,
            principal_user_id=self.user.id,
            created_by_api_key_id=(
                self.user.active_api_key.id if self.user.active_api_key else None
            ),
            run_label=run_label,
            idempotency_key=idempotency_key or None,
            input_payload_json=normalized,
        )
        await self.repo.seed_step_results(
            run.id,
            [
                (step.id, order)
                for order, step in enumerate(definition.steps)
                if step.id is not None
            ],
        )
        entries = [
            RunFileEntry(file_id=file_id, role="input", field_key=key, ordinal=index)
            for key, ids in files.items()
            for index, file_id in enumerate(dict.fromkeys(ids))
        ]
        if entries:
            await self.repo.add_run_files(run.id, entries)
        await self._queue(run, flow.name, name="Run flow")
        await self._audit_run(
            ActionType.FLOW_RUN_CREATED,
            run,
            "Started flow run",
            channel=channel,
            extra={"run_label": run_label},
        )
        refreshed = await self.repo.get_run(run.id, self.user.tenant_id)
        assert refreshed is not None
        return await self._run_public(refreshed)

    # --- Reads ---

    async def _run_public(self, run: FlowRuns) -> FlowRunPublic:
        definition = await self._definition_for(run)
        files = await self.repo.list_run_files(run.id)
        checkpoint = await self.repo.get_active_checkpoint(run.id)
        return run_public(run, definition, files, checkpoint)

    async def get_run(
        self, run_id: UUID, *, flow_id: UUID | None = None
    ) -> FlowRunPublic:
        run = await self._require_run(run_id, flow_id=flow_id)
        return await self._run_public(run)

    async def get_run_summary(
        self, run_id: UUID, *, flow_id: UUID | None = None
    ) -> FlowRunSummaryPublic:
        run = await self._require_run(run_id, flow_id=flow_id)
        return run_summary_public(run)

    async def get_run_steps(
        self, run_id: UUID, *, flow_id: UUID | None = None
    ) -> list[FlowRunStepPublic]:
        run = await self._require_run(run_id, flow_id=flow_id)
        definition = await self._definition_for(run)
        files = await self.repo.list_run_files(run.id)
        by_id = {step.id: step for step in definition.steps if step.id is not None}
        return [
            step_public(result, by_id.get(result.step_id), files)
            for result in sorted(run.step_results, key=lambda r: r.step_order)
        ]

    async def list_runs(
        self, flow_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[FlowRunSummaryPublic], int]:
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id)
        if flow is None:
            raise NotFoundException("Flow not found")
        await self.flow_service.authorize_space(flow.space_id, "read")
        runs, total = await self.repo.list_runs(
            flow_id, self.user.tenant_id, limit=limit, offset=offset
        )
        return [run_summary_public(run) for run in runs], total

    async def get_run_state(self, run_id: UUID) -> FlowRunStatePublic:
        run = await self._require_run(run_id)
        definition = await self._definition_for(run)
        files = await self.repo.list_run_files(run.id)
        checkpoint = await self.repo.get_active_checkpoint(run.id)
        return run_state_public(run, definition, files, checkpoint)

    # --- Execution (worker side, also used inline by tests) ---

    async def execute_run(self, run_id: UUID) -> None:
        await self.executor.execute_run(run_id, self.user.tenant_id)

    # --- Cancel ---

    async def cancel_run(
        self, run_id: UUID, *, flow_id: UUID | None = None, channel: str = "api"
    ) -> FlowRunPublic:
        run = await self._require_run(run_id, flow_id=flow_id)
        if not self._owns(run):
            flow = await self.repo.get_flow(
                run.flow_id, self.user.tenant_id, include_deleted=True
            )
            assert flow is not None
            try:
                await self.flow_service.authorize_space(flow.space_id, "edit")
            except UnauthorizedException as exc:
                raise UnauthorizedException(
                    "Only the person who started the run or a flow editor can "
                    "cancel it."
                ) from exc
        moved = await self.repo.update_run_status(
            run.id,
            FlowRunStatus.CANCELLED,
            expected_statuses=ACTIVE_RUN_STATUSES,
        )
        if not moved:
            raise BadRequestException("Run is already finished.")
        checkpoint = await self.repo.get_active_checkpoint(run.id)
        if checkpoint is not None:
            await self.repo.decide_checkpoint(
                checkpoint.id,
                state=ReviewCheckpointState.CANCELLED,
                from_states=(
                    ReviewCheckpointState.AWAITING_REVIEW,
                    ReviewCheckpointState.EDITED,
                    ReviewCheckpointState.APPROVED,
                ),
                decided_by_principal_type=PrincipalType.USER.value,
                decided_by_user_id=self.user.id,
            )
        await self.repo.cancel_pending_step_results(run.id)
        await self._audit_run(
            ActionType.FLOW_RUN_CANCELLED, run, "Cancelled flow run", channel=channel
        )
        refreshed = await self.repo.get_run(run.id, self.user.tenant_id)
        assert refreshed is not None
        return await self._run_public(refreshed)

    # --- Review checkpoints ---

    async def get_active_checkpoint(
        self, run_id: UUID, *, flow_id: UUID | None = None
    ) -> FlowRunReviewCheckpointPublic | None:
        run = await self._require_run(run_id, flow_id=flow_id)
        checkpoint = await self.repo.get_active_checkpoint(run.id)
        return checkpoint_public(checkpoint) if checkpoint is not None else None

    async def _require_checkpoint(
        self, run: FlowRuns, checkpoint_id: UUID
    ) -> FlowRunReviewCheckpoints:
        checkpoint = await self.repo.get_checkpoint(checkpoint_id, run.id)
        if checkpoint is None:
            raise NotFoundException("Review checkpoint not found")
        return checkpoint

    @staticmethod
    def _require_open(checkpoint: FlowRunReviewCheckpoints) -> None:
        if checkpoint.state not in [s.value for s in OPEN_CHECKPOINT_STATES]:
            raise BadRequestException(
                f"Review checkpoint is already {checkpoint.state}."
            )

    @staticmethod
    def _require_revision(
        checkpoint: FlowRunReviewCheckpoints, expected_revision: int
    ) -> None:
        if checkpoint.revision != expected_revision:
            raise BadRequestException(
                "Review checkpoint changed since it was read "
                f"(revision {checkpoint.revision}, expected {expected_revision})."
            )

    async def _validate_review_payload(
        self,
        run: FlowRuns,
        checkpoint: FlowRunReviewCheckpoints,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if checkpoint.output_type == "json":
            if "value" not in payload:
                raise BadRequestException(
                    'A JSON review payload must be {"value": ...}.'
                )
            definition = await self._definition_for(run)
            review = definition.step_by_id(checkpoint.step_id)
            target = None
            if isinstance(review, ReviewStep):
                target_key = review_target_key(definition, review)
                target = definition.step_by_key(target_key) if target_key else None
            if isinstance(target, LlmStep) and target.output.type == "json":
                try:
                    jsonschema.validate(payload["value"], target.output.schema_)
                except jsonschema.ValidationError as exc:
                    raise BadRequestException(
                        f"Edited value does not satisfy the step schema: {exc.message}"
                    ) from exc
            text = payload.get("text")
            return {
                "text": text if isinstance(text, str) else None,
                "value": payload["value"],
            }
        text = payload.get("text")
        if not isinstance(text, str):
            raise BadRequestException('A text review payload must be {"text": "..."}.')
        return {"text": text, "value": None}

    async def edit_checkpoint(
        self,
        run_id: UUID,
        checkpoint_id: UUID,
        *,
        expected_revision: int,
        current_payload_json: dict[str, Any],
        flow_id: UUID | None = None,
    ) -> FlowRunReviewCheckpointPublic:
        run = await self._require_run(run_id, flow_id=flow_id)
        checkpoint = await self._require_checkpoint(run, checkpoint_id)
        self._require_open(checkpoint)
        self._require_revision(checkpoint, expected_revision)
        if checkpoint.review_mode != "edit":
            raise BadRequestException(
                "This review only allows approving or rejecting, not editing."
            )
        payload = await self._validate_review_payload(
            run, checkpoint, current_payload_json
        )
        moved = await self.repo.edit_checkpoint(
            checkpoint.id,
            expected_revision=expected_revision,
            current_payload_json=payload,
        )
        if not moved:
            raise BadRequestException("Review checkpoint changed since it was read.")
        refreshed = await self._require_checkpoint(run, checkpoint_id)
        return checkpoint_public(refreshed)

    async def _resume(
        self, run: FlowRuns, checkpoint: FlowRunReviewCheckpoints
    ) -> FlowRunReviewCheckpointResumeResponse:
        moved = await self.repo.update_run_status(
            run.id,
            FlowRunStatus.QUEUED,
            expected_statuses=(FlowRunStatus.AWAITING_REVIEW,),
        )
        if not moved:
            raise BadRequestException("Run is not awaiting review.")
        flow = await self.repo.get_flow(
            run.flow_id, self.user.tenant_id, include_deleted=True
        )
        assert flow is not None
        await self._queue(run, flow.name, name="Resume flow run")
        refreshed_run = await self.repo.get_run(run.id, self.user.tenant_id)
        refreshed_checkpoint = await self._require_checkpoint(run, checkpoint.id)
        assert refreshed_run is not None
        return FlowRunReviewCheckpointResumeResponse(
            checkpoint=checkpoint_public(refreshed_checkpoint),
            run=run_summary_public(refreshed_run),
        )

    async def approve_checkpoint(
        self,
        run_id: UUID,
        checkpoint_id: UUID,
        *,
        expected_revision: int,
        flow_id: UUID | None = None,
        resume: bool = True,
        channel: str = "api",
    ) -> FlowRunReviewCheckpointResumeResponse:
        run = await self._require_run(run_id, flow_id=flow_id)
        if run.status != FlowRunStatus.AWAITING_REVIEW.value:
            raise BadRequestException("Run is not awaiting review.")
        checkpoint = await self._require_checkpoint(run, checkpoint_id)
        self._require_open(checkpoint)
        self._require_revision(checkpoint, expected_revision)
        moved = await self.repo.decide_checkpoint(
            checkpoint.id,
            state=ReviewCheckpointState.APPROVED,
            from_states=OPEN_CHECKPOINT_STATES,
            expected_revision=expected_revision,
            decided_by_principal_type=PrincipalType.USER.value,
            decided_by_user_id=self.user.id,
        )
        if not moved:
            raise BadRequestException("Review checkpoint was already decided.")
        await self._audit_run(
            ActionType.FLOW_RUN_REVIEWED,
            run,
            "Approved flow run review",
            channel=channel,
            extra={"checkpoint_id": str(checkpoint.id), "decision": "approve"},
        )
        if resume:
            return await self._resume(run, checkpoint)
        refreshed = await self._require_checkpoint(run, checkpoint.id)
        return FlowRunReviewCheckpointResumeResponse(
            checkpoint=checkpoint_public(refreshed), run=run_summary_public(run)
        )

    async def resume_checkpoint(
        self,
        run_id: UUID,
        checkpoint_id: UUID,
        *,
        expected_revision: int,
        flow_id: UUID | None = None,
        channel: str = "api",
    ) -> FlowRunReviewCheckpointResumeResponse:
        run = await self._require_run(run_id, flow_id=flow_id)
        checkpoint = await self._require_checkpoint(run, checkpoint_id)
        if checkpoint.state != ReviewCheckpointState.APPROVED.value:
            raise BadRequestException("Review checkpoint is not approved.")
        self._require_revision(checkpoint, expected_revision)
        return await self._resume(run, checkpoint)

    async def reject_checkpoint(
        self,
        run_id: UUID,
        checkpoint_id: UUID,
        *,
        expected_revision: int,
        reason: str | None,
        flow_id: UUID | None = None,
        channel: str = "api",
    ) -> FlowRunReviewCheckpointPublic:
        run = await self._require_run(run_id, flow_id=flow_id)
        if run.status != FlowRunStatus.AWAITING_REVIEW.value:
            raise BadRequestException("Run is not awaiting review.")
        checkpoint = await self._require_checkpoint(run, checkpoint_id)
        self._require_open(checkpoint)
        self._require_revision(checkpoint, expected_revision)
        moved = await self.repo.decide_checkpoint(
            checkpoint.id,
            state=ReviewCheckpointState.REJECTED,
            from_states=OPEN_CHECKPOINT_STATES,
            expected_revision=expected_revision,
            decided_by_principal_type=PrincipalType.USER.value,
            decided_by_user_id=self.user.id,
            reason=reason,
        )
        if not moved:
            raise BadRequestException("Review checkpoint was already decided.")
        message = "Rejected in review" + (f": {reason}" if reason else "")
        await self.repo.fail_step_result(
            run.id,
            checkpoint.step_id,
            error_code=REVIEW_REJECTED,
            error_message=message,
        )
        await self.repo.cancel_pending_step_results(run.id)
        await self.repo.update_run_status(
            run.id,
            FlowRunStatus.FAILED,
            error={"code": REVIEW_REJECTED, "message": message},
            expected_statuses=(FlowRunStatus.AWAITING_REVIEW,),
        )
        await self._audit_run(
            ActionType.FLOW_RUN_REVIEWED,
            run,
            "Rejected flow run review",
            channel=channel,
            extra={"checkpoint_id": str(checkpoint.id), "decision": "reject"},
        )
        refreshed = await self._require_checkpoint(run, checkpoint.id)
        return checkpoint_public(refreshed)

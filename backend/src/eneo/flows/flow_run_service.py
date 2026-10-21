"""Runs of a published flow: start, inspect, cancel, review.

Readers start and operate their own runs. Human space owners/admins may
also inspect and operate other principals' runs. Files follow run access.
Execution itself lives in :class:`FlowRunExecutor`; this service only
queues the durable job and exposes state.

A service API key is an automation principal: it owns no ``users`` row, so
a run it starts is recorded as ``principal_type='service'`` with the key's
id, while the job and every file the run produces belong to the flow's
author (the person who built it). A service principal sees only the runs
it started and runs published versions only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import is_service_api_key
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
    definition_to_json,
    run_definition,
    run_file_public,
    run_public,
    run_state_public,
    run_summary_public,
    step_public,
)
from eneo.flows.flow_models import (
    FlowArtifactPublic,
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
from eneo.flows.lifecycle import finish_run
from eneo.flows.schema_validation import validate_value
from eneo.jobs.job_models import Task
from eneo.jobs.job_service import JobService
from eneo.jobs.task_models import FlowRunParams
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.database.tables.flow_tables import (
        FlowRunReviewCheckpoints,
        FlowRuns,
        Flows,
    )
    from eneo.files.file_models import FileMetadata
    from eneo.files.file_service import FileService
    from eneo.flows.flow_repo import FlowRepository
    from eneo.flows.flow_run_executor import FlowRunExecutor
    from eneo.flows.flow_service import FlowService
    from eneo.users.user import UserInDB
    from eneo.users.user_repo import UsersRepository

ACTIVE_RUN_STATUSES = (
    FlowRunStatus.QUEUED,
    FlowRunStatus.RUNNING,
    FlowRunStatus.AWAITING_REVIEW,
)
OPEN_CHECKPOINT_STATES = (
    ReviewCheckpointState.AWAITING_REVIEW,
    ReviewCheckpointState.EDITED,
)
RUNTIME_UPLOAD_ROLE = "runtime_upload"
RUN_FILE_ROLES = {"input": "Input file", "output": "Artifact"}


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
        user_repo: UsersRepository,
    ):
        self.user = user
        self.repo = repo
        self.flow_service = flow_service
        self.job_service = job_service
        self.file_service = file_service
        self.audit_service = audit_service
        self.executor = executor
        self.user_repo = user_repo

    # --- Principals ---

    @property
    def service_key_id(self) -> Optional[UUID]:
        """The key id when the caller is a service API key, else None."""
        if is_service_api_key(self.user) and self.user.active_api_key is not None:
            return self.user.active_api_key.id
        return None

    @property
    def _principal_type(self) -> PrincipalType:
        return (
            PrincipalType.SERVICE
            if self.service_key_id is not None
            else PrincipalType.USER
        )

    @property
    def _principal_user_id(self) -> Optional[UUID]:
        return None if self.service_key_id is not None else self.user.id

    async def _job_owner(self, flow: Flows) -> UserInDB:
        """Who the run's job (and its files) belong to: the caller, or for a
        service principal the flow's author."""
        if self.service_key_id is None:
            return self.user
        author = (
            await self.user_repo.get_user_by_id(id=flow.user_id)
            if flow.user_id is not None
            else None
        )
        if author is None or author.tenant_id != self.user.tenant_id:
            raise BadRequestException(
                "The flow has no author to run as; a person in the space has to "
                "save it before an API key can run it."
            )
        return author

    # --- Lookups and authorization ---

    async def _require_run(
        self, run_id: UUID, *, flow_id: Optional[UUID] = None, mutate: bool = False
    ) -> FlowRuns:
        run = await self.repo.get_run(run_id, self.user.tenant_id)
        # A run is only addressable through its own flow: a valid run id
        # under another flow of the same tenant must not resolve, and a
        # service principal reaches only the runs it started.
        if run is None or (flow_id is not None and run.flow_id != flow_id):
            raise NotFoundException("Flow run not found")
        service_id = self.service_key_id
        if service_id is not None and run.principal_service_id != service_id:
            raise NotFoundException("Flow run not found")
        flow = await self.repo.get_flow(
            run.flow_id, self.user.tenant_id, include_deleted=True
        )
        if flow is None:
            raise NotFoundException("Flow run not found")
        await self.flow_service.authorize_space(flow.space_id, "read")
        if not self._owns(run) and not await self.flow_service.can_operate_runs(
            flow.space_id
        ):
            raise NotFoundException("Flow run not found")
        if mutate:
            flow = await self.repo.get_flow(
                flow.id, self.user.tenant_id, for_update=True
            )
            if flow is None:
                raise NotFoundException("Flow not found")
            run = await self.repo.get_run(run_id, self.user.tenant_id, for_update=True)
            assert run is not None
        return run

    async def _definition_for(self, run: FlowRuns) -> FlowDefinition:
        return await run_definition(self.repo, run)

    def _owns(self, run: FlowRuns) -> bool:
        if self.service_key_id is not None:
            return run.principal_service_id == self.service_key_id
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

    async def _usable_file_ids(self, flow_id: UUID, ids: list[UUID]) -> set[UUID]:
        """Files a run may be given: the caller's own, or runtime uploads of
        the caller uploaded for this flow. An id is never upload authority."""
        usable: set[UUID] = set()
        for file_id in ids:
            row = await self.repo.get_flow_file(
                flow_id, file_id, role=RUNTIME_UPLOAD_ROLE
            )
            if row is not None and (
                (
                    self.service_key_id is not None
                    and row.principal_service_id == self.service_key_id
                )
                or (
                    self.service_key_id is None
                    and row.principal_user_id == self.user.id
                )
            ):
                usable.add(file_id)
        # Service uploads are stored as the flow author's files. The scoped
        # association above is their authority; generic file ownership is not.
        remaining = [file_id for file_id in ids if file_id not in usable]
        if self.service_key_id is None and remaining:
            for info in await self.file_service.get_file_infos(remaining):
                if info.user_id == self.user.id:
                    usable.add(info.id)
        return usable

    async def _validate_run_input(
        self,
        flow_id: UUID,
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
                usable = await self._usable_file_ids(flow_id, list(set(ids)))
                if usable != set(ids):
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

    async def _queue(self, run: FlowRuns, flow: Flows, *, name: str) -> None:
        owner = await self._job_owner(flow)
        job_service = (
            self.job_service
            if owner.id == self.user.id
            else JobService(user=owner, job_repo=self.job_service.job_repo)
        )
        job = await job_service.queue_durable_job(
            Task.RUN_FLOW,
            name=f"{name}: {flow.name}",
            task_params=FlowRunParams(id=run.id, flow_id=run.flow_id, user_id=owner.id),
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
        draft: bool = False,
        channel: str = "api",
    ) -> FlowRunPublic:
        """Start a run of the published version, or with ``draft`` a test run
        of the draft as it is now (editors only; nothing is published)."""
        version: int | None
        service_id = self.service_key_id
        # Serialize creation/idempotent replay with publication and retirement.
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id, for_update=True)
        if flow is None:
            raise NotFoundException("Flow not found")
        if draft and service_id is not None:
            raise UnauthorizedException("Service API keys run published versions only.")
        if draft:
            if expected_flow_version is not None:
                raise BadRequestException(
                    "A test run executes the draft; expected_flow_version does not apply."
                )
            version = None
            definition = await self.flow_service.get_runnable_draft(flow_id)
        else:
            version, definition = await self.flow_service.get_published_definition(
                flow_id
            )
            if expected_flow_version is not None and expected_flow_version != version:
                raise BadRequestException(
                    "Flow was republished since the run contract was read. "
                    f"Expected version {expected_flow_version}, active version "
                    f"{version}."
                )
        if idempotency_key:
            existing = await self.repo.get_run_by_idempotency_key(
                flow_id,
                idempotency_key,
                tenant_id=self.user.tenant_id,
                principal_user_id=self._principal_user_id,
                principal_service_id=service_id,
            )
            if existing is not None:
                return await self._run_public(existing)
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id)
        assert flow is not None
        normalized = await self._validate_run_input(
            flow_id, definition, values=values, files=files
        )
        space = await self.flow_service.authorize_space(flow.space_id)
        published = (
            await self.repo.get_version(flow_id, version)
            if version is not None
            else None
        )
        if published is not None and published.runtime_bindings is None:
            raise BadRequestException(
                "Republish this flow to pin its execution dependencies before running it."
            )
        bindings = await self.flow_service.execution_bindings(
            definition,
            space,
            published.runtime_bindings if published is not None else None,
        )
        run = await self.repo.add_run(
            flow_id=flow_id,
            flow_version=version,
            definition=definition_to_json(definition),
            runtime_bindings=bindings,
            is_test=draft,
            tenant_id=self.user.tenant_id,
            principal_type=(
                PrincipalType.SERVICE.value
                if service_id is not None
                else PrincipalType.USER.value
            ),
            principal_user_id=None if service_id is not None else self.user.id,
            principal_service_id=service_id,
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
        await self._queue(run, flow, name="Test flow" if draft else "Run flow")
        await self._audit_run(
            ActionType.FLOW_RUN_CREATED,
            run,
            "Started flow test run" if draft else "Started flow run",
            channel=channel,
            extra={"run_label": run_label, "is_test": draft},
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
        self,
        flow_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
        statuses: Optional[tuple[FlowRunStatus, ...]] = None,
    ) -> tuple[list[FlowRunSummaryPublic], int]:
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id)
        if flow is None:
            raise NotFoundException("Flow not found")
        await self.flow_service.authorize_space(flow.space_id, "read")
        operator = await self.flow_service.can_operate_runs(flow.space_id)
        runs, total = await self.repo.list_runs(
            flow_id,
            self.user.tenant_id,
            limit=limit,
            offset=offset,
            principal_service_id=self.service_key_id,
            principal_user_id=self.user.id
            if not operator and self.service_key_id is None
            else None,
            statuses=statuses,
        )
        return [run_summary_public(run) for run in runs], total

    async def get_run_state(self, run_id: UUID) -> FlowRunStatePublic:
        run = await self._require_run(run_id)
        definition = await self._definition_for(run)
        files = await self.repo.list_run_files(run.id)
        checkpoint = await self.repo.get_active_checkpoint(run.id)
        return run_state_public(run, definition, files, checkpoint)

    # --- Run files ---

    async def list_artifacts(
        self, flow_id: UUID, *, limit: int = 50
    ) -> list[FlowArtifactPublic]:
        """Every file the flow's runs produced, newest first, so a result can
        be found again without opening the run that made it."""
        flow = await self.repo.get_flow(flow_id, self.user.tenant_id)
        if flow is None:
            raise NotFoundException("Flow not found")
        await self.flow_service.authorize_space(flow.space_id, "read")
        operator = await self.flow_service.can_operate_runs(flow.space_id)
        rows = await self.repo.list_flow_artifacts(
            flow.id,
            self.user.tenant_id,
            limit=limit,
            principal_service_id=self.service_key_id,
            principal_user_id=self.user.id
            if not operator and self.service_key_id is None
            else None,
        )
        return [
            FlowArtifactPublic(
                file=run_file_public(row.file),
                run_id=row.run_id,
                run_label=row.run_label,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def run_file_for_download(
        self, run_id: UUID, file_id: UUID, *, role: str, flow_id: UUID | None = None
    ) -> FileMetadata:
        """The file behind a run's input or output, for a signed download link.

        Reading the flow is what authorizes the file (its uploader or the
        run's principal need not be the caller); the link itself is minted by
        the caller with the metadata returned here.
        """
        run = await self._require_run(run_id, flow_id=flow_id)
        row = await self.repo.get_run_file(run.id, file_id, role=role)
        if row is None:
            raise NotFoundException(
                f"{RUN_FILE_ROLES.get(role, 'File')} not found for this run."
            )
        metadata = await self.file_service.ensure_original_available(
            file_id, require_owner=False
        )
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.FILE_ORIGINAL_DOWNLOAD_LINK_CREATED,
            entity_type=EntityType.FILE,
            entity_id=file_id,
            description=f"Created a download link for flow run file '{metadata.name}'",
            metadata=AuditMetadata.standard(
                actor=self.user,
                target=metadata,
                extra={
                    "flow_id": str(run.flow_id),
                    "run_id": str(run.id),
                    "role": role,
                },
            ),
        )
        return metadata

    # --- Execution (worker side, also used inline by tests) ---

    async def execute_run(self, run_id: UUID) -> None:
        await self.executor.execute_run(run_id, self.user.tenant_id)

    # --- Cancel ---

    async def cancel_run(
        self, run_id: UUID, *, flow_id: UUID | None = None, channel: str = "api"
    ) -> FlowRunPublic:
        run = await self._require_run(run_id, flow_id=flow_id, mutate=True)
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
        moved = await finish_run(
            self.repo,
            self.audit_service,
            run.id,
            run.tenant_id,
            FlowRunStatus.CANCELLED,
            user=self.user,
        )
        if not moved:
            raise BadRequestException("Run is already finished.")
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
        if checkpoint.expires_at is not None and checkpoint.expires_at <= datetime.now(
            UTC
        ):
            raise BadRequestException("The review checkpoint has expired.")
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
                    await validate_value(payload["value"], target.output.schema_)
                except ValueError as exc:
                    raise BadRequestException(
                        f"Edited value does not satisfy the step schema: {exc}"
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
        run = await self._require_run(run_id, flow_id=flow_id, mutate=True)
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
        await self._audit_run(
            ActionType.FLOW_RUN_REVIEW_EDITED,
            run,
            "Edited flow run review",
            channel="api",
            extra={"checkpoint_id": str(checkpoint.id)},
        )
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
        await self._queue(run, flow, name="Resume flow run")
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
        run = await self._require_run(run_id, flow_id=flow_id, mutate=True)
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
            decided_by_principal_type=self._principal_type.value,
            decided_by_user_id=self._principal_user_id,
            decided_by_service_id=self.service_key_id,
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
        run = await self._require_run(run_id, flow_id=flow_id, mutate=True)
        checkpoint = await self._require_checkpoint(run, checkpoint_id)
        if checkpoint.state != ReviewCheckpointState.APPROVED.value:
            raise BadRequestException("Review checkpoint is not approved.")
        self._require_revision(checkpoint, expected_revision)
        await self._audit_run(
            ActionType.FLOW_RUN_REVIEW_RESUMED,
            run,
            "Resumed flow run review",
            channel=channel,
            extra={"checkpoint_id": str(checkpoint.id)},
        )
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
        run = await self._require_run(run_id, flow_id=flow_id, mutate=True)
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
            decided_by_principal_type=self._principal_type.value,
            decided_by_user_id=self._principal_user_id,
            decided_by_service_id=self.service_key_id,
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
        await finish_run(
            self.repo,
            self.audit_service,
            run.id,
            run.tenant_id,
            FlowRunStatus.FAILED,
            error={"code": REVIEW_REJECTED, "message": message},
            expected_statuses=(FlowRunStatus.AWAITING_REVIEW,),
            user=self.user,
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

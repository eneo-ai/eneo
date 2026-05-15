from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence, TypedDict
from uuid import UUID

from intric.files.file_repo import FileRepository
from intric.flows.application.flow_run_access_policy import (
    FlowRunAccessKind,
    FlowRunAccessPolicy,
)
from intric.flows.application.flow_run_recovery_policy import (
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
    flow_stale_running_reconcile_after_seconds,
)
from intric.flows.application.flow_run_terminalization import FlowRunTerminalizer
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowRunTokenUsage,
    FlowStep,
    FlowStepResult,
    JsonObject,
)
from intric.flows.enums import FlowRunLifecycleSource, is_terminal_flow_run_status
from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_input_limits import (
    FlowInputLimits,
    resolve_flow_input_limits_from_source,
)
from intric.flows.flow_run_error import FlowRunError
from intric.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
from intric.flows.flow_run_payload_validation import (
    ensure_inline_payload_size_allowed,
    reject_reserved_input_payload_keys,
)
from intric.flows.flow_run_step_inputs import (
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    serialize_step_inputs_payload,
    validate_submitted_step_inputs,
)
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    PreseedStep,
    StepInputFileProjection,
)
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.principal import FlowPrincipal
from intric.flows.published_definition import parse_published_definition
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.settings.setting_service import SettingService
from intric.users.user import UserInDB

logger = get_logger(__name__)


@dataclass(frozen=True)
class FlowRunStepResultsWithFiles:
    step_results: Sequence[FlowStepResult]
    result_files: Sequence[FlowRunStepResultFile]


class FlowRunDispatchRequest(TypedDict, total=False):
    run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    user_id: UUID | None
    principal_type: str
    principal_user_id: UUID | None
    principal_api_key_id: UUID | None


class FlowRunService:
    """Tenant-scoped flow run lifecycle service."""

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_version_repo: FlowVersionRepository,
        flow_run_terminalizer: FlowRunTerminalizer | None = None,
        file_repo: FileRepository | None = None,
        settings_service: SettingService | None = None,
        execution_backend: FlowExecutionBackend | None = None,
        access_policy: FlowRunAccessPolicy | None = None,
        max_concurrent_runs: int | None = None,
        queued_redispatch_after_seconds: int | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_run_terminalizer = flow_run_terminalizer or FlowRunTerminalizer(
            flow_run_repo,
            flow_run_repo.audit_outbox_repo,
        )
        self.flow_version_repo = flow_version_repo
        self.file_repo = file_repo
        self.settings_service = settings_service
        self.execution_backend = execution_backend
        self.access_policy = access_policy or FlowRunAccessPolicy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
        )
        self.max_concurrent_runs = (
            max_concurrent_runs
            if max_concurrent_runs is not None
            else get_settings().flow_max_concurrent_runs_per_tenant
        )
        self.queued_redispatch_after_seconds = (
            queued_redispatch_after_seconds
            if queued_redispatch_after_seconds is not None
            else FLOW_QUEUED_REDISPATCH_AFTER_SECONDS
        )
        self.running_reconcile_after_seconds = (
            flow_stale_running_reconcile_after_seconds(
                task_timeout_seconds=get_settings().flow_task_timeout_seconds
            )
        )

    def _principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    def build_dispatch_request(self, run: FlowRun) -> FlowRunDispatchRequest:
        principal = FlowPrincipal.from_run(run)
        request: FlowRunDispatchRequest = {
            "run_id": run.id,
            "flow_id": run.flow_id,
            "tenant_id": run.tenant_id,
        }
        if principal.is_service_key:
            request["principal_type"] = principal.principal_type.value
            request["principal_user_id"] = principal.principal_user_id
            request["principal_api_key_id"] = principal.principal_api_key_id
        else:
            request["user_id"] = principal.principal_user_id
        return request

    def _validate_idempotency_key(self, idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        normalized = idempotency_key.strip()
        if not normalized or len(normalized) > 255:
            raise BadRequestException(
                "Idempotency key must be between 1 and 255 characters.",
                code="flow_run_invalid_idempotency_key",
            )
        return normalized

    async def create_run(
        self,
        *,
        flow_id: UUID,
        input_payload_json: dict[str, Any] | None,
        expected_flow_version: int | None = None,
        step_inputs: dict[UUID, dict[str, list[UUID]]] | None = None,
        idempotency_key: str | None = None,
    ) -> FlowRun:
        idempotency_key = self._validate_idempotency_key(idempotency_key)
        principal = self._principal()
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        if flow.published_version is None:
            raise BadRequestException(
                "Flow must be published before a run can be created.",
                code="flow_not_published",
                context={"flow_id": str(flow_id)},
            )

        if (
            expected_flow_version is not None
            and expected_flow_version != flow.published_version
        ):
            raise BadRequestException(
                "The published flow version changed before this run request was submitted.",
                code="flow_run_stale_version",
                context={
                    "expected_flow_version": expected_flow_version,
                    "published_flow_version": flow.published_version,
                },
            )

        runtime_version = await self.flow_version_repo.get(
            flow_id=flow_id,
            version=flow.published_version,
            tenant_id=self.user.tenant_id,
        )
        published_definition = parse_published_definition(
            runtime_version.definition_json
        )
        definition_json = published_definition.definition_json
        normalized_inline_payload = normalize_and_validate_flow_run_payload(
            metadata=published_definition.metadata(),
            payload=input_payload_json,
        )
        reject_reserved_input_payload_keys(normalized_inline_payload)
        normalized_step_inputs = normalize_step_inputs_payload(step_inputs)
        preseed_steps = self._build_preseed_steps(
            definition_json=definition_json,
            fallback_steps=flow.steps,
        )
        step_input_file_projections: list[StepInputFileProjection] = []
        if step_inputs is not None or published_definition.has_required_runtime_input():
            runtime_steps = published_definition.runtime_steps()
            limits = await self._resolve_flow_input_limits()
            runtime_specs = build_runtime_step_input_specs(
                steps=runtime_steps, limits=limits
            )
            await validate_submitted_step_inputs(
                steps=runtime_steps,
                specs=runtime_specs,
                normalized_step_inputs=normalized_step_inputs,
                file_repo=self.file_repo,
                user_id=self.user.id,
                principal=principal,
            )
            step_order_by_id = {
                runtime_step.step_id: runtime_step.step_order
                for runtime_step in runtime_steps
            }
            step_input_file_projections = [
                {
                    "step_id": step_id,
                    "step_order": step_order_by_id[step_id],
                    "file_ids": file_ids,
                }
                for step_id, file_ids in normalized_step_inputs.items()
                if file_ids
            ]
        effective_payload = dict(normalized_inline_payload or {})
        effective_payload["expected_flow_version"] = flow.published_version
        if normalized_step_inputs:
            effective_payload["step_inputs"] = serialize_step_inputs_payload(
                normalized_step_inputs
            )
        input_payload_json = effective_payload or None
        request_fingerprint = self._build_idempotency_fingerprint(
            tenant_id=self.user.tenant_id,
            principal=principal,
            flow_id=flow_id,
            flow_version=flow.published_version,
            input_payload_json=input_payload_json,
        )

        ensure_inline_payload_size_allowed(
            flow_id=flow_id,
            input_payload_json=input_payload_json,
        )

        # Serialize run creation per tenant to prevent concurrency-limit race conditions.
        await self.flow_run_repo.acquire_tenant_run_creation_lock(
            tenant_id=self.user.tenant_id
        )
        if idempotency_key is not None:
            existing = await self.flow_run_repo.get_idempotent_run(
                tenant_id=self.user.tenant_id,
                flow_id=flow_id,
                idempotency_key=idempotency_key,
                principal=principal,
            )
            if existing is not None:
                existing_run, existing_fingerprint = existing
                if existing_fingerprint != request_fingerprint:
                    raise BadRequestException(
                        "Idempotency key was already used with a different run request payload.",
                        code="flow_run_idempotency_conflict",
                    )
                return existing_run
        active_runs = await self.flow_run_repo.count_active_runs(
            tenant_id=self.user.tenant_id
        )
        if active_runs >= self.max_concurrent_runs:
            raise BadRequestException(
                "Concurrent flow run limit reached for this tenant.",
                code="flow_run_concurrency_limit_reached",
                context={"max_concurrent_runs": self.max_concurrent_runs},
            )
        if flow.id is None:
            raise BadRequestException(
                "Flow id missing for run creation.",
                code="flow_id_missing",
            )
        created = await self.flow_run_repo.create(
            flow_id=flow.id,
            flow_version=flow.published_version,
            user_id=principal.legacy_user_id,
            principal_type=principal.principal_type.value,
            principal_user_id=principal.principal_user_id,
            principal_api_key_id=principal.principal_api_key_id,
            tenant_id=self.user.tenant_id,
            input_payload_json=input_payload_json,
            preseed_steps=preseed_steps,
            step_input_files=step_input_file_projections,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        return created

    async def _resolve_flow_input_limits(self) -> FlowInputLimits:
        return await resolve_flow_input_limits_from_source(self.settings_service)

    def _build_idempotency_fingerprint(
        self,
        *,
        tenant_id: UUID,
        principal: FlowPrincipal,
        flow_id: UUID,
        flow_version: int,
        input_payload_json: dict[str, Any] | None,
    ) -> str:
        normalized = {
            "request_fingerprint_algo_version": 1,
            "tenant_id": str(tenant_id),
            "principal_type": principal.principal_type.value,
            "principal_user_id": (
                str(principal.principal_user_id)
                if principal.principal_user_id is not None
                else None
            ),
            "principal_api_key_id": (
                str(principal.principal_api_key_id)
                if principal.principal_api_key_id is not None
                else None
            ),
            "flow_id": str(flow_id),
            "flow_version": flow_version,
            "input_payload_json": input_payload_json,
        }
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    async def get_run(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
        access_kind: FlowRunAccessKind = "status",
    ) -> FlowRun:
        return await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind=access_kind,
        )

    async def list_runs(
        self,
        *,
        flow_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRun]:
        principal = self._principal()
        is_tenant_admin = self.access_policy.is_tenant_admin()
        if (
            not is_tenant_admin
            and not principal.is_service_key
            and flow_id is not None
        ):
            if await self.access_policy.can_list_all_runs_in_flow(flow_id=flow_id):
                return await self.flow_run_repo.list_runs(
                    tenant_id=self.user.tenant_id,
                    flow_id=flow_id,
                    user_id=None,
                    principal_api_key_id=None,
                    limit=limit,
                    offset=offset,
                )
        return await self.flow_run_repo.list_runs(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            user_id=(
                None
                if is_tenant_admin or principal.is_service_key
                else principal.principal_user_id
            ),
            principal_api_key_id=(
                principal.principal_api_key_id
                if not is_tenant_admin and principal.is_service_key
                else None
            ),
            limit=limit,
            offset=offset,
        )

    async def list_step_results(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
    ) -> list[FlowStepResult]:
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        return await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )

    async def list_result_files_for_runs(
        self, *, runs: Sequence[FlowRun]
    ) -> list[FlowRunStepResultFile]:
        if not runs:
            return []
        run_ids: list[UUID] = []
        for run in runs:
            if run.tenant_id != self.user.tenant_id:
                self.access_policy.deny_run_access(auth_layer="flow_run_argument")
            run_ids.append(run.id)
        return await self.flow_run_repo.list_result_files_for_runs(
            run_ids=run_ids,
            tenant_id=self.user.tenant_id,
        )

    async def list_token_usage_for_runs(
        self, *, runs: Sequence[FlowRun]
    ) -> dict[UUID, FlowRunTokenUsage]:
        if not runs:
            return {}
        run_ids: list[UUID] = []
        for run in runs:
            if run.tenant_id != self.user.tenant_id:
                self.access_policy.deny_run_access(auth_layer="flow_run_argument")
            run_ids.append(run.id)
        return await self.flow_run_repo.list_token_usage_for_runs(
            run_ids=run_ids,
            tenant_id=self.user.tenant_id,
        )

    async def list_step_results_with_files(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
    ) -> FlowRunStepResultsWithFiles:
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        step_results = await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        result_files = await self.flow_run_repo.list_result_files(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        return FlowRunStepResultsWithFiles(
            step_results=tuple(step_results),
            result_files=tuple(result_files),
        )

    async def redispatch_stale_queued_runs(
        self,
        *,
        flow_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 25,
        execution_backend: FlowExecutionBackend | None = None,
    ) -> int:
        backend = execution_backend or self.execution_backend
        if backend is None:
            return 0

        stale_before = datetime.now(timezone.utc) - timedelta(
            seconds=max(1, self.queued_redispatch_after_seconds)
        )
        stale_runs = await self.flow_run_repo.list_stale_queued_runs(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            run_id=run_id,
            stale_before=stale_before,
            limit=limit,
        )
        redispatched = 0
        for run in stale_runs:
            claimed_run = (
                await self.flow_run_repo.claim_stale_queued_run_for_redispatch(
                    run_id=run.id,
                    tenant_id=self.user.tenant_id,
                    stale_before=stale_before,
                    flow_id=flow_id,
                )
            )
            if claimed_run is None:
                continue
            try:
                principal = FlowPrincipal.from_run(claimed_run)
            except ValueError:
                continue
            try:
                if principal.is_service_key:
                    await backend.dispatch(
                        run_id=claimed_run.id,
                        flow_id=claimed_run.flow_id,
                        tenant_id=claimed_run.tenant_id,
                        principal_type=principal.principal_type.value,
                        principal_user_id=principal.principal_user_id,
                        principal_api_key_id=(principal.principal_api_key_id),
                    )
                else:
                    await backend.dispatch(
                        run_id=claimed_run.id,
                        flow_id=claimed_run.flow_id,
                        tenant_id=claimed_run.tenant_id,
                        user_id=principal.principal_user_id,
                    )
                redispatched += 1
            except Exception:
                logger.exception(
                    "Failed to redispatch stale queued flow run",
                    extra={
                        "run_id": str(claimed_run.id),
                        "flow_id": str(claimed_run.flow_id),
                        "tenant_id": str(claimed_run.tenant_id),
                    },
                )
                if run_id is not None:
                    raise
        return redispatched

    async def reconcile_stale_running_runs(self, *, limit: int = 25) -> int:
        stale_before = datetime.now(timezone.utc) - timedelta(
            seconds=max(1, self.running_reconcile_after_seconds)
        )
        stale_runs = await self.flow_run_repo.list_stale_running_runs(
            tenant_id=self.user.tenant_id,
            stale_before=stale_before,
            limit=limit,
        )
        reconciled = 0
        error_message = "flow_worker_stalled: Flow run exceeded the execution timeout and was reconciled as failed."
        for run in stale_runs:
            result = await self.flow_run_terminalizer.terminalize_stale_running_run(
                run_id=run.id,
                tenant_id=self.user.tenant_id,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
                    code="flow_worker_stalled",
                    message=error_message,
                ),
                stale_before=stale_before,
            )
            if result.did_transition:
                reconciled += 1
        return reconciled

    async def cancel_run(self, *, run_id: UUID) -> FlowRun:
        run = await self.get_run(run_id=run_id, access_kind="cancel")
        if is_terminal_flow_run_status(run.status):
            return run
        result = await self.flow_run_terminalizer.terminalize_run(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.USER_CANCEL,
            error=FlowRunError.from_source(
                FlowRunLifecycleSource.USER_CANCEL,
                code="user_cancelled",
                message="Run cancelled by user.",
            ),
            cancelled_at=datetime.now(timezone.utc),
            principal=self._principal(),
        )
        return result.run

    def _build_preseed_steps(
        self,
        *,
        definition_json: JsonObject,
        fallback_steps: list[FlowStep],
    ) -> list[PreseedStep]:
        raw_steps = parse_published_definition(definition_json).steps
        if not raw_steps:
            raise BadRequestException(
                "Published flow version does not contain executable steps.",
                code="flow_version_no_executable_steps",
            )

        by_step_order: dict[int, FlowStep] = {}
        for step in fallback_steps:
            if getattr(step, "id", None) is None:
                continue
            by_step_order[int(step.step_order)] = step

        preseed: list[PreseedStep] = []
        for step_snapshot in raw_steps:
            step_order_raw = step_snapshot.get("step_order", 0)
            if isinstance(step_order_raw, bool):
                raise BadRequestException(
                    "Invalid flow version step order.",
                    code="flow_version_invalid_step_order",
                    context={"step_order": step_order_raw},
                )
            try:
                step_order = int(step_order_raw)
            except (TypeError, ValueError) as exc:
                raise BadRequestException(
                    "Invalid flow version step order.",
                    code="flow_version_invalid_step_order",
                    context={"step_order": step_order_raw},
                ) from exc
            if step_order <= 0:
                raise BadRequestException(
                    "Invalid flow version step order.",
                    code="flow_version_invalid_step_order",
                    context={"step_order": step_order},
                )

            step_id_raw = step_snapshot.get("step_id")
            assistant_id_raw = step_snapshot.get("assistant_id")
            if step_id_raw is None or assistant_id_raw is None:
                fallback = by_step_order.get(step_order)
                if fallback is None:
                    raise BadRequestException(
                        f"Flow version step {step_order} is missing stable step identifiers.",
                        code="flow_version_missing_step_identifiers",
                        context={"step_order": step_order},
                    )
                step_id_raw = fallback.id
                assistant_id_raw = fallback.assistant_id

            try:
                step_id = UUID(str(step_id_raw))
            except (TypeError, ValueError, AttributeError) as exc:
                raise BadRequestException(
                    "Invalid flow version step identifier.",
                    code="flow_version_invalid_step_identifier",
                    context={
                        "step_order": step_order,
                        "field": "step_id",
                        "value": step_id_raw,
                    },
                ) from exc

            try:
                assistant_id = UUID(str(assistant_id_raw))
            except (TypeError, ValueError, AttributeError) as exc:
                raise BadRequestException(
                    "Invalid flow version step identifier.",
                    code="flow_version_invalid_step_identifier",
                    context={
                        "step_order": step_order,
                        "field": "assistant_id",
                        "value": assistant_id_raw,
                    },
                ) from exc

            preseed.append(
                {
                    "step_id": step_id,
                    "assistant_id": assistant_id,
                    "step_order": step_order,
                }
            )
        return preseed

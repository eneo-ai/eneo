from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol, Sequence, TypedDict, cast
from uuid import UUID

from intric.files.file_repo import FileRepository
from intric.flows.application.flow_run_recovery_policy import (
    FLOW_QUEUED_REDISPATCH_AFTER_SECONDS,
    flow_stale_running_reconcile_after_seconds,
)
from intric.flows.application.flow_run_terminalization import FlowRunTerminalizer
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
    FlowStep,
    FlowStepResult,
    JsonObject,
)
from intric.flows.enums import FlowRunLifecycleSource, is_terminal_flow_run_status
from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_evidence_policy import (
    EvidenceCapabilityLevel,
    classification_level_for_space,
    flow_metadata_marks_sensitive,
    resolve_flow_evidence_policy,
    resolve_service_key_evidence_capability,
)
from intric.flows.flow_input_limits import FlowInputLimits, resolve_flow_input_limits
from intric.flows.flow_metadata import (
    FlowMetadataParseMode,
    FlowMetadataV1,
    parse_flow_metadata,
)
from intric.flows.flow_permissions import user_can_view_flow_trace
from intric.flows.flow_run_evidence_bundle import (
    EvidenceBundle,
    RedactedEvidenceBundle,
    build_evidence_bundle,
    redact_evidence_bundle,
)
from intric.flows.flow_run_evidence_export_manifest import EvidenceExportContext
from intric.flows.flow_run_export_json import render_evidence_json_export
from intric.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
from intric.flows.flow_run_rerun_graph import (
    RerunGraphStepNotFound,
    RerunInvalidationGraph,
    build_rerun_invalidation_graph,
)
from intric.flows.flow_run_rerun_request import (
    FlowRunRerunRequestFingerprintInput,
    build_rerun_request_fingerprint,
)
from intric.flows.flow_run_step_inputs import (
    FLOW_RUN_ORCHESTRATION_INPUT_KEYS,
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    serialize_step_inputs_payload,
    validate_submitted_step_inputs,
)
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    FlowRunRerunCommandResult,
    FlowRunReviewCheckpointResumeResult,
    PreseedStep,
    StepInputFileProjection,
)
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.output_processing import validate_against_contract
from intric.flows.principal import FlowPrincipal
from intric.flows.published_definition import (
    PublishedFlowDefinition,
    parse_published_definition,
    parse_published_runtime_steps,
)
from intric.flows.runtime.models import RuntimeStep
from intric.main.config import get_settings
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    ResourceGoneException,
    TypedIOValidationException,
    UnauthorizedException,
)
from intric.main.logging import get_logger
from intric.roles.permissions import Permission
from intric.settings.setting_service import SettingService
from intric.users.user import UserInDB

logger = get_logger(__name__)

_RERUN_REASON_MAX_LENGTH = 1024
_REVIEW_REJECT_REASON_MAX_LENGTH = _RERUN_REASON_MAX_LENGTH

FlowRunAccessKind = Literal[
    "status",
    "cancel",
    "content",
    "artifact",
    "evidence_view",
    "evidence_export_redacted",
    "evidence_export_raw",
]


@dataclass(frozen=True)
class FlowRunStepResultsWithFiles:
    step_results: Sequence[FlowStepResult]
    result_files: Sequence[FlowRunStepResultFile]


class _SettingsServiceProtocol(Protocol):
    async def get_flow_input_limits_resolved(self) -> FlowInputLimits: ...


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
        space_service: Any | None = None,
        actor_manager: Any | None = None,
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
        self.space_service = space_service
        self.actor_manager = actor_manager
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

    def _is_tenant_admin(self) -> bool:
        return Permission.ADMIN in self.user.permissions

    def _principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    async def _load_space_access(self, *, flow_id: UUID) -> tuple[Any | None, int]:
        if self.space_service is None or self.actor_manager is None:
            return None, 0
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        space = await self.space_service.get_space(flow.space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        return actor, classification_level_for_space(space)

    def _evidence_policy(self):
        tenant = getattr(self.user, "tenant", None)
        tenant_flow_settings = getattr(tenant, "flow_settings", None)
        return resolve_flow_evidence_policy(tenant_flow_settings)

    async def _ensure_sensitive_flow_export_allowed(self, *, flow_id: UUID) -> None:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        if (
            flow_metadata_marks_sensitive(flow.metadata_json)
            and not self._evidence_policy().allow_sensitive_flow_exports
        ):
            self._raise_evidence_forbidden(
                auth_layer="flow_runtime_policy",
                message="Evidence export is disabled by policy for this sensitive flow.",
            )

    def _service_key_evidence_capability(self) -> EvidenceCapabilityLevel:
        return resolve_service_key_evidence_capability(self.user)

    def _human_trace_allowed(self) -> bool:
        return user_can_view_flow_trace(self.user)

    @staticmethod
    def _raise_run_access_denied(*, auth_layer: str) -> None:
        raise UnauthorizedException(
            "You do not have access to this flow run.",
            code="flow_run_access_denied",
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def _raise_evidence_forbidden(*, auth_layer: str, message: str) -> None:
        raise UnauthorizedException(
            message,
            code="flow_run_evidence_forbidden",
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def _raise_raw_export_forbidden(*, auth_layer: str, message: str) -> None:
        raise UnauthorizedException(
            message,
            code="flow_run_evidence_raw_export_forbidden",
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def _raise_artifact_content_unavailable(*, run_id: UUID, file_id: UUID) -> None:
        raise ResourceGoneException(
            "Artifact content has been purged by retention policy.",
            code="flow_run_artifact_content_unavailable",
            context={"run_id": str(run_id), "file_id": str(file_id)},
        )

    async def _ensure_can_access_run(self, run: FlowRun, *, access_kind: str) -> None:
        if run.tenant_id != self.user.tenant_id:
            self._raise_run_access_denied(auth_layer="tenant_isolation")
        if access_kind in {"evidence_export_redacted", "evidence_export_raw"}:
            await self._ensure_sensitive_flow_export_allowed(flow_id=run.flow_id)
        if self._is_tenant_admin():
            return
        principal = self._principal()
        if principal.is_service_key:
            if not principal.matches_run(run):
                self._raise_run_access_denied(auth_layer="flow_run_principal")
            capability = self._service_key_evidence_capability()
            policy = self._evidence_policy()
            actor, classification_level = await self._load_space_access(
                flow_id=run.flow_id
            )
            _ = actor  # classification still derives from the space, actor unused for service keys
            if access_kind in {"status", "cancel", "content", "artifact"}:
                return
            if access_kind == "evidence_view":
                if capability >= EvidenceCapabilityLevel.VIEW:
                    return
                self._raise_evidence_forbidden(
                    auth_layer="flow_run_principal",
                    message="Service principal is not authorized to view evidence for this run.",
                )
            if access_kind == "evidence_export_redacted":
                if capability >= EvidenceCapabilityLevel.REDACTED_EXPORT:
                    return
                self._raise_evidence_forbidden(
                    auth_layer="flow_run_principal",
                    message="Service principal is not authorized to export evidence for this run.",
                )
            if access_kind == "evidence_export_raw":
                if capability < EvidenceCapabilityLevel.RAW_EXPORT:
                    self._raise_evidence_forbidden(
                        auth_layer="flow_run_principal",
                        message="Service principal is not authorized to export raw evidence for this run.",
                    )
                if (
                    classification_level >= 3
                    and not policy.allow_service_key_raw_export_class3
                ):
                    self._raise_raw_export_forbidden(
                        auth_layer="flow_run_principal",
                        message="Raw evidence export is not allowed for service principals in classification 3 spaces.",
                    )
                return
            self._raise_run_access_denied(auth_layer="flow_run_principal")

        actor, classification_level = await self._load_space_access(flow_id=run.flow_id)
        role_value = (
            getattr(actor.get_current_role(), "value", actor.get_current_role())
            if actor is not None
            else None
        )
        policy = self._evidence_policy()

        if role_value in {"admin", "owner"}:
            if access_kind in {
                "status",
                "cancel",
                "content",
                "artifact",
                "evidence_view",
                "evidence_export_redacted",
            }:
                return
            if access_kind == "evidence_export_raw":
                if role_value == "owner":
                    return
                if (
                    classification_level < 3
                    or policy.allow_space_admin_raw_export_class3
                ):
                    return
                self._raise_raw_export_forbidden(
                    auth_layer="space_membership",
                    message="Raw evidence export is not allowed for space admins in classification 3 spaces.",
                )

        if principal.matches_run(run):
            if access_kind in {"status", "cancel", "content", "artifact"}:
                return
            if access_kind in {"evidence_view", "evidence_export_redacted"}:
                if self._human_trace_allowed():
                    return
                raise UnauthorizedException(
                    "You do not have permission to view flow trace.",
                    code="insufficient_tenant_permission",
                    context={"auth_layer": "tenant_role"},
                )
            if access_kind == "evidence_export_raw":
                if not self._human_trace_allowed():
                    raise UnauthorizedException(
                        "You do not have permission to view flow trace.",
                        code="insufficient_tenant_permission",
                        context={"auth_layer": "tenant_role"},
                    )
                if classification_level < 3 or policy.allow_run_owner_raw_export_class3:
                    return
                self._raise_raw_export_forbidden(
                    auth_layer="flow_run_owner",
                    message="Raw evidence export is not allowed for this run in a classification 3 space.",
                )

        self._raise_run_access_denied(auth_layer="flow_run_owner")

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

    def _review_user_principal(self, *, capability: str) -> FlowPrincipal:
        principal = self._principal()
        if principal.is_service_key:
            raise UnauthorizedException(
                "This Flows endpoint requires a user principal. Service-key principals cannot use this action.",
                code="flow_service_key_principal_not_supported",
                context={
                    "auth_layer": "service_key_principal",
                    "capability": capability,
                },
            )
        return principal

    def _validate_review_resume_idempotency_key(self, key: str | None) -> str:
        if key is None or not key.strip():
            raise BadRequestException(
                "Review resume requires an Idempotency-Key header.",
                code="flow_review_idempotency_key_required",
            )
        normalized = self._validate_idempotency_key(key)
        if normalized is None:
            raise BadRequestException(
                "Review resume requires an Idempotency-Key header.",
                code="flow_review_idempotency_key_required",
            )
        return normalized

    @staticmethod
    def _normalize_review_reject_reason(reason: str) -> str:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise BadRequestException(
                "Review rejection reason is required.",
                code="flow_review_reject_reason_required",
            )
        if len(normalized_reason) > _REVIEW_REJECT_REASON_MAX_LENGTH:
            raise BadRequestException(
                "Review rejection reason must be at most 1024 characters.",
                code="flow_review_reject_reason_too_long",
                context={"max_length": _REVIEW_REJECT_REASON_MAX_LENGTH},
            )
        return normalized_reason

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

        normalized_inline_payload = normalize_and_validate_flow_run_payload(
            metadata=self._parse_draft_metadata_lenient(flow.metadata_json),
            payload=input_payload_json,
        )
        self._reject_reserved_input_payload_keys(normalized_inline_payload)
        normalized_step_inputs = normalize_step_inputs_payload(step_inputs)
        runtime_version_definition: JsonObject | None = None
        preseed_steps: list[PreseedStep] | None = None
        step_input_file_projections: list[StepInputFileProjection] = []
        if step_inputs is not None:
            runtime_version = await self.flow_version_repo.get(
                flow_id=flow_id,
                version=flow.published_version,
                tenant_id=self.user.tenant_id,
            )
            runtime_version_definition = runtime_version.definition_json
            preseed_steps = self._build_preseed_steps(
                definition_json=runtime_version_definition,
                fallback_steps=flow.steps,
            )
            runtime_steps = parse_published_runtime_steps(runtime_version_definition)
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

        self._ensure_inline_payload_size_allowed(
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
        if runtime_version_definition is None:
            runtime_version = await self.flow_version_repo.get(
                flow_id=flow.id,
                version=flow.published_version,
                tenant_id=self.user.tenant_id,
            )
            runtime_version_definition = runtime_version.definition_json
            preseed_steps = self._build_preseed_steps(
                definition_json=runtime_version_definition,
                fallback_steps=flow.steps,
            )
            if self._definition_has_required_runtime_step_inputs(
                runtime_version_definition
            ):
                runtime_steps = parse_published_runtime_steps(
                    runtime_version_definition
                )
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
        assert preseed_steps is not None
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

    async def rerun_step(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        rerun_step_id: UUID,
        expected_run_revision: int,
        reason: str,
        input_payload_json: dict[str, Any] | None = None,
        step_inputs: dict[UUID, dict[str, list[UUID]]] | None = None,
    ) -> FlowRunRerunCommandResult:
        normalized_reason = self._normalize_rerun_reason(reason)
        run = await self.flow_run_repo.get(
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
        version = await self.flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=self.user.tenant_id,
        )
        published_definition = parse_published_definition(version.definition_json)
        runtime_steps = published_definition.runtime_steps()
        invalidation_graph, root_runtime_step = self._resolve_rerun_graph(
            runtime_steps=runtime_steps,
            rerun_step_id=rerun_step_id,
        )

        normalized_inline_payload = self._normalize_rerun_inline_payload(
            flow_id=run.flow_id,
            published_definition=published_definition,
            input_payload_json=input_payload_json,
        )
        normalized_step_inputs = await self._normalize_and_validate_rerun_step_inputs(
            runtime_steps=runtime_steps,
            root_runtime_step=root_runtime_step,
            rerun_step_id=rerun_step_id,
            step_inputs=step_inputs,
        )
        serialized_step_inputs = (
            serialize_step_inputs_payload(normalized_step_inputs)
            if normalized_step_inputs
            else None
        )
        prior_root_attempt_id = (
            await self.flow_run_repo.get_latest_completed_attempt_id_for_step(
                run_id=run.id,
                flow_id=run.flow_id,
                tenant_id=self.user.tenant_id,
                step_id=rerun_step_id,
            )
        )
        request_fingerprint = build_rerun_request_fingerprint(
            FlowRunRerunRequestFingerprintInput(
                tenant_id=self.user.tenant_id,
                requested_by_user_id=self.user.id,
                flow_id=run.flow_id,
                flow_run_id=run.id,
                rerun_step_id=rerun_step_id,
                expected_run_revision=expected_run_revision,
                prior_root_attempt_id=prior_root_attempt_id,
                input_payload_json=normalized_inline_payload,
                root_step_inputs=normalized_step_inputs or None,
            )
        )
        return await self.flow_run_repo.accept_or_replay_rerun_operation(
            tenant_id=self.user.tenant_id,
            flow_id=run.flow_id,
            flow_run_id=run.id,
            rerun_step_id=rerun_step_id,
            rerun_step_order=root_runtime_step.step_order,
            request_fingerprint=request_fingerprint,
            expected_run_revision=expected_run_revision,
            reason=normalized_reason,
            input_payload_json=normalized_inline_payload,
            step_inputs_json=serialized_step_inputs,
            requested_by_user_id=self.user.id,
            invalidated_steps=invalidation_graph.invalidated_steps,
        )

    async def _resolve_flow_input_limits(self) -> FlowInputLimits:
        settings_service = cast(_SettingsServiceProtocol | None, self.settings_service)
        if settings_service is not None:
            return await settings_service.get_flow_input_limits_resolved()
        return resolve_flow_input_limits(None)

    @staticmethod
    def _normalize_rerun_reason(reason: str) -> str:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise BadRequestException(
                "Rerun reason is required.",
                code="flow_run_rerun_reason_required",
            )
        if len(normalized_reason) > _RERUN_REASON_MAX_LENGTH:
            raise BadRequestException(
                "Rerun reason must be at most 1024 characters.",
                code="flow_run_rerun_reason_too_long",
                context={"max_length": _RERUN_REASON_MAX_LENGTH},
            )
        return normalized_reason

    @staticmethod
    def _resolve_rerun_graph(
        *,
        runtime_steps: list[RuntimeStep],
        rerun_step_id: UUID,
    ) -> tuple[RerunInvalidationGraph, RuntimeStep]:
        try:
            invalidation_graph = build_rerun_invalidation_graph(
                steps=runtime_steps,
                root_step_id=rerun_step_id,
            )
        except RerunGraphStepNotFound as exc:
            raise BadRequestException(
                "Rerun step is not in the published flow snapshot.",
                code="flow_run_rerun_step_not_found",
            ) from exc
        root_runtime_step = next(
            step for step in runtime_steps if step.step_id == rerun_step_id
        )
        return invalidation_graph, root_runtime_step

    def _normalize_rerun_inline_payload(
        self,
        *,
        flow_id: UUID,
        published_definition: PublishedFlowDefinition,
        input_payload_json: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if input_payload_json is None:
            return None
        normalized_inline_payload = normalize_and_validate_flow_run_payload(
            metadata=published_definition.metadata(),
            payload=input_payload_json,
        )
        self._reject_reserved_input_payload_keys(normalized_inline_payload)
        self._ensure_inline_payload_size_allowed(
            flow_id=flow_id,
            input_payload_json=normalized_inline_payload,
        )
        return normalized_inline_payload

    @staticmethod
    def _parse_draft_metadata_lenient(
        metadata_json: JsonObject | None,
    ) -> FlowMetadataV1 | None:
        try:
            return parse_flow_metadata(
                metadata_json, mode=FlowMetadataParseMode.PERSISTED_READ
            )
        except BadRequestException:
            # Draft metadata can be mid-edit; preserve create-run passthrough behavior.
            return None

    async def _normalize_and_validate_rerun_step_inputs(
        self,
        *,
        runtime_steps: list[RuntimeStep],
        root_runtime_step: RuntimeStep,
        rerun_step_id: UUID,
        step_inputs: dict[UUID, dict[str, list[UUID]]] | None,
    ) -> dict[UUID, list[UUID]]:
        normalized_step_inputs = normalize_step_inputs_payload(step_inputs)
        downstream_step_input_ids = [
            str(step_id)
            for step_id in normalized_step_inputs
            if step_id != rerun_step_id
        ]
        if downstream_step_input_ids:
            raise BadRequestException(
                "Rerun step_inputs may only target the rerun root step.",
                code="flow_run_rerun_step_inputs_invalid",
                context={"step_ids": downstream_step_input_ids},
            )
        if not normalized_step_inputs:
            return normalized_step_inputs

        limits = await self._resolve_flow_input_limits()
        runtime_specs = build_runtime_step_input_specs(
            steps=runtime_steps,
            limits=limits,
        )
        root_specs = (
            {rerun_step_id: runtime_specs[rerun_step_id]}
            if rerun_step_id in runtime_specs
            else {}
        )
        await validate_submitted_step_inputs(
            steps=[root_runtime_step],
            specs=root_specs,
            normalized_step_inputs=normalized_step_inputs,
            file_repo=self.file_repo,
            user_id=self.user.id,
            principal=self._principal(),
        )
        return normalized_step_inputs

    @staticmethod
    def _reject_reserved_input_payload_keys(
        input_payload_json: dict[str, Any] | None,
    ) -> None:
        if input_payload_json is None:
            return
        reserved_keys = sorted(
            set(input_payload_json) & FLOW_RUN_ORCHESTRATION_INPUT_KEYS
        )
        if not reserved_keys:
            return
        raise BadRequestException(
            "Flow run input_payload_json contains reserved orchestration keys.",
            code="flow_run_reserved_input_payload_key",
            context={"keys": reserved_keys},
        )

    @staticmethod
    def _ensure_inline_payload_size_allowed(
        *,
        flow_id: UUID,
        input_payload_json: dict[str, Any] | None,
    ) -> None:
        if input_payload_json is None:
            return
        payload_size = len(
            json.dumps(
                input_payload_json,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if payload_size <= get_settings().flow_max_inline_text_bytes:
            return
        raise BadRequestException(
            "Flow run input payload exceeds allowed size limit.",
            code="flow_run_input_payload_too_large",
            context={
                "flow_id": str(flow_id),
                "max_inline_text_bytes": get_settings().flow_max_inline_text_bytes,
            },
        )

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
        run = await self.flow_run_repo.get(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )
        await self._ensure_can_access_run(run, access_kind=access_kind)
        return run

    async def list_runs(
        self,
        *,
        flow_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRun]:
        principal = self._principal()
        if (
            not self._is_tenant_admin()
            and not principal.is_service_key
            and flow_id is not None
        ):
            actor, _classification_level = await self._load_space_access(
                flow_id=flow_id
            )
            role_value = (
                getattr(actor.get_current_role(), "value", actor.get_current_role())
                if actor is not None
                else None
            )
            if role_value in {"admin", "owner"}:
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
                if self._is_tenant_admin() or principal.is_service_key
                else principal.principal_user_id
            ),
            principal_api_key_id=(
                principal.principal_api_key_id
                if not self._is_tenant_admin() and principal.is_service_key
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
                self._raise_run_access_denied(auth_layer="flow_run_argument")
            run_ids.append(run.id)
        return await self.flow_run_repo.list_result_files_for_runs(
            run_ids=run_ids,
            tenant_id=self.user.tenant_id,
        )

    async def get_active_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
    ) -> FlowRunReviewCheckpoint | None:
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        return await self.flow_run_repo.get_active_review_checkpoint(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )

    async def edit_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
        current_payload_json: JsonObject,
    ) -> FlowRunReviewCheckpoint:
        principal = self._review_user_principal(capability="review")
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        checkpoint = await self.flow_run_repo.get_review_checkpoint_for_edit(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
        )
        self._validate_review_checkpoint_edit_payload(
            checkpoint=checkpoint,
            current_payload_json=current_payload_json,
        )
        return await self.flow_run_repo.edit_review_checkpoint_payload(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            current_payload_json=current_payload_json,
            principal=principal,
        )

    @staticmethod
    def _validate_review_checkpoint_edit_payload(
        *,
        checkpoint: FlowRunReviewCheckpoint,
        current_payload_json: JsonObject,
    ) -> None:
        if checkpoint.output_contract_json is None:
            return
        context: dict[str, object] = {
            "checkpoint_id": str(checkpoint.id),
            "step_id": str(checkpoint.step_id),
            "step_order": checkpoint.step_order,
            "payload_field": "structured",
        }
        if "structured" not in current_payload_json:
            raise TypedIOValidationException(
                f"Review checkpoint step {checkpoint.step_order} output: "
                "field `structured` is required for contract validation.",
                code="typed_io_contract_violation",
                context=context,
            )
        try:
            validate_against_contract(
                current_payload_json["structured"],
                checkpoint.output_contract_json,
                label=f"Review checkpoint step {checkpoint.step_order} output",
            )
        except TypedIOValidationException as exc:
            exc.context = context
            raise

    async def approve_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
    ) -> FlowRunReviewCheckpoint:
        principal = self._review_user_principal(capability="review")
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        return await self.flow_run_repo.approve_review_checkpoint(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            principal=principal,
        )

    async def reject_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
        reason: str,
    ) -> FlowRunReviewCheckpoint:
        principal = self._review_user_principal(capability="review")
        normalized_reason = self._normalize_review_reject_reason(reason)
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        checkpoint = await self.flow_run_repo.reject_review_checkpoint(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            reason=normalized_reason,
            principal=principal,
        )
        await self.flow_run_terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
            target_status=FlowRunStatus.CANCELLED,
            source=FlowRunLifecycleSource.REVIEW_REJECTED,
            error_code="flow_review_rejected",
            error_message=normalized_reason,
            cancelled_at=datetime.now(timezone.utc),
            principal=principal,
        )
        return checkpoint

    async def resume_review_checkpoint(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        checkpoint_id: UUID,
        expected_checkpoint_revision: int,
        idempotency_key: str | None,
    ) -> FlowRunReviewCheckpointResumeResult:
        principal = self._review_user_principal(capability="resume")
        normalized_key = self._validate_review_resume_idempotency_key(idempotency_key)
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        return await self.flow_run_repo.resume_review_checkpoint(
            checkpoint_id=checkpoint_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            flow_run_id=run.id,
            expected_revision=expected_checkpoint_revision,
            resume_idempotency_key=normalized_key,
            principal=principal,
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
                error_code="flow_worker_stalled",
                error_message=error_message,
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
            error_code="user_cancelled",
            error_message="Run cancelled by user.",
            cancelled_at=datetime.now(timezone.utc),
            principal=self._principal(),
        )
        return result.run

    async def get_run_artifact_file(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        file_id: UUID,
    ):
        from intric.files.file_models import File

        if self.file_repo is None:
            raise BadRequestException(
                "Artifact download is not available in this context.",
                code="file_repo_unavailable",
            )

        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="artifact")
        result_file = await self.flow_run_repo.get_result_file(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
            file_id=file_id,
        )
        if result_file is None:
            raise NotFoundException(
                f"File {file_id} is not a downloadable artifact of run {run_id}.",
                code="flow_run_artifact_not_found",
            )
        if not result_file.content_available:
            self._raise_artifact_content_unavailable(run_id=run_id, file_id=file_id)

        file: File = await self.file_repo.get_by_id(file_id=file_id)
        if file.tenant_id != self.user.tenant_id:
            raise UnauthorizedException(
                "You do not have access to this artifact.",
                code="forbidden_action",
                context={"auth_layer": "domain_policy"},
            )
        if file.blob is None and file.text is None:
            self._raise_artifact_content_unavailable(run_id=run_id, file_id=file_id)
        return file

    async def get_evidence(
        self, *, run_id: UUID, run: FlowRun | None = None
    ) -> dict[str, Any]:
        bundle = await self._get_redacted_evidence_bundle(
            run_id=run_id,
            access_kind="evidence_view",
            run=run,
        )
        return bundle.to_dict()

    async def export_evidence_json(
        self,
        *,
        run_id: UUID,
        detail: str = "redacted",
        run: FlowRun | None = None,
        export_reason: str = "support_debug",
    ) -> dict[str, Any]:
        if detail == "raw":
            bundle = await self._get_evidence_bundle(
                run_id=run_id,
                access_kind="evidence_export_raw",
                run=run,
            )
            return render_evidence_json_export(
                bundle=bundle,
                context=EvidenceExportContext(
                    detail_mode="raw",
                    export_reason=export_reason,
                    exported_by_user_id=str(self.user.id),
                ),
            )
        bundle = await self._get_redacted_evidence_bundle(
            run_id=run_id,
            access_kind="evidence_export_redacted",
            run=run,
        )
        return render_evidence_json_export(
            bundle=bundle,
            context=EvidenceExportContext(
                detail_mode="redacted",
                export_reason=export_reason,
                exported_by_user_id=str(self.user.id),
            ),
        )

    async def _get_redacted_evidence_bundle(
        self,
        *,
        run_id: UUID,
        access_kind: FlowRunAccessKind,
        run: FlowRun | None = None,
    ) -> RedactedEvidenceBundle:
        bundle = await self._get_evidence_bundle(
            run_id=run_id,
            access_kind=access_kind,
            run=run,
        )
        return redact_evidence_bundle(bundle)

    async def _get_evidence_bundle(
        self,
        *,
        run_id: UUID,
        access_kind: FlowRunAccessKind,
        run: FlowRun | None = None,
    ) -> EvidenceBundle:
        resolved_run = (
            run
            if run is not None
            else await self.get_run(run_id=run_id, access_kind=access_kind)
        )
        if run is not None:
            if resolved_run.id != run_id:
                self._raise_run_access_denied(auth_layer="flow_run_argument")
            await self._ensure_can_access_run(resolved_run, access_kind=access_kind)
        version = await self.flow_version_repo.get(
            flow_id=resolved_run.flow_id,
            version=resolved_run.flow_version,
            tenant_id=self.user.tenant_id,
        )
        step_results = await self.flow_run_repo.list_step_results(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
        )
        step_attempts = await self.flow_run_repo.list_step_attempts(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
        )
        rerun_operations = await self.flow_run_repo.list_rerun_operations_for_run(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
        )
        rerun_invalidated_steps = (
            await self.flow_run_repo.list_rerun_invalidated_steps_for_run(
                run_id=resolved_run.id,
                tenant_id=self.user.tenant_id,
            )
        )
        review_checkpoints = await self.flow_run_repo.list_review_checkpoints_for_run(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
        )
        result_files = await self.flow_run_repo.list_result_files(
            run_id=resolved_run.id,
            tenant_id=self.user.tenant_id,
        )
        return build_evidence_bundle(
            run=resolved_run,
            version=version,
            step_results=step_results,
            step_attempts=step_attempts,
            result_files=result_files,
            rerun_operations=rerun_operations,
            rerun_invalidated_steps=rerun_invalidated_steps,
            review_checkpoints=review_checkpoints,
        )

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
        for raw_step_dict in raw_steps:
            step_order_raw = raw_step_dict.get("step_order", 0)
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

            step_id_raw = raw_step_dict.get("step_id")
            assistant_id_raw = raw_step_dict.get("assistant_id")
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

    @staticmethod
    def _definition_has_required_runtime_step_inputs(
        definition_json: JsonObject,
    ) -> bool:
        raw_steps_obj: object = definition_json.get("steps")
        if not isinstance(raw_steps_obj, list):
            return False
        raw_steps = cast(list[object], raw_steps_obj)
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                continue
            raw_step_dict = cast(dict[str, object], raw_step)
            raw_input_config_obj: object = raw_step_dict.get("input_config")
            if not isinstance(raw_input_config_obj, dict):
                continue
            raw_input_config = cast(dict[str, object], raw_input_config_obj)
            raw_runtime_input_obj: object = raw_input_config.get("runtime_input")
            if not isinstance(raw_runtime_input_obj, dict):
                continue
            raw_runtime_input = cast(dict[str, object], raw_runtime_input_obj)
            if (
                raw_runtime_input.get("enabled") is True
                and raw_runtime_input.get("required") is True
            ):
                return True
        return False

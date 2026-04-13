from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol, TypedDict, cast
from uuid import UUID

from intric.files.file_repo import FileRepository
from intric.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowStepResult,
    JsonObject,
)
from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_evidence_policy import (
    EvidenceCapabilityLevel,
    classification_level_for_space,
    resolve_flow_evidence_policy,
    resolve_service_key_evidence_capability,
)
from intric.flows.flow_input_limits import FlowInputLimits, resolve_flow_input_limits
from intric.flows.flow_permissions import user_can_view_flow_trace
from intric.flows.flow_run_evidence_bundle import (
    EvidenceBundle,
    RedactedEvidenceBundle,
    build_evidence_bundle,
    redact_evidence_bundle,
)
from intric.flows.flow_run_export_json import render_evidence_json_export
from intric.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
from intric.flows.flow_run_step_inputs import (
    apply_legacy_step_one_adapter,
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    serialize_step_inputs_payload,
    validate_submitted_step_inputs,
)
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository, PreseedStep
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.principal import FlowPrincipal
from intric.flows.runtime.step_definition_parser import parse_runtime_steps
from intric.main.config import get_settings
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.logging import get_logger
from intric.roles.permissions import Permission
from intric.settings.setting_service import SettingService
from intric.users.user import UserInDB

logger = get_logger(__name__)

FlowRunAccessKind = Literal[
    "status",
    "cancel",
    "content",
    "artifact",
    "evidence_view",
    "evidence_export_redacted",
    "evidence_export_raw",
]


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

    _TERMINAL_STATUSES = {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_version_repo: FlowVersionRepository,
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
            else 30
        )
        self.running_reconcile_after_seconds = (
            max(int(get_settings().flow_task_timeout_seconds), 1) + 60
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

    async def _ensure_can_access_run(self, run: FlowRun, *, access_kind: str) -> None:
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

    async def create_run(
        self,
        *,
        flow_id: UUID,
        input_payload_json: dict[str, Any] | None,
        expected_flow_version: int | None = None,
        step_inputs: dict[UUID, dict[str, list[UUID]]] | None = None,
        file_ids: list[UUID] | None = None,
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
            metadata_json=flow.metadata_json
            if isinstance(flow.metadata_json, dict)
            else None,
            payload=input_payload_json,
        )
        normalized_step_inputs: dict[UUID, list[UUID]] = {}
        runtime_version = None
        if step_inputs is not None or file_ids:
            flow_id = cast(UUID, flow.id)
            runtime_version = await self.flow_version_repo.get(
                flow_id=flow_id,
                version=flow.published_version,
                tenant_id=self.user.tenant_id,
            )
            runtime_steps = parse_runtime_steps(runtime_version.definition_json)
            settings_service = cast(
                _SettingsServiceProtocol | None, self.settings_service
            )
            limits = (
                await settings_service.get_flow_input_limits_resolved()
                if settings_service is not None
                else resolve_flow_input_limits(None)
            )
            runtime_specs = build_runtime_step_input_specs(
                steps=runtime_steps, limits=limits
            )
            normalized_step_inputs = apply_legacy_step_one_adapter(
                steps=runtime_steps,
                specs=runtime_specs,
                normalized_step_inputs=normalize_step_inputs_payload(step_inputs),
                file_ids=file_ids,
            )
            await validate_submitted_step_inputs(
                steps=runtime_steps,
                specs=runtime_specs,
                normalized_step_inputs=normalized_step_inputs,
                file_repo=self.file_repo,
                user_id=self.user.id,
                principal=principal,
            )
        effective_payload = dict(normalized_inline_payload or {})
        effective_payload["expected_flow_version"] = flow.published_version
        if normalized_step_inputs:
            effective_payload["step_inputs"] = serialize_step_inputs_payload(
                normalized_step_inputs
            )
        if file_ids:
            effective_payload["file_ids"] = [str(fid) for fid in file_ids]
        input_payload_json = effective_payload or None
        request_fingerprint = self._build_idempotency_fingerprint(
            flow_id=flow_id,
            flow_version=flow.published_version,
            input_payload_json=input_payload_json,
        )

        if input_payload_json is not None:
            payload_size = len(
                json.dumps(
                    input_payload_json,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if payload_size > get_settings().flow_max_inline_text_bytes:
                raise BadRequestException(
                    "Flow run input payload exceeds allowed size limit.",
                    code="flow_run_input_payload_too_large",
                    context={
                        "flow_id": str(flow_id),
                        "max_inline_text_bytes": get_settings().flow_max_inline_text_bytes,
                    },
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
        version = runtime_version
        if version is None:
            version = await self.flow_version_repo.get(
                flow_id=flow.id,
                version=flow.published_version,
                tenant_id=self.user.tenant_id,
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
            preseed_steps=self._build_preseed_steps(
                definition_json=version.definition_json,
                fallback_steps=flow.steps,
            ),
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        return created

    def _build_idempotency_fingerprint(
        self,
        *,
        flow_id: UUID,
        flow_version: int,
        input_payload_json: dict[str, Any] | None,
    ) -> str:
        normalized = {
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
            updated = await self.flow_run_repo.fail_stale_running_run(
                run_id=run.id,
                tenant_id=self.user.tenant_id,
                stale_before=stale_before,
                error_message=error_message,
            )
            if updated is not None:
                reconciled += 1
        return reconciled

    async def cancel_run(self, *, run_id: UUID) -> FlowRun:
        run = await self.get_run(run_id=run_id, access_kind="cancel")
        if run.status in self._TERMINAL_STATUSES:
            return run
        await self.flow_run_repo.mark_pending_steps_cancelled(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            error_message="Run cancelled by user.",
        )
        return await self.flow_run_repo.cancel(
            run_id=run_id, tenant_id=self.user.tenant_id
        )

    async def complete_run(
        self,
        *,
        run_id: UUID,
        output_payload_json: dict[str, Any] | None = None,
    ) -> FlowRun:
        return await self.flow_run_repo.update_status(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            status=FlowRunStatus.COMPLETED,
            output_payload_json=output_payload_json,
        )

    async def fail_run(self, *, run_id: UUID, error_message: str) -> FlowRun:
        return await self.flow_run_repo.update_status(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            status=FlowRunStatus.FAILED,
            error_message=error_message,
        )

    async def get_run_artifact_file(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        file_id: UUID,
    ):
        """Resolve and return a File that is a downloadable artifact of the given run."""
        from intric.files.file_models import File

        if self.file_repo is None:
            raise BadRequestException(
                "Artifact download is not available in this context.",
                code="file_repo_unavailable",
            )

        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="artifact")
        step_results = await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )

        downloadable_file_ids: set[str] = set()
        for result in step_results:
            payload = result.output_payload_json
            if not isinstance(payload, dict):
                continue
            for artifact in cast(list[Any], payload.get("artifacts", [])):
                if isinstance(artifact, dict) and "file_id" in artifact:
                    artifact_dict = cast(JsonObject, artifact)
                    downloadable_file_ids.add(str(artifact_dict["file_id"]))
            for gfid in cast(list[Any], payload.get("generated_file_ids", [])):
                downloadable_file_ids.add(str(gfid))

        if str(file_id) not in downloadable_file_ids:
            raise NotFoundException(
                f"File {file_id} is not a downloadable artifact of run {run_id}.",
                code="flow_run_artifact_not_found",
            )

        file: File = await self.file_repo.get_by_id(file_id=file_id)
        if file.tenant_id != self.user.tenant_id:
            raise UnauthorizedException(
                "You do not have access to this artifact.",
                code="forbidden_action",
                context={"auth_layer": "domain_policy"},
            )
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
    ) -> dict[str, Any]:
        if detail == "raw":
            bundle = await self._get_evidence_bundle(
                run_id=run_id,
                access_kind="evidence_export_raw",
                run=run,
            )
            return cast(dict[str, Any], render_evidence_json_export(bundle=bundle))
        bundle = await self._get_redacted_evidence_bundle(
            run_id=run_id,
            access_kind="evidence_export_redacted",
            run=run,
        )
        return cast(dict[str, Any], render_evidence_json_export(bundle=bundle))

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
        resolved_run = run or await self.get_run(run_id=run_id, access_kind=access_kind)
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
        return build_evidence_bundle(
            run=resolved_run,
            version=version,
            step_results=step_results,
            step_attempts=step_attempts,
        )

    def _build_preseed_steps(
        self,
        *,
        definition_json: JsonObject,
        fallback_steps: list[FlowStep],
    ) -> list[PreseedStep]:
        raw_steps = definition_json.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
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
        for raw_step in cast(list[Any], raw_steps):
            if not isinstance(raw_step, dict):
                raise BadRequestException(
                    "Invalid flow version step definition.",
                    code="flow_version_invalid_step_definition",
                )
            raw_step_dict = cast(dict[str, Any], raw_step)
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

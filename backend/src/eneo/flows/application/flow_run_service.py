from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from eneo.authentication.api_key_resolver import resolve_effective_resource_permission
from eneo.authentication.auth_models import ApiKeyPermission
from eneo.files.file_repo import FileRepository
from eneo.flows.api.flow_run_contract_models import FlowFinalOutputContractPublic
from eneo.flows.application.flow_run_access_policy import (
    FlowRunAccessKind,
    FlowRunAccessPolicy,
)
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import (
    Flow,
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowRunTokenUsage,
    FlowStepResult,
)
from eneo.flows.domain.flow_run_exceptions import (
    FlowRunConcurrencyLimitReachedError,
    FlowRunNotFoundError,
)
from eneo.flows.domain.mapped_execution_policy import (
    resolve_flow_mapped_execution_policy_from_source,
)
from eneo.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from eneo.flows.enums import FlowRunLifecycleSource, is_terminal_flow_run_status
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_input_limits import (
    FlowInputLimits,
    resolve_flow_input_limits_from_source,
)
from eneo.flows.flow_run_contract_service import build_final_output_contract
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_input_envelope import build_initial_run_input_envelope
from eneo.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
from eneo.flows.flow_run_payload_validation import (
    ensure_inline_payload_size_allowed,
    reject_reserved_input_payload_keys,
)
from eneo.flows.flow_run_step_inputs import (
    FlowRunStepInputFileProjection,
    FlowRunStepInputs,
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    runtime_file_not_bound_to_flow_error,
    validate_submitted_step_inputs,
)
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    PreseedStep,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRead,
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_definition import (
    PublishedFlowDefinition,
    parse_verified_published_definition,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import NotFoundException
from eneo.settings.setting_service import SettingService
from eneo.users.user import UserInDB


@dataclass(frozen=True, slots=True)
class FlowRunStepResultWithFiles:
    step_result: FlowStepResult
    runtime_input_file_ids: Sequence[UUID]
    result_files: Sequence[FlowRunStepResultFile]


@dataclass(frozen=True)
class CreateRunResult:
    run: FlowRun
    created: bool


@dataclass(frozen=True, slots=True)
class FlowRunVersionedView:
    published_definition: PublishedFlowDefinition
    step_results: Sequence[FlowStepResult]


@dataclass(frozen=True, slots=True)
class FlowRunWithResultFilesAndTokenUsage:
    run: FlowRun
    result_files: Sequence[FlowRunStepResultFile]
    token_usage: FlowRunTokenUsage | None
    final_output: FlowFinalOutputContractPublic | None = None


@dataclass(frozen=True, slots=True)
class FlowRunDetailView(FlowRunWithResultFilesAndTokenUsage):
    webhook_deliveries: Sequence[FlowRunWebhookDeliveryRead] = ()


@dataclass(frozen=True, slots=True)
class FlowRunPageWithResultFilesAndTokenUsage:
    items: Sequence[FlowRunWithResultFilesAndTokenUsage]
    has_more: bool


@dataclass(frozen=True)
class _PublishedRunDefinition:
    flow: Flow
    flow_version: int
    definition: PublishedFlowDefinition


@dataclass(frozen=True)
class _PreparedRunCreation:
    input_payload_json: FlowPersistedJsonObject | None
    preseed_steps: list[PreseedStep]
    step_input_files: list[FlowRunStepInputFileProjection]
    request_fingerprint: str


def _normalize_step_input_files_for_fingerprint(
    step_input_files: Sequence[FlowRunStepInputFileProjection] | None,
) -> dict[str, dict[str, list[str]]]:
    return {
        str(projection["step_id"]): {
            "file_ids": [str(file_id) for file_id in projection["file_ids"]]
        }
        for projection in step_input_files or ()
    }


def _result_files_by_run_id(
    result_files: Sequence[FlowRunStepResultFile],
) -> dict[UUID, list[FlowRunStepResultFile]]:
    grouped: dict[UUID, list[FlowRunStepResultFile]] = {}
    for result_file in result_files:
        grouped.setdefault(result_file.flow_run_id, []).append(result_file)
    return grouped


def _result_files_by_step_result_id(
    result_files: Sequence[FlowRunStepResultFile],
) -> dict[UUID, list[FlowRunStepResultFile]]:
    grouped: dict[UUID, list[FlowRunStepResultFile]] = {}
    for result_file in result_files:
        grouped.setdefault(result_file.step_result_id, []).append(result_file)
    return grouped


class FlowRunService:
    """Tenant-scoped flow run lifecycle service."""

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
        flow_version_repo: FlowVersionRepository,
        runtime_upload_repo: FlowRuntimeUploadRepository,
        file_repo: FileRepository,
        flow_run_terminalizer: FlowRunTerminalizer,
        access_policy: FlowRunAccessPolicy,
        webhook_delivery_repo: FlowRunWebhookDeliveryRepository,
        settings_service: SettingService | None = None,
        max_concurrent_runs: int | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_run_terminalizer = flow_run_terminalizer
        self.flow_version_repo = flow_version_repo
        self.file_repo = file_repo
        self.runtime_upload_repo = runtime_upload_repo
        self.settings_service = settings_service
        self.access_policy = access_policy
        self.webhook_delivery_repo = webhook_delivery_repo
        self.max_concurrent_runs = (
            max_concurrent_runs
            if max_concurrent_runs is not None
            else get_settings().flow_max_concurrent_runs_per_tenant
        )

    def _principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    def _runtime_service_permission(
        self,
        principal: FlowPrincipal,
    ) -> ApiKeyPermission | None:
        if not principal.is_service_key:
            return None
        key = getattr(self.user, "active_api_key", None)
        assert key is not None, "service-key Flow principal requires active_api_key"
        return resolve_effective_resource_permission(key, "flows")

    def _validate_idempotency_key(self, idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        normalized = idempotency_key.strip()
        if not normalized or len(normalized) > 255:
            raise FlowBadRequestException(
                "Idempotency key must be between 1 and 255 characters.",
                code=FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY,
            )
        return normalized

    async def create_run(
        self,
        *,
        flow_id: UUID,
        input_payload_json: FlowPersistedJsonObject | None,
        expected_flow_version: int | None = None,
        step_inputs: FlowRunStepInputs | None = None,
        idempotency_key: str | None = None,
    ) -> CreateRunResult:
        idempotency_key = self._validate_idempotency_key(idempotency_key)
        principal = self._principal()
        published = await self._load_published_run_definition(
            flow_id=flow_id,
            expected_flow_version=expected_flow_version,
        )
        prepared = await self._prepare_run_creation(
            flow_id=flow_id,
            flow=published.flow,
            flow_version=published.flow_version,
            definition=published.definition,
            principal=principal,
            input_payload_json=input_payload_json,
            step_inputs=step_inputs,
        )
        existing_run = await self._find_idempotent_run_or_enforce_creation_limits(
            flow_id=flow_id,
            idempotency_key=idempotency_key,
            principal=principal,
            request_fingerprint=prepared.request_fingerprint,
        )
        if existing_run is not None:
            return CreateRunResult(run=existing_run, created=False)
        created_run = await self._create_persisted_run(
            flow=published.flow,
            flow_version=published.flow_version,
            principal=principal,
            prepared=prepared,
            idempotency_key=idempotency_key,
        )
        return CreateRunResult(run=created_run, created=True)

    async def _load_published_run_definition(
        self,
        *,
        flow_id: UUID,
        expected_flow_version: int | None,
    ) -> _PublishedRunDefinition:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        if flow.published_version is None:
            raise FlowBadRequestException(
                "Flow must be published before a run can be created.",
                code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
                context={"flow_id": str(flow_id)},
            )

        if (
            expected_flow_version is not None
            and expected_flow_version != flow.published_version
        ):
            raise FlowBadRequestException(
                "The published flow version changed before this run request was submitted.",
                code=FlowApiErrorCode.RUN_STALE_VERSION,
                context={
                    "expected_flow_version": expected_flow_version,
                    "published_flow_version": flow.published_version,
                },
            )
        flow_version = flow.published_version

        runtime_version = await self.flow_version_repo.get(
            flow_id=flow_id,
            version=flow_version,
            tenant_id=self.user.tenant_id,
        )
        published_definition = parse_verified_published_definition(
            runtime_version.definition_json,
            expected_checksum=runtime_version.definition_checksum,
            flow_version=runtime_version.version,
        )
        return _PublishedRunDefinition(
            flow=flow,
            flow_version=flow_version,
            definition=published_definition,
        )

    async def _prepare_run_creation(
        self,
        *,
        flow_id: UUID,
        flow: Flow,
        flow_version: int,
        definition: PublishedFlowDefinition,
        principal: FlowPrincipal,
        input_payload_json: FlowPersistedJsonObject | None,
        step_inputs: FlowRunStepInputs | None,
    ) -> _PreparedRunCreation:
        normalized_inline_payload = normalize_and_validate_flow_run_payload(
            metadata=definition.metadata(),
            payload=input_payload_json,
        )
        reject_reserved_input_payload_keys(normalized_inline_payload)
        normalized_step_inputs = normalize_step_inputs_payload(step_inputs)
        preseed_steps: list[PreseedStep] = [
            {
                "step_id": identity.step_id,
                "assistant_id": identity.assistant_id,
                "step_order": identity.step_order,
            }
            for identity in definition.step_identities
        ]
        step_input_file_projections: list[FlowRunStepInputFileProjection] = []
        if step_inputs is not None or definition.has_required_runtime_input():
            runtime_steps = definition.runtime_steps()
            limits = await self._resolve_flow_input_limits()
            mapped_policy = await resolve_flow_mapped_execution_policy_from_source(
                self.settings_service
            )
            runtime_specs = build_runtime_step_input_specs(
                steps=runtime_steps,
                limits=limits,
                mapped_policy=mapped_policy,
            )
            await validate_submitted_step_inputs(
                flow_id=flow_id,
                steps=runtime_steps,
                specs=runtime_specs,
                normalized_step_inputs=normalized_step_inputs,
                file_repo=self.file_repo,
                runtime_upload_repo=self.runtime_upload_repo,
                principal=principal,
                tenant_id=self.user.tenant_id,
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
        prepared_payload = build_initial_run_input_envelope(
            normalized_inline_payload=normalized_inline_payload,
            flow_version=flow_version,
        )
        request_fingerprint = self._build_idempotency_fingerprint(
            tenant_id=self.user.tenant_id,
            principal=principal,
            flow_id=flow_id,
            flow_version=flow_version,
            input_payload_json=prepared_payload,
            step_input_files=step_input_file_projections,
        )

        ensure_inline_payload_size_allowed(
            flow_id=flow_id,
            input_payload_json=prepared_payload,
        )
        return _PreparedRunCreation(
            input_payload_json=prepared_payload,
            preseed_steps=preseed_steps,
            step_input_files=step_input_file_projections,
            request_fingerprint=request_fingerprint,
        )

    async def _find_idempotent_run_or_enforce_creation_limits(
        self,
        *,
        flow_id: UUID,
        idempotency_key: str | None,
        principal: FlowPrincipal,
        request_fingerprint: str,
    ) -> FlowRun | None:
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
                    raise FlowBadRequestException(
                        "Idempotency key was already used with a different run request payload.",
                        code=FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT,
                    )
                return existing_run
        active_runs = await self.flow_run_repo.count_active_runs(
            tenant_id=self.user.tenant_id
        )
        if active_runs >= self.max_concurrent_runs:
            raise FlowRunConcurrencyLimitReachedError(
                max_concurrent_runs=self.max_concurrent_runs
            )
        return None

    async def _create_persisted_run(
        self,
        *,
        flow: Flow,
        flow_version: int,
        principal: FlowPrincipal,
        prepared: _PreparedRunCreation,
        idempotency_key: str | None,
    ) -> FlowRun:
        flow_id = flow.require_persisted_id()
        try:
            return await self.flow_run_repo.create(
                flow_id=flow_id,
                flow_version=flow_version,
                principal_type=principal.principal_type.value,
                principal_user_id=principal.principal_user_id,
                principal_service_id=principal.principal_service_id,
                created_by_api_key_id=principal.actor_api_key_id,
                runtime_service_permission=self._runtime_service_permission(principal),
                tenant_id=self.user.tenant_id,
                input_payload_json=prepared.input_payload_json,
                preseed_steps=prepared.preseed_steps,
                step_input_files=prepared.step_input_files,
                idempotency_key=idempotency_key,
                request_fingerprint=prepared.request_fingerprint,
            )
        except FlowRunRuntimeUploadBindingRaceError as exc:
            raise runtime_file_not_bound_to_flow_error(
                step_id=exc.step_id,
                file_ids=exc.file_ids,
            ) from exc

    async def _resolve_flow_input_limits(self) -> FlowInputLimits:
        return await resolve_flow_input_limits_from_source(self.settings_service)

    def _build_idempotency_fingerprint(
        self,
        *,
        tenant_id: UUID,
        principal: FlowPrincipal,
        flow_id: UUID,
        flow_version: int,
        input_payload_json: FlowPersistedJsonObject | None,
        step_input_files: Sequence[FlowRunStepInputFileProjection] | None = None,
    ) -> str:
        normalized = {
            "request_fingerprint_algo_version": 3,
            "tenant_id": str(tenant_id),
            "principal_type": principal.principal_type.value,
            "principal_user_id": (
                str(principal.principal_user_id)
                if principal.principal_user_id is not None
                else None
            ),
            "principal_service_id": (
                str(principal.principal_service_id)
                if principal.principal_service_id is not None
                else None
            ),
            "flow_id": str(flow_id),
            "flow_version": flow_version,
            "input_payload_json": input_payload_json,
            "step_input_files": _normalize_step_input_files_for_fingerprint(
                step_input_files
            ),
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
        statuses: Sequence[FlowRunStatus] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRun]:
        principal = self._principal()
        is_tenant_admin = self.access_policy.is_tenant_admin()
        if not is_tenant_admin and not principal.is_service_key and flow_id is not None:
            if await self.access_policy.can_list_all_runs_in_flow(flow_id=flow_id):
                return await self.flow_run_repo.list_runs(
                    tenant_id=self.user.tenant_id,
                    flow_id=flow_id,
                    principal_user_id=None,
                    principal_service_id=None,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                )
        return await self.flow_run_repo.list_runs(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            statuses=statuses,
            principal_user_id=(
                None
                if is_tenant_admin or principal.is_service_key
                else principal.principal_user_id
            ),
            principal_service_id=(
                principal.principal_service_id
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

    async def get_run_versioned_view(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
    ) -> FlowRunVersionedView:
        run = await self.get_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="content",
        )
        flow_version = await self.flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=run.tenant_id,
        )
        published_definition = parse_verified_published_definition(
            flow_version.definition_json,
            expected_checksum=flow_version.definition_checksum,
            flow_version=flow_version.version,
        )
        step_results = await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        return FlowRunVersionedView(
            published_definition=published_definition,
            step_results=tuple(step_results),
        )

    async def get_run_with_result_files_and_token_usage(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
    ) -> FlowRunWithResultFilesAndTokenUsage:
        run = await self.get_run(run_id=run_id, flow_id=flow_id)
        return await self.enrich_run_with_result_files_and_token_usage(run=run)

    async def get_run_detail_with_result_files_and_token_usage(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
    ) -> FlowRunDetailView:
        run_view = await self.get_run_with_result_files_and_token_usage(
            flow_id=flow_id,
            run_id=run_id,
        )
        webhook_deliveries = (
            await self.webhook_delivery_repo.list_run_delivery_statuses(
                run_id=run_view.run.id,
                tenant_id=self.user.tenant_id,
            )
        )
        return FlowRunDetailView(
            run=run_view.run,
            result_files=run_view.result_files,
            token_usage=run_view.token_usage,
            final_output=run_view.final_output,
            webhook_deliveries=tuple(webhook_deliveries),
        )

    async def enrich_run_with_result_files_and_token_usage(
        self,
        *,
        run: FlowRun,
    ) -> FlowRunWithResultFilesAndTokenUsage:
        views = await self._runs_with_result_files_and_token_usage(runs=(run,))
        return views[0]

    async def list_runs_with_result_files_and_token_usage(
        self,
        *,
        flow_id: UUID,
        statuses: Sequence[FlowRunStatus] | None = None,
        limit: int,
        offset: int,
    ) -> FlowRunPageWithResultFilesAndTokenUsage:
        runs = await self.list_runs(
            flow_id=flow_id,
            statuses=statuses,
            limit=limit + 1,
            offset=offset,
        )
        page_runs = tuple(runs[:limit])
        return FlowRunPageWithResultFilesAndTokenUsage(
            items=await self._runs_with_result_files_and_token_usage(runs=page_runs),
            has_more=len(runs) > limit,
        )

    async def _runs_with_result_files_and_token_usage(
        self, *, runs: Sequence[FlowRun]
    ) -> tuple[FlowRunWithResultFilesAndTokenUsage, ...]:
        if not runs:
            return ()
        run_ids: list[UUID] = []
        for run in runs:
            if run.tenant_id != self.user.tenant_id:
                self.access_policy.deny_run_access(auth_layer="flow_run_argument")
            run_ids.append(run.id)
        result_files = await self.flow_run_repo.list_result_files_for_runs(
            run_ids=run_ids,
            tenant_id=self.user.tenant_id,
        )
        token_usage_by_run_id = await self.flow_run_repo.list_token_usage_for_runs(
            run_ids=run_ids,
            tenant_id=self.user.tenant_id,
        )
        result_files_by_run_id = _result_files_by_run_id(result_files)
        final_output_by_version_ref = await self._final_outputs_for_runs(runs=runs)
        return tuple(
            FlowRunWithResultFilesAndTokenUsage(
                run=run,
                result_files=tuple(result_files_by_run_id.get(run.id, ())),
                token_usage=token_usage_by_run_id.get(run.id),
                final_output=final_output_by_version_ref.get(
                    (run.flow_id, run.flow_version)
                ),
            )
            for run in runs
        )

    async def _final_outputs_for_runs(
        self, *, runs: Sequence[FlowRun]
    ) -> dict[tuple[UUID, int], FlowFinalOutputContractPublic]:
        version_refs = tuple(
            dict.fromkeys(
                (run.flow_id, run.flow_version)
                for run in runs
                if run.status is FlowRunStatus.COMPLETED
            )
        )
        if not version_refs:
            return {}
        versions_by_ref = await self.flow_version_repo.get_many(
            version_refs=version_refs,
            tenant_id=self.user.tenant_id,
        )
        final_outputs: dict[tuple[UUID, int], FlowFinalOutputContractPublic] = {}
        for version_ref, flow_version in versions_by_ref.items():
            definition = parse_verified_published_definition(
                flow_version.definition_json,
                expected_checksum=flow_version.definition_checksum,
                flow_version=flow_version.version,
            )
            final_output = build_final_output_contract(definition.runtime_steps())
            if final_output is None:
                raise FlowPublishedDefinitionWithoutExecutableStepsError(
                    flow_id=flow_version.flow_id,
                    flow_version=flow_version.version,
                )
            final_outputs[version_ref] = final_output
        return final_outputs

    async def list_step_results_with_files(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
    ) -> tuple[FlowRunStepResultWithFiles, ...]:
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="content")
        step_results = await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        result_files = await self.flow_run_repo.list_result_files(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        runtime_input_file_ids_by_step_result_id = (
            await self.flow_run_repo.list_current_step_input_file_ids_by_step_result_id(
                run_id=run.id,
                tenant_id=self.user.tenant_id,
                step_results=step_results,
            )
        )
        result_files_by_step_result_id = _result_files_by_step_result_id(result_files)
        views: list[FlowRunStepResultWithFiles] = []
        for result in step_results:
            result_id = result.id
            if result_id is None:
                # Domain ids are optional; persisted reads normally set this.
                views.append(
                    FlowRunStepResultWithFiles(
                        step_result=result,
                        runtime_input_file_ids=(),
                        result_files=(),
                    )
                )
                continue
            views.append(
                FlowRunStepResultWithFiles(
                    step_result=result,
                    runtime_input_file_ids=runtime_input_file_ids_by_step_result_id.get(
                        result_id, ()
                    ),
                    result_files=tuple(
                        result_files_by_step_result_id.get(result_id, ())
                    ),
                )
            )
        return tuple(views)

    async def cancel_run(self, *, run_id: UUID, flow_id: UUID) -> FlowRun:
        run = await self.get_run(run_id=run_id, flow_id=flow_id, access_kind="cancel")
        if is_terminal_flow_run_status(run.status):
            return run
        try:
            result = await self.flow_run_terminalizer.terminalize_run(
                run_id=run_id,
                tenant_id=self.user.tenant_id,
                target_status=FlowRunStatus.CANCELLED,
                source=FlowRunLifecycleSource.USER_CANCEL,
                error=FlowRunError.from_source(
                    FlowRunLifecycleSource.USER_CANCEL,
                    code=FlowApiErrorCode.RUN_USER_CANCELLED,
                    message="Run cancelled by user.",
                ),
                cancelled_at=datetime.now(timezone.utc),
                principal=self._principal(),
            )
        except FlowRunNotFoundError as exc:
            raise NotFoundException("Flow run not found.") from exc
        return result.run

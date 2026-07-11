from __future__ import annotations

from typing import assert_never
from uuid import UUID

from eneo.files.file_repo import FileRepository
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.domain.flow import FlowPersistedJsonObject, RerunStepInputOverride
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.rerun_exceptions import (
    FLOW_RUN_RERUN_LIFECYCLE_FAILURE_CLASSES,
    FlowRunRerunInvalidTransitionError,
    FlowRunRerunLifecycleFailure,
    FlowRunRerunMissingCurrentResultsError,
    FlowRunRerunRootStepIncompleteError,
    FlowRunRerunStaleRevisionError,
    FlowRunRerunStepInputsInvalidError,
    FlowRunRerunStepNotFoundError,
)
from eneo.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_input_limits import (
    FlowInputLimits,
    resolve_flow_input_limits_from_source,
)
from eneo.flows.flow_run_input_envelope import RerunInputOverride
from eneo.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
from eneo.flows.flow_run_payload_validation import (
    ensure_inline_payload_size_allowed,
    reject_reserved_input_payload_keys,
)
from eneo.flows.flow_run_rerun_graph import (
    RerunGraphStepNotFound,
    RerunInvalidationGraph,
    build_rerun_invalidation_graph,
)
from eneo.flows.flow_run_rerun_request import (
    FlowRunRerunRequestFingerprintInput,
    build_rerun_request_fingerprint,
)
from eneo.flows.flow_run_step_inputs import (
    FlowRunStepInputs,
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    runtime_file_not_bound_to_flow_error,
    validate_submitted_step_inputs,
)
from eneo.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_rerun_repo import (
    FlowRunRerunCommandResult,
    FlowRunRerunRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_definition import (
    PublishedFlowDefinition,
    parse_verified_published_definition,
)
from eneo.flows.runtime.models import RuntimeStep
from eneo.main.exceptions import NotFoundException
from eneo.settings.setting_service import SettingService
from eneo.users.user import UserInDB

_RERUN_REASON_MAX_LENGTH = 1024


def _step_ids_context(step_ids: tuple[UUID, ...]) -> dict[str, object]:
    return {"step_ids": [str(step_id) for step_id in step_ids]}


def _rerun_lifecycle_failure_to_bad_request(
    exc: FlowRunRerunLifecycleFailure,
) -> FlowBadRequestException:
    match exc:
        case FlowRunRerunStaleRevisionError():
            return FlowBadRequestException(
                "Flow run revision is stale.",
                code=FlowApiErrorCode.RUN_RERUN_STALE_REVISION,
                context={
                    "expected_run_revision": exc.expected_run_revision,
                    "current_run_revision": exc.current_run_revision,
                },
            )
        case FlowRunRerunInvalidTransitionError():
            return FlowBadRequestException(
                "Flow run is not eligible for rerun.",
                code=FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION,
                context={"status": exc.status},
            )
        case FlowRunRerunStepNotFoundError():
            return FlowBadRequestException(
                "Rerun step is not in the published flow snapshot.",
                code=FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND,
            )
        case FlowRunRerunMissingCurrentResultsError():
            return FlowBadRequestException(
                "Rerun graph has no current result for every invalidated step.",
                code=FlowApiErrorCode.RUN_RERUN_STEP_INCOMPLETE,
                context=_step_ids_context(exc.step_ids),
            )
        case FlowRunRerunRootStepIncompleteError():
            return FlowBadRequestException(
                "Rerun step has no completed current result.",
                code=FlowApiErrorCode.RUN_RERUN_STEP_INCOMPLETE,
                context=_step_ids_context(exc.step_ids),
            )
        case FlowRunRerunStepInputsInvalidError():
            return FlowBadRequestException(
                "Rerun step_inputs may only target the rerun root step.",
                code=FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID,
                context=_step_ids_context(exc.step_ids),
            )
        case _:
            assert_never(exc)


class FlowRunRerunService:
    """Owns rerun request validation, invalidation planning, and operation creation."""

    def __init__(
        self,
        *,
        user: UserInDB,
        flow_run_repo: FlowRunRepository,
        flow_run_rerun_repo: FlowRunRerunRepository,
        flow_version_repo: FlowVersionRepository,
        runtime_upload_repo: FlowRuntimeUploadRepository,
        file_repo: FileRepository,
        settings_service: SettingService | None = None,
        access_policy: FlowRunAccessPolicy,
    ):
        self.user = user
        self.flow_run_repo = flow_run_repo
        self.flow_run_rerun_repo = flow_run_rerun_repo
        self.flow_version_repo = flow_version_repo
        self.file_repo = file_repo
        self.runtime_upload_repo = runtime_upload_repo
        self.settings_service = settings_service
        self.access_policy = access_policy

    def _principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    async def rerun_step(
        self,
        *,
        flow_id: UUID,
        run_id: UUID,
        rerun_step_id: UUID,
        expected_run_revision: int,
        reason: str,
        input_payload_json: FlowPersistedJsonObject | None = None,
        step_inputs: FlowRunStepInputs | None = None,
    ) -> FlowRunRerunCommandResult:
        normalized_reason = self._normalize_rerun_reason(reason)
        run = await self.access_policy.load_run(
            run_id=run_id,
            flow_id=flow_id,
            access_kind="rerun",
        )
        version = await self.flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=self.user.tenant_id,
        )
        published_definition = parse_verified_published_definition(
            version.definition_json,
            expected_checksum=version.definition_checksum,
            flow_version=version.version,
        )
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
            flow_id=run.flow_id,
            runtime_steps=runtime_steps,
            root_runtime_step=root_runtime_step,
            rerun_step_id=rerun_step_id,
            step_inputs=step_inputs,
        )
        rerun_input_override = RerunInputOverride(
            inline_payload_json=normalized_inline_payload,
            root_step_input=(
                RerunStepInputOverride(
                    step_id=rerun_step_id,
                    file_ids=tuple(normalized_step_inputs[rerun_step_id]),
                )
                if rerun_step_id in normalized_step_inputs
                else None
            ),
        )
        prior_root_attempt_id = (
            await self.flow_run_rerun_repo.get_latest_completed_attempt_id_for_step(
                run_id=run.id,
                flow_id=run.flow_id,
                tenant_id=self.user.tenant_id,
                step_id=rerun_step_id,
            )
        )
        principal = self._principal()
        request_fingerprint = build_rerun_request_fingerprint(
            FlowRunRerunRequestFingerprintInput(
                tenant_id=self.user.tenant_id,
                requested_by_principal_type=principal.principal_type,
                requested_by_user_id=principal.principal_user_id,
                requested_by_service_id=principal.principal_service_id,
                flow_id=run.flow_id,
                flow_run_id=run.id,
                rerun_step_id=rerun_step_id,
                expected_run_revision=expected_run_revision,
                prior_root_attempt_id=prior_root_attempt_id,
                input_payload_json=normalized_inline_payload,
                root_step_inputs=normalized_step_inputs or None,
            )
        )
        try:
            return await self.flow_run_rerun_repo.accept_or_replay_rerun_operation(
                tenant_id=self.user.tenant_id,
                flow_id=run.flow_id,
                flow_run_id=run.id,
                rerun_step_id=rerun_step_id,
                rerun_step_order=root_runtime_step.step_order,
                request_fingerprint=request_fingerprint,
                expected_run_revision=expected_run_revision,
                reason=normalized_reason,
                rerun_input_override=rerun_input_override,
                requested_by_principal=principal,
                invalidated_steps=invalidation_graph.invalidated_steps,
            )
        except FLOW_RUN_RERUN_LIFECYCLE_FAILURE_CLASSES as exc:
            raise _rerun_lifecycle_failure_to_bad_request(exc) from exc
        except FlowRunNotFoundError as exc:
            raise NotFoundException("Flow run not found.") from exc
        except FlowRunRuntimeUploadBindingRaceError as exc:
            raise runtime_file_not_bound_to_flow_error(
                step_id=exc.step_id,
                file_ids=exc.file_ids,
            ) from exc

    async def _resolve_flow_input_limits(self) -> FlowInputLimits:
        return await resolve_flow_input_limits_from_source(self.settings_service)

    @staticmethod
    def _normalize_rerun_reason(reason: str) -> str:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise FlowBadRequestException(
                "Rerun reason is required.",
                code=FlowApiErrorCode.RUN_RERUN_REASON_REQUIRED,
            )
        if len(normalized_reason) > _RERUN_REASON_MAX_LENGTH:
            raise FlowBadRequestException(
                f"Rerun reason must be at most {_RERUN_REASON_MAX_LENGTH} characters.",
                code=FlowApiErrorCode.RUN_RERUN_REASON_TOO_LONG,
                context={"max_length": _RERUN_REASON_MAX_LENGTH},
            )
        return normalized_reason

    @staticmethod
    def _resolve_rerun_graph(
        *,
        runtime_steps: list[RuntimeStep],
        rerun_step_id: UUID,
    ) -> tuple[RerunInvalidationGraph, RuntimeStep]:
        root_runtime_step = next(
            (step for step in runtime_steps if step.step_id == rerun_step_id),
            None,
        )
        if root_runtime_step is None:
            raise FlowBadRequestException(
                "Rerun step is not in the published flow snapshot.",
                code=FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND,
            )
        try:
            invalidation_graph = build_rerun_invalidation_graph(
                steps=runtime_steps,
                root_step_id=rerun_step_id,
            )
        except RerunGraphStepNotFound as exc:
            raise FlowBadRequestException(
                "Rerun step is not in the published flow snapshot.",
                code=FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND,
            ) from exc
        return invalidation_graph, root_runtime_step

    def _normalize_rerun_inline_payload(
        self,
        *,
        flow_id: UUID,
        published_definition: PublishedFlowDefinition,
        input_payload_json: FlowPersistedJsonObject | None,
    ) -> FlowPersistedJsonObject | None:
        if input_payload_json is None:
            return None
        normalized_inline_payload = normalize_and_validate_flow_run_payload(
            metadata=published_definition.metadata(),
            payload=input_payload_json,
        )
        reject_reserved_input_payload_keys(normalized_inline_payload)
        ensure_inline_payload_size_allowed(
            flow_id=flow_id,
            input_payload_json=normalized_inline_payload,
        )
        return normalized_inline_payload

    async def _normalize_and_validate_rerun_step_inputs(
        self,
        *,
        flow_id: UUID,
        runtime_steps: list[RuntimeStep],
        root_runtime_step: RuntimeStep,
        rerun_step_id: UUID,
        step_inputs: FlowRunStepInputs | None,
    ) -> dict[UUID, list[UUID]]:
        normalized_step_inputs = normalize_step_inputs_payload(step_inputs)
        downstream_step_input_ids = [
            str(step_id)
            for step_id in normalized_step_inputs
            if step_id != rerun_step_id
        ]
        if downstream_step_input_ids:
            raise FlowBadRequestException(
                "Rerun step_inputs may only target the rerun root step.",
                code=FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID,
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
            flow_id=flow_id,
            steps=[root_runtime_step],
            specs=root_specs,
            normalized_step_inputs=normalized_step_inputs,
            file_repo=self.file_repo,
            runtime_upload_repo=self.runtime_upload_repo,
            principal=self._principal(),
            tenant_id=self.user.tenant_id,
        )
        return normalized_step_inputs

from __future__ import annotations

from uuid import UUID

from intric.files.file_repo import FileRepository
from intric.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from intric.flows.domain.flow import JsonObject
from intric.flows.flow_input_limits import (
    FlowInputLimits,
    resolve_flow_input_limits_from_source,
)
from intric.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
from intric.flows.flow_run_payload_validation import (
    ensure_inline_payload_size_allowed,
    reject_reserved_input_payload_keys,
)
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
    FlowRunStepInputs,
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    serialize_step_inputs_payload,
    validate_submitted_step_inputs,
)
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    FlowRunRerunCommandResult,
)
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.principal import FlowPrincipal
from intric.flows.published_definition import (
    PublishedFlowDefinition,
    parse_published_definition,
)
from intric.flows.runtime.models import RuntimeStep
from intric.main.exceptions import BadRequestException
from intric.settings.setting_service import SettingService
from intric.users.user import UserInDB

_RERUN_REASON_MAX_LENGTH = 1024


class FlowRunRerunService:
    """Owns rerun request validation, invalidation planning, and operation creation."""

    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowRepository | None = None,
        flow_run_repo: FlowRunRepository,
        flow_version_repo: FlowVersionRepository,
        file_repo: FileRepository | None = None,
        settings_service: SettingService | None = None,
        access_policy: FlowRunAccessPolicy | None = None,
    ):
        self.user = user
        self.flow_run_repo = flow_run_repo
        self.flow_version_repo = flow_version_repo
        self.file_repo = file_repo
        self.settings_service = settings_service
        if access_policy is None:
            if flow_repo is None:
                raise ValueError(
                    "FlowRunRerunService requires flow_repo when access_policy is not provided."
                )
            access_policy = FlowRunAccessPolicy(
                user=user,
                flow_repo=flow_repo,
                flow_run_repo=flow_run_repo,
            )
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
        input_payload_json: JsonObject | None = None,
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
        return await resolve_flow_input_limits_from_source(self.settings_service)

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
                f"Rerun reason must be at most {_RERUN_REASON_MAX_LENGTH} characters.",
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
        root_runtime_step = next(
            (step for step in runtime_steps if step.step_id == rerun_step_id),
            None,
        )
        if root_runtime_step is None:
            raise BadRequestException(
                "Rerun step is not in the published flow snapshot.",
                code="flow_run_rerun_step_not_found",
            )
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
        return invalidation_graph, root_runtime_step

    def _normalize_rerun_inline_payload(
        self,
        *,
        flow_id: UUID,
        published_definition: PublishedFlowDefinition,
        input_payload_json: JsonObject | None,
    ) -> JsonObject | None:
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
            principal=self._principal(),
        )
        return normalized_step_inputs

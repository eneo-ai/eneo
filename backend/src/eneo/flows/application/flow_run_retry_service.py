from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, NoReturn, cast
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_service import (
    CreateRunResult,
    FlowRunService,
    find_prefix_seed_replay,
)
from eneo.flows.application.flow_trace_audit import raise_flow_trace_audit_unavailable
from eneo.flows.domain.flow import FlowRunStatus, FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.step_output import (
    OUTPUT_TEXT_OVERFLOW_KEY,
)
from eneo.flows.domain.transcript_regeneration import FlowRunPrefixSeed
from eneo.flows.enums import FlowRunReviewCheckpointState
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    TRANSCRIPT_REGENERATION_KEY,
    read_semantic_flow_input_payload,
)
from eneo.flows.flow_run_payload_validation import ensure_inline_payload_size_allowed
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import ConflictException
from eneo.users.user import UserInDB


@dataclass(frozen=True)
class FlowRunRetryResult:
    run_result: CreateRunResult
    source_run_id: UUID
    first_executed_step_order: int
    reused_step_orders: tuple[int, ...]


def _unsupported(*, step_order: int, reason: str) -> NoReturn:
    raise ConflictException(
        "The completed prefix cannot be reused.",
        code=FlowApiErrorCode.RUN_RETRY_PREFIX_UNSUPPORTED.value,
        context={"step_order": step_order, "reason": reason},
    )


class FlowRunRetryService:
    def __init__(
        self,
        *,
        user: UserInDB,
        run_service: FlowRunService,
        access_policy: FlowRunAccessPolicy,
        run_repo: FlowRunRepository,
        flow_repo: FlowRepository,
        checkpoint_repo: FlowRunReviewCheckpointRepository,
        audit_service: AuditService,
    ):
        self.user = user
        self.run_service = run_service
        self.access_policy = access_policy
        self.run_repo = run_repo
        self.flow_repo = flow_repo
        self.checkpoint_repo = checkpoint_repo
        self.audit_service = audit_service

    async def retry_from_failed_step(
        self, *, flow_id: UUID, run_id: UUID, idempotency_key: str
    ) -> FlowRunRetryResult:
        source = await self.access_policy.load_run(
            flow_id=flow_id, run_id=run_id, access_kind="content"
        )
        principal = FlowPrincipal.from_user(self.user)
        if not principal.matches_run(source):
            FlowRunAccessPolicy.deny_run_access(auth_layer="flow_run_principal")
        key = idempotency_key.strip()
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "operation": "run_retry_v1",
                    "source_run_id": str(source.id),
                    "source_run_revision": source.revision,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = await find_prefix_seed_replay(
            run_repo=self.run_repo,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            principal=principal,
            idempotency_key=key,
            request_hash=request_hash,
        )
        if existing is not None:
            provenance = cast(
                dict[str, Any],
                (existing.run.input_payload_json or {})[TRANSCRIPT_REGENERATION_KEY],
            )
            return FlowRunRetryResult(
                run_result=existing,
                source_run_id=source.id,
                first_executed_step_order=provenance["first_executed_step_order"],
                reused_step_orders=tuple(provenance["reused_step_orders"]),
            )
        if source.status != FlowRunStatus.FAILED:
            raise ConflictException(
                "Only failed runs can be retried from their first unfinished step.",
                code=FlowApiErrorCode.RUN_RETRY_SOURCE_NOT_FAILED.value,
                context={"status": source.status.value},
            )
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        if source.flow_version != flow.published_version:
            raise ConflictException(
                "The source run's flow version is no longer published.",
                code=FlowApiErrorCode.RUN_RETRY_SOURCE_VERSION_STALE.value,
                context={
                    "source_flow_version": source.flow_version,
                    "published_version": flow.published_version,
                },
            )
        steps = sorted(
            await self.run_repo.list_step_results(
                run_id=source.id, tenant_id=self.user.tenant_id
            ),
            key=lambda step: step.step_order,
        )
        prefix: list[FlowStepResult] = []
        for step in steps:
            if step.status != FlowStepResultStatus.COMPLETED:
                break
            if step.step_order != len(prefix) + 1:
                _unsupported(step_order=step.step_order, reason="non_contiguous_prefix")
            prefix.append(step)
        if not prefix:
            raise ConflictException(
                "The source run has no completed prefix to reuse. Create a new run.",
                code=FlowApiErrorCode.RUN_RETRY_NOTHING_TO_REUSE.value,
                context={},
            )
        if len(prefix) == len(steps):
            _unsupported(step_order=prefix[-1].step_order, reason="no_unfinished_step")
        first_executed_step_order = len(prefix) + 1
        if steps[len(prefix)].step_order != first_executed_step_order:
            _unsupported(
                step_order=steps[len(prefix)].step_order,
                reason="non_contiguous_prefix",
            )
        file_orders = await self.run_repo.list_step_orders_with_result_files(
            run_id=source.id, tenant_id=self.user.tenant_id
        )
        checkpoints = await self.checkpoint_repo.list_review_checkpoints_for_run(
            run_id=source.id, tenant_id=self.user.tenant_id
        )
        unapproved_orders = {
            checkpoint.step_order
            for checkpoint in checkpoints
            if checkpoint.state != FlowRunReviewCheckpointState.APPROVED
        }
        for step in prefix:
            if step.step_order in file_orders or OUTPUT_TEXT_OVERFLOW_KEY in (
                step.output_payload_json or {}
            ):
                _unsupported(
                    step_order=step.step_order,
                    reason="file_backed_prefix_unsupported",
                )
            if step.step_order in unapproved_orders:
                _unsupported(
                    step_order=step.step_order,
                    reason="review_checkpoint_not_approved",
                )
        for step in prefix:
            ensure_inline_payload_size_allowed(
                flow_id=flow_id, input_payload_json=step.output_payload_json
            )
        reused_step_orders = tuple(step.step_order for step in prefix)
        provenance = {
            "version": 1,
            "kind": "reused_prefix",
            "source_run_id": str(source.id),
            "source_run_revision": source.revision,
            "source_flow_version": source.flow_version,
            "request_hash": request_hash,
            "first_executed_step_order": first_executed_step_order,
            "reused_step_orders": list(reused_step_orders),
        }
        files = await self.run_repo.list_current_step_input_file_ids_by_step_result_id(
            run_id=source.id, tenant_id=self.user.tenant_id, step_results=steps
        )
        transcript = (source.input_payload_json or {}).get(FLOW_INPUT_TRANSCRIPTION_KEY)
        created = await self.run_service.create_run(
            flow_id=flow_id,
            run_label=source.run_label,
            input_payload_json=read_semantic_flow_input_payload(
                source.input_payload_json
            ),
            expected_flow_version=source.flow_version,
            step_inputs={
                step.step_id: FlowRunStepInputFiles(file_ids=tuple(files[step.id]))
                for step in steps
                if step.id is not None and files.get(step.id)
            },
            idempotency_key=key,
            purpose=source.purpose,
            prefix_seed=FlowRunPrefixSeed(
                source_run_id=source.id,
                results=tuple(prefix),
                provenance=provenance,
                kind="reused_prefix",
                transcript=transcript if isinstance(transcript, str) else None,
            ),
        )
        if created.created:
            try:
                await self.audit_service.log(
                    tenant_id=self.user.tenant_id,
                    user=self.user,
                    action=ActionType.FLOW_RUN_CREATED,
                    entity_type=EntityType.FLOW_RUN,
                    entity_id=created.run.id,
                    description="Created retry run from a completed prefix",
                    metadata=AuditMetadata.standard(
                        actor=self.user,
                        target=created.run,
                        extra={
                            "flow_id": str(flow_id),
                            "run_id": str(created.run.id),
                            "revision": created.run.revision,
                            "reused_prefix": provenance,
                        },
                    ),
                    required=True,
                )
            except Exception as exc:
                raise_flow_trace_audit_unavailable(
                    user=self.user,
                    run=created.run,
                    action=ActionType.FLOW_RUN_CREATED,
                    cause=exc,
                )
        return FlowRunRetryResult(
            run_result=created,
            source_run_id=source.id,
            first_executed_step_order=first_executed_step_order,
            reused_step_orders=reused_step_orders,
        )

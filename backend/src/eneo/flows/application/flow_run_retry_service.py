from __future__ import annotations

import hashlib
import json
import logging
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
from eneo.flows.domain.flow import FlowRunStatus, FlowStepResultStatus
from eneo.flows.domain.step_output import (
    OUTPUT_TEXT_OVERFLOW_KEY,
    FileBackedStepText,
    InlineTranscript,
)
from eneo.flows.domain.transcript_regeneration import FlowRunPrefixSeed
from eneo.flows.enums import FlowRunReviewCheckpointState
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    TRANSCRIPT_FORMAT_UNSUPPORTED_MESSAGE,
    TRANSCRIPT_REGENERATION_KEY,
    read_max_speakers_decision,
    read_semantic_flow_input_payload,
    read_speaker_labels_choice,
)
from eneo.flows.flow_run_payload_validation import ensure_inline_payload_size_allowed
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    FlowStepResultIdentity,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_runtime import load_published_definition
from eneo.main.config import get_settings
from eneo.main.exceptions import ConflictException
from eneo.users.user import UserInDB

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlowRunRetryResult:
    run_result: CreateRunResult
    source_run_id: UUID
    first_executed_step_order: int
    reused_step_orders: tuple[int, ...]


def _replay_result(
    existing: CreateRunResult, source_run_id: UUID
) -> FlowRunRetryResult:
    provenance = cast(
        dict[str, Any],
        (existing.run.input_payload_json or {})[TRANSCRIPT_REGENERATION_KEY],
    )
    return FlowRunRetryResult(
        run_result=existing,
        source_run_id=source_run_id,
        first_executed_step_order=provenance["first_executed_step_order"],
        reused_step_orders=tuple(provenance["reused_step_orders"]),
    )


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
            lock_creation=False,
        )
        if existing is not None:
            return _replay_result(existing, source.id)
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
            await self.run_repo.list_step_result_identities(
                run_id=source.id, tenant_id=self.user.tenant_id
            ),
            key=lambda step: step.step_order,
        )
        prefix: list[FlowStepResultIdentity] = []
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
        reused_step_orders = tuple(step.step_order for step in prefix)
        transcript = (source.input_payload_json or {}).get(FLOW_INPUT_TRANSCRIPTION_KEY)
        inline = None
        if isinstance(transcript, str):
            logger.warning(
                "Transcript omitted from retry. %s",
                TRANSCRIPT_FORMAT_UNSUPPORTED_MESSAGE,
                extra={
                    "diagnostic_code": "transcript_format_unsupported",
                    "run_id": str(source.id),
                },
            )
        if (
            isinstance(transcript, dict)
            and cast(dict[str, object], transcript).get("kind") == "inline_transcript"
        ):
            inline = InlineTranscript.model_validate(transcript)
            if not any(
                step.step_id == inline.reference.source_step_id
                and step.current_attempt_no == inline.reference.source_attempt_no
                for step in prefix
            ):
                inline = None
        elif isinstance(transcript, dict):
            reference = FileBackedStepText.model_validate(transcript)
            for step in prefix:
                if (
                    step.step_id == reference.source_step_id
                    and step.current_attempt_no == reference.source_attempt_no
                ):
                    _unsupported(
                        step_order=step.step_order,
                        reason="file_backed_prefix_unsupported",
                    )
        definition = await load_published_definition(
            flow_version_repo=self.run_service.flow_version_repo,
            flow_id=flow_id,
            version=source.flow_version,
            tenant_id=self.user.tenant_id,
        )
        review_required = {
            step.step_id
            for step in definition.runtime_steps()
            if step.review_policy is not None
        }
        checkpoints = await self.checkpoint_repo.list_review_checkpoint_identities(
            run_id=source.id,
            tenant_id=self.user.tenant_id,
            step_orders=reused_step_orders,
        )
        checkpoint_states = {
            (checkpoint.step_id, checkpoint.attempt_no): checkpoint.state
            for checkpoint in checkpoints
        }
        review_established_step_ids: set[UUID] = set()
        for step in prefix:
            if step.step_order in file_orders:
                _unsupported(
                    step_order=step.step_order, reason="file_backed_prefix_unsupported"
                )
            if step.current_attempt_no is None:
                _unsupported(step_order=step.step_order, reason="prefix_changed")
            state = checkpoint_states.get((step.step_id, step.current_attempt_no))
            review_established = step.imported_review_established
            if review_established is None:
                review_established = state in (
                    FlowRunReviewCheckpointState.APPROVED,
                    FlowRunReviewCheckpointState.RESUMED,
                )
            if (
                step.step_id in review_required or state is not None
            ) and not review_established:
                _unsupported(
                    step_order=step.step_order, reason="review_not_established"
                )
            if step.step_id in review_required and review_established:
                review_established_step_ids.add(step.step_id)
        measurement = await self.run_repo.measure_prefix_results(
            run_id=source.id,
            tenant_id=self.user.tenant_id,
            step_orders=reused_step_orders,
        )
        if measurement.step_count != len(prefix):
            _unsupported(
                step_order=prefix[0].step_order, reason="non_contiguous_prefix"
            )
        if measurement.logical_bytes > get_settings().flow_max_inline_text_bytes:
            _unsupported(step_order=prefix[0].step_order, reason="prefix_too_large")
        results = await self.run_repo.list_step_results_by_orders(
            run_id=source.id,
            tenant_id=self.user.tenant_id,
            step_orders=reused_step_orders,
        )
        if len(results) != len(prefix) or any(
            result.id != identity.id
            or result.current_attempt_no != identity.current_attempt_no
            or result.status != FlowStepResultStatus.COMPLETED
            for result, identity in zip(results, prefix, strict=True)
        ):
            _unsupported(step_order=prefix[0].step_order, reason="prefix_changed")
        for step in results:
            if OUTPUT_TEXT_OVERFLOW_KEY in (step.output_payload_json or {}):
                _unsupported(
                    step_order=step.step_order, reason="file_backed_prefix_unsupported"
                )
            ensure_inline_payload_size_allowed(
                flow_id=flow_id, input_payload_json=step.output_payload_json
            )
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
        existing = await find_prefix_seed_replay(
            run_repo=self.run_repo,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            principal=principal,
            idempotency_key=key,
            request_hash=request_hash,
        )
        if existing is not None:
            return _replay_result(existing, source.id)
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
                if files.get(step.id)
            },
            idempotency_key=key,
            purpose=source.purpose,
            prefix_seed=FlowRunPrefixSeed(
                source_run_id=source.id,
                results=tuple(results),
                provenance=provenance,
                kind="reused_prefix",
                review_established_step_ids=frozenset(review_established_step_ids),
                transcript=inline,
                speaker_labels=read_speaker_labels_choice(source.input_payload_json),
                max_speakers=read_max_speakers_decision(source.input_payload_json),
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

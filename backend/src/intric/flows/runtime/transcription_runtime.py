from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome

from .transcription import resolve_and_transcribe_audio_for_step

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.files.file_models import File
    from intric.files.transcriber import Transcriber
    from intric.flows.flow import FlowRun
    from intric.flows.flow_run_repo import FlowRunRepository
    from intric.spaces.space_repo import SpaceRepository
    from intric.users.user import UserInDB

logger = logging.getLogger(__name__)

FLOW_INPUT_TRANSCRIPTION_KEY = "transkribering"


@dataclass(frozen=True)
class AudioRuntimeResolution:
    text: str
    transcription_metadata: dict[str, Any]
    near_inline_limit_message: str | None


class RuntimeAudioStep(Protocol):
    @property
    def assistant_id(self) -> UUID: ...

    @property
    def step_order(self) -> int: ...

    @property
    def step_id(self) -> UUID: ...


@dataclass(frozen=True)
class AudioRuntimeRequest:
    run: "FlowRun"
    step: RuntimeAudioStep
    context: dict[str, Any]
    version_metadata: dict[str, Any] | None
    files: list["File"]
    requested_ids: list[UUID]
    max_audio_files: int
    max_inline_text_bytes: int


@dataclass(frozen=True)
class AudioRuntimeDeps:
    transcriber: "Transcriber"
    space_repo: "SpaceRepository"
    flow_run_repo: "FlowRunRepository"
    audit_service: "AuditService | None"
    actor: "UserInDB"


def apply_transcription_to_context(*, context: dict[str, Any], transcript: str) -> None:
    context[FLOW_INPUT_TRANSCRIPTION_KEY] = transcript
    flow_input_context = context.get("flow_input")
    if isinstance(flow_input_context, dict):
        flow_input_context[FLOW_INPUT_TRANSCRIPTION_KEY] = transcript


async def persist_transcription_on_run_input(
    *,
    flow_run_repo: "FlowRunRepository",
    run: "FlowRun",
    transcript: str,
) -> None:
    updated_payload = dict(run.input_payload_json or {})
    updated_payload[FLOW_INPUT_TRANSCRIPTION_KEY] = transcript
    await flow_run_repo.update_input_payload(
        run_id=run.id,
        tenant_id=run.tenant_id,
        input_payload_json={FLOW_INPUT_TRANSCRIPTION_KEY: transcript},
    )
    run.input_payload_json = updated_payload


def build_near_limit_message(
    *,
    step_order: int,
    transcript_bytes: int,
    max_inline_text_bytes: int,
) -> str:
    return (
        f"Step {step_order}: transcript is near inline input limit "
        f"({transcript_bytes}/{max_inline_text_bytes} bytes)."
    )


async def log_audio_transcribed_audit(
    *,
    audit_service: "AuditService | None",
    actor: "UserInDB",
    run: "FlowRun",
    step_order: int,
    step_id: UUID,
    metadata: dict[str, Any],
) -> None:
    if audit_service is None:
        return
    try:
        await audit_service.log_async(
            tenant_id=run.tenant_id,
            actor_id=actor.id,
            action=ActionType.FLOW_RUN_AUDIO_TRANSCRIBED,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run.id,
            description=f"Flow step {step_order} transcribed audio input.",
            metadata=AuditMetadata.standard(
                actor=actor,
                target=run,
                extra={
                    "flow_id": str(run.flow_id),
                    "step_order": step_order,
                    "step_id": str(step_id),
                    "file_ids": metadata.get("file_ids"),
                    "model": metadata.get("model"),
                    "language": metadata.get("language"),
                    "text_length": len(str(run.input_payload_json.get(FLOW_INPUT_TRANSCRIPTION_KEY, "")))
                    if isinstance(run.input_payload_json, dict)
                    else 0,
                    "elapsed_ms": metadata.get("elapsed_ms"),
                    "files_count": metadata.get("files_count"),
                    "used_cache": metadata.get("used_cache"),
                },
            ),
            outcome=Outcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "flow_executor.audit_audio_transcribed_failed run_id=%s step_order=%d",
            run.id,
            step_order,
            exc_info=True,
        )


async def resolve_transcribe_and_attach_audio_input(
    *,
    request: AudioRuntimeRequest,
    deps: AudioRuntimeDeps,
) -> AudioRuntimeResolution:
    transcription_result = await resolve_and_transcribe_audio_for_step(
        version_metadata=request.version_metadata,
        space_repo=deps.space_repo,
        assistant_id=request.step.assistant_id,
        step_order=request.step.step_order,
        files=request.files,
        requested_ids=request.requested_ids,
        transcriber=deps.transcriber,
        max_files=request.max_audio_files,
        max_inline_text_bytes=request.max_inline_text_bytes,
    )
    metadata = transcription_result.to_metadata()

    await persist_transcription_on_run_input(
        flow_run_repo=deps.flow_run_repo,
        run=request.run,
        transcript=transcription_result.text,
    )
    apply_transcription_to_context(context=request.context, transcript=transcription_result.text)
    await log_audio_transcribed_audit(
        audit_service=deps.audit_service,
        actor=deps.actor,
        run=request.run,
        step_order=request.step.step_order,
        step_id=request.step.step_id,
        metadata=metadata,
    )

    near_limit_message = None
    if transcription_result.near_inline_limit:
        near_limit_message = build_near_limit_message(
            step_order=request.step.step_order,
            transcript_bytes=transcription_result.transcript_bytes,
            max_inline_text_bytes=request.max_inline_text_bytes,
        )

    return AudioRuntimeResolution(
        text=transcription_result.text,
        transcription_metadata=metadata,
        near_inline_limit_message=near_limit_message,
    )

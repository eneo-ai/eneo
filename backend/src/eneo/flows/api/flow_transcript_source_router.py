from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from eneo.audit.domain.action_types import ActionType
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.application.flow_run_evidence_service import (
    RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES,
)
from eneo.flows.application.flow_run_evidence_snapshot import (
    flow_run_evidence_snapshot_transaction,
)
from eneo.flows.application.flow_trace_audit import (
    log_flow_trace_audit_or_raise,
    raise_flow_trace_audit_unavailable,
)
from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.transcript_source import (
    TranscriptComponentOmissions,
    TranscriptSourceBounds,
    TranscriptSourceOmissionReason,
)
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    AuditLoggingUnavailableException,
    ErrorCodes,
    FileTooLargeException,
)
from eneo.server.dependencies.container import get_container_for_explicit_transaction
from eneo.users.user import UserInDB

router = APIRouter()
TRANSCRIPT_SOURCE_PAGE_SIZE = 200


class TranscriptSourcePageIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    step_id: UUID
    attempt_no: int


class TranscriptSourceSegmentPublic(BaseModel):
    model_config = ConfigDict(extra="allow")

    segment_index: int = Field(ge=0)


class PresentTranscriptSourcePage(TranscriptSourcePageIdentity):
    status: Literal["present"] = "present"
    source_hash: str
    bounds: TranscriptSourceBounds
    component_omissions: TranscriptComponentOmissions
    start_segment_index: int
    page_size: int
    max_response_bytes: int
    next_segment_index: int | None
    segments: list[TranscriptSourceSegmentPublic]
    speaker_review: dict[str, Any] | None = None


class OmittedTranscriptSourcePage(TranscriptSourcePageIdentity):
    status: Literal["omitted"] = "omitted"
    reason: TranscriptSourceOmissionReason
    bounds: TranscriptSourceBounds


class UnavailableTranscriptSourcePage(TranscriptSourcePageIdentity):
    status: Literal["unavailable_pre_row"] = "unavailable_pre_row"


TranscriptSourcePage = Annotated[
    PresentTranscriptSourcePage
    | OmittedTranscriptSourcePage
    | UnavailableTranscriptSourcePage,
    Field(discriminator="status"),
]


@router.get(
    "/{flow_id}/runs/{run_id}/steps/{step_id}/attempts/{attempt_no}/transcript-source/",
    response_model=TranscriptSourcePage,
    operation_id="get_flow_run_transcript_source",
    summary="Get transcript source detail for one attempt",
    description=(
        "Returns up to 200 segments with absolute indexes and the complete source hash. "
        "Follow next_segment_index until null. Send source_hash unchanged as "
        "segments_hash when saving corrections or regenerating. Speaker review detail "
        "is included only at start_segment_index=0. Component omissions describe "
        "production evidence, not the current availability of word timings. "
        "Content authorization and a committed access audit are required."
    ),
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "unavailable_pre_row",
                        "run_id": "00000000-0000-0000-0000-000000000301",
                        "step_id": "00000000-0000-0000-0000-000000000101",
                        "attempt_no": 1,
                    }
                }
            }
        },
        403: error_response(
            description="The caller cannot access this run's content.",
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="The run or named step attempt does not exist.",
            message="Flow run step attempt not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        413: error_response(
            description="The encoded detail response exceeds its byte limit.",
            message="Transcript source detail exceeds the response size limit.",
            eneo_error_code=ErrorCodes.FILE_TOO_LARGE,
            code="file_too_large",
        ),
        503: error_response(
            description="Required access audit logging is unavailable.",
            message="Evidence audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
async def get_flow_run_transcript_source(
    flow_id: UUID,
    run_id: UUID,
    step_id: UUID,
    attempt_no: Annotated[int, Path(ge=1)],
    request: Request,
    start_segment_index: Annotated[int, Query(ge=0)] = 0,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
) -> JSONResponse:
    committed_audit_context: tuple[UserInDB, FlowRun] | None = None
    try:
        async with flow_run_evidence_snapshot_transaction(container):
            await flow_access_context.enforce_flow_scope(
                request,
                container,
                flow_id=flow_id,
                required_access=FlowApiAction.VIEW,
                allow_service_key_principals=True,
            )
            run = await container.flow_run_service().get_run(
                run_id=run_id, flow_id=flow_id, access_kind="content"
            )
            state = await container.flow_transcript_source_service().get_for_attempt(
                flow_id=flow_id, run_id=run_id, step_id=step_id, attempt_no=attempt_no
            )
            identity = TranscriptSourcePageIdentity(
                run_id=run.id, step_id=step_id, attempt_no=attempt_no
            ).model_dump()
            page: TranscriptSourcePage
            if state.status == "present":
                source = state.source
                if source.segments is None or source.source_hash is None:
                    raise ValueError(
                        "Present transcript source lacks segments or hash."
                    )
                end = min(
                    start_segment_index + TRANSCRIPT_SOURCE_PAGE_SIZE,
                    len(source.segments),
                )
                page = PresentTranscriptSourcePage(
                    **identity,
                    source_hash=source.source_hash,
                    bounds=source.bounds,
                    component_omissions=state.component_omissions,
                    start_segment_index=start_segment_index,
                    page_size=TRANSCRIPT_SOURCE_PAGE_SIZE,
                    max_response_bytes=RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES,
                    next_segment_index=end if end < len(source.segments) else None,
                    segments=[
                        TranscriptSourceSegmentPublic.model_validate(
                            {**segment, "segment_index": index}
                        )
                        for index, segment in enumerate(
                            source.segments[start_segment_index:end],
                            start=start_segment_index,
                        )
                    ],
                )
                payload = page.model_dump(mode="json", exclude={"speaker_review"})
                if start_segment_index == 0:
                    payload["speaker_review"] = source.speaker_review
            elif state.status == "omitted":
                page = OmittedTranscriptSourcePage(
                    **identity, reason=state.reason, bounds=state.bounds
                )
                payload = page.model_dump(mode="json")
            else:
                page = UnavailableTranscriptSourcePage(**identity)
                payload = page.model_dump(mode="json")
            response = JSONResponse(payload)
            if len(response.body) > RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES:
                raise FileTooLargeException(
                    "Transcript source detail exceeds the response size limit."
                )
            user = container.user()
            await log_flow_trace_audit_or_raise(
                container=container,
                user=user,
                run=run,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                description=f"Viewed transcript source for flow run {run.id}",
                extra={
                    "evidence_detail": "transcript_source",
                    "step_id": str(step_id),
                    "attempt_no": attempt_no,
                },
            )
            committed_audit_context = (user, run)
    except AuditLoggingUnavailableException:
        raise
    except Exception as exc:
        if committed_audit_context is not None:
            audit_user, audited_run = committed_audit_context
            raise_flow_trace_audit_unavailable(
                user=audit_user,
                run=audited_run,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                cause=exc,
            )
        raise
    return response

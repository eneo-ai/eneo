from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status

from eneo.audit.domain.action_types import ActionType
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE,
    FLOW_RUN_FORBIDDEN_DESCRIPTION,
    commit_flow_runtime_write_before_response,
    error_response,
)
from eneo.flows.api.flow_models import (
    FlowTranscriptCorrectionRevisionPagePublic,
    FlowTranscriptCorrectionRevisionPublic,
    FlowTranscriptCorrectionsEditRequest,
    FlowTranscriptCorrectionsPublic,
    TranscriptCorrectionOccurrencePublic,
    TranscriptSpeakerEditPublic,
)
from eneo.flows.api.flow_runtime_paths import (
    FLOW_RUN_STEP_TRANSCRIPT_CORRECTIONS_PATH,
    FLOW_RUN_TRANSCRIPT_CORRECTIONS_PATH,
)
from eneo.flows.api.flow_service_principal_actor_read_model import (
    FlowServicePrincipalActorPresenter,
)
from eneo.flows.application.flow_run_evidence_snapshot import (
    flow_run_evidence_snapshot_transaction,
)
from eneo.flows.application.flow_trace_audit import (
    log_flow_trace_audit_or_raise,
    raise_flow_trace_audit_unavailable,
)
from eneo.flows.application.flow_transcript_corrections_service import (
    FlowTranscriptCorrectionsView,
)
from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.transcript_corrections import (
    TranscriptCorrectionOccurrence,
    TranscriptSpeakerEdit,
)
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import AuditLoggingUnavailableException, ErrorCodes
from eneo.server.dependencies.container import (
    get_container_for_explicit_transaction,
)
from eneo.users.user import UserInDB

router = APIRouter()


@router.get(
    FLOW_RUN_TRANSCRIPT_CORRECTIONS_PATH.rstrip("/") + "/{step_id}/revisions",
    operation_id="list_flow_run_transcript_correction_revisions",
    response_model=FlowTranscriptCorrectionRevisionPagePublic,
    summary="List transcript correction revisions",
    description=(
        "Page through the committed correction sets of one transcription step "
        "in the order they were saved (ascending revision, continuing after "
        "`after_revision`), each with the revision it replaced so a reviewer "
        "can see what changed between saves. Reverts appear as revisions of "
        "their own. Reading history is an audited evidence view; the same "
        "authorization as the run's evidence applies."
    ),
    responses={
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run or history baseline not found for this flow and tenant.",
            message="History not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        413: error_response(
            description="The baseline and first remaining revision exceed the history page byte limit.",
            message="Review history comparison exceeds the page size limit.",
            eneo_error_code=ErrorCodes.FILE_TOO_LARGE,
            code=FlowApiErrorCode.REVIEW_HISTORY_TOO_LARGE,
            context={"revision": 2},
        ),
        503: error_response(
            description="Required access audit logging is unavailable; no history was returned.",
            message="Evidence audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
async def list_flow_run_transcript_correction_revisions(
    id: UUID,
    run_id: UUID,
    step_id: UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after_revision: Annotated[int | None, Query(ge=1)] = None,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True, with_module_user=True)
    ),
) -> FlowTranscriptCorrectionRevisionPagePublic:
    committed_audit_context: tuple[UserInDB, FlowRun] | None = None
    try:
        async with flow_run_evidence_snapshot_transaction(container):
            await flow_access_context.enforce_flow_scope(
                request,
                container,
                flow_id=id,
                required_access=FlowApiAction.VIEW,
                allow_service_key_principals=True,
            )
            run = await container.flow_run_service().get_run(
                run_id=run_id, flow_id=id, access_kind="content"
            )
            service = container.flow_run_evidence_service()
            page = await service.list_transcript_correction_revisions(
                run=run,
                step_id=step_id,
                after_revision=after_revision,
                limit=limit,
            )
            user = container.user()
            presenter = FlowServicePrincipalActorPresenter(
                api_key_repo=container.api_key_v2_repo(), tenant_id=user.tenant_id
            )
            enriched_items = await presenter.present_history_items(
                [item.model_dump(mode="json") for item in page.items]
            )
            page = page.model_copy(
                update={
                    "items": [
                        FlowTranscriptCorrectionRevisionPublic.model_validate(item)
                        for item in enriched_items
                    ]
                }
            )
            response = service.admit_history_page(page)
            await log_flow_trace_audit_or_raise(
                container=container,
                user=user,
                run=run,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                description=f"Viewed transcript correction revisions for flow run {run.id}",
                extra={
                    "evidence_detail": "transcript_correction_revisions",
                    "step_id": str(step_id),
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


_FLOW_RUN_TRANSCRIPT_CORRECTIONS_LIST_DESCRIPTION = """
List stored transcript corrections for one flow run.

Corrections are non-destructive char-range replacements anchored to the structured
transcript lines a transcription step stored (`transcription.segments` in the step's
`input_payload_json` from the steps listing). The stored transcript is never rewritten:
clients apply the returned occurrences on read and can always show the `original` text
of every corrected span.

The response holds one entry per transcription step that has corrections. An entry
flagged `stale` anchors to a transcript that has since been replaced (step re-run or
re-transcription); render the notice, never apply stale occurrences.

Current content visibility follows run-detail visibility: callers can inspect their own
runs, tenant admins can inspect runs across the tenant, trusted in-space operators can
inspect content for runs in their space, and service-key principals can inspect only
their own runs.

Content access is audit-logged before the response. If the required audit cannot
be committed, the endpoint returns 503 and exposes no transcript corrections.
    """

_FLOW_RUN_TRANSCRIPT_CORRECTIONS_EDIT_DESCRIPTION = (
    """
Replace the transcript corrections of one transcription step.

The request is replace-style: send the full `occurrences` list for the step, with
`expected_revision` as the compare token (`null` creates the step's first set, an empty
list clears the corrections). Every occurrence must anchor exactly: `original` must equal
the current text at `[char_start, char_end)` of the addressed segment, ranges must not
overlap within a segment, and the step must have stored structured transcript lines.
Anchoring failures return `400` with code `flow_transcript_corrections_invalid_occurrence`;
steps without structured lines return `flow_transcript_corrections_segments_unavailable`.

`speaker_edits` replaces the step's speaker reassignments the same way: a null span
reassigns the whole segment, a present span reassigns exactly `original` at
`[char_start, char_end)` of the raw text. `original_speaker` must equal the segment's
stored label, span edits must not overlap within a segment and are exclusive with a
whole-segment edit there. Version 3 supports same-label confirmation and explicit
unresolved decisions (null speaker); it requires the original segments_hash. Older
clients cannot replace v3 decisions. Failures return
`400` with code `flow_transcript_corrections_invalid_speaker_edit`.

Service-key principals may edit corrections only for runs they own (key must have
`resource_permissions.flows = write`).

"""
    + FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)

_FLOW_TRANSCRIPT_CORRECTIONS_STALE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Transcript corrections revision is stale.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION.value,
    "context": {"expected_revision": 1, "current_revision": 2},
}

_FLOW_TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE_ERROR_EXAMPLE: dict[str, object] = {
    "message": (
        "The step has no structured transcript lines to anchor corrections to."
    ),
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE.value,
    "context": {"step_id": "00000000-0000-0000-0000-000000000101"},
}

_FLOW_TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "A correction occurrence does not match the stored transcript.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE.value,
    "context": {
        "reason": "original_mismatch",
        "segment_index": 4,
        "char_start": 27,
        "char_end": 33,
        "anchored_text": "sugar",
        "original": "sugary",
    },
}

_FLOW_TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT_ERROR_EXAMPLE: dict[str, object] = {
    "message": "A speaker edit does not match the stored transcript.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT.value,
    "context": {
        "reason": "original_speaker_mismatch",
        "segment_index": 12,
        "original_speaker": "SPEAKER_00",
        "stored_speaker": "SPEAKER_01",
    },
}

_FLOW_TRANSCRIPT_CORRECTIONS_EDIT_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION.value: {
        "summary": "Another editor saved corrections first.",
        "value": _FLOW_TRANSCRIPT_CORRECTIONS_STALE_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE.value: {
        "summary": "The step stored no structured transcript lines.",
        "value": _FLOW_TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE.value: {
        "summary": "An occurrence no longer matches the stored transcript.",
        "value": _FLOW_TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT.value: {
        "summary": "A speaker edit no longer matches the stored transcript.",
        "value": _FLOW_TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT_ERROR_EXAMPLE,
    },
}


def _present_transcript_corrections(
    view: FlowTranscriptCorrectionsView,
) -> FlowTranscriptCorrectionsPublic:
    return FlowTranscriptCorrectionsPublic(
        schema_version=view.corrections.schema_version,
        segments_hash=view.corrections.segments_hash,
        flow_run_id=view.corrections.flow_run_id,
        step_id=view.corrections.step_id,
        occurrences=[
            TranscriptCorrectionOccurrencePublic.model_validate(item)
            for item in view.corrections.occurrences_json
        ],
        speaker_edits=[
            TranscriptSpeakerEditPublic.model_validate(item)
            for item in view.corrections.speaker_edits_json
        ],
        revision=view.corrections.revision,
        stale=view.stale,
        edited_by_principal_type=view.corrections.edited_by_principal_type,
        created_at=view.corrections.created_at,
        updated_at=view.corrections.updated_at,
    )


@router.get(
    FLOW_RUN_TRANSCRIPT_CORRECTIONS_PATH,
    response_model=list[FlowTranscriptCorrectionsPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_run_transcript_corrections",
    summary="List flow run transcript corrections",
    description=_FLOW_RUN_TRANSCRIPT_CORRECTIONS_LIST_DESCRIPTION,
    responses={
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        503: error_response(
            description="Required access audit logging is unavailable; no transcript corrections were returned.",
            message="Evidence audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
async def list_flow_run_transcript_corrections(
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the requested run.")
    ],
    run_id: Annotated[
        UUID,
        Path(description="Identifier of the run whose corrections should be listed."),
    ],
    request: Request,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True, with_module_user=True)
    ),
):
    committed_audit_context: tuple[UserInDB, FlowRun] | None = None
    try:
        async with flow_run_evidence_snapshot_transaction(container):
            await flow_access_context.enforce_flow_scope(
                request,
                container,
                flow_id=id,
                required_access=FlowApiAction.VIEW,
                allow_service_key_principals=True,
            )
            run = await container.flow_run_service().get_run(
                run_id=run_id, flow_id=id, access_kind="content"
            )
            views = await container.flow_transcript_corrections_service().list_for_run(
                flow_id=id,
                run_id=run_id,
            )
            response = [_present_transcript_corrections(view) for view in views]
            user = container.user()
            await log_flow_trace_audit_or_raise(
                container=container,
                user=user,
                run=run,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                description=f"Viewed transcript corrections for flow run {run.id}",
                extra={"evidence_detail": "transcript_corrections"},
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


@router.patch(
    FLOW_RUN_STEP_TRANSCRIPT_CORRECTIONS_PATH,
    response_model=FlowTranscriptCorrectionsPublic,
    status_code=status.HTTP_200_OK,
    operation_id="edit_flow_run_transcript_corrections",
    summary="Edit flow run transcript corrections",
    description=_FLOW_RUN_TRANSCRIPT_CORRECTIONS_EDIT_DESCRIPTION,
    responses={
        400: error_response(
            description=(
                "Transcript corrections edit failed. Machine-readable codes are "
                "`flow_transcript_corrections_stale_revision`, "
                "`flow_transcript_corrections_segments_unavailable`, "
                "`flow_transcript_corrections_invalid_occurrence`, and "
                "`flow_transcript_corrections_invalid_speaker_edit` (the "
                "last two carry `reason` plus the offending anchor fields "
                "in `context`)."
            ),
            examples=_FLOW_TRANSCRIPT_CORRECTIONS_EDIT_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to review flows.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or step result not found for this flow and tenant.",
            message="Flow run step result not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        503: error_response(
            description="Required audit logging is unavailable; no correction changes were committed.",
            message="Evidence audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
async def edit_flow_run_transcript_corrections(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to mutate.")],
    step_id: Annotated[
        UUID,
        Path(
            description="Identifier of the transcription step whose corrections "
            "should be replaced."
        ),
    ],
    request: Request,
    corrections_in: FlowTranscriptCorrectionsEditRequest,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True, with_module_user=True)
    ),
):
    async with commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.REVIEW,
            allow_service_key_principals=True,
        )
        view = await container.flow_transcript_corrections_service().save(
            flow_id=id,
            run_id=run_id,
            step_id=step_id,
            expected_revision=corrections_in.expected_revision,
            schema_version=corrections_in.schema_version,
            expected_segments_hash=corrections_in.segments_hash,
            occurrences=[
                TranscriptCorrectionOccurrence(
                    segment_index=occurrence.segment_index,
                    char_start=occurrence.char_start,
                    char_end=occurrence.char_end,
                    original=occurrence.original,
                    corrected=occurrence.corrected,
                )
                for occurrence in corrections_in.occurrences
            ],
            speaker_edits=[
                TranscriptSpeakerEdit(
                    segment_index=edit.segment_index,
                    char_start=edit.char_start,
                    char_end=edit.char_end,
                    original=edit.original,
                    original_speaker=edit.original_speaker,
                    speaker=edit.speaker,
                    decision=edit.decision,
                )
                for edit in corrections_in.speaker_edits
            ],
        )
        response = _present_transcript_corrections(view)
    return response


__all__ = ["router"]

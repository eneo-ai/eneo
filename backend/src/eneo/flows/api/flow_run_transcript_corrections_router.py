from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE,
    FLOW_RUN_FORBIDDEN_DESCRIPTION,
    audit_actor_kwargs,
    commit_flow_runtime_write_before_response,
    error_response,
)
from eneo.flows.api.flow_models import (
    FlowTranscriptCorrectionsEditRequest,
    FlowTranscriptCorrectionsPublic,
    TranscriptCorrectionOccurrencePublic,
)
from eneo.flows.api.flow_runtime_paths import (
    FLOW_RUN_STEP_TRANSCRIPT_CORRECTIONS_PATH,
    FLOW_RUN_TRANSCRIPT_CORRECTIONS_PATH,
)
from eneo.flows.application.flow_transcript_corrections_service import (
    FlowTranscriptCorrectionsView,
)
from eneo.flows.domain.transcript_corrections import TranscriptCorrectionOccurrence
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)

router = APIRouter()

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
}


def _present_transcript_corrections(
    view: FlowTranscriptCorrectionsView,
) -> FlowTranscriptCorrectionsPublic:
    return FlowTranscriptCorrectionsPublic(
        flow_run_id=view.corrections.flow_run_id,
        step_id=view.corrections.step_id,
        occurrences=[
            TranscriptCorrectionOccurrencePublic.model_validate(item)
            for item in view.corrections.occurrences_json
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
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    views = await container.flow_transcript_corrections_service().list_for_run(
        flow_id=id,
        run_id=run_id,
    )
    return [_present_transcript_corrections(view) for view in views]


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
                "`flow_transcript_corrections_segments_unavailable`, and "
                "`flow_transcript_corrections_invalid_occurrence` (whose context "
                "carries `reason` plus the offending anchor fields)."
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
        get_container_for_explicit_transaction(with_user=True)
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
        )
        user = container.user()
        actor_kwargs = audit_actor_kwargs(user)
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            actor_id=actor_kwargs["actor_id"],
            actor_type=actor_kwargs["actor_type"],
            actor_api_key_id=actor_kwargs["actor_api_key_id"],
            action=ActionType.FLOW_RUN_TRANSCRIPT_CORRECTIONS_EDITED,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run_id,
            description="Replaced transcript corrections for a flow run step",
            metadata=AuditMetadata.standard(
                actor=user,
                target=view.corrections,
                extra={
                    "flow_id": str(id),
                    "run_id": str(run_id),
                    "step_id": str(step_id),
                    "occurrence_count": len(view.corrections.occurrences_json),
                    "revision": view.corrections.revision,
                },
            ),
        )
        response = _present_transcript_corrections(view)
    return response


__all__ = ["router"]

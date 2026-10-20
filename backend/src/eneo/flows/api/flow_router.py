"""REST surface for flows.

Authoring happens through the loopback ``flows`` MCP tools and, for the
panel's own editor, the PATCH and edit-mode endpoints here. Otherwise this
router reads flows, exposes the hidden authoring assistant and carries the
run side of the API (published view, run contract, runtime uploads, runs,
status, steps, cancel, review checkpoints, signed file links) that external
consumers integrate against. The run-side paths are the ones
:mod:`eneo.flows.flow_runtime_paths` advertises.
"""

from __future__ import annotations

import time
from typing import Annotated, Optional
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, UploadFile

from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.authentication.signed_urls import generate_file_original_download_token
from eneo.files.file_models import FilePublic, SignedURLRequest, SignedURLResponse
from eneo.flows.api.dependencies import require_flows_enabled
from eneo.flows.flow_functions import list_flow_functions
from eneo.flows.flow_models import (
    FlowArtifactPublic,
    FlowAuthoringAssistantPublic,
    FlowConversationBindRequest,
    FlowCreateRequest,
    FlowFunctionPublic,
    FlowPublic,
    FlowRevisionPublic,
    FlowRevisionSummaryPublic,
    FlowRunContractPublic,
    FlowRunCreateRequest,
    FlowRunPublic,
    FlowRunReviewCheckpointApproveRequest,
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointPublic,
    FlowRunReviewCheckpointRejectRequest,
    FlowRunReviewCheckpointResumeRequest,
    FlowRunReviewCheckpointResumeResponse,
    FlowRunStatus,
    FlowRunStepPublic,
    FlowRunSummaryPublic,
    FlowSparsePublic,
    FlowTranscriptCorrectionsEditRequest,
    FlowTranscriptCorrectionsPublic,
    FlowTranscriptPublic,
    FlowUpdateRequest,
)
from eneo.flows.flow_runtime_paths import (
    DELETE_RUNTIME_FILE_PATH,
    FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
    FLOW_RUN_INPUT_FILE_SIGNED_URL_PATH,
    PUBLISHED_FLOW_RUNTIME_PATH,
    UPLOAD_RUNTIME_FILE_PATH,
    FlowRuntimePublic,
)
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter(dependencies=[Depends(require_flows_enabled)])

_Container = Annotated[Container, Depends(get_container(with_user=True))]
# An upload writes to the object store, which cannot happen inside a
# transaction; the service opens its own short ones around the rows.
_UploadContainer = Annotated[
    Container,
    Depends(
        get_container(
            with_user=True, with_transaction=False, with_upload_admission=True
        )
    ),
]


_UPLOAD_OPENAPI_EXTRA: dict[str, object] = {
    "requestBody": {
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["upload_file"],
                    "properties": {
                        "upload_file": {"type": "string", "format": "binary"}
                    },
                }
            }
        }
    }
}
_READ_REASON = "FlowService enforces space membership and flow read permission."
_RUN_REASON = (
    "FlowRunService enforces flow read permission; runs resolve only "
    "through their own flow."
)
_REVIEW_REASON = (
    "FlowRunService enforces flow read permission and checkpoint revision CAS."
)
MAX_RUN_PAGE = 100
MAX_REVISION_PAGE = 100


# --- Flows ---


@router.get(
    "/",
    response_model=PaginatedResponse[FlowSparsePublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def list_flows(
    container: _Container, space_id: UUID
) -> PaginatedResponse[FlowSparsePublic]:
    flows = await container.flow_service().list_flows(space_id)
    return PaginatedResponse(items=flows)


@router.post(
    "/",
    description="Start a flow as an empty draft in a space; its chat fills it in afterwards.",
    response_model=FlowPublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow create permission in the space.",
)
async def create_flow(
    request: FlowCreateRequest,
    container: _Container,
    _user_for_creation: None = Depends(require_user_for_creation),
) -> FlowPublic:
    """Start a flow as an empty draft; its chat fills it in afterwards."""
    return await container.flow_service().create_draft(
        space_id=request.space_id, name=request.name
    )


@router.get(
    "/functions/",
    response_model=list[FlowFunctionPublic],
    description=(
        "The functions a function step can call in a space: each purpose, "
        "whether the space enables it, and the tools of the provider a run "
        "reaches for it."
    ),
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def list_functions(
    container: _Container, space_id: UUID
) -> list[FlowFunctionPublic]:
    space = await container.flow_service().authorize_space(space_id)
    return await list_flow_functions(
        space, container.assistant_service().capability_server
    )


@router.get(
    "/authoring-assistant/",
    response_model=FlowAuthoringAssistantPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowAuthoringAssistantService requires flow create permission.",
)
async def get_authoring_assistant(
    container: _Container, space_id: UUID
) -> FlowAuthoringAssistantPublic:
    return await container.flow_authoring_assistant_service().get_or_create(space_id)


@router.get(
    "/{id}/",
    response_model=FlowPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def get_flow(id: UUID, container: _Container) -> FlowPublic:
    return await container.flow_service().get_flow(id)


@router.patch(
    "/{id}/",
    description="Change the draft from the panel (needs edit mode); only the fields given change.",
    response_model=FlowPublic,
    responses=responses.get_responses([400, 403, 404, 409, 422]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=(
        "FlowService enforces flow edit permission in the space and that the "
        "caller is in edit mode on the flow."
    ),
)
async def update_flow(
    id: UUID, request: FlowUpdateRequest, container: _Container
) -> FlowPublic:
    """Change the draft from the panel; only the fields given change.

    Needs edit mode (409 otherwise). Every change is kept as a revision.
    A definition with problems is refused with 422 and the problems listed
    in ``details.problems``.
    """
    service = container.flow_service()
    await service.require_editing(id)
    return await service.update_flow(
        id,
        name=request.name,
        description=request.description,
        definition=request.definition,
        channel="api",
        note=request.note,
    )


@router.post(
    "/{id}/edit-mode/",
    description="Enter edit mode on the flow for the caller (idempotent); others may be editing too.",
    response_model=FlowPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow edit permission in the space.",
)
async def enter_edit_mode(
    id: UUID,
    container: _Container,
    _user_for_creation: None = Depends(require_user_for_creation),
) -> FlowPublic:
    """Enter edit mode on the flow (idempotent); others may be editing too."""
    return await container.flow_service().enter_edit_mode(id)


@router.delete(
    "/{id}/edit-mode/",
    description="Leave edit mode (idempotent); nothing is saved, every change already is a revision.",
    response_model=FlowPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def leave_edit_mode(id: UUID, container: _Container) -> FlowPublic:
    """Leave edit mode (idempotent); nothing is saved, every change already is."""
    return await container.flow_service().leave_edit_mode(id)


@router.delete(
    "/{id}/",
    description="Delete the flow; runs already made stay in the history.",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow delete permission in the space.",
)
async def delete_flow(id: UUID, container: _Container) -> Response:
    await container.flow_service().delete_flow(id)
    return Response(status_code=204)


@router.post(
    "/{id}/conversation/",
    description="Bind the flow to the chat that authors it (409 when bound elsewhere).",
    response_model=FlowPublic,
    responses=responses.get_responses([400, 403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=(
        "FlowService enforces flow edit permission and that the session is the "
        "caller's own flows chat."
    ),
)
async def bind_conversation(
    id: UUID, request: FlowConversationBindRequest, container: _Container
) -> FlowPublic:
    """Bind the flow to the chat that authors it (409 when bound elsewhere)."""
    return await container.flow_service().bind_conversation(id, request.session_id)


@router.get(
    PUBLISHED_FLOW_RUNTIME_PATH,
    response_model=FlowRuntimePublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def get_published_flow_runtime(
    id: UUID, container: _Container
) -> FlowRuntimePublic:
    """A published flow's metadata and every run-side path a client needs."""
    return await container.flow_service().get_published_runtime(id)


@router.get(
    "/{id}/run-contract/",
    response_model=FlowRunContractPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def get_run_contract(id: UUID, container: _Container) -> FlowRunContractPublic:
    return await container.flow_service().get_run_contract(id)


# --- Runtime files ---


@router.post(
    UPLOAD_RUNTIME_FILE_PATH,
    description="Upload a file to give a run; bind its id to a file form field when starting the run.",
    response_model=FilePublic,
    status_code=201,
    openapi_extra=_UPLOAD_OPENAPI_EXTRA,
    responses=responses.get_responses([400, 403, 404, 413, 415]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow read permission; the file is the caller's.",
)
async def upload_runtime_file(
    id: UUID, upload_file: UploadFile, container: _UploadContainer
) -> FilePublic:
    """Upload a file to give a run; bind its id to a file form field in the run.

    Open to service keys: the file is stored as the flow author's, so the
    creation guard for user-owned rows does not apply.
    """
    return await container.flow_service().add_runtime_file(id, upload_file)


@router.delete(
    DELETE_RUNTIME_FILE_PATH,
    description="Remove an upload no run has used yet (409 once a run took it).",
    status_code=204,
    responses=responses.get_responses([403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow read permission and file ownership.",
)
async def delete_runtime_file(
    id: UUID, file_id: UUID, container: _Container
) -> Response:
    """Remove an upload no run has used yet (409 once a run took it)."""
    await container.flow_service().delete_runtime_file(id, file_id)
    return Response(status_code=204)


# --- Revisions ---


@router.get(
    "/{id}/revisions/",
    response_model=PaginatedResponse[FlowRevisionSummaryPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def list_revisions(
    id: UUID,
    container: _Container,
    limit: Annotated[int, Query(ge=1, le=MAX_REVISION_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[FlowRevisionSummaryPublic]:
    """The flow's history, newest first: every save, with what it changed."""
    revisions, _total = await container.flow_service().list_revisions(
        id, limit=limit, offset=offset
    )
    return PaginatedResponse(items=revisions)


@router.get(
    "/{id}/revisions/{revision}/",
    response_model=FlowRevisionPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def get_revision(
    id: UUID, revision: int, container: _Container
) -> FlowRevisionPublic:
    return await container.flow_service().get_revision(id, revision)


@router.post(
    "/{id}/revisions/{revision}/restore/",
    description="Make an earlier revision the draft again; the restore is a new revision.",
    response_model=FlowPublic,
    responses=responses.get_responses([400, 403, 404, 422]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow edit permission in the space.",
)
async def restore_revision(
    id: UUID, revision: int, container: _Container
) -> FlowPublic:
    """Make the revision the draft again; the restore is a new revision."""
    return await container.flow_service().restore_revision(id, revision)


# --- Runs ---


@router.get(
    "/{id}/artifacts/",
    response_model=list[FlowArtifactPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def list_artifacts(
    id: UUID,
    container: _Container,
    limit: Annotated[int, Query(ge=1, le=MAX_RUN_PAGE)] = 50,
) -> list[FlowArtifactPublic]:
    """Files the flow's runs produced, newest first."""
    return await container.flow_run_service().list_artifacts(id, limit=limit)


@router.post(
    "/{id}/runs/",
    description="Start a run of the published version, or a test run of the draft.",
    response_model=FlowRunPublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404, 422]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def create_run(
    id: UUID,
    request: FlowRunCreateRequest,
    container: _Container,
    idempotency_key: Annotated[
        Optional[str], Header(alias="Idempotency-Key", max_length=200)
    ] = None,
) -> FlowRunPublic:
    return await container.flow_run_service().create_run(
        id,
        values=request.values,
        files=request.files,
        run_label=request.run_label,
        expected_flow_version=request.expected_flow_version,
        idempotency_key=idempotency_key,
        draft=request.draft,
    )


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[FlowRunSummaryPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def list_runs(
    id: UUID,
    container: _Container,
    limit: Annotated[int, Query(ge=1, le=MAX_RUN_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[
        Optional[list[FlowRunStatus]],
        Query(description="Only runs in these statuses (repeat the parameter)."),
    ] = None,
) -> PaginatedResponse[FlowRunSummaryPublic]:
    runs, _total = await container.flow_run_service().list_runs(
        id, limit=limit, offset=offset, statuses=tuple(status) if status else None
    )
    return PaginatedResponse(items=runs)


@router.get(
    "/{id}/runs/{run_id}/",
    response_model=FlowRunPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def get_run(id: UUID, run_id: UUID, container: _Container) -> FlowRunPublic:
    return await container.flow_run_service().get_run(run_id, flow_id=id)


@router.get(
    "/{id}/runs/{run_id}/status/",
    response_model=FlowRunSummaryPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def get_run_status(
    id: UUID, run_id: UUID, container: _Container
) -> FlowRunSummaryPublic:
    return await container.flow_run_service().get_run_summary(run_id, flow_id=id)


@router.get(
    "/{id}/runs/{run_id}/steps/",
    response_model=list[FlowRunStepPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def get_run_steps(
    id: UUID, run_id: UUID, container: _Container
) -> list[FlowRunStepPublic]:
    return await container.flow_run_service().get_run_steps(run_id, flow_id=id)


@router.post(
    "/{id}/runs/{run_id}/cancel/",
    description="Cancel a run that is queued, running or waiting for a review.",
    response_model=FlowRunPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowRunService allows cancel for the run owner or a flow editor.",
)
async def cancel_run(id: UUID, run_id: UUID, container: _Container) -> FlowRunPublic:
    return await container.flow_run_service().cancel_run(run_id, flow_id=id)


# --- Review checkpoints ---


@router.get(
    "/{id}/runs/{run_id}/review-checkpoints/active/",
    response_model=Optional[FlowRunReviewCheckpointPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def get_active_checkpoint(
    id: UUID, run_id: UUID, container: _Container
) -> Optional[FlowRunReviewCheckpointPublic]:
    return await container.flow_run_service().get_active_checkpoint(run_id, flow_id=id)


@router.patch(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
    description="Replace the payload under review (checked against the checkpoint revision).",
    response_model=FlowRunReviewCheckpointPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def edit_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointEditRequest,
    container: _Container,
) -> FlowRunReviewCheckpointPublic:
    return await container.flow_run_service().edit_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        current_payload_json=request.current_payload_json,
        flow_id=id,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
    description="Approve the review checkpoint without resuming the run.",
    response_model=FlowRunReviewCheckpointResumeResponse,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def approve_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointApproveRequest,
    container: _Container,
) -> FlowRunReviewCheckpointResumeResponse:
    return await container.flow_run_service().approve_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        flow_id=id,
        resume=False,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
    description="Reject the review checkpoint; the run stops and the reason is kept.",
    response_model=FlowRunReviewCheckpointPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def reject_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointRejectRequest,
    container: _Container,
) -> FlowRunReviewCheckpointPublic:
    return await container.flow_run_service().reject_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        reason=request.reason,
        flow_id=id,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
    description="Resume the run after an approved checkpoint.",
    response_model=FlowRunReviewCheckpointResumeResponse,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def resume_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointResumeRequest,
    container: _Container,
) -> FlowRunReviewCheckpointResumeResponse:
    return await container.flow_run_service().resume_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        flow_id=id,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/",
    description="Approve the review checkpoint and resume the run.",
    response_model=FlowRunReviewCheckpointResumeResponse,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def approve_and_continue(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointApproveRequest,
    container: _Container,
) -> FlowRunReviewCheckpointResumeResponse:
    return await container.flow_run_service().approve_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        flow_id=id,
        resume=True,
    )


# --- Transcripts and their corrections ---


@router.get(
    "/{id}/runs/{run_id}/transcript-corrections/",
    response_model=list[FlowTranscriptCorrectionsPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def list_transcript_corrections(
    id: UUID, run_id: UUID, container: _Container
) -> list[FlowTranscriptCorrectionsPublic]:
    """The stored corrections of the run's transcribe steps (``stale`` ones
    anchor to a transcript that has since changed and must not be applied)."""
    return await container.flow_transcript_corrections_service().list_for_run(
        run_id, flow_id=id
    )


@router.patch(
    "/{id}/runs/{run_id}/steps/{step_id}/transcript-corrections/",
    description="Replace one transcribe step's corrections (full lists, checked against the revision).",
    response_model=FlowTranscriptCorrectionsPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def edit_transcript_corrections(
    id: UUID,
    run_id: UUID,
    step_id: UUID,
    request: FlowTranscriptCorrectionsEditRequest,
    container: _Container,
) -> FlowTranscriptCorrectionsPublic:
    """Replace one transcribe step's corrections: send the full lists, the
    ``segments_hash`` of the transcript they anchor to and
    ``expected_revision`` (null to create)."""
    return await container.flow_transcript_corrections_service().save(
        run_id,
        step_id,
        flow_id=id,
        schema_version=request.schema_version,
        segments_hash=request.segments_hash,
        expected_revision=request.expected_revision,
        occurrences=request.occurrences,
        speaker_edits=request.speaker_edits,
        speaker_names=request.speaker_names,
    )


@router.get(
    "/{id}/runs/{run_id}/steps/{step_id}/transcript/",
    response_model=FlowTranscriptPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def get_transcript(
    id: UUID, run_id: UUID, step_id: UUID, container: _Container
) -> FlowTranscriptPublic:
    """A transcribe step's transcript with its corrections applied."""
    return await container.flow_transcript_corrections_service().get_transcript(
        run_id, step_id, flow_id=id
    )


# --- Signed links to a run's files ---


def _signed_download(
    request: Request,
    *,
    file_id: UUID,
    tenant_id: UUID,
    signed_url_req: SignedURLRequest,
) -> SignedURLResponse:
    issued_at = int(time.time())
    expires_at = issued_at + signed_url_req.expires_in
    token = generate_file_original_download_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=signed_url_req.content_disposition,
        tenant_id=tenant_id,
        issued_at=issued_at,
    )
    url = request.url_for("download_original_file_signed", id=str(file_id))
    return SignedURLResponse(
        url=f"{url}?{urlencode({'token': token})}", expires_at=expires_at
    )


@router.post(
    FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
    description="A time-limited link to a file the run produced.",
    response_model=SignedURLResponse,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def generate_run_artifact_signed_url(
    id: UUID,
    run_id: UUID,
    file_id: UUID,
    request: Request,
    signed_url_req: SignedURLRequest,
    container: _Container,
) -> SignedURLResponse:
    """A time-limited link to a file the run produced."""
    file = await container.flow_run_service().run_file_for_download(
        run_id, file_id, role="output", flow_id=id
    )
    return _signed_download(
        request,
        file_id=file.id,
        tenant_id=file.tenant_id,
        signed_url_req=signed_url_req,
    )


@router.post(
    FLOW_RUN_INPUT_FILE_SIGNED_URL_PATH,
    description="A time-limited link to a file the run was given.",
    response_model=SignedURLResponse,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def generate_run_input_file_signed_url(
    id: UUID,
    run_id: UUID,
    file_id: UUID,
    request: Request,
    signed_url_req: SignedURLRequest,
    container: _Container,
) -> SignedURLResponse:
    """A time-limited link to a file the run was given."""
    file = await container.flow_run_service().run_file_for_download(
        run_id, file_id, role="input", flow_id=id
    )
    return _signed_download(
        request,
        file_id=file.id,
        tenant_id=file.tenant_id,
        signed_url_req=signed_url_req,
    )

"""Helper-run router for ``/api/v1/help-assistants/...`` (PRD §5, §10).

Four endpoints, two shared services:

* ``POST /runs/`` — start a new helper run for ``{kind, target_type,
  target_id, question, stream}``. The helper assistant resolves
  server-side from the active ``OrgSpaceAssistantRoleService`` for the
  caller's tenant — the frontend never sends a helper-assistant id (PRD
  §10).
* ``POST /runs/{run_id}/turns/`` — follow-up turn on an existing run.
* ``PATCH /runs/{run_id}/`` — UX-driven terminal-status transition
  (Apply, Abandon, Failed).
* ``GET /availability`` — cheap pre-flight the frontend hits before
  rendering the prompt-guide toolbar button. Mirrors every gate
  ``HelperRunService.run`` would enforce but returns a typed
  ``disabled_reason`` instead of raising.

Authorization is owned by ``HelperRunService``: the start and follow-up
paths require ``ResourcePermission.EDIT`` on the target assistant; the
status path requires the caller to be the original actor. The router only
adds the standard "authenticated user" guard via ``get_container(with_user=True)``.

Streaming behavior mirrors ``assistants/api/assistant_router.py``
``ask_assistant``: the service's ``answer`` is an async generator and the
router wraps it in ``EventSourceResponse`` so the client receives each
chunk as it arrives. Persistence at stream close lives inside the
service's streaming wrapper (``_stream_and_persist``), so the router
never re-implements question/token bookkeeping.

Helper-run status transitions are **not** audit-logged — the
``help_assistant_runs`` row itself is the record (PRD §3 + step 019).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse

from eneo.ai_models.completion_models.completion_model import Completion, ResponseType
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.help_assistants.api.run_models import (
    AvailabilityResponse,
    ContinueTurnRequest,
    HelperRunPublic,
    HelperRunResponsePublic,
    StartRunRequest,
    UpdateStatusRequest,
)
from eneo.help_assistants.application.helper_run_service import HelperRunResponse
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.helper_run import HelperRun
from eneo.info_blobs.info_blob import (
    InfoBlobAskAssistantPublic,
    InfoBlobInDBWithScore,
    InfoBlobMetadata,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.main.logging import get_logger
from eneo.main.models import ResourcePermission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()
logger = get_logger(__name__)

HelperRunContainer = Annotated[Container, Depends(get_container(with_user=True))]


def _run_to_public(run: HelperRun) -> HelperRunPublic:
    assert run.id is not None
    return HelperRunPublic(
        id=run.id,
        kind=run.kind,
        assistant_id=run.assistant_id,
        target_type=run.target_type,
        target_id=run.target_id,
        session_id=run.session_id,
        actor_user_id=run.actor_user_id,
        status=run.status,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _references_to_public(
    info_blobs: list[InfoBlobInDBWithScore],
) -> list[InfoBlobAskAssistantPublic]:
    return [
        InfoBlobAskAssistantPublic(
            **blob.model_dump(),
            metadata=InfoBlobMetadata(**blob.model_dump()),
        )
        for blob in info_blobs
    ]


def _to_event_stream(
    response: HelperRunResponse,
) -> EventSourceResponse:
    """Wrap the service's async-generator answer in an SSE response.

    Yields one JSON-encoded ``HelperRunResponsePublic`` per ``TEXT`` chunk
    so the client sees the answer build up incrementally. The static
    ``run`` and ``references`` payload travels on every chunk — the
    frontend already de-duplicates on ``run.id`` for follow-up turns.

    Persistence at stream-close happens inside the service-owned
    generator (``HelperRunService._stream_and_persist``), so iterating
    this stream to exhaustion is what records the question/answer row.
    """

    run_public = _run_to_public(response.run)
    references = _references_to_public(response.info_blobs)
    answer = response.answer
    assert not isinstance(answer, str), (
        "Streaming HelperRunResponse must carry an async-generator answer"
    )

    async def event_stream():
        try:
            async for chunk in answer:
                if chunk.response_type == ResponseType.ERROR:
                    # The completion adapter yields an ERROR chunk (rather than
                    # raising) when the provider fails mid-stream. Forward it as
                    # a terminal error event so the client stops and marks the
                    # run failed, instead of silently ending with a partial
                    # answer.
                    yield HelperRunResponsePublic(
                        run=run_public,
                        answer="",
                        references=[],
                        error=chunk.error or "completion_failed",
                    ).model_dump_json()
                    return
                if chunk.response_type == ResponseType.TEXT:
                    yield HelperRunResponsePublic(
                        run=run_public,
                        answer=chunk.text or "",
                        references=_chunk_references_or_default(chunk, references),
                    ).model_dump_json()
        except Exception:
            # Defense in depth: any unexpected mid-stream failure becomes a
            # terminal error event, not a raw traceback that drops the SSE
            # connection ambiguously.
            logger.exception("Helper run %s stream failed mid-flight", run_public.id)
            yield HelperRunResponsePublic(
                run=run_public,
                answer="",
                references=[],
                error="completion_failed",
            ).model_dump_json()

    return EventSourceResponse(event_stream(), ping=15)


def _chunk_references_or_default(
    chunk: Completion,
    default_references: list[InfoBlobAskAssistantPublic],
) -> list[InfoBlobAskAssistantPublic]:
    if chunk.reference_chunks:
        return [
            InfoBlobAskAssistantPublic(
                **blob.model_dump(),
                metadata=InfoBlobMetadata(**blob.model_dump()),
            )
            for blob in chunk.reference_chunks
        ]
    return default_references


def _to_json_response(response: HelperRunResponse) -> HelperRunResponsePublic:
    answer = response.answer
    assert isinstance(answer, str), (
        "Non-streaming HelperRunResponse must carry a string answer"
    )
    return HelperRunResponsePublic(
        run=_run_to_public(response.run),
        answer=answer,
        references=_references_to_public(response.info_blobs),
    )


@router.post(
    "/runs/",
    response_model=HelperRunResponsePublic,
    description="Start a new helper run for a target assistant (JSON or SSE).",
    responses=responses.streaming_response(HelperRunResponsePublic, [400, 403, 404]),
)
async def start_helper_run(
    body: StartRunRequest,
    container: HelperRunContainer,
    _user_for_creation: None = Depends(require_user_for_creation),
):
    """Start a new helper run.

    Helper-assistant resolution lives in ``HelperRunService``: it loads
    the active role for ``body.kind`` and rejects with 403 +
    ``helper_not_available`` if the role is disabled or hidden. Edit-permission
    on ``body.target_id`` is enforced inside the service (403 +
    ``forbidden_action`` otherwise). SSE response when ``body.stream``.
    """
    service = container.helper_run_service()
    response = await service.run(
        kind=body.kind,
        target_type=body.target_type,
        target_id=body.target_id,
        question=body.question,
        stream=body.stream,
    )
    if body.stream:
        return _to_event_stream(response)
    return _to_json_response(response)


@router.post(
    "/runs/{run_id}/turns/",
    response_model=HelperRunResponsePublic,
    description="Follow-up turn on an existing helper run (JSON or SSE).",
    responses=responses.streaming_response(HelperRunResponsePublic, [400, 403, 404]),
)
async def continue_helper_run(
    run_id: UUID,
    body: ContinueTurnRequest,
    container: HelperRunContainer,
    _user_for_creation: None = Depends(require_user_for_creation),
):
    """Follow-up turn on an existing helper run.

    Only the original actor may follow up (service raises 403 otherwise).
    Re-runs the role availability / completion-model checks every turn —
    an admin may disable the role between turns, and the completion model
    may have been removed.
    """
    service = container.helper_run_service()
    response = await service.continue_turn(
        run_id=run_id,
        question=body.question,
        stream=body.stream,
    )
    if body.stream:
        return _to_event_stream(response)
    return _to_json_response(response)


@router.patch(
    "/runs/{run_id}/",
    response_model=HelperRunPublic,
    description="Transition a helper run to a terminal status (completed/abandoned/failed).",
    responses=responses.get_responses([400, 403, 404]),
)
async def update_helper_run_status(
    run_id: UUID,
    body: UpdateStatusRequest,
    container: HelperRunContainer,
):
    """Transition a helper run to a terminal status.

    UX-driven: ``completed`` from Apply, ``abandoned`` from closing the
    modal, ``failed`` from a client-side fault. The service rejects
    ``in_progress`` and rejects repeat transitions on an already-terminal
    run with 400.
    """
    service = container.helper_run_service()
    run = await service.set_status(run_id=run_id, status=body.status)
    return _run_to_public(run)


@router.get(
    "/availability",
    response_model=AvailabilityResponse,
    description="Pre-flight signal for whether the prompt-guide button should render.",
    responses=responses.get_responses([403]),
)
async def get_helper_availability(
    kind: HelperKind,
    target_id: UUID,
    container: HelperRunContainer,
) -> AvailabilityResponse:
    """Decide whether to render the prompt-guide toolbar button.

    Mirrors every gate ``HelperRunService.run`` would enforce, but maps
    each failure mode to a typed ``disabled_reason`` instead of raising.
    The frontend hides the button whenever ``available`` is False; the
    reason is diagnostic so an admin UX can surface a clear message
    ("role disabled", "no completion model", ...).

    The helper assistant id is intentionally **not** in the response —
    callers never need it (resolution is server-side via
    :class:`StartRunRequest`) and exposing it would defeat the
    "helper assistants are hidden" invariant.

    ``no_edit_rights`` collapses three target-side failure cases — the
    assistant does not exist, the caller cannot read its space, the
    caller can read but cannot edit — into a single reason so this
    endpoint cannot be used as an assistant-existence probe.
    """
    assistant_service = container.assistant_service()
    role_service = container.org_space_assistant_role_service()

    try:
        _, permissions = await assistant_service.get_assistant(assistant_id=target_id)
    except (NotFoundException, UnauthorizedException):
        return AvailabilityResponse(available=False, disabled_reason="no_edit_rights")
    if ResourcePermission.EDIT not in permissions:
        return AvailabilityResponse(available=False, disabled_reason="no_edit_rights")

    role = await role_service.get_active(kind)
    if role is None:
        return AvailabilityResponse(available=False, disabled_reason="no_assignment")
    if not role.is_enabled:
        return AvailabilityResponse(available=False, disabled_reason="role_disabled")
    if not role.is_visible_to_users:
        return AvailabilityResponse(available=False, disabled_reason="role_not_visible")

    # Privileged read of the designated helper (PRD §5/§6/§10): non-admin end
    # users are not org-space members, so the permission-enforcing
    # get_assistant would 403 here even though they legitimately reach this
    # pre-flight via edit rights on the target. get_help_assistant loads the
    # role's assistant without the org-space read gate. If the helper was
    # deleted/archived out from under the active role, treat it as "no usable
    # assignment" rather than letting the pre-flight raise.
    try:
        helper = await assistant_service.get_help_assistant(role.assistant_id)
    except NotFoundException:
        return AvailabilityResponse(available=False, disabled_reason="no_assignment")
    if helper.completion_model is None or not helper.completion_model.can_access:
        return AvailabilityResponse(
            available=False, disabled_reason="no_completion_model"
        )

    return AvailabilityResponse(available=True)

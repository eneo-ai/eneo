"""Pydantic models for the helper-run router (PRD §5, §10).

The frontend only sends ``{kind, target_type, target_id, question, stream}``
when starting a run — the helper assistant is resolved server-side via the
active ``OrgSpaceAssistantRoleService.get_active`` for the calling tenant
(PRD §10). Follow-up turns and status transitions keep the wire shape
minimal: the run id in the URL identifies the conversation and the actor
is the authenticated user.

``HelperRunResponsePublic`` is the JSON shape returned for non-stream
responses. References surface as the same ``InfoBlobAskAssistantPublic``
that the assistant ``ask`` endpoints emit so the frontend can reuse its
reference-renderer without a second schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.helper_run_status import HelperRunStatus
from intric.info_blobs.info_blob import InfoBlobAskAssistantPublic


class StartRunRequest(BaseModel):
    """Body for ``POST /runs/`` — start a new helper run.

    ``target_type`` is currently always ``"assistant"`` (PRD §5). The
    service validates it; the model keeps the field open-ended so a future
    target kind (group chat, app run) can be added without a wire-format
    bump.
    """

    kind: HelperKind
    target_type: str = Field(min_length=1, max_length=64)
    target_id: UUID
    question: str = Field(min_length=1, max_length=100_000)
    stream: bool = False


class ContinueTurnRequest(BaseModel):
    """Body for ``POST /runs/{run_id}/turns/`` — follow-up turn."""

    question: str = Field(min_length=1, max_length=100_000)
    stream: bool = False


class UpdateStatusRequest(BaseModel):
    """Body for ``PATCH /runs/{run_id}/`` — terminal status transition.

    The service rejects ``IN_PROGRESS`` (only terminal statuses transition)
    and rejects repeat transitions, so the wire model accepts every value
    and lets the service do the policy enforcement.
    """

    status: HelperRunStatus


class HelperRunPublic(BaseModel):
    """One row of ``help_assistant_runs`` exposed to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: HelperKind
    assistant_id: UUID | None
    target_type: str
    target_id: UUID
    session_id: UUID
    actor_user_id: UUID | None
    status: HelperRunStatus
    completed_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class HelperRunResponsePublic(BaseModel):
    """Non-stream response body for the helper-run ask paths.

    ``answer`` is the final completion text; ``references`` are the
    info-blob chunks pulled into the helper assistant's prompt. ``run``
    carries enough context for the modal to drive its Apply / Abandon
    buttons (id + status).
    """

    run: HelperRunPublic
    answer: str
    references: list[InfoBlobAskAssistantPublic]
    # Set on a streamed event when the completion provider fails mid-stream
    # (the router converts an ERROR chunk / exception into a terminal error
    # event). The client surfaces it and marks the run failed.
    error: str | None = None


class AvailabilityResponse(BaseModel):
    """Cheap read-only signal for the prompt-guide toolbar button (PRD §5, §10).

    Returned by ``GET /help-assistants/availability``. The frontend hides
    the toolbar button whenever ``available`` is False; ``disabled_reason``
    lets the admin UX surface the underlying cause without parsing a
    human-readable message.

    The helper assistant id is intentionally absent — the modal never
    needs it (helper resolution is server-side per :class:`StartRunRequest`)
    and exposing it here would defeat the "helper assistants are hidden
    from every listing" invariant.
    """

    available: bool
    disabled_reason: (
        Literal[
            "no_assignment",
            "role_disabled",
            "role_not_visible",
            "no_completion_model",
            "no_edit_rights",
        ]
        | None
    ) = None

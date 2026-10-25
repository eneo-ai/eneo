"""Dismissing a suggestion of a flow, and taking a dismissal back.

A dismissal is the flow's, shared by everyone who edits it, and hides the
suggestion its fingerprint names from the flow's suggestions until the
premise of that suggestion changes. It changes nothing of the flow: not the
draft, its revision or what publishing checks. Both operations need edit
access to the flow, as reading and applying suggestions do, and write one
required audit entry on the flow in the caller's transaction, so the change
and its entry are saved together or not at all. The caller owns the
transaction.

What can be dismissed: a suggestion the draft proves (a static code) only
while the draft has it, which is checked against the draft's suggestions as
they are now; a suggestion only runs prove (``MEASURED_SUGGESTION_CODES``)
as the caller names it, since checking it would read the runs' evidence. A
fingerprint the draft's static suggestions have must come with their code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from fastapi import Request

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.api.flow_definition_access import require_flow_edit_access
from eneo.flows.application.flow_suggestion_service import list_flow_suggestions
from eneo.flows.domain.flow import Flow
from eneo.flows.domain.flow_suggestion_dismissal import (
    FlowSuggestionDismissal,
    split_dismissed,
)
from eneo.flows.domain.flow_suggestion_model import (
    MEASURED_SUGGESTION_CODES,
    FlowSuggestion,
    FlowSuggestionCode,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import ConflictException, NotFoundException

NOT_DISMISSED_MESSAGE = "This suggestion is not dismissed."


async def dismiss_flow_suggestion(
    id: UUID,
    request: Request,
    *,
    fingerprint: str,
    code: FlowSuggestionCode,
    container: Container,
) -> FlowSuggestionDismissal:
    """Dismiss the suggestion ``fingerprint`` of the flow ``id``.

    A suggestion already dismissed answers with its dismissal as it was
    made, and writes nothing. Refused with ``409 flow_suggestion_stale``
    when ``code`` is a static code and the draft does not have that
    suggestion, or when the fingerprint is one of the draft's static
    suggestions under another code."""

    access = await require_flow_edit_access(request, container, flow_id=id)
    flow = access.flow
    flow_id = flow.require_persisted_id()
    await _require_dismissable(container, flow, fingerprint=fingerprint, code=code)
    user = container.user()
    dismissal, written = await container.flow_suggestion_dismissal_repo().add(
        flow_id=flow_id,
        tenant_id=user.tenant_id,
        fingerprint=fingerprint,
        code=code.value,
        dismissed_by=user.id,
    )
    if written:
        await _audit(
            container,
            flow,
            action=ActionType.FLOW_SUGGESTION_DISMISSED,
            dismissal=dismissal,
            description=f"Dismissed a suggestion ({dismissal.code}) on flow "
            f"'{flow.name}'",
        )
    return dismissal


async def restore_flow_suggestion(
    id: UUID,
    request: Request,
    *,
    fingerprint: str,
    container: Container,
) -> FlowSuggestionDismissal:
    """Take back the flow's dismissal of ``fingerprint``, so the suggestion
    is shown again while the draft has it; the dismissal it took back.
    ``404`` when the flow has no such dismissal."""

    access = await require_flow_edit_access(request, container, flow_id=id)
    flow = access.flow
    removed = await container.flow_suggestion_dismissal_repo().remove(
        flow_id=flow.require_persisted_id(),
        tenant_id=container.user().tenant_id,
        fingerprint=fingerprint,
    )
    if removed is None:
        raise NotFoundException(NOT_DISMISSED_MESSAGE)
    await _audit(
        container,
        flow,
        action=ActionType.FLOW_SUGGESTION_RESTORED,
        dismissal=removed,
        description=f"Restored a dismissed suggestion ({removed.code}) on flow "
        f"'{flow.name}'",
    )
    return removed


async def flow_suggestion_dismissals(
    container: Container, flow: Flow
) -> dict[str, FlowSuggestionDismissal]:
    """The flow's dismissals by fingerprint, tenant-scoped. The caller has
    decided that the user may read the flow's suggestions."""
    return await container.flow_suggestion_dismissal_repo().list_for_flow(
        flow_id=flow.require_persisted_id(), tenant_id=container.user().tenant_id
    )


async def shown_flow_suggestions(
    container: Container, flow: Flow, suggestions: Sequence[FlowSuggestion]
) -> tuple[FlowSuggestion, ...]:
    """``suggestions`` of ``flow`` without those its editors dismissed."""
    dismissals = await flow_suggestion_dismissals(container, flow)
    return split_dismissed(suggestions, dismissals).shown


async def _require_dismissable(
    container: Container,
    flow: Flow,
    *,
    fingerprint: str,
    code: FlowSuggestionCode,
) -> None:
    static = await list_flow_suggestions(container=container, flow=flow)
    listed = next((item for item in static if item.fingerprint == fingerprint), None)
    if listed is not None:
        if listed.code is code:
            return
    elif code in MEASURED_SUGGESTION_CODES:
        return
    raise ConflictException(
        "The draft no longer has this suggestion. Read the suggestions again.",
        code=FlowApiErrorCode.SUGGESTION_STALE.value,
        context={"fingerprint": fingerprint, "fingerprints": [fingerprint]},
    )


async def _audit(
    container: Container,
    flow: Flow,
    *,
    action: ActionType,
    dismissal: FlowSuggestionDismissal,
    description: str,
) -> None:
    user = container.user()
    flow_id = flow.require_persisted_id()
    extra: Mapping[str, object] = {
        "flow_id": str(flow_id),
        "suggestion_fingerprint": dismissal.fingerprint,
        "suggestion_code": dismissal.code,
    }
    await container.audit_service().log(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.FLOW,
        entity_id=flow_id,
        description=description,
        metadata=AuditMetadata.standard(actor=user, target=flow, extra=extra),
        required=True,
    )


__all__ = [
    "NOT_DISMISSED_MESSAGE",
    "dismiss_flow_suggestion",
    "flow_suggestion_dismissals",
    "restore_flow_suggestion",
    "shown_flow_suggestions",
]

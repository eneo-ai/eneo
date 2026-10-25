from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query, Request, status

from eneo.audit.domain.action_types import ActionType
from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_authoring_router import (
    DRAFT_CHANGE_REFUSAL_EXAMPLES,
    FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION,
)
from eneo.flows.api.flow_definition_access import require_flow_edit_access
from eneo.flows.api.flow_suggestion_apply_models import (
    MAX_APPLIED_SUGGESTIONS,
    FlowSuggestionsAppliedPublic,
    FlowSuggestionsApplyRequest,
)
from eneo.flows.api.flow_suggestions_models import (
    FLOW_SUGGESTIONS_EXAMPLE,
    FlowSuggestionRunsPublic,
    FlowSuggestionsPublic,
)
from eneo.flows.application import flow_authoring_operations as authoring_operations
from eneo.flows.application import flow_suggestion_apply
from eneo.flows.application.flow_run_evidence_snapshot import (
    flow_run_evidence_snapshot_transaction,
)
from eneo.flows.application.flow_suggestion_service import (
    list_flow_suggestions,
    list_measured_flow_suggestions,
)
from eneo.flows.application.flow_trace_audit import (
    raise_flow_evidence_read_audit_unavailable,
)
from eneo.flows.domain.flow_suggestion_evidence import MAX_MEASURED_RUNS
from eneo.flows.flow_access_policy import (
    FlowApiAction,
    flow_action_access_reason,
    require_flow_action,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import AuditLoggingUnavailableException, ErrorCodes
from eneo.server.dependencies.container import (
    get_container_for_explicit_transaction,
)

router = APIRouter()

# Applying suggestions is an editor change: it commits in the route
# (`authoring_transaction`), so its audit entries are logged after the commit
# and a refused change logs none.
_AUTHORING_CONTAINER = get_container_for_explicit_transaction(
    with_user=True, with_module_user=True
)
# Reading suggestions owns its transaction too: a measured read commits its
# audit entry before the answer is sent.
_READ_CONTAINER = get_container_for_explicit_transaction(
    with_user=True, with_module_user=True
)

_SUGGESTION_STALE_EXAMPLE: dict[str, object] = {
    "summary": "The draft no longer has the suggestion",
    "value": {
        "message": (
            "The draft no longer has this suggestion. Read the suggestions again."
        ),
        "eneo_error_code": int(ErrorCodes.CONFLICT),
        "code": FlowApiErrorCode.SUGGESTION_STALE.value,
        "context": {
            "fingerprint": "9b2d3f1a" * 8,
            "fingerprints": ["9b2d3f1a" * 8],
        },
    },
}
_SUGGESTION_NOT_PATCHABLE_EXAMPLE: dict[str, object] = {
    "summary": "The suggestion has no fix that can be applied as it is",
    "value": {
        "message": (
            "This suggestion has no fix that can be applied as it is. Make the "
            "change it describes in the editor."
        ),
        "eneo_error_code": int(ErrorCodes.CONFLICT),
        "code": FlowApiErrorCode.SUGGESTION_NOT_PATCHABLE.value,
        "context": {
            "fingerprint": "9b2d3f1a" * 8,
            "suggestion_code": "whole_structured_read",
            "fix_kind": "assisted",
        },
    },
}


_SUGGESTIONS_DESCRIPTION = (
    "What the draft could do cheaper or simpler. By default it is judged from "
    "the saved definition alone: where a step's model receives the same "
    "earlier result twice (`duplicate_read`), takes more of the earlier "
    "results than it needs, carries data no later step reads, or relays a "
    "result another step could read directly. The reads are the ones publish "
    "and the runtime resolve, so a suggestion states what the definition "
    "proves and nothing it does not: no prompt is judged by a model and a "
    "read of a field next to a read of the whole result is reported as "
    "`contained` rather than guessed at.\n\n"
    f"With `runs` (1 to {MAX_MEASURED_RUNS}) the newest finished runs in which "
    "a step ran (completed, failed or cancelled) are measured as well: what a "
    "duplicate or an unused result cost in tokens per run (`impact.basis` "
    "`runs`, with the run count and the published version measured, and "
    "whether the step changed since), and three findings only runs show: "
    "`identical_inputs`, `context_headroom` and `format_fallback`. Measured "
    "suggestions come first, most tokens first. Only numbers are read from "
    "the runs (sizes, hashes, token counts and call reasons), never their "
    "content. Measuring needs the permission to view flow traces on top of "
    "editing the flow; runs whose evidence the caller may not see (another "
    "member's run, without the space role that shows it) are left out and "
    "counted in `runs.left_out`. A measured read writes one audit entry on "
    "the flow (`flow_evidence_viewed`) naming the runs it counted and how "
    "many it left out, and is refused with 503 when that entry cannot be "
    "written.\n\n"
    "Each suggestion names its steps, a `fingerprint` that is stable across "
    "unrelated edits and measurements, an `impact` and how it is acted on "
    "(`fix.kind`). Suggestions never block publishing and never change the "
    "flow: acting on one is a separate, explicit editor update. The answer "
    "judges `draft_revision`; read again after a save. It reads the prompts "
    "of the flow's assistants, so it needs the permission to edit the flow."
)


@router.get(
    "/{id}/suggestions/",
    response_model=FlowSuggestionsPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_suggestions",
    summary="Get Flow Suggestions",
    description=_SUGGESTIONS_DESCRIPTION,
    responses={
        200: {
            "description": "The draft's suggestions, possibly none.",
            "content": {"application/json": {"example": FLOW_SUGGESTIONS_EXAMPLE}},
        },
        403: error_response(
            description=(
                "Forbidden. Machine-readable codes include `insufficient_scope` "
                "when the API key space scope does not match the flow, "
                "`insufficient_space_permission` when the caller may not edit "
                "flows in the space, `flow_owner_required` when another "
                "member owns the draft, and `insufficient_tenant_permission` "
                "when `runs` is above 0 and the caller may not view flow "
                "traces."
            ),
            message="You do not have permission to edit flows in this space.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
        ),
        503: error_response(
            description=(
                "The audit entry of a measured read could not be written; "
                "nothing is returned."
            ),
            message="Evidence audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def get_flow_suggestions(
    id: Annotated[UUID, Path(description="Identifier of the draft flow.")],
    request: Request,
    runs: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_MEASURED_RUNS,
            description=(
                "How many of the newest finished runs to measure; 0, the "
                "default, judges the definition alone. Above 0 it needs the "
                "permission to view flow traces."
            ),
        ),
    ] = 0,
    container: Container = Depends(_READ_CONTAINER),
) -> FlowSuggestionsPublic:
    # The audit entry of a measured read commits with the read, before the
    # answer is sent, as for the evidence routes.
    audited_flow: UUID | None = None
    try:
        async with flow_run_evidence_snapshot_transaction(container):
            answer = await read_flow_suggestions_answer(
                id=id, request=request, runs=runs, container=container
            )
            audited_flow = id if answer.runs is not None else None
    except AuditLoggingUnavailableException:
        raise
    except Exception as exc:
        if audited_flow is not None:
            raise_flow_evidence_read_audit_unavailable(
                user=container.user(),
                flow_id=audited_flow,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                cause=exc,
            )
        raise
    return answer


async def read_flow_suggestions_answer(
    *, id: UUID, request: Request, runs: int, container: Container
) -> FlowSuggestionsPublic:
    """The answer of ``GET .../suggestions/`` in the caller's transaction:
    edit access to the flow, and with ``runs`` above 0 the trace permission,
    then the suggestions, measured over ``runs`` runs when asked."""
    access = await require_flow_edit_access(request, container, flow_id=id)
    flow = access.flow
    if runs <= 0:
        suggestions = await list_flow_suggestions(container=container, flow=flow)
        measured_runs = None
    else:
        require_flow_action(container.user(), FlowApiAction.TRACE_VIEW)
        suggestions, measured = await list_measured_flow_suggestions(
            container=container, flow=flow, runs=runs
        )
        measured_runs = FlowSuggestionRunsPublic(
            requested=measured.requested,
            counted=len(measured.counted_run_ids),
            left_out=measured.left_out,
        )
    return FlowSuggestionsPublic.from_suggestions(
        flow_id=flow.require_persisted_id(),
        draft_revision=flow.draft_revision,
        suggestions=suggestions,
        runs=measured_runs,
    )


@router.post(
    "/{id}/suggestions/apply/",
    response_model=FlowSuggestionsAppliedPublic,
    status_code=status.HTTP_200_OK,
    operation_id="apply_flow_suggestions",
    summary="Apply Flow Suggestions",
    description=(
        "Apply the fixes of one or more suggestions of the draft, all of them "
        "or none: for each, the editor update in its `fix.patch`. One fix is "
        f"a list of one; at most {MAX_APPLIED_SUGGESTIONS}. The batch is "
        "fenced on `expected_revision` and the suggestions are computed again "
        "on the draft as it is saved, so it is made only while they still "
        "hold: a fingerprint the draft does not have (a change since it was "
        "read fixed it or removed what it was about) refuses the batch with "
        "`flow_suggestion_stale`, and one whose `fix.kind` is `assisted` or "
        "`advice` with `flow_suggestion_not_patchable`. The fixes are applied "
        "in the order the suggestions are listed, and after each one the "
        "suggestions are computed again, so two fixes of the same prompt both "
        "land; a suggestion an earlier fix of the batch made go away is "
        "skipped and listed under `skipped`. Each fix is the same change "
        "`PATCH /api/v1/flows/{id}/editor/` makes with that body: the same "
        "revision fence, reads that follow a moved or removed step, a copy "
        "for a step whose assistant other steps share, classification, and "
        "audit entries logged once the batch has saved, which here also name "
        "the suggestion (`origin: suggestion`, `suggestion_code`, "
        "`suggestion_fingerprint`). Each fix is a draft revision of its own; "
        "`flow.draft_revision` is the one after the last. "
        "It needs the permission to edit the flow."
    ),
    responses={
        400: error_response(
            description=(
                "The draft moved on since `expected_revision` "
                "(`stale_revision`), the flow is published "
                "(`flow_unpublish_required`), or the editor update refuses a "
                "fix, with the codes `PATCH .../editor/` documents. Nothing "
                "of the batch is saved."
            ),
            examples=DRAFT_CHANGE_REFUSAL_EXAMPLES,
        ),
        403: error_response(
            description=FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to edit flows in this space.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
        ),
        409: error_response(
            description=(
                "The draft does not have a suggestion the batch names "
                "(`flow_suggestion_stale`, with the `fingerprints` it lacks in "
                "`context`), or the fix of one is not a patch "
                "(`flow_suggestion_not_patchable`, with its `fingerprint`, "
                "`suggestion_code` and `fix_kind` in `context`). Nothing of "
                "the batch is saved."
            ),
            examples={
                FlowApiErrorCode.SUGGESTION_STALE.value: _SUGGESTION_STALE_EXAMPLE,
                FlowApiErrorCode.SUGGESTION_NOT_PATCHABLE.value: (
                    _SUGGESTION_NOT_PATCHABLE_EXAMPLE
                ),
            },
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def apply_flow_suggestions(
    id: Annotated[UUID, Path(description="Identifier of the draft flow.")],
    request: Request,
    body: Annotated[FlowSuggestionsApplyRequest, Body()],
    container: Container = Depends(_AUTHORING_CONTAINER),
) -> FlowSuggestionsAppliedPublic:
    async with authoring_operations.authoring_transaction(container):
        result = await flow_suggestion_apply.apply_flow_suggestions(
            id,
            request,
            fingerprints=body.fingerprints,
            expected_revision=body.expected_revision,
            container=container,
        )
    return FlowSuggestionsAppliedPublic(
        flow=result.flow, applied=list(result.applied), skipped=list(result.skipped)
    )


__all__ = ["read_flow_suggestions_answer", "router"]

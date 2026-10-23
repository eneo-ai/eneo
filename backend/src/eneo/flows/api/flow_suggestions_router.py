from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_definition_access import require_flow_edit_access
from eneo.flows.api.flow_suggestions_models import (
    FLOW_SUGGESTIONS_EXAMPLE,
    FlowSuggestionsPublic,
)
from eneo.flows.application.flow_suggestion_service import list_flow_suggestions
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import get_container

router = APIRouter()


@router.get(
    "/{id}/suggestions/",
    response_model=FlowSuggestionsPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_suggestions",
    summary="Get Flow Suggestions",
    description=(
        "What the draft could do cheaper or simpler, judged from the saved "
        "definition: where a step's model receives the same earlier result "
        "twice (`duplicate_read`), through its input (`previous_step`, "
        "`all_previous_steps`, a question or source references) and a read of "
        "the same step in its assistant's prompt, or twice in one of them. The "
        "reads are the ones publish and the runtime resolve, so a suggestion "
        "states what the definition proves and nothing it does not: no prompt "
        "is judged by a model, no run content is read, and a read of a field "
        "next to a read of the whole result is reported as `contained` rather "
        "than guessed at. Each suggestion names its steps, a `fingerprint` "
        "that is stable across unrelated edits, an `impact` level and how it "
        "is acted on (`fix.kind`). Suggestions never block publishing and "
        "never change the flow: acting on one is a separate, explicit editor "
        "update. The answer judges `draft_revision`; read again after a save. "
        "It reads the prompts of the flow's assistants, so it needs the "
        "permission to edit the flow."
    ),
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
                "flows in the space, and `flow_owner_required` when another "
                "member owns the draft."
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
    container: Container = Depends(
        get_container(with_user=True, with_module_user=True)
    ),
):
    access = await require_flow_edit_access(request, container, flow_id=id)
    flow = access.flow
    suggestions = await list_flow_suggestions(container=container, flow=flow)
    return FlowSuggestionsPublic.from_suggestions(
        flow_id=flow.require_persisted_id(),
        draft_revision=flow.draft_revision,
        suggestions=suggestions,
    )


__all__ = ["router"]

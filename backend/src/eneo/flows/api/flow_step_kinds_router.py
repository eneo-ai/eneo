from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_definition_access import (
    require_flow_current_definition_access,
)
from eneo.flows.api.flow_step_kinds_models import (
    FLOW_STEP_KINDS_EXAMPLE,
    FlowStepKindsPublic,
)
from eneo.flows.application.flow_step_kinds import step_kind_answer
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, ErrorCodes, NotFoundException
from eneo.server.dependencies.container import get_container

router = APIRouter()


@router.get(
    "/{id}/step-kinds/",
    response_model=FlowStepKindsPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_step_kinds",
    summary="Get Allowed Step Kinds",
    description=(
        "Which kinds of step the draft allows at each place, and why it refuses "
        "the others: for each place a step can be added (before every step and "
        "after the last) and for each saved step turned to another kind. Each "
        "answer is the draft save's own: the kind's change is built as "
        "`PATCH /flows/{id}/editor/` makes it and judged by that save's "
        "placement, read following and step rules, so a kind is `allowed` "
        "exactly when the save accepts it and `refusals` are the errors the save "
        "gives. The change is in the answer: the kind's starting `configuration`, "
        "the saved steps it edits too (a step added first takes the run's input "
        "over from the step that was first) and whether it turns transcription "
        "on. Not judged: the new step's name; the URL of `fetch_http` and "
        "`send_http` and the tool of `tool`, judged as entered and valid; and "
        "the checks a save makes against the space (assistants, security "
        "classification, the transcription service). Every change to a "
        "published flow is refused with `flow_unpublish_required`. A read names "
        "the places it asks about, `position`, `step_id` or both: each place "
        "judges the whole draft once per kind, so every place at once would "
        "grow with the square of the step count. It needs read access to the "
        "draft."
    ),
    responses={
        200: {
            "description": "The kinds at each place, with the save's refusals.",
            "content": {"application/json": {"example": FLOW_STEP_KINDS_EXAMPLE}},
        },
        400: error_response(
            description=(
                "Neither `position` nor `step_id` names a place, or `position` "
                "is past the place after the last step."
            ),
            message="position must be between 1 and 3.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
        ),
        403: error_response(
            description=(
                "Forbidden. Machine-readable codes include `insufficient_scope` "
                "when the API key space scope does not match the flow, "
                "`flow_service_key_admin_required` when a non-admin service-key "
                "principal reads the draft, and `insufficient_space_permission` "
                "when the caller cannot read the flow."
            ),
            message="You do not have permission to access this flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        ),
        404: error_response(
            description="The flow, or the step `step_id` names, is not found.",
            message="Step not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.VIEW),
)
async def get_flow_step_kinds(
    id: Annotated[UUID, Path(description="Identifier of the draft flow.")],
    request: Request,
    position: Annotated[
        int | None,
        Query(
            ge=1,
            description=(
                "The insertion place to answer (1 is first, one past the last "
                "step is last). A read names this, `step_id` or both."
            ),
        ),
    ] = None,
    step_id: Annotated[
        UUID | None,
        Query(
            description=(
                "The saved step to answer, turned to each kind. A read names "
                "this, `position` or both."
            ),
        ),
    ] = None,
    container: Container = Depends(
        get_container(with_user=True, with_module_user=True)
    ),
):
    if position is None and step_id is None:
        raise BadRequestException("position or step_id must name the place to answer.")
    access = await require_flow_current_definition_access(
        request, container, flow_id=id
    )
    flow = access.flow
    if position is not None and position > len(flow.steps) + 1:
        raise BadRequestException(
            f"position must be between 1 and {len(flow.steps) + 1}."
        )
    if step_id is not None and all(step.id != step_id for step in flow.steps):
        raise NotFoundException("Step not found.")
    stored = await container.flow_service().get_flow_assistant_prompts(flow)
    # Pure computation over the draft; off the event loop for large flows.
    answer = await asyncio.to_thread(
        step_kind_answer,
        flow,
        prompts={assistant_id: prompt.text for assistant_id, prompt in stored.items()},
        positions=[] if position is None else [position],
        step_ids=[] if step_id is None else [step_id],
    )
    return FlowStepKindsPublic.from_answer(
        flow_id=flow.require_persisted_id(),
        draft_revision=flow.draft_revision,
        answer=answer,
    )


__all__ = ["router"]

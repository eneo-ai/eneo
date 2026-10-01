from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_assistant_router import (
    flow_assistant_update_command,
    require_flow_assistant_access,
)
from eneo.flows.api.flow_request_body import body_too_large, capped_body_route_class
from eneo.flows.api.flow_security_classification_models import (
    FLOW_SECURITY_CLASSIFICATION_PREVIEW_EXAMPLE,
    FlowSecurityClassificationPreviewPublic,
    FlowSecurityClassificationPreviewRequest,
)
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_authoring_spec import (
    MAX_FLOW_AUTHORING_REQUEST_BYTES,
    MAX_FLOW_AUTHORING_STEP_BYTES,
    MAX_FLOW_AUTHORING_STEPS,
)
from eneo.flows.flow_validators import validate_step_count
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes, FileTooLargeException
from eneo.server.dependencies.container import get_container

_BODY_TOO_LARGE_MESSAGE = (
    "The request is larger than the {max_bytes} bytes a security "
    "classification preview accepts. Send fewer or shorter steps."
)


def _body_too_large(max_bytes: int) -> FileTooLargeException:
    return body_too_large(
        max_bytes, _BODY_TOO_LARGE_MESSAGE.format(max_bytes=max_bytes)
    )


_CappedBodyRoute = capped_body_route_class(
    MAX_FLOW_AUTHORING_REQUEST_BYTES,
    message=_BODY_TOO_LARGE_MESSAGE.format(max_bytes=MAX_FLOW_AUTHORING_REQUEST_BYTES),
)


router = APIRouter(route_class=_CappedBodyRoute)


@router.post(
    "/{id}/security-classification/preview",
    response_model=FlowSecurityClassificationPreviewPublic,
    status_code=status.HTTP_200_OK,
    operation_id="preview_flow_security_classification",
    summary="Preview Security Classification",
    description=(
        "Explain, step by step, what the security classification rule makes of "
        "the submitted editor state: the level each step's inputs carry, which "
        "earlier steps it reads, the level its model must clear, the models of "
        "the space that qualify, the level its output carries, the lowest output "
        "override the rule accepts, and the violation a save would be refused "
        "with. `steps` and `assistants` are the editor's unsaved state in the "
        "shape a flow update and an assistant update accept; omit them to "
        "explain the saved draft. The rule is the one a save applies, so a "
        "candidate reported without a violation is not refused for "
        "classification. This endpoint does not save the flow or any assistant "
        "and writes no audit record. It reads the flow's assistants, so it needs "
        "the same permission as reading them: editing flows in the space."
    ),
    responses={
        200: {
            "description": (
                "One explanation per step. Levels are null and no step has a "
                "violation while security classifications are off."
            ),
            "content": {
                "application/json": {
                    "example": FLOW_SECURITY_CLASSIFICATION_PREVIEW_EXAMPLE
                }
            },
        },
        400: error_response(
            description=(
                "The candidate state cannot be evaluated: a step names an "
                "assistant the flow does not manage, an assistant change "
                "names an assistant no candidate step uses, or the steps, "
                "submitted or saved, are more than a flow can have "
                "(`flow_step_limit_exceeded`, with `step_count` and "
                "`max_steps` in the context)."
            ),
            message=(
                "One or more steps reference assistants outside the selected "
                "space or tenant."
            ),
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description="Caller lacks permission to edit flows in this space.",
            message="You do not have permission to edit flows in this space.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        413: error_response(
            description=(
                "The request body is larger than a preview accepts "
                f"({MAX_FLOW_AUTHORING_REQUEST_BYTES} bytes: "
                f"{MAX_FLOW_AUTHORING_STEP_BYTES} for each of the "
                f"{MAX_FLOW_AUTHORING_STEPS} steps a flow can have). It is "
                "refused before the body is parsed."
            ),
            message=_body_too_large(MAX_FLOW_AUTHORING_REQUEST_BYTES).args[0],
            eneo_error_code=ErrorCodes.FILE_TOO_LARGE,
            code=FlowApiErrorCode.REQUEST_BODY_TOO_LARGE,
            context={"max_bytes": MAX_FLOW_AUTHORING_REQUEST_BYTES},
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def preview_flow_security_classification(
    id: Annotated[UUID, Path(description="Identifier of the draft flow to explain.")],
    request: Request,
    body: FlowSecurityClassificationPreviewRequest,
    container: Container = Depends(
        get_container(with_user=True, with_module_user=True)
    ),
):
    # The result is derived from the flow's assistants (prompt, model,
    # knowledge), which are readable only with the permission to edit the flow.
    await require_flow_assistant_access(request, container, flow_id=id)
    # Before any step is converted: the canonical refusal for an oversized list.
    if body.steps is not None:
        validate_step_count(len(body.steps))
    assembler = FlowAssembler()
    explanations = await container.flow_service().preview_step_security_classification(
        flow_id=id,
        steps=(
            None
            if body.steps is None
            else [assembler.to_domain_step_for_update(step) for step in body.steps]
        ),
        assistant_updates={
            candidate.assistant_id: flow_assistant_update_command(candidate.update)
            for candidate in body.assistants
        },
    )
    return FlowSecurityClassificationPreviewPublic.from_explanations(explanations)


__all__ = ["router"]

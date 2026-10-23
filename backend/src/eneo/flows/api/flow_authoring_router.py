from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_definition_access import (
    SERVICE_KEY_ADMIN_REQUIRED_MESSAGE,
    flow_permissions,
    require_flow_delete_access,
    require_flow_published_runtime_access,
)
from eneo.flows.api.flow_models import (
    PAGINATED_FLOW_SPARSE_RESPONSE_EXAMPLE,
    FlowCreateRequest,
    FlowEditorUpdateRequest,
    FlowPublic,
    FlowSparsePublic,
    FlowUpdateRequest,
)
from eneo.flows.api.flow_runtime_paths import (
    PUBLISHED_FLOW_RUNTIME_PATH,
    FlowRuntimePublic,
)
from eneo.flows.application import flow_authoring_operations as authoring_operations
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import (
    FlowBadRequestException,
    FlowUnauthorizedException,
)
from eneo.flows.principal import FlowPrincipal
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    ErrorCodes,
)
from eneo.main.models import OffsetPaginatedResponse
from eneo.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)

router = APIRouter()

# Mutations commit before the response is sent. With the default request scope
# the transaction closes after the body has gone out, so a client that creates
# a flow and immediately addresses it (the editor, the authoring chat) can
# be told the flow does not exist.
_MUTATING_CONTAINER = get_container(
    with_user=True, with_module_user=True, transaction_scope="function"
)
# An authoring change commits in the route (`authoring_transaction`), so its
# audit entries are logged after the commit and a refused change logs none.
_AUTHORING_CONTAINER = get_container_for_explicit_transaction(
    with_user=True, with_module_user=True
)

_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Machine-readable codes include `insufficient_scope` when the API key "
    "space scope does not match the flow, `insufficient_space_permission` when the "
    "caller lacks the required shared-space role, and the "
    "fail-closed `flow_service_key_principal_not_supported` when a service-key "
    "principal calls flow authoring endpoints that require a user principal."
)

_FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Machine-readable codes include `insufficient_scope` when the API key "
    "space scope does not match the flow, `insufficient_space_permission` when the "
    "caller lacks the required shared-space role, `flow_owner_required` when the "
    "caller is not allowed to override another member's draft, and the current "
    "fail-closed `flow_service_key_principal_not_supported` when a service-key "
    "principal calls flow authoring endpoints before first-class support lands."
)

_FLOW_DRAFT_OWNERSHIP_DESCRIPTION = (
    "Draft ownership stays with the draft owner in the current backend policy. "
    "Space admins can manage shared space resources, but overriding another member's "
    "draft still requires the draft owner, a space owner, or a tenant admin."
)

_FLOW_SERVICE_KEY_DISCOVERY_DESCRIPTION = (
    "Service-key principals may use this endpoint only for published-flow discovery in "
    "their scoped space, and must send its `space_id`: a key has no space memberships "
    "to list. Service-key webapps should use the returned ids with "
    "`GET /api/v1/flows/{id}/published/` and the runtime paths from that response; "
    "draft authoring still requires a user principal."
)

_FLOW_PUBLISHED_RUNTIME_DESCRIPTION = (
    "Return the runtime-safe published projection of a flow. "
    "This endpoint is intended for runtime consumers, including service-key principals, "
    "and does not expose the current draft/current-definition authoring view. Treat it "
    "as the entry point for external webapps that already know a published flow id."
)

_PUBLISHED_FLOW_RUNTIME_OPERATION_ID = "get_published_flow_runtime"
_FLOW_NAME_TAKEN_MESSAGE = "A flow with this name already exists in this space."
_STEP_READ_LOST_PRODUCER_EXAMPLE: dict[str, object] = {
    "summary": "A step reads a step the change removes",
    "value": {
        "message": (
            "Write (step 3) reads a step this change removes: step 2 in its "
            "prompt. Change that read first, or keep each step before the "
            "steps that read it."
        ),
        "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
        "code": FlowApiErrorCode.STEP_READ_LOST_PRODUCER.value,
        "context": {
            "step_id": "00000000-0000-0000-0000-000000000103",
            "step_order": 3,
            "site": "prompt",
            "reads_step": 2,
            "reason": "producer_removed",
        },
    },
}
_STEP_READ_LOST_PRODUCER_DESCRIPTION = (
    "a change would make a step read another step than it reads now "
    "(`flow_step_read_lost_producer`). Its `context` names the reading step "
    "(`step_id`, `step_order`), where the read is (`site`), the saved order of "
    "the step it reads (`reads_step`, with `reads_name` for a read by step "
    "name) and `reason`: `producer_removed` (the change removes that step), "
    "`producer_moved_after_reader` (it moves that step to or after the "
    "reader), `reader_moved_before_producer` (it moves the reader to or before "
    "that step), `producer_renamed` (the step loses the name the read uses, "
    "or another step takes it) or `would_read_another_step` (a read that "
    "named no step it could read would come to name one)"
)
_FORM_FIELD_REFUSALS_DESCRIPTION = (
    "A saved run form field the new `metadata_json.form_schema` drops, and "
    "`form_field_renames` does not rename, is refused with "
    "`flow_form_field_still_read` while a step reads it; `context.readers` "
    "lists each read (`field`, `step_id`, `step_order`, `site`). A rename the "
    "forms do not describe is refused with `flow_form_field_rename_invalid` "
    "(`context`: `from`, `to`, `problem`). A published flow is refused with "
    "`flow_unpublish_required`."
)
_FORM_FIELD_STILL_READ_EXAMPLE: dict[str, object] = {
    "summary": "A step still reads the form field the change removes",
    "value": {
        "message": (
            "This change removes the form field 'kommun', which steps still "
            "read: Write (step 3) reads 'kommun' in its prompt. Change those "
            "reads first, or rename the field with form_field_renames so they "
            "follow it."
        ),
        "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
        "code": FlowApiErrorCode.FORM_FIELD_STILL_READ.value,
        "context": {
            "fields": ["kommun"],
            "readers": [
                {
                    "field": "kommun",
                    "step_id": "00000000-0000-0000-0000-000000000103",
                    "step_order": 3,
                    "site": "prompt",
                }
            ],
        },
    },
}
_FORM_FIELD_RENAME_INVALID_EXAMPLE: dict[str, object] = {
    "summary": "form_field_renames names a field the saved form does not have",
    "value": {
        "message": (
            "form_field_renames renames 'kommunn' to 'ort', which the form does "
            "not allow (unknown_field). Rename each saved field once, to its "
            "name in metadata_json.form_schema."
        ),
        "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
        "code": FlowApiErrorCode.FORM_FIELD_RENAME_INVALID.value,
        "context": {"from": "kommunn", "to": "ort", "problem": "unknown_field"},
    },
}
_UNPUBLISH_REQUIRED_EXAMPLE: dict[str, object] = {
    "summary": "The flow is published",
    "value": {
        "message": "Cannot mutate a published flow. Unpublish first.",
        "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
        "code": FlowApiErrorCode.UNPUBLISH_REQUIRED.value,
    },
}
_STALE_REVISION_EXAMPLE: dict[str, object] = {
    "summary": "The draft changed since it was read",
    "value": {
        "message": "The flow draft changed since it was read.",
        "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
        "code": FlowApiErrorCode.STALE_REVISION.value,
    },
}
_DRAFT_CHANGE_REFUSAL_EXAMPLES: dict[str, dict[str, object]] = {
    FlowApiErrorCode.STALE_REVISION.value: _STALE_REVISION_EXAMPLE,
    FlowApiErrorCode.STEP_READ_LOST_PRODUCER.value: _STEP_READ_LOST_PRODUCER_EXAMPLE,
    FlowApiErrorCode.FORM_FIELD_STILL_READ.value: _FORM_FIELD_STILL_READ_EXAMPLE,
    FlowApiErrorCode.FORM_FIELD_RENAME_INVALID.value: _FORM_FIELD_RENAME_INVALID_EXAMPLE,
    FlowApiErrorCode.UNPUBLISH_REQUIRED.value: _UNPUBLISH_REQUIRED_EXAMPLE,
}


_FLOW_NAME_TAKEN_RESPONSE = error_response(
    description="Another active flow in the space already has this name.",
    message=_FLOW_NAME_TAKEN_MESSAGE,
    eneo_error_code=ErrorCodes.CONFLICT,
    code=FlowApiErrorCode.FLOW_NAME_TAKEN,
)


@router.post(
    "/",
    response_model=FlowPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow",
    summary="Create Flow",
    description=(
        "Create a new, empty draft flow inside a space. Each step runs an "
        "assistant the flow owns, so steps follow once the flow exists: create "
        "each step's assistant with `POST /api/v1/flows/{id}/assistants/`, then "
        "send the steps with `PATCH /api/v1/flows/{id}/`. "
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description="The submitted draft flow definition is invalid.",
            message="Flow definition is invalid.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
        ),
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
        ),
        409: _FLOW_NAME_TAKEN_RESPONSE,
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def create_flow(
    request: Request,
    flow_in: FlowCreateRequest,
    container: Container = Depends(_AUTHORING_CONTAINER),
):
    async with authoring_operations.authoring_transaction(container):
        return await authoring_operations.create_flow(
            request=request, container=container, flow_in=flow_in
        )


@router.get(
    "/",
    response_model=OffsetPaginatedResponse[FlowSparsePublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flows",
    summary="List Flows",
    description=(
        "List the flows the caller can see, with pagination-friendly sparse metadata. "
        "With `space_id` the list covers that space. Without it the list covers every "
        "space the signed-in user belongs to: their personal space, spaces shared with "
        "them directly or through a group, and the organization space when their role "
        "there shows flows. A space-scoped API key narrows the list to its space. "
        "Drafts appear only in spaces where the caller may edit flows, and "
        "`published_only=true` returns published flows only, which is what clients that "
        "run flows need. Seeing a flow does not mean the caller may run it or that it is "
        "ready to run. Items are ordered oldest first. "
        "The `count` field in the paginated response reports the number of items returned "
        "in the current page, not the total number of matching flows across all pages. "
        "`has_more` reports whether another page exists after this offset window. "
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION} {_FLOW_SERVICE_KEY_DISCOVERY_DESCRIPTION}"
    ),
    responses={
        200: {
            "description": (
                "Sparse flow page. `items` contains the returned page only; "
                "`count` is the number of returned items and `has_more` tells "
                "clients whether to request the next offset window."
            ),
            "content": {
                "application/json": {
                    "example": PAGINATED_FLOW_SPARSE_RESPONSE_EXAMPLE,
                }
            },
        },
        400: error_response(
            description=(
                "A service key listed flows without `space_id`. A key has no space "
                "memberships, so it names the space it is scoped to."
            ),
            message="Service keys must name the space to list flows from with space_id.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.SERVICE_KEY_SPACE_ID_REQUIRED,
        ),
        403: error_response(
            description=_FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.VIEW),
)
async def list_flows(
    request: Request,
    space_id: Annotated[
        UUID | None,
        Query(
            description=(
                "Only return flows in this space. Omit it to list the flows of every "
                "space the signed-in user belongs to; service keys must send it."
            ),
        ),
    ] = None,
    published_only: Annotated[
        bool,
        Query(
            description=(
                "Only return published flows, for clients that run flows rather "
                "than edit them."
            ),
        ),
    ] = False,
    limit: int = Query(
        default=50, ge=1, le=200, description="Maximum number of flows to return."
    ),
    offset: int = Query(
        default=0, ge=0, description="Number of flows to skip before returning results."
    ),
    container: Container = Depends(
        get_container(with_user=True, with_module_user=True)
    ),
):
    service_key_principal = FlowPrincipal.from_user(container.user()).is_service_key
    if space_id is not None:
        access_context = await flow_access_context.resolve_space_access_context(
            request,
            container,
            space_id=space_id,
            required_access=FlowApiAction.VIEW,
            scope_mismatch_message="API key space scope does not match requested space.",
            allow_service_key_principals=True,
        )
        if not access_context.actor.can_read_flows():
            raise FlowUnauthorizedException(
                "You do not have permission to access flows in this space.",
                code=AccessDenialCode.INSUFFICIENT_SPACE_PERMISSION,
                context={"auth_layer": "space_membership"},
            )
        spaces = {space_id: access_context.actor}
    elif service_key_principal:
        raise FlowBadRequestException(
            "Service keys must name the space to list flows from with space_id.",
            code=FlowApiErrorCode.SERVICE_KEY_SPACE_ID_REQUIRED,
        )
    else:
        spaces = await flow_access_context.resolve_member_flow_spaces(
            request, container
        )

    drafts_visible = not (published_only or service_key_principal)
    assembler = FlowAssembler()
    flows = await container.flow_service().list_flows(
        space_ids=list(spaces),
        draft_space_ids=[
            listed_space_id
            for listed_space_id, actor in spaces.items()
            if drafts_visible and actor.can_edit_flows()
        ],
        limit=limit + 1,
        offset=offset,
    )
    page_items = flows[:limit]
    scope_filter = flow_access_context.get_scope_filter(request)
    return {
        "count": len(page_items),
        "items": [
            assembler.to_sparse_public(
                flow,
                permissions=flow_permissions(
                    container,
                    flow=flow,
                    actor=spaces.get(flow.space_id),
                    scope_filter=scope_filter,
                ),
            )
            for flow in page_items
        ],
        "has_more": len(flows) > limit,
    }


@router.get(
    "/{id}/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow",
    summary="Get Flow",
    description=(
        "Return the full current draft representation of a flow, including all configured "
        f"steps and metadata. {_FLOW_DRAFT_OWNERSHIP_DESCRIPTION} "
        "Admin service-key principals may read the current draft definition when their "
        "scope covers the flow. Read and write service-key clients should call "
        "`/api/v1/flows/{id}/published/` for runtime-safe published projections and "
        "runtime paths."
    ),
    responses={
        403: error_response(
            description=(
                "Forbidden. Machine-readable codes include `insufficient_scope` when the "
                "API key space scope does not match the flow, "
                "`flow_service_key_admin_required` when a non-admin service-key principal "
                "calls the current draft definition endpoint, and "
                "`insufficient_space_permission` when the caller cannot read the flow."
            ),
            examples={
                AccessDenialCode.INSUFFICIENT_SCOPE.value: {
                    "summary": "API key scope mismatch",
                    "value": {
                        "message": "API key space scope does not match requested flow.",
                        "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
                        "code": AccessDenialCode.INSUFFICIENT_SCOPE.value,
                        "context": {"auth_layer": "api_key_scope"},
                    },
                },
                FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED.value: {
                    "summary": "Non-admin service-key principal called current draft endpoint",
                    "value": {
                        "message": SERVICE_KEY_ADMIN_REQUIRED_MESSAGE,
                        "eneo_error_code": int(ErrorCodes.UNAUTHORIZED),
                        "code": FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED.value,
                        "context": {
                            "auth_layer": "service_key_principal",
                            "capability": "view_current_definition",
                            "required_role": "admin",
                            "runtime_endpoint_hint": {
                                "key": "published_flow_runtime",
                                "description": (
                                    "Use the published runtime projection for "
                                    "service-key Flow clients."
                                ),
                                "endpoint_template": "/api/v1/flows/{id}/published/",
                            },
                        },
                    },
                },
            },
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
    reason=flow_action_access_reason(FlowApiAction.VIEW),
)
async def get_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to return.")
    ],
    request: Request,
    container: Container = Depends(
        get_container(with_user=True, with_module_user=True)
    ),
):
    return await authoring_operations.get_flow(
        id=id, request=request, container=container
    )


@router.get(
    PUBLISHED_FLOW_RUNTIME_PATH,
    response_model=FlowRuntimePublic,
    status_code=status.HTTP_200_OK,
    operation_id=_PUBLISHED_FLOW_RUNTIME_OPERATION_ID,
    summary="Get Published Flow Runtime View",
    description=(
        f"{_FLOW_PUBLISHED_RUNTIME_DESCRIPTION} "
        "Use this endpoint when a client needs one published flow's metadata plus the "
        "canonical runtime paths for contract discovery, file upload, run creation, "
        "polling, review checkpoints, and artifact/evidence retrieval."
    ),
    responses={
        403: error_response(
            description=(
                "Forbidden. Machine-readable codes include `insufficient_scope` when the "
                "API key scope does not match the flow and `insufficient_space_permission` "
                "when the caller cannot read the published flow in the space."
            ),
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Published flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
        ),
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.VIEW),
)
async def get_published_flow_runtime(
    id: Annotated[
        UUID,
        Path(
            description="Identifier of the published flow to expose as a runtime-safe projection."
        ),
    ],
    request: Request,
    container: Container = Depends(
        get_container(with_user=True, with_module_user=True)
    ),
):
    published_access = await require_flow_published_runtime_access(
        request,
        container,
        flow_id=id,
    )

    assembler = FlowAssembler()
    return assembler.to_runtime_public(
        published_access.flow,
        published_version=published_access.published_version,
        api_prefix=get_settings().api_prefix,
    )


@router.patch(
    "/{id}/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="update_flow",
    summary="Update Flow",
    description=(
        "Update a draft flow definition, including steps and metadata. `steps`, "
        "when sent, replaces the step list: a step that keeps its `id` moves to "
        "its `step_order`, a step without an `id` is new, and a saved step left "
        "out is removed. A read column (`input_bindings`, `input_config`, "
        "`output_config`) a step sends as it was read is the saved one, and its "
        "reads of other steps follow the change (`step_N` is renumbered, a read "
        "by step name follows a rename); one it sends changed is taken as given. "
        "Prompts of the step assistants follow in the same revision. A rename of "
        "a run form field (`form_field_renames`) takes its reads along. "
        "Operational retention is managed separately by Organization administrators. "
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description=(
                "The submitted draft flow update is invalid, the draft moved on "
                "since `expected_revision` (`stale_revision`), or "
                f"{_STEP_READ_LOST_PRODUCER_DESCRIPTION}. "
                f"{_FORM_FIELD_REFUSALS_DESCRIPTION}"
            ),
            examples=_DRAFT_CHANGE_REFUSAL_EXAMPLES,
        ),
        403: error_response(
            description=_FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
        ),
        409: _FLOW_NAME_TAKEN_RESPONSE,
    },
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.EDIT),
)
async def update_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to update.")
    ],
    request: Request,
    flow_in: FlowUpdateRequest,
    container: Container = Depends(_AUTHORING_CONTAINER),
):
    async with authoring_operations.authoring_transaction(container):
        return await authoring_operations.update_flow(
            id=id, request=request, container=container, flow_in=flow_in
        )


@router.delete(
    "/{id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    operation_id="delete_flow",
    summary="Delete Flow",
    description=(
        "Soft-delete a flow definition so it is no longer available for editing or "
        "execution. The deletion and its audit record are committed together: a "
        "flow is never deleted without its audit row. The request does not wait "
        "for the flow's runs: a background sweep cancels its queued, running and "
        "awaiting-review runs with the error code `flow_deleted`. "
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
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
async def delete_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to delete.")
    ],
    request: Request,
    container: Container = Depends(_MUTATING_CONTAINER),
):
    access_context = await require_flow_delete_access(request, container, flow_id=id)

    await container.flow_service().delete_flow(id)
    user = container.user()
    await container.audit_service().log(
        tenant_id=user.tenant_id,
        user=user,
        required=True,
        action=ActionType.FLOW_DELETED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Deleted flow '{access_context.flow.name}'",
        metadata=AuditMetadata.standard(actor=user, target=access_context.flow),
    )


@router.post(
    "/{id}/publish/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="publish_flow",
    summary="Publish Flow",
    description=(
        "Publish the current draft revision so new runs use a version-pinned definition. "
        "A step whose input source is `tool` is published only when the instance and "
        "the space allow that tool in the flow's space; the published definition then "
        "holds the tool's name and the SHA-256 fingerprint of its approved input "
        "schema inside `input_config.tool`. "
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description=(
                "The flow cannot be published because its draft definition is "
                "incomplete or invalid. A step whose tool the instance or the space "
                "does not allow is refused with `typed_io_tool_not_allowed`; "
                "`context` holds `step_order`, `refusal` (the refusing level), "
                "`mcp_server_id` and `tool_id`. A step whose tool has an input "
                "schema that is not a valid JSON Schema, or of a draft Eneo "
                "does not support, is refused with "
                "`typed_io_tool_invalid_schema`. A step that gives no value for "
                "an argument the schema's top-level `required` names is refused "
                "with `typed_io_tool_invalid_config` (not for a `required` beside "
                "a top-level `$ref` in drafts 3, 4, 6 and 7, which a run does not "
                "read either); `context` holds "
                "`step_order`, `field`, `argument` and `problem` "
                "`missing_required`. A step that gives an argument whose name "
                "the schema refuses whatever its value (top-level "
                "`additionalProperties` is false, no top-level "
                "`patternProperties`, and top-level `properties` does not name "
                "it; not beside a top-level `$ref` in drafts 3, 4, 6 and 7) is "
                "refused with `typed_io_tool_invalid_config` and `problem` "
                "`undeclared_argument`. A step whose fixed (not bound) argument "
                "value does not fit the subschema the input schema's top-level "
                "`properties` gives for that argument is refused with "
                "`typed_io_tool_invalid_config` and `problem` `outside_schema`; "
                "not beside a top-level `$ref` in drafts 3, 4, 6 and 7, and not "
                "when the bounded property check times out, cannot evaluate the "
                "subschema, or cannot run on this host: a run checks those. "
                "A step that calls an AI model while its assistant has no model, "
                "or a step whose model has no provider, is refused with "
                "`flow_assistant_model_provider_required`; `context` holds "
                "`issue_code` and `step_order`. When security classifications "
                "are on and such a step must clear a classification level, "
                "publish reports the classification refusal first."
            ),
            message="Flow cannot be published in its current state.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
        ),
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
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
async def publish_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to publish.")
    ],
    request: Request,
    container: Container = Depends(_AUTHORING_CONTAINER),
    expected_revision: Annotated[int | None, Query(ge=0)] = None,
):
    async with authoring_operations.authoring_transaction(container):
        return await authoring_operations.publish_flow(
            id=id,
            request=request,
            container=container,
            expected_revision=expected_revision,
        )


@router.post(
    "/{id}/unpublish/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="unpublish_flow",
    summary="Unpublish Flow",
    description=(
        "Remove the active published revision while keeping the draft definition "
        f"available for editing. {_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description=(
                "The flow cannot be unpublished in its current state: it is not "
                "published (`flow_not_published`)."
            ),
            message="Flow is not published.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
        ),
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
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
async def unpublish_flow(
    id: Annotated[
        UUID,
        Path(description="Identifier of the published flow definition to unpublish."),
    ],
    request: Request,
    container: Container = Depends(_AUTHORING_CONTAINER),
    expected_revision: Annotated[int | None, Query(ge=0)] = None,
):
    async with authoring_operations.authoring_transaction(container):
        return await authoring_operations.unpublish_flow(
            id=id,
            request=request,
            container=container,
            expected_revision=expected_revision,
        )


__all__ = ["router"]


@router.patch(
    "/{id}/editor/",
    response_model=FlowPublic,
    operation_id="update_flow_editor",
    summary="Update Flow and Step Assistants",
    description=(
        "Apply one editor change to a draft flow and its flow-managed step "
        "assistants in a single revision: flow settings, sparse step edits, new "
        "steps with their assistants, and `step_order` to move, insert or remove "
        "steps. The change is fenced on `expected_revision` and either saves as "
        "a whole or not at all, and its audit entries are logged only once it "
        "has passed every check. Reads of a step that moves follow it, reads of "
        "a renamed step or run form field (`definition.form_field_renames`) "
        "follow the new name; a change that would make a step read another step "
        "than it reads now is refused with `flow_step_read_lost_producer`. An "
        "assistant change with `step_id` gives that step its own copy of an "
        "assistant it shares with other steps. "
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description=(
                "The change is invalid, the draft moved on since "
                "`expected_revision` (`stale_revision`), or "
                f"{_STEP_READ_LOST_PRODUCER_DESCRIPTION}. "
                f"{_FORM_FIELD_REFUSALS_DESCRIPTION}"
            ),
            examples=_DRAFT_CHANGE_REFUSAL_EXAMPLES,
        ),
        403: error_response(
            description=_FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow or step not found in tenant scope.",
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
async def update_flow_editor(
    id: UUID,
    request: Request,
    update: FlowEditorUpdateRequest,
    container: Container = Depends(_AUTHORING_CONTAINER),
) -> FlowPublic:
    async with authoring_operations.authoring_transaction(container):
        return await authoring_operations.apply_editor_update(
            id=id, request=request, update=update, container=container
        )

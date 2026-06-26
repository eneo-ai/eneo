from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api import flow_access_context
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_definition_access import (
    SERVICE_KEY_ADMIN_REQUIRED_MESSAGE,
    require_flow_current_definition_access,
    require_flow_delete_access,
    require_flow_edit_access,
    require_flow_publish_access,
    require_flow_published_runtime_access,
    require_flow_unpublish_access,
)
from intric.flows.api.flow_models import (
    PAGINATED_FLOW_SPARSE_RESPONSE_EXAMPLE,
    FlowCreateRequest,
    FlowPublic,
    FlowSparsePublic,
    FlowUpdateRequest,
)
from intric.flows.api.flow_runtime_paths import (
    PUBLISHED_FLOW_RUNTIME_PATH,
    FlowRuntimePublic,
)
from intric.flows.flow_access_policy import FlowApiAction
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.principal import FlowPrincipal
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, UnauthorizedException
from intric.main.models import NOT_PROVIDED, OffsetPaginatedResponse
from intric.server.dependencies.container import get_container

router = APIRouter()

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
    "their scoped space. Service-key webapps should use the returned ids with "
    "`GET /api/v1/flows/{id}/published/` and the runtime paths from that response; "
    "draft authoring and AI Builder still require a user principal."
)

_FLOW_PUBLISHED_RUNTIME_DESCRIPTION = (
    "Return the runtime-safe published projection of a flow. "
    "This endpoint is intended for runtime consumers, including service-key principals, "
    "and does not expose the current draft/current-definition authoring view. Treat it "
    "as the entry point for external webapps that already know a published flow id."
)

_PUBLISHED_FLOW_RUNTIME_OPERATION_ID = "get_published_flow_runtime"


def _classification_override_step_orders(
    flow_data: FlowCreateRequest | FlowUpdateRequest,
) -> list[int]:
    steps = flow_data.steps
    if not steps:
        return []
    return [
        step.step_order
        for step in steps
        if step.output_classification_override is not None
    ]


@router.post(
    "/",
    response_model=FlowPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow",
    summary="Create Flow",
    description=(
        "Create a new draft flow definition, including its initial ordered steps, "
        f"inside a space. {_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description="The submitted draft flow definition is invalid.",
            message="Flow definition is invalid.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
    },
)
async def create_flow(
    request: Request,
    flow_in: FlowCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await flow_access_context.resolve_space_access_context(
        request,
        container,
        space_id=flow_in.space_id,
        required_access=FlowApiAction.EDIT,
        scope_mismatch_message=(
            f"API key is scoped to space '{flow_access_context.get_scope_filter(request).space_id}'. "
            f"Cannot create flow in space '{flow_in.space_id}'."
        ),
    )
    if not access_context.actor.can_create_flows():
        raise UnauthorizedException(
            "You do not have permission to create flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    assembler = FlowAssembler()
    flow_service = container.flow_service()
    user = container.user()

    created = await flow_service.create_flow(
        space_id=flow_in.space_id,
        name=flow_in.name,
        description=flow_in.description,
        steps=[assembler.to_domain_step(step) for step in flow_in.steps],
        metadata_json=flow_in.metadata_json,
        data_retention_days=flow_in.data_retention_days,
    )

    created_flow_id = created.require_persisted_id()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_CREATED,
        entity_type=EntityType.FLOW,
        entity_id=created_flow_id,
        description=f"Created flow '{created.name}'",
        metadata=AuditMetadata.standard(actor=user, target=created),
    )
    overrides = _classification_override_step_orders(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=created_flow_id,
            description="Configured output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=created,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(created)


@router.get(
    "/",
    response_model=OffsetPaginatedResponse[FlowSparsePublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flows",
    summary="List Flows",
    description=(
        "List flow definitions in a space with pagination-friendly sparse metadata. "
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
        403: error_response(
            description=_FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
    },
)
async def list_flows(
    request: Request,
    space_id: UUID = Query(
        ..., description="Only return flows that belong to this space."
    ),
    limit: int = Query(
        default=50, ge=1, le=200, description="Maximum number of flows to return."
    ),
    offset: int = Query(
        default=0, ge=0, description="Number of flows to skip before returning results."
    ),
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await flow_access_context.resolve_space_access_context(
        request,
        container,
        space_id=space_id,
        required_access=FlowApiAction.VIEW,
        scope_mismatch_message="API key space scope does not match requested space.",
        allow_service_key_principals=True,
    )
    if not access_context.actor.can_read_flows():
        raise UnauthorizedException(
            "You do not have permission to access flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    service_key_principal = FlowPrincipal.from_user(container.user()).is_service_key
    assembler = FlowAssembler()
    flows = await container.flow_service().list_flows(
        space_id=space_id,
        sparse=True,
        published_only=service_key_principal
        or not access_context.actor.can_edit_flows(),
        limit=limit + 1,
        offset=offset,
    )
    page_items = flows[:limit]
    return {
        "count": len(page_items),
        "items": [assembler.to_sparse_public(flow) for flow in page_items],
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
                "insufficient_scope": {
                    "summary": "API key scope mismatch",
                    "value": {
                        "message": "API key space scope does not match requested flow.",
                        "intric_error_code": int(ErrorCodes.UNAUTHORIZED),
                        "code": "insufficient_scope",
                        "context": {"auth_layer": "api_key_scope"},
                    },
                },
                FlowApiErrorCode.SERVICE_KEY_ADMIN_REQUIRED.value: {
                    "summary": "Non-admin service-key principal called current draft endpoint",
                    "value": {
                        "message": SERVICE_KEY_ADMIN_REQUIRED_MESSAGE,
                        "intric_error_code": int(ErrorCodes.UNAUTHORIZED),
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
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to return.")
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await require_flow_current_definition_access(
        request,
        container,
        flow_id=id,
    )
    assembler = FlowAssembler()

    return assembler.to_public(access_context.flow)


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
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Published flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_published_flow_runtime(
    id: Annotated[
        UUID,
        Path(
            description="Identifier of the published flow to expose as a runtime-safe projection."
        ),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
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
        "Update a draft flow definition, including steps, metadata, and retention "
        f"settings. {_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description="The submitted draft flow update is invalid or the flow cannot be updated in its current state.",
            message="Flow update is invalid.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description=_FLOW_DRAFT_MUTATION_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def update_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to update.")
    ],
    request: Request,
    flow_in: FlowUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    await require_flow_edit_access(request, container, flow_id=id)

    assembler = FlowAssembler()
    payload = flow_in.model_dump(exclude_unset=True)
    steps = None
    if "steps" in payload:
        steps = [assembler.to_domain_step_for_update(step) for step in flow_in.steps]

    updated = await container.flow_service().update_flow(
        flow_id=id,
        name=payload.get("name", NOT_PROVIDED),
        description=payload.get("description", NOT_PROVIDED),
        steps=steps,
        metadata_json=payload.get("metadata_json", NOT_PROVIDED),
        data_retention_days=payload.get("data_retention_days", NOT_PROVIDED),
    )

    updated_flow_id = updated.require_persisted_id()
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UPDATED,
        entity_type=EntityType.FLOW,
        entity_id=updated_flow_id,
        description=f"Updated flow '{updated.name}'",
        metadata=AuditMetadata.standard(actor=user, target=updated),
    )
    overrides = _classification_override_step_orders(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=updated_flow_id,
            description="Updated output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=updated,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(updated)


@router.delete(
    "/{id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    operation_id="delete_flow",
    summary="Delete Flow",
    description=(
        "Soft-delete a flow definition so it is no longer available for editing or "
        f"execution. {_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def delete_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to delete.")
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await require_flow_delete_access(request, container, flow_id=id)

    await container.flow_service().delete_flow(id)
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
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
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION}"
    ),
    responses={
        400: error_response(
            description="The flow cannot be published because its draft definition is incomplete or invalid.",
            message="Flow cannot be published in its current state.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def publish_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to publish.")
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await require_flow_publish_access(request, container, flow_id=id)

    published = await container.flow_service().publish_flow(flow_id=id)
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_PUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Published flow '{published.name}' as version {published.published_version}",
        metadata=AuditMetadata.standard(actor=user, target=published),
    )
    return FlowAssembler().to_public(published)


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
            description="The flow cannot be unpublished in its current state.",
            message="Flow cannot be unpublished in its current state.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description=_FLOW_AUTHORING_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def unpublish_flow(
    id: Annotated[
        UUID,
        Path(description="Identifier of the published flow definition to unpublish."),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await require_flow_unpublish_access(request, container, flow_id=id)

    unpublished = await container.flow_service().unpublish_flow(flow_id=id)
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UNPUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Unpublished flow '{unpublished.name}'",
        metadata=AuditMetadata.standard(actor=user, target=unpublished),
    )
    return FlowAssembler().to_public(unpublished)


__all__ = ["router"]

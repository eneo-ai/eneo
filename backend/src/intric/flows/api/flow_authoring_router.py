from __future__ import annotations

from typing import Annotated, Any, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_definition_access import (
    ensure_can_mutate_flow_draft,
    require_flow_edit_access,
)
from intric.flows.api.flow_models import (
    FlowCreateRequest,
    FlowPublic,
    FlowRuntimePublic,
    FlowSparsePublic,
    FlowUpdateRequest,
)
from intric.flows.application.flow_service import FlowService
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, NotFoundException, UnauthorizedException
from intric.main.models import NOT_PROVIDED, PaginatedResponse
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
    "their scoped space. Draft authoring and AI Builder still require a user principal."
)

_FLOW_PUBLISHED_RUNTIME_DESCRIPTION = (
    "Return the runtime-safe published projection of a flow. "
    "This endpoint is intended for runtime consumers, including service-key principals, "
    "and does not expose the current draft/current-definition authoring view."
)


class _FlowReaderProtocol(Protocol):
    def can_read_flow(self, flow: object) -> bool: ...


def _get_flow_service(container: Container) -> FlowService:
    return container.flow_service()


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
    access_context = await common.get_space_access_context_for_request(
        request,
        container,
        space_id=flow_in.space_id,
        required_access="manage",
        scope_mismatch_message=(
            f"API key is scoped to space '{common.get_scope_filter(request).space_id}'. "
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
    flow_service = _get_flow_service(container)
    user = container.user()

    created = await flow_service.create_flow(
        space_id=flow_in.space_id,
        name=flow_in.name,
        description=flow_in.description,
        steps=[assembler.to_domain_step(step) for step in flow_in.steps],
        metadata_json=flow_in.metadata_json,
        data_retention_days=flow_in.data_retention_days,
    )

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_CREATED,
        entity_type=EntityType.FLOW,
        entity_id=common.required_uuid(created.id, field="flow.id"),
        description=f"Created flow '{created.name}'",
        metadata=AuditMetadata.standard(actor=user, target=created),
    )
    overrides = common.find_classification_overrides(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=common.required_uuid(created.id, field="flow.id"),
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
    response_model=PaginatedResponse[FlowSparsePublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flows",
    summary="List Flows",
    description=(
        "List flow definitions in a space with pagination-friendly sparse metadata. "
        "The `count` field in the paginated response reports the number of items returned "
        "in the current page, not the total number of matching flows across all pages. "
        f"{_FLOW_DRAFT_OWNERSHIP_DESCRIPTION} {_FLOW_SERVICE_KEY_DISCOVERY_DESCRIPTION}"
    ),
    responses={
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
    access_context = await common.get_space_access_context_for_request(
        request,
        container,
        space_id=space_id,
        required_access="view",
        scope_mismatch_message="API key space scope does not match requested space.",
        allow_service_key_principals=True,
    )
    if not access_context.actor.can_read_flows():
        raise UnauthorizedException(
            "You do not have permission to access flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    service_key_principal = common.is_service_key_principal(container.user())
    assembler = FlowAssembler()
    flows = await _get_flow_service(container).list_flows(
        space_id=space_id,
        sparse=True,
        published_only=service_key_principal
        or not access_context.actor.can_edit_flows(),
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(flows),
        "items": [assembler.to_sparse_public(flow) for flow in flows],
    }


@router.get(
    "/{id}/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow",
    summary="Get Flow",
    description=(
        "Return the full draft representation of a flow, including all configured steps "
        f"and metadata. {_FLOW_DRAFT_OWNERSHIP_DESCRIPTION} "
        "This endpoint is user-principal-oriented and returns the current draft definition."
    ),
    responses={
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
async def get_flow(
    id: Annotated[
        UUID, Path(description="Identifier of the draft flow definition to return.")
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
    )
    assembler = FlowAssembler()
    actor = cast(_FlowReaderProtocol | None, access_context.actor)
    if actor is None or not actor.can_read_flow(cast(Any, access_context.flow)):
        raise UnauthorizedException(
            "You do not have permission to access this flow.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    return assembler.to_public(access_context.flow)


@router.get(
    "/{id}/published/",
    response_model=FlowRuntimePublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_published_flow_runtime",
    summary="Get Published Flow Runtime View",
    description=(
        f"{_FLOW_PUBLISHED_RUNTIME_DESCRIPTION} "
        "Use this endpoint when a client needs one published flow's metadata plus the "
        "canonical runtime paths for contract discovery, run creation, polling, and "
        "artifact/evidence retrieval."
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
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    if access_context.flow.published_version is None:
        raise NotFoundException("Flow not found.")

    actor = cast(_FlowReaderProtocol | None, access_context.actor)
    if actor is None or not actor.can_read_flow(cast(Any, access_context.flow)):
        raise UnauthorizedException(
            "You do not have permission to access this flow.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    assembler = FlowAssembler()
    return assembler.to_runtime_public(access_context.flow)


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
        steps = [assembler.to_domain_step(step) for step in flow_in.steps]

    updated = await _get_flow_service(container).update_flow(
        flow_id=id,
        name=payload.get("name", NOT_PROVIDED),
        description=payload.get("description", NOT_PROVIDED),
        steps=steps,
        metadata_json=payload.get("metadata_json", NOT_PROVIDED),
        data_retention_days=payload.get("data_retention_days", NOT_PROVIDED),
    )

    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UPDATED,
        entity_type=EntityType.FLOW,
        entity_id=common.required_uuid(updated.id, field="flow.id"),
        description=f"Updated flow '{updated.name}'",
        metadata=AuditMetadata.standard(actor=user, target=updated),
    )
    overrides = common.find_classification_overrides(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=common.required_uuid(updated.id, field="flow.id"),
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
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="manage",
    )
    if access_context.actor is None or not access_context.actor.can_delete_flows():
        raise UnauthorizedException(
            "You do not have permission to delete flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    ensure_can_mutate_flow_draft(container, access_context)

    await _get_flow_service(container).delete_flow(id)
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
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="manage",
    )
    if access_context.actor is None or not access_context.actor.can_publish_flows():
        raise UnauthorizedException(
            "You do not have permission to publish flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    ensure_can_mutate_flow_draft(container, access_context)

    published = await _get_flow_service(container).publish_flow(flow_id=id)
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
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="manage",
    )
    if access_context.actor is None or not access_context.actor.can_publish_flows():
        raise UnauthorizedException(
            "You do not have permission to unpublish flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    ensure_can_mutate_flow_draft(container, access_context)

    unpublished = await _get_flow_service(container).unpublish_flow(flow_id=id)
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


__all__ = [
    "create_flow",
    "delete_flow",
    "get_flow",
    "list_flows",
    "publish_flow",
    "router",
    "unpublish_flow",
    "update_flow",
]

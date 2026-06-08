# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.main.container.container import Container
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationCreatePublic,
    SecurityClassificationLevelsUpdateRequest,
    SecurityClassificationPublic,
    SecurityClassificationResponse,
    SecurityClassificationSingleUpdate,
    SecurityClassificationsListPublic,
    SecurityEnableRequest,
    SecurityEnableResponse,
)
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()

ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]


@router.post(
    "/",
    response_model=SecurityClassificationPublic,
    status_code=201,
    description="Create a new security classification for the current tenant.",
    responses=responses.get_responses([400]),
)
async def create_security_classification(
    request: SecurityClassificationCreatePublic,
    container: ContainerDep,
) -> SecurityClassificationPublic | None:
    """Create a new security classification for the current tenant.
    Args:
        request: The security classification creation request.
    Returns:
        The created security classification.
    Raises:
        400: If the request is invalid. Names must be unique.
    """
    service = container.security_classification_service()
    user = container.user()

    # Create security classification
    security_classification = await service.create_security_classification(
        name=request.name,
        description=request.description,
        set_lowest_security=request.set_lowest_security,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.SECURITY_CLASSIFICATION_CREATED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=security_classification.id,
        description=f"Created security classification '{security_classification.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=security_classification,
            extra={
                "description": security_classification.description,
                "security_level": security_classification.security_level,
            },
        ),
    )

    return SecurityClassificationPublic.from_domain(
        security_classification, return_none_if_not_enabled=False
    )


@router.get(
    "/",
    response_model=SecurityClassificationResponse,
    responses=responses.get_responses([403]),
)
async def list_security_classifications(
    container: ContainerDep,
) -> SecurityClassificationResponse:
    """List all security classifications ordered by security classification level.
    Returns:
        List of security classifications ordered by security classification level.
    Raises:
        403: If the user doesn't have permission to list security classifications.
    """
    service = container.security_classification_service()

    security_classifications = await service.list_security_classifications()
    user = container.user()

    scs: list[SecurityClassificationPublic] = [
        pub
        for sc in security_classifications
        if (
            pub := SecurityClassificationPublic.from_domain(
                sc, return_none_if_not_enabled=False
            )
        )
        is not None
    ]

    return SecurityClassificationResponse(
        security_enabled=user.tenant.security_enabled,
        security_classifications=scs,
    )


@router.get(
    "/{id}/",
    response_model=SecurityClassificationPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_security_classification(
    id: UUID,
    container: ContainerDep,
) -> SecurityClassificationPublic | None:
    """Get a security classification by ID.
    Args:
        id: The ID of the security classification.
    Returns:
        The security classification.
    Raises:
        403: If the user doesn't have permission to view the security classification.
        404: If the security classification doesn't exist or belongs to a different tenant.
    """
    service = container.security_classification_service()
    security_classification = await service.get_security_classification(id)
    return SecurityClassificationPublic.from_domain(
        security_classification, return_none_if_not_enabled=False
    )


@router.patch(
    "/",
    response_model=SecurityClassificationsListPublic,
    description="Update the security levels (ordering) of security classifications.",
    responses=responses.get_responses([400, 403, 404]),
)
async def update_security_classification_levels(
    request: SecurityClassificationLevelsUpdateRequest,
    container: ContainerDep,
) -> SecurityClassificationsListPublic:
    """Update the security levels of security classifications.
    Args:
        request: Security classifications to update.
    Returns:
        The updated security classifications.
    Raises:
        400: If the request is invalid.
        403: If the user doesn't have permission to update the security classification.
        404: If the security classification doesn't exist or belongs to a different tenant.
    """
    service = container.security_classification_service()
    user = container.user()

    sc_ids = [model.id for model in request.security_classifications]
    security_classifications = await service.update_security_levels(
        security_classifications=sc_ids
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.SECURITY_CLASSIFICATION_LEVELS_UPDATED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=user.tenant_id,  # Use tenant as entity since multiple classifications affected
        description=f"Updated security classification levels (reordered {len(security_classifications)} classifications)",
        metadata=AuditMetadata.standard(
            actor=user,
            target=user.tenant,
            extra={
                "classifications_count": len(security_classifications),
                "new_order": [
                    {
                        "position": idx + 1,
                        "id": str(sc.id),
                        "name": sc.name,
                        "security_level": sc.security_level,
                    }
                    for idx, sc in enumerate(security_classifications)
                ],
            },
        ),
    )

    return SecurityClassificationsListPublic(
        security_classifications=[
            pub
            for sc in security_classifications
            if (
                pub := SecurityClassificationPublic.from_domain(
                    sc, return_none_if_not_enabled=False
                )
            )
            is not None
        ]
    )


@router.delete(
    "/{id}/",
    status_code=204,
    description="Delete a security classification, optionally forcing if still referenced.",
    responses=responses.get_responses([400, 403, 404]),
)
async def delete_security_classification(
    id: UUID,
    container: ContainerDep,
    force: bool = False,
) -> None:
    """Delete a security classification.

    Refuses if any model, space or MCP server still references it — the
    FK is `ON DELETE SET NULL`, so dropping a referenced classification
    would silently downgrade every dependent row to "no classification".
    Pass `?force=true` to override after reviewing the usage report.

    Args:
        id: The ID of the security classification to delete.
        force: When true, delete even if rows still reference this
            classification. Those rows will be downgraded to NULL.
    Raises:
        400: If the classification is referenced and `force` is false.
        403: If the user doesn't have permission to delete the security classification.
        404: If the security classification doesn't exist.
    """
    service = container.security_classification_service()
    user = container.user()

    # Get security classification info before deletion (snapshot pattern)
    security_classification = await service.get_security_classification(id)

    # Delete security classification
    await service.delete_security_classification(id, force=force)

    # Audit logging — flag forced deletes prominently so a reader can
    # tell when an admin overrode the in-use guard.
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.SECURITY_CLASSIFICATION_DELETED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=id,
        description=f"Deleted security classification '{security_classification.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=security_classification,
            extra={
                "security_level": security_classification.security_level,
                "forced": force,
            },
        ),
    )


@router.patch(
    "/{id}/",
    response_model=SecurityClassificationPublic,
    description="Update a single security classification's name and/or description.",
    responses=responses.get_responses([400, 403, 404]),
)
async def update_security_classification(
    id: UUID,
    request: SecurityClassificationSingleUpdate,
    container: ContainerDep,
) -> SecurityClassificationPublic | None:
    """Update a single security classification's name and/or description.

    This endpoint allows updating just the name and description of a security classification
    without changing its security level.

    Args:
        id: The ID of the security classification to update
        request: The update request containing new name and/or description

    Returns:
        The updated security classification

    Raises:
        400: If the request is invalid or security is disabled. Names must be unique.
        403: If the user doesn't have permission to update the classification
        404: If the security classification doesn't exist
    """
    from intric.main.models import is_provided

    service = container.security_classification_service()
    user = container.user()

    # Get old state for change tracking
    old_sc = await service.get_security_classification(id)

    # Update security classification
    security_classification = await service.update_security_classification(
        id=id, name=request.name, description=request.description
    )
    assert security_classification is not None

    # Track changes
    changes: dict[str, object] = {}
    if is_provided(request.name) and request.name != old_sc.name:
        changes["name"] = {"old": old_sc.name, "new": request.name}
    if is_provided(request.description) and request.description != old_sc.description:
        changes["description"] = {"old": old_sc.description, "new": request.description}

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.SECURITY_CLASSIFICATION_UPDATED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=id,
        description=f"Updated security classification '{security_classification.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=security_classification,
            changes=changes,
        ),
    )

    return SecurityClassificationPublic.from_domain(
        security_classification, return_none_if_not_enabled=False
    )


@router.post(
    "/enable/",
    response_model=SecurityEnableResponse,
    description="Enable or disable security classifications for the current tenant.",
    responses=responses.get_responses([400, 403]),
)
async def toggle_security_classifications(
    request: SecurityEnableRequest,
    container: ContainerDep,
) -> SecurityEnableResponse:
    """Enable or disable security classifications for the current tenant.

    Args:
        request: Contains a flag to enable or disable security classifications.

    Returns:
        The updated tenant information with security_enabled status.

    Raises:
        400: If the request is invalid.
        403: If the user doesn't have permission to update tenant settings.
    """
    service = container.security_classification_service()
    user = container.user()

    # Toggle security classifications
    tenant = await service.toggle_security_on_tenant(enabled=request.enabled)
    assert tenant is not None

    # Audit logging
    audit_service = container.audit_service()
    action = (
        ActionType.SECURITY_CLASSIFICATION_ENABLED
        if request.enabled
        else ActionType.SECURITY_CLASSIFICATION_DISABLED
    )

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description=f"{'Enabled' if request.enabled else 'Disabled'} security classifications for tenant",
        metadata=AuditMetadata.standard(
            actor=user,
            target=tenant,
            extra={"security_enabled": request.enabled},
        ),
    )

    return SecurityEnableResponse(
        **dict(  # type: ignore[arg-type]
            tenant_id=tenant.id,
            security_enabled=tenant.security_enabled,
        )
    )

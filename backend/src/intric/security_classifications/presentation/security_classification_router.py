# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from uuid import UUID

from fastapi import APIRouter, Depends

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


@router.post(
    "/",
    response_model=SecurityClassificationPublic,
    status_code=201,
    responses=responses.get_responses([400]),
)
async def create_security_classification(
    request: SecurityClassificationCreatePublic,
    container: Container = Depends(get_container(with_user=True)),
) -> SecurityClassificationPublic:
    """Create a new security classification for the current tenant.
    Args:
        request: The security classification creation request.
    Returns:
        The created security classification.
    Raises:
        400: If the request is invalid. Names must be unique.
    """
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.security_classification_service()
    user = container.user()

    # Create security classification
    security_classification = await service.create_security_classification(
        name=request.name,
        description=request.description,
        set_lowest_security=request.set_lowest_security,
    )

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.SECURITY_CLASSIFICATION_CREATED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=security_classification.id,
        description=f"Created security classification '{security_classification.name}'",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "id": str(security_classification.id),
                "name": security_classification.name,
                "description": security_classification.description,
                "security_level": security_classification.security_level,
            },
        },
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
    container: Container = Depends(get_container(with_user=True)),
) -> list[SecurityClassificationPublic]:
    """List all security classifications ordered by security classification level.
    Returns:
        List of security classifications ordered by security classification level.
    Raises:
        403: If the user doesn't have permission to list security classifications.
    """
    service = container.security_classification_service()

    security_classifications = await service.list_security_classifications()
    user = container.user()

    scs = [
        SecurityClassificationPublic.from_domain(sc, return_none_if_not_enabled=False)
        for sc in security_classifications
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
    container: Container = Depends(get_container(with_user=True)),
) -> SecurityClassificationPublic:
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
    responses=responses.get_responses([400, 403, 404]),
)
async def update_security_classification_levels(
    request: SecurityClassificationLevelsUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
) -> SecurityClassificationPublic:
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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.security_classification_service()
    user = container.user()

    sc_ids = [model.id for model in request.security_classifications]
    security_classifications = await service.update_security_levels(security_classifications=sc_ids)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.SECURITY_CLASSIFICATION_LEVELS_UPDATED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=user.tenant_id,  # Use tenant as entity since multiple classifications affected
        description=f"Updated security classification levels (reordered {len(security_classifications)} classifications)",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "tenant_id": str(user.tenant_id),
                "classifications_count": len(security_classifications),
                "new_order": [str(sc_id) for sc_id in sc_ids],
            },
        },
    )

    return SecurityClassificationsListPublic(
        security_classifications=[
            SecurityClassificationPublic.from_domain(sc, return_none_if_not_enabled=False)
            for sc in security_classifications
        ]
    )


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_security_classification(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
) -> None:
    """Delete a security classification.
    Args:
        id: The ID of the security classification to delete.
    Raises:
        403: If the user doesn't have permission to delete the security classification.
        404: If the security classification doesn't exist.
    """
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.security_classification_service()
    user = container.user()

    # Get security classification info before deletion
    security_classification = await service.get_security_classification(id)

    # Delete security classification
    await service.delete_security_classification(id)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.SECURITY_CLASSIFICATION_DELETED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=id,
        description=f"Deleted security classification '{security_classification.name}'",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "id": str(id),
                "name": security_classification.name,
                "security_level": security_classification.security_level,
            },
        },
    )


@router.patch(
    "/{id}/",
    response_model=SecurityClassificationPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_security_classification(
    id: UUID,
    request: SecurityClassificationSingleUpdate,
    container: Container = Depends(get_container(with_user=True)),
) -> SecurityClassificationPublic:
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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.security_classification_service()
    user = container.user()

    # Get old state for change tracking
    old_sc = await service.get_security_classification(id)

    # Update security classification
    security_classification = await service.update_security_classification(
        id=id, name=request.name, description=request.description
    )

    # Track changes
    changes = {}
    if request.name and request.name != old_sc.name:
        changes["name"] = {"old": old_sc.name, "new": request.name}
    if request.description is not None and request.description != old_sc.description:
        changes["description"] = {"old": old_sc.description, "new": request.description}

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.SECURITY_CLASSIFICATION_UPDATED,
        entity_type=EntityType.SECURITY_CLASSIFICATION,
        entity_id=id,
        description=f"Updated security classification '{security_classification.name}'",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "id": str(id),
                "name": security_classification.name,
            },
            "changes": changes,
        },
    )

    return SecurityClassificationPublic.from_domain(
        security_classification, return_none_if_not_enabled=False
    )


@router.post(
    "/enable/",
    response_model=SecurityEnableResponse,
    responses=responses.get_responses([400, 403]),
)
async def toggle_security_classifications(
    request: SecurityEnableRequest,
    container: Container = Depends(get_container(with_user=True)),
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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.security_classification_service()
    user = container.user()

    # Toggle security classifications
    tenant = await service.toggle_security_on_tenant(enabled=request.enabled)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    action = (
        ActionType.SECURITY_CLASSIFICATION_ENABLED
        if request.enabled
        else ActionType.SECURITY_CLASSIFICATION_DISABLED
    )

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=action,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description=f"{'Enabled' if request.enabled else 'Disabled'} security classifications for tenant",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "tenant_id": str(user.tenant_id),
                "security_enabled": request.enabled,
            },
        },
    )

    return SecurityEnableResponse(
        tenant_id=tenant.id,
        security_enabled=tenant.security_enabled,
    )

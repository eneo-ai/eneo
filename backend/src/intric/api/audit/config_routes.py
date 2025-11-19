"""API routes for audit category configuration."""

import logging

from fastapi import APIRouter, Depends

from intric.audit.schemas.audit_config_schemas import (
    ActionConfigResponse,
    ActionConfigUpdateRequest,
    AuditConfigResponse,
    AuditConfigUpdateRequest,
)
from intric.main.container.container import Container
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container

logger = logging.getLogger(__name__)

# No tags here - inherits from parent router (/audit) to avoid duplicates in Swagger
router = APIRouter(prefix="/config")


@router.get(
    "",
    response_model=AuditConfigResponse,
    summary="Get audit category configuration",
    description="Retrieve all audit category configurations for the current tenant.",
)
async def get_audit_config(
    container: Container = Depends(get_container(with_user=True)),
) -> AuditConfigResponse:
    """
    Get audit category configuration for the current tenant.

    Returns all 7 audit categories with their enabled status, descriptions,
    action counts, and example action types.

    Requires admin permission.
    """
    user = container.user()

    # Validate admin permissions
    validate_permission(user, Permission.ADMIN)

    audit_config_service = container.audit_config_service()

    logger.info(
        f"User {user.id} fetching audit config for tenant {user.tenant_id}"
    )

    return await audit_config_service.get_config(user.tenant_id)


@router.patch(
    "",
    response_model=AuditConfigResponse,
    summary="Update audit category configuration",
    description="Update one or more audit category configurations for the current tenant.",
)
async def update_audit_config(
    request: AuditConfigUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
) -> AuditConfigResponse:
    """
    Update audit category configurations for the current tenant.

    Accepts bulk updates for one or more categories. Changes take effect
    immediately for new audit events. Historical audit logs are unaffected.

    Requires admin permission.
    """
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType

    user = container.user()

    # Validate admin permissions
    validate_permission(user, Permission.ADMIN)

    audit_config_service = container.audit_config_service()
    audit_service = container.audit_service()

    logger.info(
        f"User {user.id} updating audit config for tenant {user.tenant_id}: "
        f"{len(request.updates)} category updates"
    )

    # Capture old configuration for audit log
    old_config = await audit_config_service.get_config(user.tenant_id)
    old_config_dict = {c.category: c.enabled for c in old_config.categories}

    # Update configuration
    updated_config = await audit_config_service.update_config(
        user.tenant_id, request.updates
    )

    # Build changes dict for audit log
    changes = {}
    for update in request.updates:
        old_value = old_config_dict.get(update.category)
        if old_value != update.enabled:
            changes[update.category] = {
                "old": old_value,
                "new": update.enabled
            }

    # Create audit log for configuration change
    if changes:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=user.tenant_id,
            description="Updated audit logging configuration",
            metadata={
                "setting": "audit_category_config",
                "changes": changes
            },
        )

    return updated_config


# ============================================================================
# ACTION-LEVEL CONFIGURATION ENDPOINTS
# ============================================================================


@router.get(
    "/actions",
    response_model=ActionConfigResponse,
    summary="Get per-action audit configuration",
    description="Retrieve all 65 actions with their enabled status for the modal UI.",
)
async def get_action_config(
    container: Container = Depends(get_container(with_user=True)),
) -> ActionConfigResponse:
    """
    Get all actions with their enabled status (considering category + overrides).

    Returns all 65 actions grouped by category with Swedish metadata.
    Used for populating the audit configuration modal UI.

    Requires admin permission.
    """
    user = container.user()

    # Validate admin permissions
    validate_permission(user, Permission.ADMIN)

    audit_config_service = container.audit_config_service()

    logger.info(
        f"User {user.id} fetching action config for tenant {user.tenant_id}"
    )

    return await audit_config_service.get_action_config(user.tenant_id)


@router.patch(
    "/actions",
    response_model=ActionConfigResponse,
    summary="Update per-action audit configuration",
    description="Update one or more action-level audit configurations.",
)
async def update_action_config(
    request: ActionConfigUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
) -> ActionConfigResponse:
    """
    Update action overrides for a tenant.

    Accepts bulk updates for one or more actions. Changes are stored in
    the action_overrides JSONB column of the category config.

    Requires admin permission.
    """
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType

    user = container.user()

    # Validate admin permissions
    validate_permission(user, Permission.ADMIN)

    audit_config_service = container.audit_config_service()
    audit_service = container.audit_service()

    logger.info(
        f"User {user.id} updating {len(request.updates)} action configs "
        f"for tenant {user.tenant_id}"
    )

    # Update configuration
    updated_config = await audit_config_service.update_action_config(
        user.tenant_id, request.updates
    )

    # Create audit log for configuration change
    if request.updates:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=user.tenant_id,
            description=f"Updated {len(request.updates)} audit action configurations",
            metadata={
                "setting": "audit_action_config",
                "updates": [
                    {"action": u.action, "enabled": u.enabled}
                    for u in request.updates
                ]
            },
        )

    return updated_config

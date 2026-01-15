from fastapi import APIRouter, Depends
from uuid import UUID

from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.templates.assistant_template.api.assistant_template_models import (
    AssistantTemplateAdminPublic,
    AssistantTemplateAdminListPublic,
    AssistantTemplateAdminCreate,
    AssistantTemplateAdminUpdate,
    AssistantTemplateToggleDefaultRequest,
)

router = APIRouter(prefix="/admin/templates/assistants", tags=["admin-templates"])


@router.get(
    "/",
    response_model=AssistantTemplateAdminListPublic,
    status_code=200,
    summary="List tenant's assistant templates",
    description="""
List all active (non-deleted) assistant templates owned by your tenant.

**Admin Only:** Requires admin permissions.

**Visibility:**
- Only shows templates where `tenant_id` matches your tenant
- Excludes global templates (tenant_id = NULL)
- Excludes soft-deleted templates (deleted_at IS NOT NULL)

Use this endpoint for the admin template management page.
    """,
    responses=responses.get_responses([401, 403]),
)
async def list_templates(
    container: Container = Depends(get_container(with_user=True))
):
    """List all active assistant templates for the tenant with usage counts."""
    service = container.assistant_template_service()
    user = container.user()

    templates_with_usage = await service.get_templates_for_tenant(tenant_id=user.tenant_id)

    # Convert to admin response model
    items = [
        AssistantTemplateAdminPublic(
            id=t.id,
            name=t.name,
            description=t.description,
            category=t.category,
            prompt_text=t.prompt_text,
            completion_model_kwargs=t.completion_model_kwargs or {},
            completion_model_id=t.completion_model.id if t.completion_model else None,
            completion_model_name=t.completion_model.name if t.completion_model else None,
            wizard=t.wizard,
            organization=t.organization,
            tenant_id=t.tenant_id,
            deleted_at=t.deleted_at,
            deleted_by_user_id=t.deleted_by_user_id,
            restored_at=t.restored_at,
            restored_by_user_id=t.restored_by_user_id,
            original_snapshot=t.original_snapshot,
            created_at=t.created_at,
            updated_at=t.updated_at,
            usage_count=usage_count,
            is_default=t.is_default,
            icon_name=t.icon_name,
        )
        for t, usage_count in templates_with_usage
    ]

    return AssistantTemplateAdminListPublic(items=items)


@router.post(
    "/",
    response_model=AssistantTemplateAdminPublic,
    status_code=201,
    summary="Create assistant template",
    description="""
Create a new assistant template for your tenant.

**Admin Only:** Requires admin permissions.

**Prerequisites:**
- Feature flag `using_templates` must be enabled for your tenant
- Template name must be unique within your tenant

**Business Logic:**
- Template is automatically scoped to your tenant
- Original state is saved in `original_snapshot` for rollback
- Template immediately available in gallery for users in your tenant

**Example Request:**
```json
{
  "name": "Customer Support Assistant",
  "description": "Handles customer inquiries professionally and efficiently",
  "category": "Support",
  "prompt": "You are a helpful customer support agent. Always be polite and professional.",
  "completion_model_kwargs": {"temperature": 0.7, "max_tokens": 500},
  "wizard": {
    "attachments": {"required": false, "title": "Add product docs", "description": "Optional documentation"},
    "collections": {"required": true, "title": "Select knowledge base", "description": "Choose support knowledge base"}
  }
}
```
    """,
    responses=responses.get_responses([400, 401, 403, 409, 424]),
)
async def create_template(
    data: AssistantTemplateAdminCreate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Create a new assistant template for the tenant."""
    service = container.assistant_template_service()
    user = container.user()

    # Convert to service input model
    from intric.templates.assistant_template.api.assistant_template_models import (
        AssistantTemplateCreate,
    )

    create_data = AssistantTemplateCreate(
        name=data.name,
        description=data.description or "",
        category=data.category,
        prompt=data.prompt or "",
        completion_model_kwargs=data.completion_model_kwargs or {},
        wizard=data.wizard,
        icon_name=data.icon_name,
    )

    template = await service.create_template(
        data=create_data,
        tenant_id=user.tenant_id,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.TEMPLATE_CREATED,
        entity_type=EntityType.TEMPLATE,
        entity_id=template.id,
        description=f"Created assistant template '{template.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=template,
            extra={
                "template_type": "assistant",
                "category": template.category,
            },
        ),
    )

    return AssistantTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        completion_model_id=template.completion_model.id if template.completion_model else None,
        completion_model_name=template.completion_model.name if template.completion_model else None,
        wizard=template.wizard,
        organization=template.organization,
        tenant_id=template.tenant_id,
        deleted_at=template.deleted_at,
        deleted_by_user_id=template.deleted_by_user_id,
        restored_at=template.restored_at,
        restored_by_user_id=template.restored_by_user_id,
        original_snapshot=template.original_snapshot,
        created_at=template.created_at,
        updated_at=template.updated_at,
        icon_name=template.icon_name,
    )


@router.patch(
    "/{template_id}",
    response_model=AssistantTemplateAdminPublic,
    status_code=200,
    summary="Update assistant template",
    description="Updates an existing assistant template (admin only)",
    responses=responses.get_responses([400, 401, 403, 404, 409]),
)
async def update_template(
    template_id: "UUID",
    data: AssistantTemplateAdminUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Update an assistant template."""
    service = container.assistant_template_service()
    user = container.user()

    # Convert to service input model
    from intric.templates.assistant_template.api.assistant_template_models import (
        AssistantTemplateUpdate,
    )

    update_data = AssistantTemplateUpdate(
        name=data.name,
        description=data.description,
        category=data.category,
        prompt=data.prompt,
        completion_model_kwargs=data.completion_model_kwargs,
        completion_model_id=data.completion_model_id,
        wizard=data.wizard,
        icon_name=data.icon_name,
    )

    template = await service.update_template(
        template_id=template_id,
        data=update_data,
        tenant_id=user.tenant_id,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.TEMPLATE_UPDATED,
        entity_type=EntityType.TEMPLATE,
        entity_id=template_id,
        description=f"Updated assistant template '{template.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=template,
            extra={"template_type": "assistant"},
        ),
    )

    return AssistantTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        completion_model_id=template.completion_model.id if template.completion_model else None,
        completion_model_name=template.completion_model.name if template.completion_model else None,
        wizard=template.wizard,
        organization=template.organization,
        tenant_id=template.tenant_id,
        deleted_at=template.deleted_at,
        deleted_by_user_id=template.deleted_by_user_id,
        restored_at=template.restored_at,
        restored_by_user_id=template.restored_by_user_id,
        original_snapshot=template.original_snapshot,
        created_at=template.created_at,
        updated_at=template.updated_at,
        icon_name=template.icon_name,
    )


@router.patch(
    "/{template_id}/default",
    response_model=AssistantTemplateAdminPublic,
    status_code=200,
    summary="Toggle assistant template as featured",
    description="""
Toggle an assistant template as featured/default.

**Admin Only:** Requires admin permissions.

**Validation:**
- Template must belong to your tenant
- Maximum 5 featured templates per tenant
- Returns 400 if limit exceeded

**Behavior:**
- Featured templates appear first in the template gallery
- Featured templates are sorted alphabetically by name
- Non-featured templates appear below, sorted by creation date

**Example Request:**
```json
{
  "is_default": true
}
```
    """,
    responses=responses.get_responses([400, 401, 403, 404]),
)
async def toggle_default(
    template_id: UUID,
    data: AssistantTemplateToggleDefaultRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """Toggle template as featured/default."""
    service = container.assistant_template_service()
    user = container.user()

    template = await service.toggle_default(
        template_id=template_id,
        is_default=data.is_default,
        tenant_id=user.tenant_id,
    )

    return AssistantTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        completion_model_id=template.completion_model.id if template.completion_model else None,
        completion_model_name=template.completion_model.name if template.completion_model else None,
        wizard=template.wizard,
        organization=template.organization,
        tenant_id=template.tenant_id,
        deleted_at=template.deleted_at,
        deleted_by_user_id=template.deleted_by_user_id,
        restored_at=template.restored_at,
        restored_by_user_id=template.restored_by_user_id,
        original_snapshot=template.original_snapshot,
        created_at=template.created_at,
        updated_at=template.updated_at,
        is_default=template.is_default,
        icon_name=template.icon_name,
    )


@router.delete(
    "/{template_id}",
    status_code=204,
    summary="Delete assistant template",
    description="""
Soft-delete an assistant template (marks with deleted_at timestamp).

**Admin Only:** Requires admin permissions.

**Safety Checks:**
- Validates template belongs to your tenant
- Checks if template is currently in use by assistants
- Returns 409 Conflict if template is in use with usage count

**Behavior:**
- Sets `deleted_at` to current timestamp
- Template no longer appears in gallery or admin list
- Template can be viewed in deleted list (audit trail)
- Template remains in database (soft-delete only)

**Error Response (In Use):**
```json
{
  "detail": "Cannot delete template 'My Template'. It is used by 3 assistant(s).",
  "error_code": "BAD_REQUEST"
}
```
    """,
    responses=responses.get_responses([400, 401, 403, 404, 409]),
)
async def delete_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Soft-delete an assistant template."""
    service = container.assistant_template_service()
    user = container.user()

    # Delete template (returns deleted template for audit logging)
    template = await service.delete_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.TEMPLATE_DELETED,
        entity_type=EntityType.TEMPLATE,
        entity_id=template_id,
        description=f"Deleted assistant template '{template.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=template,
            extra={"template_type": "assistant"},
        ),
    )


@router.post(
    "/{template_id}/rollback",
    response_model=AssistantTemplateAdminPublic,
    status_code=200,
    summary="Rollback assistant template",
    description="Restores template to original snapshot (admin only)",
    responses=responses.get_responses([400, 401, 403, 404]),
)
async def rollback_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Rollback an assistant template to its original state."""
    service = container.assistant_template_service()
    user = container.user()

    template = await service.rollback_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
    )

    return AssistantTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        completion_model_id=template.completion_model.id if template.completion_model else None,
        completion_model_name=template.completion_model.name if template.completion_model else None,
        wizard=template.wizard,
        organization=template.organization,
        tenant_id=template.tenant_id,
        deleted_at=template.deleted_at,
        deleted_by_user_id=template.deleted_by_user_id,
        restored_at=template.restored_at,
        restored_by_user_id=template.restored_by_user_id,
        original_snapshot=template.original_snapshot,
        created_at=template.created_at,
        updated_at=template.updated_at,
        icon_name=template.icon_name,
    )


@router.post(
    "/{template_id}/restore",
    response_model=AssistantTemplateAdminPublic,
    status_code=200,
    summary="Restore deleted assistant template",
    description="Restores a soft-deleted template (admin only)",
    responses=responses.get_responses([400, 401, 403, 404]),
)
async def restore_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Restore a soft-deleted assistant template."""
    service = container.assistant_template_service()
    user = container.user()

    template = await service.restore_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )

    return AssistantTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        completion_model_id=template.completion_model.id if template.completion_model else None,
        completion_model_name=template.completion_model.name if template.completion_model else None,
        wizard=template.wizard,
        organization=template.organization,
        tenant_id=template.tenant_id,
        deleted_at=template.deleted_at,
        deleted_by_user_id=template.deleted_by_user_id,
        restored_at=template.restored_at,
        restored_by_user_id=template.restored_by_user_id,
        original_snapshot=template.original_snapshot,
        created_at=template.created_at,
        updated_at=template.updated_at,
        icon_name=template.icon_name,
    )


@router.delete(
    "/{template_id}/permanent",
    status_code=204,
    summary="Permanently delete assistant template",
    description="Permanently removes a soft-deleted template from database (admin only)",
    responses=responses.get_responses([401, 403, 404]),
)
async def permanent_delete_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Permanently delete a soft-deleted assistant template (hard delete)."""
    service = container.assistant_template_service()
    user = container.user()

    await service.permanent_delete_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
    )


@router.get(
    "/deleted",
    response_model=AssistantTemplateAdminListPublic,
    status_code=200,
    summary="List deleted assistant templates",
    description="Returns soft-deleted templates for audit trail (admin only)",
    responses=responses.get_responses([401, 403]),
)
async def list_deleted_templates(
    container: Container = Depends(get_container(with_user=True))
):
    """List all deleted assistant templates for audit purposes with usage counts."""
    service = container.assistant_template_service()
    user = container.user()

    templates_with_usage = await service.get_deleted_templates_for_tenant(tenant_id=user.tenant_id)

    items = [
        AssistantTemplateAdminPublic(
            id=t.id,
            name=t.name,
            description=t.description,
            category=t.category,
            prompt_text=t.prompt_text,
            completion_model_kwargs=t.completion_model_kwargs or {},
            completion_model_id=t.completion_model.id if t.completion_model else None,
            completion_model_name=t.completion_model.name if t.completion_model else None,
            wizard=t.wizard,
            organization=t.organization,
            tenant_id=t.tenant_id,
            deleted_at=t.deleted_at,
            deleted_by_user_id=t.deleted_by_user_id,
            restored_at=t.restored_at,
            restored_by_user_id=t.restored_by_user_id,
            original_snapshot=t.original_snapshot,
            created_at=t.created_at,
            updated_at=t.updated_at,
            usage_count=usage_count,
            is_default=t.is_default,
            icon_name=t.icon_name,
        )
        for t, usage_count in templates_with_usage
    ]

    return AssistantTemplateAdminListPublic(items=items)

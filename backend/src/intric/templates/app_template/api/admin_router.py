from fastapi import APIRouter, Depends
from uuid import UUID

from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.templates.app_template.api.app_template_models import (
    AppTemplateAdminPublic,
    AppTemplateAdminListPublic,
    AppTemplateAdminCreate,
    AppTemplateAdminUpdate,
    AppTemplateToggleDefaultRequest,
)

router = APIRouter(prefix="/admin/templates/apps", tags=["admin-templates"])


@router.get(
    "/",
    response_model=AppTemplateAdminListPublic,
    status_code=200,
    summary="List tenant's app templates",
    description="Returns all active app templates for your tenant (admin only)",
    responses=responses.get_responses([401, 403]),
)
async def list_templates(
    container: Container = Depends(get_container(with_user=True))
):
    """List all active app templates for the tenant with usage counts."""
    service = container.app_template_service()
    user = container.user()

    templates_with_usage = await service.get_templates_for_tenant(tenant_id=user.tenant_id)

    items = [
        AppTemplateAdminPublic(
            id=t.id,
            name=t.name,
            description=t.description,
            category=t.category,
            prompt_text=t.prompt_text,
            completion_model_kwargs=t.completion_model_kwargs or {},
            wizard=t.wizard,
            input_type=t.input_type,
            input_description=t.input_description,
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

    return AppTemplateAdminListPublic(items=items)


@router.post(
    "/",
    response_model=AppTemplateAdminPublic,
    status_code=201,
    summary="Create app template",
    description="""
Create a new app template for your tenant.

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
  "name": "Document Analyzer",
  "description": "Analyzes uploaded documents and extracts key insights",
  "category": "Analysis",
  "prompt": "Analyze the following document and provide a summary with key insights.",
  "completion_model_kwargs": {"temperature": 0.3, "max_tokens": 1000},
  "wizard": {
    "attachments": {"required": true, "title": "Upload document", "description": "Upload PDF or text file"},
    "collections": null
  },
  "input_type": "file",
  "input_description": "Upload a document (PDF, TXT, or DOCX)"
}
```
    """,
    responses=responses.get_responses([400, 401, 403, 409, 424]),
)
async def create_template(
    data: AppTemplateAdminCreate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Create a new app template for the tenant."""
    service = container.app_template_service()
    user = container.user()

    from intric.templates.app_template.api.app_template_models import AppTemplateCreate

    create_data = AppTemplateCreate(
        name=data.name,
        description=data.description,
        category=data.category,
        prompt=data.prompt or "",
        completion_model_kwargs=data.completion_model_kwargs or {},
        wizard=data.wizard,
        input_type=data.input_type,
        input_description=data.input_description,
        icon_name=data.icon_name,
    )

    template = await service.create_template(
        data=create_data,
        tenant_id=user.tenant_id,
    )

    return AppTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        wizard=template.wizard,
        input_type=template.input_type,
        input_description=template.input_description,
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
    response_model=AppTemplateAdminPublic,
    status_code=200,
    summary="Update app template",
    description="Updates an existing app template (admin only)",
    responses=responses.get_responses([400, 401, 403, 404, 409]),
)
async def update_template(
    template_id: "UUID",
    data: AppTemplateAdminUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Update an app template."""
    service = container.app_template_service()
    user = container.user()

    from intric.templates.app_template.api.app_template_models import AppTemplateUpdate

    update_data = AppTemplateUpdate(
        name=data.name,
        description=data.description,
        category=data.category,
        prompt=data.prompt,
        completion_model_kwargs=data.completion_model_kwargs,
        wizard=data.wizard,
        input_type=data.input_type,
        input_description=data.input_description,
        icon_name=data.icon_name,
    )

    template = await service.update_template(
        template_id=template_id,
        data=update_data,
        tenant_id=user.tenant_id,
    )

    return AppTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        wizard=template.wizard,
        input_type=template.input_type,
        input_description=template.input_description,
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
    response_model=AppTemplateAdminPublic,
    status_code=200,
    summary="Toggle app template as featured",
    description="""
Toggle an app template as featured/default.

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
    data: AppTemplateToggleDefaultRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """Toggle template as featured/default."""
    service = container.app_template_service()
    user = container.user()

    template = await service.toggle_default(
        template_id=template_id,
        is_default=data.is_default,
        tenant_id=user.tenant_id,
    )

    return AppTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        wizard=template.wizard,
        input_type=template.input_type,
        input_description=template.input_description,
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
    summary="Delete app template",
    description="Soft-deletes an app template (admin only)",
    responses=responses.get_responses([400, 401, 403, 404, 409]),
)
async def delete_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Soft-delete an app template."""
    service = container.app_template_service()
    user = container.user()

    await service.delete_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


@router.post(
    "/{template_id}/rollback",
    response_model=AppTemplateAdminPublic,
    status_code=200,
    summary="Rollback app template",
    description="Restores template to original snapshot (admin only)",
    responses=responses.get_responses([400, 401, 403, 404]),
)
async def rollback_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Rollback an app template to its original state."""
    service = container.app_template_service()
    user = container.user()

    template = await service.rollback_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
    )

    return AppTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        wizard=template.wizard,
        input_type=template.input_type,
        input_description=template.input_description,
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
    response_model=AppTemplateAdminPublic,
    status_code=200,
    summary="Restore deleted app template",
    description="Restores a soft-deleted template (admin only)",
    responses=responses.get_responses([400, 401, 403, 404]),
)
async def restore_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Restore a soft-deleted app template."""
    service = container.app_template_service()
    user = container.user()

    template = await service.restore_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )

    return AppTemplateAdminPublic(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        prompt_text=template.prompt_text,
        completion_model_kwargs=template.completion_model_kwargs or {},
        wizard=template.wizard,
        input_type=template.input_type,
        input_description=template.input_description,
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
    summary="Permanently delete app template",
    description="Permanently removes a soft-deleted template from database (admin only)",
    responses=responses.get_responses([401, 403, 404]),
)
async def permanent_delete_template(
    template_id: "UUID",
    container: Container = Depends(get_container(with_user=True)),
):
    """Permanently delete a soft-deleted app template (hard delete)."""
    service = container.app_template_service()
    user = container.user()

    await service.permanent_delete_template(
        template_id=template_id,
        tenant_id=user.tenant_id,
    )


@router.get(
    "/deleted",
    response_model=AppTemplateAdminListPublic,
    status_code=200,
    summary="List deleted app templates",
    description="Returns soft-deleted templates for audit trail (admin only)",
    responses=responses.get_responses([401, 403]),
)
async def list_deleted_templates(
    container: Container = Depends(get_container(with_user=True))
):
    """List all deleted app templates for audit purposes with usage counts."""
    service = container.app_template_service()
    user = container.user()

    templates_with_usage = await service.get_deleted_templates_for_tenant(tenant_id=user.tenant_id)

    items = [
        AppTemplateAdminPublic(
            id=t.id,
            name=t.name,
            description=t.description,
            category=t.category,
            prompt_text=t.prompt_text,
            completion_model_kwargs=t.completion_model_kwargs or {},
            wizard=t.wizard,
            input_type=t.input_type,
            input_description=t.input_description,
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

    return AppTemplateAdminListPublic(items=items)

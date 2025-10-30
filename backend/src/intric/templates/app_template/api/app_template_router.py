from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.templates.app_template.api.app_template_models import (
    AppTemplateListPublic,
)

router = APIRouter()


@router.get(
    "/",
    response_model=AppTemplateListPublic,
    status_code=200,
    summary="List available app templates",
    description="""
Get app templates available for creating new apps.

**Feature Flag Behavior:**
- If `using_templates` feature is disabled: Returns empty list (not an error)
- If `using_templates` feature is enabled: Returns all available templates

**Template Scope:**
- Global templates (tenant_id = NULL): Available to all tenants
- Tenant-specific templates: Only available to that tenant

**Response:**
Returns paginated list of templates with basic information for gallery display.
    """,
    responses=responses.get_responses([401]),
    response_model_exclude_none=True,
)
async def get_templates(
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get app templates for gallery.

    Returns templates available to the current user's tenant. If the templates
    feature is disabled, returns an empty list instead of an error.

    **Example Response:**
    ```json
    {
      "items": [
        {
          "id": "123e4567-e89b-12d3-a456-426614174000",
          "name": "Document Analyzer",
          "description": "Analyzes uploaded documents and extracts insights",
          "category": "Analysis",
          "type": "app",
          "app": {
            "name": "Document Analyzer",
            "completion_model": {"id": "gpt-4"},
            "completion_model_kwargs": {"temperature": 0.3},
            "prompt": {"text": "Analyze the following document..."},
            "input_type": "file",
            "input_description": "Upload PDF or text document"
          },
          "wizard": {
            "attachments": {"required": true, "title": "Upload documents"},
            "collections": null
          },
          "organization": {"name": "default"},
          "created_at": "2025-10-27T10:00:00Z",
          "updated_at": "2025-10-27T10:00:00Z"
        }
      ],
      "count": 1
    }
    ```
    """
    service = container.app_template_service()
    assembler = container.app_template_assembler()
    user = container.user()

    # Pass tenant_id for feature flag check and filtering
    app_templates = await service.get_app_templates(tenant_id=user.tenant_id)

    return assembler.to_paginated_response(items=app_templates)

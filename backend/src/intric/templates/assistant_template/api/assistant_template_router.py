from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.templates.assistant_template.api.assistant_template_models import (
    AssistantTemplateListPublic,
)

router = APIRouter()


@router.get(
    "/",
    response_model=AssistantTemplateListPublic,
    status_code=200,
    summary="List available assistant templates",
    description="""
Get assistant templates available for creating new assistants.

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
    container: Container = Depends(get_container(with_user=True))
):
    """
    Get assistant templates for gallery.

    Returns templates available to the current user's tenant. If the templates
    feature is disabled, returns an empty list instead of an error.

    **Example Response:**
    ```json
    {
      "items": [
        {
          "id": "123e4567-e89b-12d3-a456-426614174000",
          "name": "Customer Support Assistant",
          "description": "Handles customer inquiries professionally",
          "category": "Support",
          "type": "assistant",
          "assistant": {
            "name": "Customer Support Assistant",
            "completion_model": {"id": "gpt-4"},
            "completion_model_kwargs": {"temperature": 0.7},
            "prompt": {"text": "You are a helpful customer support agent..."}
          },
          "wizard": {
            "attachments": {"required": false, "title": "Add documents"},
            "collections": {"required": true, "title": "Select knowledge base"}
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
    service = container.assistant_template_service()
    assembler = container.assistant_template_assembler()
    user = container.user()

    # Pass tenant_id for feature flag check and filtering
    templates = await service.get_assistant_templates(tenant_id=user.tenant_id)

    return assembler.to_paginated_response(templates)

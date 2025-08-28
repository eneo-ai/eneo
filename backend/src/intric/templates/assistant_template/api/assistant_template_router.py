
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
    responses=responses.get_responses([400, 404]),
)
async def get_templates(container: Container = Depends(get_container(with_user=True))):
    """Get all assistant templates"""
    service = container.assistant_template_service()
    assembler = container.assistant_template_assembler()

    templates = await service.get_assistant_templates()

    return assembler.to_paginated_response(templates)

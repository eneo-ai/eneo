
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
    responses=responses.get_responses([400, 404]),
)
async def get_templates(
    container: Container = Depends(get_container(with_user=True)),
):
    """Get all app templates"""
    service = container.app_template_service()
    assembler = container.app_template_assembler()

    app_templates = await service.get_app_templates()

    return assembler.to_paginated_response(items=app_templates)

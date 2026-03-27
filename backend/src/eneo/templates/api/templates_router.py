from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.templates.api.template_models import TemplateListPublic

router = APIRouter()


@router.get(
    "/",
    response_model=TemplateListPublic,
    status_code=200,
)
async def get_templates(container: Container = Depends(get_container(with_user=True))):
    """Get all types of templates"""
    template_service = container.template_service()

    templates = await template_service.get_templates()

    template_assembler = container.template_assembler()

    return template_assembler.to_paginated_response(templates=templates)

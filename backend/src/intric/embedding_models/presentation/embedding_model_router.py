from uuid import UUID

from fastapi import APIRouter, Depends

from intric.jobs.job_models import JobPublic

from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelMigrationRequest,
    EmbeddingModelPublic,
    EmbeddingModelUpdate,
)
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[EmbeddingModelPublic])
async def get_embedding_models(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.embedding_model_crud_service()
    models = await service.get_embedding_models()

    return PaginatedResponse(items=[EmbeddingModelPublic.from_domain(model) for model in models])


@router.get(
    "/{id}/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([404]),
)
async def get_embedding_model(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.embedding_model_crud_service()
    model = await service.get_embedding_model(model_id=id)

    return EmbeddingModelPublic.from_domain(model)


@router.post(
    "/{id}/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([404]),
)
async def update_embedding_model(
    id: UUID,
    update: EmbeddingModelUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.embedding_model_crud_service()
    model = await service.update_embedding_model(
        model_id=id,
        is_org_enabled=update.is_org_enabled,
        security_classification=update.security_classification,
    )

    return EmbeddingModelPublic.from_domain(model)


@router.post(
    "/migrate",
    response_model=JobPublic,
    responses=responses.get_responses([400]),
)
async def migrate_embedding_model(
    request: EmbeddingModelMigrationRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.embedding_model_migration_service()
    job = await service.start_migration(
        old_embedding_model_id=request.old_embedding_model_id,
        new_embedding_model_id=request.new_embedding_model_id,
        group_limit=request.group_limit,
    )

    return job

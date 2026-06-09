from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from intric.jobs.job_models import JobPublic
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[JobPublic],
    description="List the current user's running jobs.",
    responses=responses.get_responses([]),
)
async def get_running_jobs(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    job_service = container.job_service()
    jobs = await job_service.get_running_jobs()

    return protocol.to_paginated_response(jobs)


@router.get(
    "/{id}/",
    response_model=JobPublic,
    description="Get a single job owned by the current user by id.",
    responses=responses.get_responses([404]),
)
async def get_job(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    job_service = container.job_service()
    return await job_service.get_job(id)

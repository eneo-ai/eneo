from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from intric.jobs.job_models import JobPublic
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[JobPublic])
async def get_running_jobs(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    job_service = container.job_service()
    jobs = await job_service.get_running_jobs()

    return protocol.to_paginated_response(jobs)


@router.get("/{id}/", response_model=JobPublic)
async def get_job(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    job_service = container.job_service()
    return await job_service.get_job(id)

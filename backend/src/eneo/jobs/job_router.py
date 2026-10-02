from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sse_starlette import EventSourceResponse

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.jobs.job_events import stream_job_events
from eneo.jobs.job_models import JobPublic
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[JobPublic],
    description="List the current user's running jobs.",
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="JobService authorizes access to the requested job.",
)
async def get_running_jobs(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    job_service = container.job_service()
    jobs = await job_service.get_running_jobs()

    return protocol.to_paginated_response(jobs)


@router.get(
    "/events/",
    description=(
        "Stream the current user's job updates as server-sent events. Each "
        "`job` event carries the job as GET /jobs/ returns it, sent whenever "
        "its status changes; the connection stays open until the client closes it."
    ),
    responses=responses.streaming_response(models=[JobPublic]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="The stream is bound to the authenticated user's own job channel.",
)
async def job_events(
    request: Request,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> EventSourceResponse:
    user = container.user()
    return EventSourceResponse(
        stream_job_events(user.id, request),
        ping=15,
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/{id}/",
    response_model=JobPublic,
    description="Get a single job owned by the current user by id.",
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="JobService authorizes access to the requested job.",
)
async def get_job(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    job_service = container.job_service()
    return await job_service.get_job(id)

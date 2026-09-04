from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.websites.presentation.website_models import CrawlRunPublic

router = APIRouter()
logger = get_logger(__name__)

ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]


@router.get(
    "/{id}/", response_model=CrawlRunPublic, responses=responses.get_responses([404])
)
async def get_crawl_run(
    id: Annotated[
        UUID, Path(description="Unique identifier of the crawl run to retrieve")
    ],
    container: ContainerDep,
) -> CrawlRunPublic:
    service = container.website_crud_service()
    return CrawlRunPublic.from_domain(await service.get_crawl_run(id=id))


@router.post(
    "/{id}/cancel/",
    response_model=CrawlRunPublic,
    responses=responses.get_responses([403, 404]),
    summary="Stop a crawl run",
    description=(
        "Persist an idempotent cancellation request. Queued work stops immediately; "
        "running work transitions through the stopping phase."
    ),
)
async def cancel_crawl_run(
    id: Annotated[UUID, Path(description="Unique identifier of the crawl run to stop")],
    container: ContainerDep,
) -> CrawlRunPublic:
    service = container.website_crud_service()
    return CrawlRunPublic.from_domain(await service.cancel_crawl_run(id=id))

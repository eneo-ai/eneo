from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.websites.domain.crawl_run import CrawlResourceKind
from eneo.websites.presentation.website_models import (
    CrawlFailurePagePublic,
    CrawlResourceFailurePublic,
    CrawlRunPublic,
)

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


@router.get(
    "/{id}/failures/",
    response_model=CrawlFailurePagePublic,
    responses=responses.get_responses([400, 403, 404]),
    summary="List failed crawl addresses",
    description="Read a bounded page of recorded page and file failures, oldest first. Older runs retain aggregate counts but may have no recorded addresses.",
)
async def get_crawl_failures(
    id: Annotated[UUID, Path(description="Unique identifier of the crawl run")],
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: Annotated[UUID | None, Query()] = None,
    kind: Annotated[CrawlResourceKind | None, Query()] = None,
) -> CrawlFailurePagePublic:
    run, page = await container.website_crud_service().get_crawl_failures(
        id, limit=limit, cursor=cursor, kind=kind
    )
    return CrawlFailurePagePublic(
        run=CrawlRunPublic.from_domain(run),
        details_available=run.failure_details_available,
        items=[
            CrawlResourceFailurePublic.model_validate(item, from_attributes=True)
            for item in page.items
        ],
        limit=limit,
        total_count=page.total_count,
        next_cursor=str(page.next_cursor) if page.next_cursor else None,
    )


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

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from intric.info_blobs import info_blob_protocol
from intric.info_blobs.info_blob import InfoBlobPublicNoText
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses, to_paginated_response
from intric.spaces.api.space_models import TransferRequest
from intric.websites.presentation.website_models import (
    CrawlRunPublic,
    WebsiteCreateRequestDeprecated,
    WebsitePublic,
    WebsiteUpdate,
)

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[WebsitePublic], deprecated=True)
async def get_websites(
    for_tenant: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    return HTTPException(status_code=410, detail="This endpoint is deprecated")


@router.post("/", response_model=WebsitePublic, deprecated=True)
async def create_website(
    crawl: WebsiteCreateRequestDeprecated,
    container: Container = Depends(get_container(with_user=True)),
):
    return HTTPException(status_code=410, detail="This endpoint is deprecated")


@router.get("/{id}/", response_model=WebsitePublic, responses=responses.get_responses([404]))
async def get_website(id: UUID, container: Container = Depends(get_container(with_user=True))):
    service = container.website_crud_service()
    website = await service.get_website(id)

    return WebsitePublic.from_domain(website)


@router.post("/{id}/", response_model=WebsitePublic, responses=responses.get_responses([404]))
async def update_website(
    id: UUID,
    website_update: WebsiteUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.website_crud_service()

    website = await service.update_website(
        id=id,
        url=website_update.url,
        name=website_update.name,
        download_files=website_update.download_files,
        crawl_type=website_update.crawl_type,
        update_interval=website_update.update_interval,
    )

    return WebsitePublic.from_domain(website)


@router.delete("/{id}/", status_code=200, responses=responses.get_responses([404]))
async def delete_website(id: UUID, container: Container = Depends(get_container(with_user=True))):
    service = container.website_crud_service()
    await service.delete_website(id)
    return {"id": id, "deletion_info": {"success": True}}

@router.post(
    "/{id}/run/",
    response_model=CrawlRunPublic,
    responses=responses.get_responses([403, 404]),
)
async def run_crawl(id: UUID, container: Container = Depends(get_container(with_user=True))):
    # MIT License

    service = container.website_crud_service()
    crawl_run = await service.crawl_website(id)

    return CrawlRunPublic.from_domain(crawl_run)


@router.get("/{id}/runs/", response_model=PaginatedResponse[CrawlRunPublic])
async def get_crawl_runs(id: UUID, container: Container = Depends(get_container(with_user=True))):
    service = container.website_crud_service()
    crawl_runs = await service.get_crawl_runs(id)

    return to_paginated_response(
        [CrawlRunPublic.from_domain(crawl_run) for crawl_run in crawl_runs]
    )


@router.post("/{id}/transfer/", status_code=204)
async def transfer_website_to_space(
    id: UUID,
    transfer_req: TransferRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.resource_mover_service()
    await service.link_website_to_space(website_id=id, space_id=transfer_req.target_space_id)


@router.get(
    "/{id}/info-blobs/",
    response_model=PaginatedResponse[InfoBlobPublicNoText],
    responses=responses.get_responses([400, 404]),
)
async def get_info_blobs(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.info_blob_service()

    info_blobs_in_db = await service.get_by_website(id)

    info_blobs_public = [
        info_blob_protocol.to_info_blob_public_no_text(blob) for blob in info_blobs_in_db
    ]

    return protocol.to_paginated_response(info_blobs_public)

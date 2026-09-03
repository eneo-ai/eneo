from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.info_blobs import info_blob_protocol
from eneo.info_blobs.info_blob import InfoBlobPublicNoText
from eneo.main.container.container import Container
from eneo.main.models import CursorPaginatedResponse, PaginatedResponse
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses, to_paginated_response
from eneo.spaces.api.space_models import TransferRequest
from eneo.websites.presentation.website_models import (
    BulkCrawlRequest,
    BulkCrawlResponse,
    BulkCrawlStopResponse,
    BulkWebsiteDeleteResponse,
    CrawlRunPublic,
    WebsiteBulkActionError,
    WebsiteCreateRequestDeprecated,
    WebsiteExistsResponse,
    WebsitePublic,
    WebsiteUpdate,
)

router = APIRouter()

ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]


@router.get(
    "/",
    response_model=PaginatedResponse[WebsitePublic],
    responses=responses.get_responses([410]),
    description="Deprecated: list websites. Always returns 410 Gone.",
    deprecated=True,
)
async def get_websites(
    container: ContainerDep,
    for_tenant: Annotated[
        bool,
        Query(description="Filter websites by tenant scope"),
    ] = False,
):
    raise HTTPException(status_code=410, detail="This endpoint is deprecated")


@router.post(
    "/",
    response_model=WebsitePublic,
    responses=responses.get_responses([410]),
    description="Deprecated: create a website. Always returns 410 Gone.",
    deprecated=True,
)
async def create_website(
    crawl: WebsiteCreateRequestDeprecated,
    container: ContainerDep,
):
    raise HTTPException(status_code=410, detail="This endpoint is deprecated")


@router.get(
    "/check-url/",
    response_model=WebsiteExistsResponse | None,
    responses=responses.get_responses([]),
    summary="Check if URL exists on Organization space",
    description="""
    Check if a website URL already exists on the user's Organization space.

    **Use case:**
    When creating a new website on a Personal or Shared space, call this endpoint
    to check if the URL is already being crawled on the Organization space.
    This helps avoid duplicate crawls and informs users that the knowledge
    might already be available for import.

    **Returns:**
    - Website info if URL exists on Organization space
    - `null` if URL not found or user has no Organization space

    **Note:** This does not block website creation - it's informational only.
    """,
)
async def check_existing_website_url(
    container: ContainerDep,
    url: Annotated[str, Query(description="The website URL to check")],
) -> WebsiteExistsResponse | None:
    """Check if URL exists on the Organization space."""
    service = container.website_crud_service()
    result = await service.find_on_organization_space(url)

    if result is None:
        return None

    return WebsiteExistsResponse.model_validate(result)


@router.post(
    "/bulk/run/",
    response_model=BulkCrawlResponse,
    responses=responses.get_responses([400, 403]),
    summary="Trigger bulk crawl",
    description="""
    Trigger crawls for multiple websites at once. Useful for:
    - Batch recrawling selected websites
    - Refreshing multiple knowledge sources simultaneously
    - Recovering from failed crawls across multiple sites

    **Features:**
    - Maximum 50 websites per request (safety limit)
    - Individual failures don't stop the batch
    - A website with an active crawl returns that existing run
    - Returns detailed status for each website

    **Example Request:**
    ```json
    {
      "website_ids": [
        "123e4567-e89b-12d3-a456-426614174000",
        "123e4567-e89b-12d3-a456-426614174001"
      ]
    }
    ```

    **Example Response:**
    ```json
    {
      "total": 2,
      "queued": 2,
      "failed": 0,
      "crawl_runs": [...],
      "errors": []
    }
    ```
    """,
)
async def bulk_run_crawl(
    request: BulkCrawlRequest,
    container: ContainerDep,
):
    """Trigger crawls for multiple websites in a single request."""
    import logging

    logger = logging.getLogger(__name__)

    logger.info(f"Bulk crawl request received: {len(request.website_ids)} websites")
    logger.debug(f"Website IDs: {request.website_ids}")

    service = container.website_crud_service()

    try:
        successful_runs, errors = await service.bulk_crawl_websites(request.website_ids)

        logger.info(
            f"Bulk crawl completed: {len(successful_runs)} queued, {len(errors)} failed"
        )
        if errors:
            logger.warning(f"Bulk crawl errors: {errors}")

        unique_total = len(set(request.website_ids))
        return BulkCrawlResponse(
            total=unique_total,
            queued=len(successful_runs),
            failed=len(errors),
            crawl_runs=[CrawlRunPublic.from_domain(run) for run in successful_runs],
            errors=[
                WebsiteBulkActionError(
                    website_id=error.website_id,
                    error=error.error,
                )
                for error in errors
            ],
        )
    except Exception as e:
        logger.error(f"Bulk crawl endpoint error: {str(e)}", exc_info=True)
        raise


@router.post(
    "/bulk/stop/",
    response_model=BulkCrawlStopResponse,
    responses=responses.get_responses([400, 403]),
    summary="Stop active crawls for selected websites",
    description=(
        "Stops the active crawl, if any, for up to 50 websites. Websites without "
        "an active crawl are reported separately and do not fail the batch."
    ),
)
async def bulk_stop_crawl(
    request: BulkCrawlRequest,
    container: ContainerDep,
) -> BulkCrawlStopResponse:
    service = container.website_crud_service()
    stopped_runs, not_running, errors = await service.bulk_stop_websites(
        request.website_ids
    )
    unique_total = len(dict.fromkeys(request.website_ids))
    return BulkCrawlStopResponse(
        total=unique_total,
        stopped=len(stopped_runs),
        not_running=len(not_running),
        failed=len(errors),
        crawl_runs=[CrawlRunPublic.from_domain(run) for run in stopped_runs],
        errors=[
            WebsiteBulkActionError(website_id=error.website_id, error=error.error)
            for error in errors
        ],
    )


@router.post(
    "/bulk/delete/",
    response_model=BulkWebsiteDeleteResponse,
    responses=responses.get_responses([400, 403]),
    summary="Delete selected website sources",
    description=(
        "Permanently deletes up to 50 website sources, their indexed content, "
        "and their crawl history. Sources with active crawls remain in place while "
        "their crawl is stopped and must be submitted again after cleanup completes."
    ),
)
async def bulk_delete_websites(
    request: BulkCrawlRequest,
    container: ContainerDep,
) -> BulkWebsiteDeleteResponse:
    service = container.website_crud_service()
    user = container.user()
    deleted, not_found, errors = await service.bulk_delete_websites(request.website_ids)

    audit_service = container.audit_service()
    for website in deleted:
        assert website.id is not None
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.WEBSITE_DELETED,
            entity_type=EntityType.WEBSITE,
            entity_id=website.id,
            description=f"Deleted website '{website.url}'",
            metadata=AuditMetadata.standard(
                actor=user,
                target=website,
                extra={"url": website.url},
            ),
        )

    unique_total = len(dict.fromkeys(request.website_ids))
    return BulkWebsiteDeleteResponse(
        total=unique_total,
        deleted=len(deleted),
        not_found=len(not_found),
        failed=len(errors),
        errors=[
            WebsiteBulkActionError(website_id=error.website_id, error=error.error)
            for error in errors
        ],
    )


@router.get(
    "/{id}/",
    response_model=WebsitePublic,
    responses=responses.get_responses([403, 404]),
)
async def get_website(
    id: Annotated[UUID, Path(description="Unique identifier of the website")],
    container: ContainerDep,
):
    service = container.website_crud_service()
    website = await service.get_website(id)

    return WebsitePublic.from_domain(website)


@router.post(
    "/{id}/",
    response_model=WebsitePublic,
    responses=responses.get_responses([403, 404]),
    description="Update a website's configuration by id.",
)
async def update_website(
    website_update: WebsiteUpdate,
    id: Annotated[UUID, Path(description="Unique identifier of the website to update")],
    container: ContainerDep,
):
    service = container.website_crud_service()
    user = container.user()

    # Update website
    website = await service.update_website(
        id=id,
        url=website_update.url,
        name=website_update.name,
        download_files=website_update.download_files,
        crawl_type=website_update.crawl_type,
        update_interval=website_update.update_interval,
        http_auth_username=website_update.http_auth_username,
        http_auth_password=website_update.http_auth_password,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.WEBSITE_UPDATED,
        entity_type=EntityType.WEBSITE,
        entity_id=id,
        description=f"Updated website '{website.url}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=website,
            extra={"url": website.url},
        ),
    )

    return WebsitePublic.from_domain(website)


@router.delete(
    "/{id}/",
    status_code=200,
    response_model=None,
    responses=responses.get_responses([403, 404, 409]),
    description=(
        "Delete a website by id. Returns a conflict while its crawl is active or "
        "durable crawler cleanup is still pending."
    ),
)
async def delete_website(
    id: Annotated[UUID, Path(description="Unique identifier of the website to delete")],
    container: ContainerDep,
):
    service = container.website_crud_service()
    user = container.user()

    website = await service.delete_website(id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.WEBSITE_DELETED,
        entity_type=EntityType.WEBSITE,
        entity_id=id,
        description=f"Deleted website '{website.url}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=website,
            extra={"url": website.url},
        ),
    )

    return {"id": id, "deletion_info": {"success": True}}


@router.post(
    "/{id}/run/",
    response_model=CrawlRunPublic,
    responses=responses.get_responses([403, 404, 429]),
    summary="Trigger a crawl",
    description="""
    Manually trigger or retry a crawl for a specific website. If the website
    already has an active crawl, the existing durable run is returned instead
    of creating duplicate work.

    The crawl will use the website's configured settings (crawler engine, crawl type, etc.).

    `phase` describes the lifecycle (`pending_dispatch`, `queued`, `running`,
    `finalizing`, `stopping`, or `terminal`). A terminal run's `outcome`
    describes whether it completed, failed, or was cancelled.
    """,
)
async def run_crawl(
    id: Annotated[UUID, Path(description="Unique identifier of the website to crawl")],
    container: ContainerDep,
):
    # MIT License

    service = container.website_crud_service()
    crawl_run = await service.crawl_website(id)

    return CrawlRunPublic.from_domain(crawl_run)


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[CrawlRunPublic],
    responses=responses.get_responses([403, 404]),
    description="List crawl runs for a website by id.",
)
async def get_crawl_runs(
    id: Annotated[UUID, Path(description="Unique identifier of the website")],
    container: ContainerDep,
):
    service = container.website_crud_service()
    crawl_runs = await service.get_crawl_runs(id)

    return to_paginated_response(
        [CrawlRunPublic.from_domain(crawl_run) for crawl_run in crawl_runs]
    )


@router.post(
    "/{id}/transfer/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
    description="Transfer a website to another space by id.",
)
async def transfer_website_to_space(
    transfer_req: TransferRequest,
    id: Annotated[
        UUID, Path(description="Unique identifier of the website to transfer")
    ],
    container: ContainerDep,
):
    # Transfer website (do this FIRST to avoid DI issues)
    service = container.resource_mover_service()
    await service.link_website_to_space(
        website_id=id, space_id=transfer_req.target_space_id
    )

    # Get user and website info AFTER transfer for audit logging
    user = container.user()
    website_service = container.website_crud_service()
    website = await website_service.get_website(id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.WEBSITE_TRANSFERRED,
        entity_type=EntityType.WEBSITE,
        entity_id=id,
        description=f"Transferred website '{website.url}' to new space",
        metadata=AuditMetadata.standard(
            actor=user,
            target=website,
            extra={
                "url": website.url,
                "target_space_id": str(transfer_req.target_space_id),
            },
        ),
    )


@router.get(
    "/{id}/info-blobs/",
    response_model=PaginatedResponse[InfoBlobPublicNoText],
    responses=responses.get_responses([400, 403, 404]),
)
async def get_info_blobs(
    id: Annotated[UUID, Path(description="Unique identifier of the website")],
    container: ContainerDep,
) -> PaginatedResponse[InfoBlobPublicNoText]:
    service = container.info_blob_service()
    info_blobs = await service.get_by_website(id)
    public_info_blobs = [
        info_blob_protocol.to_info_blob_public_no_text(blob) for blob in info_blobs
    ]
    return to_paginated_response(public_info_blobs)


@router.get(
    "/{id}/info-blobs/page/",
    response_model=CursorPaginatedResponse[InfoBlobPublicNoText],
    responses=responses.get_responses([400, 403, 404]),
)
async def get_info_blob_page(
    id: Annotated[UUID, Path(description="Unique identifier of the website")],
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: Annotated[UUID | None, Query()] = None,
) -> CursorPaginatedResponse[InfoBlobPublicNoText]:
    service = container.info_blob_service()

    page = await service.get_by_website_page(
        id,
        limit=limit,
        cursor=cursor,
    )

    info_blobs_public = [
        info_blob_protocol.to_info_blob_public_no_text(blob) for blob in page.items
    ]

    return CursorPaginatedResponse(
        items=info_blobs_public,
        limit=limit,
        next_cursor=str(page.next_cursor) if page.next_cursor is not None else None,
        total_count=page.total_count,
    )

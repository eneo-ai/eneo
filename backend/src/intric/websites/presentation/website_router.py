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
    BulkCrawlRequest,
    BulkCrawlResponse,
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
      "queued": 1,
      "failed": 1,
      "crawl_runs": [...],
      "errors": [
        {
          "website_id": "123e4567-e89b-12d3-a456-426614174001",
          "error": "Crawl already in progress for this website"
        }
      ]
    }
    ```
    """,
)
async def bulk_run_crawl(
    request: BulkCrawlRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """Trigger crawls for multiple websites in a single request."""
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"Bulk crawl request received: {len(request.website_ids)} websites")
    logger.debug(f"Website IDs: {request.website_ids}")

    service = container.website_crud_service()

    try:
        successful_runs, errors = await service.bulk_crawl_websites(request.website_ids)

        logger.info(f"Bulk crawl completed: {len(successful_runs)} queued, {len(errors)} failed")
        if errors:
            logger.warning(f"Bulk crawl errors: {errors}")

        return BulkCrawlResponse(
            total=len(request.website_ids),
            queued=len(successful_runs),
            failed=len(errors),
            crawl_runs=[CrawlRunPublic.from_domain(run) for run in successful_runs],
            errors=errors,
        )
    except Exception as e:
        logger.error(f"Bulk crawl endpoint error: {str(e)}", exc_info=True)
        raise


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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

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
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.WEBSITE_UPDATED,
        entity_type=EntityType.WEBSITE,
        entity_id=id,
        description=f"Updated website '{website.url}'",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "website_id": str(id),
                "url": website.url,
                "name": website.name,
            },
        },
    )

    return WebsitePublic.from_domain(website)


@router.delete("/{id}/", status_code=200, responses=responses.get_responses([404]))
async def delete_website(id: UUID, container: Container = Depends(get_container(with_user=True))):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.website_crud_service()
    user = container.user()

    # Get website info before deletion
    website = await service.get_website(id)

    # Delete website
    await service.delete_website(id)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.WEBSITE_DELETED,
        entity_type=EntityType.WEBSITE,
        entity_id=id,
        description=f"Deleted website '{website.url}'",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "website_id": str(id),
                "url": website.url,
                "name": website.name,
            },
        },
    )

    return {"id": id, "deletion_info": {"success": True}}

@router.post(
    "/{id}/run/",
    response_model=CrawlRunPublic,
    responses=responses.get_responses([403, 404]),
    summary="Trigger a crawl",
    description="""
    Manually trigger a crawl for a specific website. This can be used to:
    - Recrawl a website to update its content
    - Force a crawl outside the automatic update schedule
    - Retry a failed crawl

    The crawl will use the website's configured settings (crawler engine, crawl type, etc.).

    **Status Flow:**
    1. `queued` - Crawl is waiting to start
    2. `in progress` - Crawl is actively running
    3. `complete` - Crawl finished successfully
    4. `failed` - Crawl encountered an error

    Returns the new crawl run with status information.
    """,
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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    # Transfer website (do this FIRST to avoid DI issues)
    service = container.resource_mover_service()
    await service.link_website_to_space(website_id=id, space_id=transfer_req.target_space_id)

    # Get user and website info AFTER transfer for audit logging
    user = container.user()
    website_service = container.website_crud_service()
    website = await website_service.get_website(id)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.WEBSITE_TRANSFERRED,
        entity_type=EntityType.WEBSITE,
        entity_id=id,
        description="Transferred website to new space",
        metadata={
            "actor": {
                "id": str(user.id),
                "name": user.username,
                "email": user.email,
            },
            "target": {
                "website_id": str(id),
                "url": website.url,
                "target_space_id": str(transfer_req.target_space_id),
            },
        },
    )


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

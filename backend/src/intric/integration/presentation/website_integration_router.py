from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.database.tables.website_integration_table import WebsiteIntegrationConfig
from intric.jobs.job_models import JobPublic
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


async def _queue_website_sync_with_token(
    config_id: UUID,
    token: Annotated[str, Query(min_length=1)],
    container: Annotated[Container, Depends(get_container(with_user=False))],
):
    config = await container.session().get(WebsiteIntegrationConfig, config_id)  # type: ignore[union-attr]
    if config is None:
        from intric.main.exceptions import NotFoundException

        raise NotFoundException("Website integration not found")

    user = await container.user_repo().get_user_by_id(config.created_by_user_id)
    if user is None:
        from intric.main.exceptions import NotFoundException

        raise NotFoundException("Website integration owner not found")

    from intric.main.container.container_overrides import override_user

    override_user(container=container, user=user)
    service = container.website_integration_service()
    job = await service.queue_sync_for_token(config_id=config_id, ping_token=token)
    return JobPublic.model_validate(job)


@router.post(
    "/websites/{config_id}/sync/",
    response_model=JobPublic,
    status_code=202,
    responses=responses.get_responses([404]),
    summary="Queue website integration sync",
    description="""
    Queue a sitemap-based website integration sync using the integration-specific token.

    This endpoint is the primary sync webhook URL exposed in the UI. It validates the
    token, fetches the integration config, and queues a background job that checks the
    sitemap for new or updated pages.
    """,
)
async def sync_website_integration_endpoint(
    config_id: UUID,
    token: Annotated[str, Query(min_length=1)],
    container: Annotated[Container, Depends(get_container(with_user=False))],
):
    return await _queue_website_sync_with_token(
        config_id=config_id,
        token=token,
        container=container,
    )

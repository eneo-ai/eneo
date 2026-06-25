from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.database.tables.website_integration_table import WebsiteIntegrationConfig
from intric.jobs.job_models import JobPublic
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


class _WebsiteIntegrationConfigWithCreator(Protocol):
    created_by_user_id: UUID


async def _queue_website_sync_with_token(
    config_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=False))],
    webhook_token: Annotated[str | None, Query(min_length=1)] = None,
    token: Annotated[str | None, Query(min_length=1)] = None,
):
    config = await container.session().get(WebsiteIntegrationConfig, config_id)  # type: ignore[union-attr]
    if config is None:
        from intric.main.exceptions import NotFoundException

        raise NotFoundException("Sitemap webhook integration not found")

    typed_config = cast(_WebsiteIntegrationConfigWithCreator, config)
    created_by_user_id = typed_config.created_by_user_id
    user = await container.user_repo().get_user_by_id(created_by_user_id)
    if user is None:
        from intric.main.exceptions import NotFoundException

        raise NotFoundException("Sitemap webhook integration owner not found")

    from intric.main.container.container_overrides import override_user

    override_user(container=container, user=user)
    service = container.website_integration_service()
    resolved_token = webhook_token or token
    if resolved_token is None:
        from intric.main.exceptions import BadRequestException

        raise BadRequestException("webhook_token is required")
    job = await service.queue_webhook_sync_for_token(
        config_id=config_id, webhook_token=resolved_token
    )
    return JobPublic.model_validate(job)


@router.post(
    "/websites/{config_id}/sync/",
    response_model=JobPublic,
    status_code=202,
    responses=responses.get_responses([404]),
    summary="Queue sitemap webhook integration sync",
    description="""
    Queue a sitemap webhook integration sync using the integration-specific webhook token.

    This endpoint is the primary webhook URL exposed in the UI. It validates the
    webhook token, fetches the integration config, and queues a background job that
    checks the sitemap for new or updated pages.
    """,
)
async def trigger_sitemap_webhook_integration_endpoint(
    config_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=False))],
    webhook_token: Annotated[str | None, Query(min_length=1)] = None,
    token: Annotated[str | None, Query(min_length=1)] = None,
):
    return await _queue_website_sync_with_token(
        config_id=config_id,
        webhook_token=webhook_token,
        token=token,
        container=container,
    )

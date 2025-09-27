from uuid import UUID

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.websites.crawl_dependencies.crawl_models import CrawlRunPublic

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/{id}/",
    response_model=CrawlRunPublic,
    responses=responses.get_responses([404]),
    summary="Get crawl run details",
    description="Retrieve detailed information about a specific crawl run, including status, metrics, and timing."
)
async def get_crawl_run(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get detailed information about a specific crawl run.

    Returns comprehensive crawl run information including:
    - Current status (queued, in_progress, complete, failed)
    - Performance metrics (pages crawled, files downloaded)
    - Error counts (pages failed, files failed)
    - Timing information (start time, completion time)
    - Result location for accessing the crawled content

    This endpoint is useful for monitoring crawl progress and troubleshooting
    crawl issues. Use this in combination with WebSocket notifications for
    real-time status updates.

    Args:
        id: The UUID of the crawl run to retrieve

    Returns:
        CrawlRunPublic: Detailed crawl run information

    Raises:
        404: If the crawl run doesn't exist or user doesn't have access
    """
    service = container.website_crud_service()
    return await service.get_crawl_run(id=id)

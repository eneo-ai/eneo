from uuid import UUID

from fastapi import APIRouter, Depends, Path

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.websites.crawl_dependencies.crawl_models import CrawlRunPublic

router = APIRouter()
logger = get_logger(__name__)


@router.get("/{id}/", response_model=CrawlRunPublic, responses=responses.get_responses([404]))
async def get_crawl_run(
    id: UUID = Path(description="Unique identifier of the crawl run to retrieve"),
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.website_crud_service()
    return await service.get_crawl_run(id=id)

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitConfig,
    RateLimitServiceUnavailableError,
    check_rate_limit,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import get_container
from eneo.websites.application.crawl_webhook import (
    lock_website,
    request_crawl,
    verify_token,
)
from eneo.websites.domain.crawl_run import CrawlType
from eneo.websites.domain.website import UpdateInterval

router = APIRouter()
logger = get_logger(__name__)
WebhookContainer = Annotated[
    Container, Depends(get_container(transaction_scope="function"))
]


class CrawlWebhookResponse(BaseModel):
    status: Literal["queued", "pending", "coalesced"]


@router.post(
    "/websites/{website_id}/crawl",
    status_code=202,
    response_model=CrawlWebhookResponse,
    description="Request a sitemap crawl using a bearer webhook token. Concurrent requests coalesce into one pending run.",
    responses={
        400: {"description": "HTTPS is required in production"},
        401: {"description": "Invalid token or inactive webhook"},
        429: {"description": "Webhook rate limit exceeded"},
        503: {"description": "Rate limiting is temporarily unavailable"},
    },
)
async def trigger_crawl(
    website_id: UUID,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    container: WebhookContainer,
    authorization: Annotated[str | None, Header()] = None,
):
    settings = get_settings()
    if settings.environment == "production" and request.url.scheme != "https":
        raise HTTPException(400, "HTTPS is required")
    response.headers["Cache-Control"] = "no-store"
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 256:
        raise HTTPException(401, "Invalid webhook credentials")
    website = await lock_website(cast(AsyncSession, container.session()), website_id)
    valid = verify_token(token, website.webhook_token_hash if website else None)
    if (
        not valid
        or website is None
        or website.update_interval != UpdateInterval.WEBHOOK
        or website.crawl_type != CrawlType.SITEMAP
    ):
        raise HTTPException(401, "Invalid webhook credentials")
    try:
        limit = await check_rate_limit(
            container.redis_client(),
            f"rate_limit:crawl_webhook:{website.tenant_id}:{website.id}",
            RateLimitConfig(
                max_requests=settings.crawl_webhook_rate_limit_per_minute,
                window_seconds=60,
            ),
        )
    except RateLimitServiceUnavailableError:
        raise HTTPException(503, "Rate limiting is temporarily unavailable") from None
    if not limit.allowed:
        raise HTTPException(
            429, "Webhook rate limit exceeded", headers={"Retry-After": "60"}
        )
    status = await request_crawl(cast(AsyncSession, container.session()), website)
    logger.info(
        "Crawl webhook accepted",
        extra={"website_id": str(website_id), "status": status},
    )
    from eneo.worker.crawl_webhook_dispatch import dispatch_after_commit

    background_tasks.add_task(dispatch_after_commit, website_id)
    return {"status": status}

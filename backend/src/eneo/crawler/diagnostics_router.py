from time import monotonic
from typing import Annotated, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import (
    require_permission,
    require_session_auth,
)
from eneo.crawler.diagnostics_models import (
    CrawlerCapacity,
    CrawlerDiagnosticsModel,
    CrawlerLimitsModel,
    CrawlerProbeModel,
    CrawlerWebsiteModel,
)
from eneo.crawler.engine import (
    CrawlFinished,
    CrawlLimits,
    CrawlRequest,
    PageCrawled,
    PageFailed,
    PageUnchanged,
)
from eneo.database.tables.websites_table import Websites
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenants.crawler_settings_helper import get_crawler_setting

router = APIRouter(
    dependencies=[Depends(require_permission(Permission.ADMIN))],
)

ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]


def _effective_limits(container: Container) -> CrawlerLimitsModel:
    settings = get_settings()
    tenant_settings = container.tenant().crawler_settings
    return CrawlerLimitsModel(
        max_pages=get_crawler_setting("closespider_itemcount", tenant_settings),
        max_crawl_seconds=get_crawler_setting("crawl_max_length", tenant_settings),
        request_timeout_seconds=get_crawler_setting(
            "download_timeout", tenant_settings
        ),
        max_page_bytes=settings.crawl_page_max_size,
        max_file_bytes=get_crawler_setting("download_max_size", tenant_settings),
        retries=get_crawler_setting("retry_times", tenant_settings),
        obey_robots=get_crawler_setting("obey_robots", tenant_settings),
    )


@router.get(
    "/diagnostics/",
    response_model=CrawlerDiagnosticsModel,
    responses=responses.get_responses([403]),
    description="Get tenant-scoped native crawler configuration and probe targets.",
)
async def get_crawler_diagnostics(container: ContainerDep) -> CrawlerDiagnosticsModel:
    settings = get_settings()
    tenant = container.tenant()
    session = cast(AsyncSession, container.session())
    rows = (
        await session.scalars(
            sa.select(Websites)
            .where(Websites.tenant_id == tenant.id)
            .order_by(Websites.name.asc().nulls_last(), Websites.url.asc())
            .limit(500)
        )
    ).all()

    return CrawlerDiagnosticsModel(
        capacity=CrawlerCapacity(
            max_http_requests_per_process=settings.crawl_global_http_concurrency,
            requests_per_crawl=settings.crawl_fetch_concurrency,
            max_concurrent_crawl_jobs=(settings.effective_crawl_job_concurrency_limit),
        ),
        limits=_effective_limits(container),
        # Whole-sitemap skipping is intentionally disabled until discovery edges
        # can be restored without re-reading unchanged parent pages.
        sitemap_change_detection=False,
        websites=[
            CrawlerWebsiteModel(
                id=website.id,
                name=website.name or website.url,
                url=website.url,
                crawl_type=website.crawl_type,
                requires_http_auth=bool(
                    website.http_auth_username and website.encrypted_auth_password
                ),
            )
            for website in rows
        ],
    )


async def _audit_probe(
    *,
    container: Container,
    website: Websites,
    result: CrawlerProbeModel,
) -> None:
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.WEBSITE_CRAWL_PROBED,
        entity_type=EntityType.WEBSITE,
        entity_id=website.id,
        description=f"Probed website crawler connectivity for '{website.url}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=website,
            extra={
                "outcome": result.outcome,
                "duration_ms": result.duration_ms,
                "reason": result.reason,
            },
        ),
    )


@router.post(
    "/diagnostics/{website_id}/probe/",
    response_model=CrawlerProbeModel,
    responses=responses.get_responses([403, 404]),
    description=(
        "Run a bounded, audited native crawler connectivity probe against one "
        "configured website owned by the current tenant."
    ),
)
async def probe_crawler_website(
    website_id: Annotated[UUID, Path(description="Configured website identifier")],
    container: ContainerDep,
    _session_guard: None = Depends(require_session_auth),
) -> CrawlerProbeModel:
    settings = get_settings()
    tenant = container.tenant()
    session = cast(AsyncSession, container.session())
    website = await session.scalar(
        sa.select(Websites).where(
            Websites.id == website_id,
            Websites.tenant_id == tenant.id,
        )
    )
    if website is None:
        raise HTTPException(status_code=404, detail="Website not found")

    http_user: str | None = None
    http_pass: str | None = None
    if website.http_auth_username and website.encrypted_auth_password:
        http_user = website.http_auth_username
        try:
            http_pass = container.http_auth_encryption_service().decrypt_password(
                website.encrypted_auth_password
            )
        except Exception:
            result = CrawlerProbeModel(
                website_id=website.id,
                url=website.url,
                crawl_type=website.crawl_type,
                outcome="failed",
                duration_ms=0,
                pages_crawled=0,
                pages_unchanged=0,
                pages_failed=1,
                reason="http_auth_unavailable",
            )
            await _audit_probe(container=container, website=website, result=result)
            return result

    effective = _effective_limits(container)
    request = CrawlRequest(
        url=website.url,
        crawl_type=website.crawl_type,
        download_files=False,
        obey_robots=effective.obey_robots,
        http_user=http_user,
        http_pass=http_pass,
        limits=CrawlLimits(
            max_pages=1,
            max_seconds=min(float(effective.max_crawl_seconds), 20.0),
            request_timeout_seconds=min(float(effective.request_timeout_seconds), 15.0),
            max_response_bytes=min(effective.max_page_bytes, 2 * 1024 * 1024),
            max_file_bytes=effective.max_file_bytes,
            dns_timeout_seconds=get_crawler_setting(
                "dns_timeout", tenant.crawler_settings
            ),
            concurrency=1,
            request_delay_seconds=settings.crawl_request_delay_seconds,
            retries=min(effective.retries, 1),
        ),
    )

    started = monotonic()
    pages_crawled = 0
    pages_unchanged = 0
    pages_failed = 0
    sample_title: str | None = None
    reason: str | None = None
    partial = False
    sitemap_snapshot_available = False
    try:
        async for event in container.crawler().crawl(request):
            if isinstance(event, PageCrawled):
                pages_crawled += 1
                sample_title = event.title
            elif isinstance(event, PageUnchanged):
                pages_unchanged += 1
            elif isinstance(event, PageFailed):
                pages_failed += 1
                reason = reason or event.reason
            elif isinstance(event, CrawlFinished):
                partial = event.status == "partial"
                reason = event.reason or reason
                sitemap_snapshot_available = event.sitemap_fingerprint is not None
    except Exception as exc:
        pages_failed += 1
        reason = type(exc).__name__

    if partial:
        outcome = "partial"
    elif pages_crawled:
        outcome = "reachable"
    elif pages_unchanged:
        outcome = "unchanged"
    else:
        outcome = "failed"

    result = CrawlerProbeModel(
        website_id=website.id,
        url=website.url,
        crawl_type=website.crawl_type,
        outcome=outcome,
        duration_ms=round((monotonic() - started) * 1000),
        pages_crawled=pages_crawled,
        pages_unchanged=pages_unchanged,
        pages_failed=pages_failed,
        sample_title=sample_title,
        reason=reason,
        sitemap_snapshot_available=sitemap_snapshot_available,
    )
    await _audit_probe(container=container, website=website, result=result)
    return result

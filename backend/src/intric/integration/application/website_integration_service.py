from __future__ import annotations

import hashlib
import json
import secrets
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import quote, urlparse
from uuid import UUID

import aiohttp
import sqlalchemy as sa
from pydantic import TypeAdapter

from intric.database.tables.integration_table import Integration as IntegrationDB
from intric.database.tables.integration_table import TenantIntegration
from intric.database.tables.website_integration_table import (
    WebsiteIntegrationConfig,
    WebsiteIntegrationPage,
)
from intric.database.tables.websites_spaces_table import WebsitesSpaces
from intric.database.tables.websites_table import Websites
from intric.info_blobs.text_processor import TextProcessor
from intric.integration.presentation.models import (
    IntegrationType,
    WebsiteIntegrationConfigCreate,
    WebsiteIntegrationConfigPublic,
    WebsiteIntegrationConfigUpdate,
    WebsiteIntegrationHeader,
    WebsiteIntegrationMarkdownMethod,
    WebsiteIntegrationMarkdownUrlLocation,
)
from intric.jobs.job_models import JobInDb, Task
from intric.jobs.job_service import JobService
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.logging import get_logger
from intric.main.models import is_provided
from intric.roles.permissions import Permission
from intric.spaces.space_service import SpaceService
from intric.users.user import UserInDB
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval, Website

if TYPE_CHECKING:
    from intric.database.database import AsyncSession
    from intric.embedding_models.infrastructure.datastore import Datastore
    from intric.info_blobs.info_blob_repo import InfoBlobRepository
    from intric.websites.application.website_crud_service import WebsiteCRUDService
    from intric.websites.domain.website import Website as WebsiteDomain
    from intric.websites.presentation.website_models import WebsiteUpdate

logger = get_logger(__name__)

_HEADER_ADAPTER = TypeAdapter(dict[str, str])


@dataclass
class SitemapPage:
    url: str
    lastmod: datetime | None


@dataclass
class SimpleMarkdownConfig:
    endpoint_url: str | None
    method: WebsiteIntegrationMarkdownMethod
    url_location: WebsiteIntegrationMarkdownUrlLocation
    param_name: str


class WebsiteIntegrationService:
    def __init__(
        self,
        *,
        session: "AsyncSession",
        user: UserInDB,
        space_service: SpaceService,
        job_service: JobService,
        website_crud_service: "WebsiteCRUDService",
        text_processor: TextProcessor,
        datastore: "Datastore",
        info_blob_repo: "InfoBlobRepository",
        aiohttp_session: aiohttp.ClientSession,
    ) -> None:
        super().__init__()
        self.session = session
        self.user = user
        self.space_service = space_service
        self.job_service = job_service
        self.website_crud_service = website_crud_service
        self.text_processor = text_processor
        self.datastore = datastore
        self.info_blob_repo = info_blob_repo
        self.aiohttp_session = aiohttp_session

    async def list_configs(
        self, *, owner_type: Literal["tenant", "user"]
    ) -> list[WebsiteIntegrationConfigPublic]:
        stmt = self._base_config_stmt(owner_type=owner_type)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return [self._to_public(row) for row in rows]

    async def create_config(
        self,
        *,
        owner_type: Literal["tenant", "user"],
        payload: WebsiteIntegrationConfigCreate,
    ) -> WebsiteIntegrationConfigPublic:
        tenant_integration = await self._get_or_create_website_tenant_integration()
        owner_space_id, owner_user_id = await self._resolve_owner(owner_type)
        name = payload.name.strip()
        sitemap_url = payload.sitemap_url.strip()
        if not name:
            raise BadRequestException("Sitemap webhook integration name is required")
        if not sitemap_url:
            raise BadRequestException("Sitemap URL is required")
        markdown_config = self._build_page_content_webhook_config(
            page_content_webhook_url=(
                str(payload.page_content_webhook_url).strip()
                if payload.page_content_webhook_url
                else None
            ),
            page_content_webhook_method=payload.page_content_webhook_method,
            page_content_webhook_url_location=payload.page_content_webhook_url_location,
            page_content_webhook_url_param_name=payload.page_content_webhook_url_param_name,
        )

        config = cast(Any, WebsiteIntegrationConfig)(
            tenant_integration_id=tenant_integration.id,
            tenant_id=self.user.tenant_id,
            owner_type=owner_type,
            owner_user_id=owner_user_id,
            owner_space_id=owner_space_id,
            created_by_user_id=self.user.id,
            ping_token=self._generate_ping_token(),
            name=name,
            sitemap_url=sitemap_url,
            markdown_endpoint_url=markdown_config.endpoint_url,
            markdown_endpoint_method=markdown_config.method.value,
            markdown_endpoint_url_location=markdown_config.url_location.value,
            markdown_endpoint_url_param_name=markdown_config.param_name,
            headers=self._headers_to_dict(payload.headers),
            sync_status="idle",
        )
        self.session.add(config)
        await self.session.flush()
        await self.queue_sync(config_id=config.id, owner_type=owner_type)
        await self.session.refresh(config)
        return self._to_public(config)

    async def update_config(
        self,
        *,
        config_id: UUID,
        owner_type: Literal["tenant", "user"],
        payload: WebsiteIntegrationConfigUpdate,
    ) -> WebsiteIntegrationConfigPublic:
        config = await self._get_owned_config(
            config_id=config_id, owner_type=owner_type
        )

        if is_provided(payload.name):
            name = payload.name.strip()
            if not name:
                raise BadRequestException(
                    "Sitemap webhook integration name is required"
                )
            config.name = name
        if is_provided(payload.sitemap_url):
            sitemap_url = payload.sitemap_url.strip()
            if not sitemap_url:
                raise BadRequestException("Sitemap URL is required")
            config.sitemap_url = sitemap_url

        markdown_endpoint_url = (
            config.markdown_endpoint_url
            if not is_provided(payload.page_content_webhook_url)
            else (
                payload.page_content_webhook_url.strip()
                if payload.page_content_webhook_url
                else None
            )
        )
        markdown_endpoint_method = (
            WebsiteIntegrationMarkdownMethod(config.markdown_endpoint_method)
            if not is_provided(payload.page_content_webhook_method)
            else payload.page_content_webhook_method
        )
        markdown_endpoint_url_location = (
            WebsiteIntegrationMarkdownUrlLocation(config.markdown_endpoint_url_location)
            if not is_provided(payload.page_content_webhook_url_location)
            else payload.page_content_webhook_url_location
        )
        markdown_endpoint_url_param_name = (
            config.markdown_endpoint_url_param_name
            if not is_provided(payload.page_content_webhook_url_param_name)
            else payload.page_content_webhook_url_param_name
        )
        markdown_config = self._build_page_content_webhook_config(
            page_content_webhook_url=markdown_endpoint_url,
            page_content_webhook_method=markdown_endpoint_method,
            page_content_webhook_url_location=markdown_endpoint_url_location,
            page_content_webhook_url_param_name=markdown_endpoint_url_param_name,
        )
        config.markdown_endpoint_url = markdown_config.endpoint_url
        config.markdown_endpoint_method = markdown_config.method.value
        config.markdown_endpoint_url_location = markdown_config.url_location.value
        config.markdown_endpoint_url_param_name = markdown_config.param_name
        if is_provided(payload.headers):
            config.headers = self._headers_to_dict(payload.headers)
        config.last_sync_error = None
        await self.session.flush()
        await self.session.refresh(config)
        return self._to_public(config)

    async def delete_config(
        self, *, config_id: UUID, owner_type: Literal["tenant", "user"]
    ) -> None:
        config = await self._get_owned_config(
            config_id=config_id, owner_type=owner_type
        )
        website_ids = list(
            await self.session.scalars(
                sa.select(WebsiteIntegrationPage.website_id).where(
                    WebsiteIntegrationPage.website_integration_config_id == config.id
                )
            )
        )
        await self.session.delete(config)
        await self.session.flush()

        for website_id in set(website_ids):
            await self._cleanup_website_if_unreferenced(website_id)

    async def queue_sync(
        self, *, config_id: UUID, owner_type: Literal["tenant", "user"] | None = None
    ) -> JobInDb:
        config = await self._get_owned_config(
            config_id=config_id, owner_type=owner_type
        )
        return await self._queue_sitemap_webhook_sync_for_config(config)

    async def queue_webhook_sync_for_token(
        self, *, config_id: UUID, webhook_token: str
    ) -> JobInDb:
        config = await self._get_config_by_id(config_id)
        if not secrets.compare_digest(config.ping_token, webhook_token):
            raise UnauthorizedException("Invalid webhook token")

        return await self._queue_sitemap_webhook_sync_for_config(config)

    async def _queue_sitemap_webhook_sync_for_config(
        self,
        config: WebsiteIntegrationConfig,
    ) -> JobInDb:
        if config.sync_status in {"queued", "in_progress"}:
            raise BadRequestException("A sync is already queued for this integration")

        config.sync_status = "queued"
        config.last_sync_error = None
        config.last_sync_queued_at = datetime.now(timezone.utc)
        await self.session.flush()

        from intric.integration.presentation.models import (
            WebsiteIntegrationSyncTaskParam,
        )

        return await self.job_service.queue_job(
            task=Task.SYNC_WEBSITE_INTEGRATION,
            name=f"Sitemap webhook integration sync: {config.name}",
            task_params=WebsiteIntegrationSyncTaskParam(
                user_id=self.user.id,
                id=config.id,
                website_integration_config_id=config.id,
            ),
        )

    async def sync_sitemap_webhook_integration(
        self, *, config_id: UUID
    ) -> WebsiteIntegrationConfigPublic:
        config = await self._get_config_by_id(config_id)
        if config.website_id is None:
            raise BadRequestException(
                "Sitemap webhook integration is not linked to a website source"
            )
        root_website = await self.website_crud_service.get_website(config.website_id)
        config.sync_status = "in_progress"
        config.last_sync_error = None
        await self.session.flush()

        now = datetime.now(timezone.utc)
        try:
            pages = await self._fetch_sitemap_recursive(
                config.sitemap_url, headers=config.headers
            )
            config.last_sitemap_fetched_at = now
            pages_by_url = {page.url: page for page in pages}

            existing_pages = list(
                (
                    await self.session.execute(
                        sa.select(WebsiteIntegrationPage).where(
                            WebsiteIntegrationPage.website_integration_config_id
                            == config.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_by_url = {page.page_url: page for page in existing_pages}
            obsolete_page_website_ids: set[UUID] = set()

            for page_url, page in pages_by_url.items():
                existing = existing_by_url.get(page_url)
                remap_required = (
                    existing is not None and existing.website_id != root_website.id
                )
                if (
                    existing
                    and not remap_required
                    and not self._page_needs_sync(existing, page)
                ):
                    existing.last_checked_at = now
                    continue

                markdown = await self._fetch_page_content(
                    config=config, page_url=page_url
                )
                digest = self._fingerprint(markdown)
                fingerprint = digest.hex()
                existing_hash = await self.info_blob_repo.get_content_hash(
                    root_website.id, page_url
                )
                if existing_hash != digest:
                    await self.text_processor.process_text(
                        text=markdown,
                        title=page_url,
                        embedding_model=root_website.embedding_model,
                        website_id=root_website.id,
                        url=page_url,
                        content_hash=digest,
                    )

                if existing is None:
                    existing = cast(Any, WebsiteIntegrationPage)(
                        website_integration_config_id=config.id,
                        page_url=page_url,
                        website_id=root_website.id,
                    )
                    self.session.add(existing)
                elif existing.website_id != root_website.id:
                    obsolete_page_website_ids.add(existing.website_id)

                existing.website_id = root_website.id
                existing.sitemap_lastmod = page.lastmod
                existing.content_fingerprint = fingerprint
                existing.last_checked_at = now
                existing.last_synced_at = now

            stale_urls = set(existing_by_url) - set(pages_by_url)
            if stale_urls:
                stale_pages = [existing_by_url[url] for url in stale_urls]
                stale_website_ids = {
                    page.website_id
                    for page in stale_pages
                    if page.website_id != root_website.id
                }
                await self.info_blob_repo.batch_delete_by_titles_and_website(
                    titles=list(stale_urls),
                    website_id=root_website.id,
                )
                for stale_page in stale_pages:
                    await self.session.delete(stale_page)
                await self.session.flush()
                for website_id in stale_website_ids:
                    await self._cleanup_website_if_unreferenced(website_id)

            if obsolete_page_website_ids:
                await self.session.flush()
                for website_id in obsolete_page_website_ids:
                    await self._cleanup_website_if_unreferenced(website_id)

            config.sync_status = "complete"
            config.last_successful_sync_at = now
            await self.session.flush()
            await self.session.refresh(config)
            return self._to_public(config)
        except Exception as exc:
            logger.exception(
                "Sitemap webhook integration sync failed",
                extra={"config_id": str(config_id)},
            )
            config.sync_status = "failed"
            config.last_sync_error = str(exc)
            await self.session.flush()
            raise

    async def _get_or_create_website_tenant_integration(self) -> TenantIntegration:
        stmt = (
            sa.select(TenantIntegration)
            .join(IntegrationDB, TenantIntegration.integration_id == IntegrationDB.id)
            .where(TenantIntegration.tenant_id == self.user.tenant_id)
            .where(IntegrationDB.integration_type == IntegrationType.Website.value)
        )
        result = (await self.session.execute(stmt)).scalars().first()
        if result is not None:
            return result

        integration = (
            (
                await self.session.execute(
                    sa.select(IntegrationDB).where(
                        IntegrationDB.integration_type == IntegrationType.Website.value
                    )
                )
            )
            .scalars()
            .first()
        )
        if integration is None:
            raise BadRequestException("Sitemap webhook integration is not available")

        tenant_integration = cast(Any, TenantIntegration)(
            tenant_id=self.user.tenant_id,
            integration_id=integration.id,
        )
        self.session.add(tenant_integration)
        await self.session.flush()
        return tenant_integration

    async def create_or_reuse_sitemap_webhook_integration(
        self,
        *,
        space_id: UUID,
        name: str | None,
        url: str | None,
        embedding_model_id: UUID | None,
        sitemap_url: str,
        page_content_webhook_url: str | None,
        page_content_webhook_method: WebsiteIntegrationMarkdownMethod,
        page_content_webhook_url_location: WebsiteIntegrationMarkdownUrlLocation,
        page_content_webhook_url_param_name: str,
        headers: list[WebsiteIntegrationHeader],
    ) -> "WebsiteDomain":
        normalized_sitemap_url = sitemap_url.strip()
        if not normalized_sitemap_url:
            raise BadRequestException("Sitemap URL is required")

        existing_config = await self._find_accessible_config_for_space(
            space_id=space_id,
            sitemap_url=normalized_sitemap_url,
        )
        if existing_config is not None:
            existing_website_id = existing_config.website_id
            if existing_website_id is None:
                raise BadRequestException(
                    "Sitemap webhook integration is missing its linked website"
                )
            website = await self.website_crud_service.get_website(existing_website_id)
            setattr(website, "website_integration_config", existing_config)
            setattr(website, "reused_existing", True)
            return website

        tenant_integration = await self._get_or_create_website_tenant_integration()
        markdown_config = self._build_page_content_webhook_config(
            page_content_webhook_url=page_content_webhook_url,
            page_content_webhook_method=page_content_webhook_method,
            page_content_webhook_url_location=page_content_webhook_url_location,
            page_content_webhook_url_param_name=page_content_webhook_url_param_name,
        )

        website = await self.website_crud_service.create_website(
            space_id=space_id,
            url=self._resolve_root_url(url=url, sitemap_url=normalized_sitemap_url),
            name=(name.strip() if name else None),
            download_files=False,
            crawl_type=CrawlType.SITEMAP,
            update_interval=UpdateInterval.NEVER,
            embedding_model_id=embedding_model_id,
            run_initial_crawl=False,
        )

        config = cast(Any, WebsiteIntegrationConfig)(
            website_id=website.id,
            tenant_integration_id=tenant_integration.id,
            tenant_id=self.user.tenant_id,
            owner_type="space",
            owner_user_id=None,
            owner_space_id=space_id,
            created_by_user_id=self.user.id,
            ping_token=self._generate_ping_token(),
            name=(
                name.strip()
                if name and name.strip()
                else website.name or normalized_sitemap_url
            ),
            sitemap_url=normalized_sitemap_url,
            markdown_endpoint_url=markdown_config.endpoint_url,
            markdown_endpoint_method=markdown_config.method.value,
            markdown_endpoint_url_location=markdown_config.url_location.value,
            markdown_endpoint_url_param_name=markdown_config.param_name,
            headers=self._headers_to_dict(headers),
            sync_status="idle",
        )
        self.session.add(config)
        await self.session.flush()
        await self.queue_sync(config_id=config.id, owner_type=None)
        await self.session.refresh(config)
        setattr(website, "website_integration_config", config)
        setattr(website, "reused_existing", False)
        return website

    async def update_for_website(
        self,
        *,
        website_id: UUID,
        payload: "WebsiteUpdate",
    ) -> WebsiteIntegrationConfig | None:
        config = await self._get_config_by_website_id(website_id)
        if config is None:
            return None

        sitemap_url = (
            config.sitemap_url
            if not is_provided(payload.sitemap_url)
            else (payload.sitemap_url.strip() if payload.sitemap_url else "")
        )
        if not sitemap_url:
            raise BadRequestException("Sitemap URL is required")

        markdown_endpoint_url = (
            config.markdown_endpoint_url
            if not is_provided(payload.page_content_webhook_url)
            else (
                payload.page_content_webhook_url.strip()
                if payload.page_content_webhook_url
                else None
            )
        )
        markdown_endpoint_method = (
            WebsiteIntegrationMarkdownMethod(config.markdown_endpoint_method)
            if not is_provided(payload.page_content_webhook_method)
            else payload.page_content_webhook_method
        )
        markdown_endpoint_url_location = (
            WebsiteIntegrationMarkdownUrlLocation(config.markdown_endpoint_url_location)
            if not is_provided(payload.page_content_webhook_url_location)
            else payload.page_content_webhook_url_location
        )
        markdown_endpoint_url_param_name = (
            config.markdown_endpoint_url_param_name
            if not is_provided(payload.page_content_webhook_url_param_name)
            else payload.page_content_webhook_url_param_name
        )
        markdown_config = self._build_page_content_webhook_config(
            page_content_webhook_url=markdown_endpoint_url,
            page_content_webhook_method=markdown_endpoint_method,
            page_content_webhook_url_location=markdown_endpoint_url_location,
            page_content_webhook_url_param_name=markdown_endpoint_url_param_name,
        )
        config.sitemap_url = sitemap_url
        config.markdown_endpoint_url = markdown_config.endpoint_url
        config.markdown_endpoint_method = markdown_config.method.value
        config.markdown_endpoint_url_location = markdown_config.url_location.value
        config.markdown_endpoint_url_param_name = markdown_config.param_name
        if is_provided(payload.headers):
            config.headers = self._headers_to_dict(payload.headers)
        config.last_sync_error = None
        await self.session.flush()
        await self.session.refresh(config)
        return config

    async def delete_for_website(self, *, website_id: UUID) -> None:
        config = await self._get_config_by_website_id(website_id)
        if config is None:
            return

        page_website_ids = list(
            await self.session.scalars(
                sa.select(WebsiteIntegrationPage.website_id).where(
                    WebsiteIntegrationPage.website_integration_config_id == config.id
                )
            )
        )
        await self.session.execute(
            sa.delete(WebsiteIntegrationPage).where(
                WebsiteIntegrationPage.website_integration_config_id == config.id
            )
        )
        await self.session.delete(config)
        await self.session.flush()

        for page_website_id in {
            page_website_id
            for page_website_id in set(page_website_ids)
            if page_website_id != website_id
        }:
            await self._cleanup_website_if_unreferenced(page_website_id)

    async def _resolve_owner(
        self, owner_type: Literal["tenant", "user"]
    ) -> tuple[UUID, UUID | None]:
        if owner_type == "tenant":
            space = await self.space_service.get_or_create_tenant_space()
            if space.id is None:
                raise BadRequestException("Tenant space is missing an id")
            return space.id, None

        space = await self.space_service.get_personal_space()
        if space is None:
            space = await self.space_service.create_personal_space()
        if space.id is None:
            raise BadRequestException("Personal space is missing an id")
        return space.id, self.user.id

    def _base_config_stmt(self, *, owner_type: Literal["tenant", "user"]):
        stmt = sa.select(WebsiteIntegrationConfig).where(
            WebsiteIntegrationConfig.tenant_id == self.user.tenant_id,
            WebsiteIntegrationConfig.owner_type == owner_type,
        )
        if owner_type == "user":
            stmt = stmt.where(WebsiteIntegrationConfig.owner_user_id == self.user.id)
        return stmt.order_by(WebsiteIntegrationConfig.created_at.desc())

    async def _get_owned_config(
        self,
        *,
        config_id: UUID,
        owner_type: Literal["tenant", "user"] | None,
    ) -> WebsiteIntegrationConfig:
        config = await self._get_config_by_id(config_id)
        if config.tenant_id != self.user.tenant_id:
            raise NotFoundException("Sitemap webhook integration not found")
        if owner_type is not None and config.owner_type != owner_type:
            raise NotFoundException("Sitemap webhook integration not found")
        if config.owner_type == "user" and config.owner_user_id != self.user.id:
            raise NotFoundException("Sitemap webhook integration not found")
        if (
            config.owner_type == "tenant"
            and Permission.ADMIN not in self.user.permissions
        ):
            raise UnauthorizedException("Admin permission is required")
        return config

    async def _get_config_by_website_id(
        self, website_id: UUID
    ) -> WebsiteIntegrationConfig | None:
        stmt = sa.select(WebsiteIntegrationConfig).where(
            WebsiteIntegrationConfig.website_id == website_id
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _get_config_by_id(self, config_id: UUID) -> WebsiteIntegrationConfig:
        config = await self.session.get(WebsiteIntegrationConfig, config_id)
        if config is None:
            raise NotFoundException("Sitemap webhook integration not found")
        return config

    async def _find_accessible_config_for_space(
        self, *, space_id: UUID, sitemap_url: str
    ) -> WebsiteIntegrationConfig | None:
        stmt = (
            sa.select(WebsiteIntegrationConfig)
            .join(Websites, Websites.id == WebsiteIntegrationConfig.website_id)
            .where(
                WebsiteIntegrationConfig.tenant_id == self.user.tenant_id,
                WebsiteIntegrationConfig.sitemap_url == sitemap_url,
                sa.or_(
                    Websites.space_id == space_id,
                    sa.exists(
                        sa.select(sa.literal(1))
                        .select_from(WebsitesSpaces)
                        .where(WebsitesSpaces.website_id == Websites.id)
                        .where(WebsitesSpaces.space_id == space_id)
                    ),
                ),
            )
            .order_by(WebsiteIntegrationConfig.created_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _fetch_sitemap_recursive(
        self, sitemap_url: str, *, headers: dict[str, str]
    ) -> list[SitemapPage]:
        async with self.aiohttp_session.get(sitemap_url, headers=headers) as response:
            response.raise_for_status()
            xml_text = await response.text()

        root = ET.fromstring(xml_text)
        namespace = ""
        if root.tag.startswith("{") and "}" in root.tag:
            namespace = root.tag.split("}", 1)[0] + "}"

        if root.tag.endswith("sitemapindex"):
            pages: list[SitemapPage] = []
            for sitemap in root.findall(f"{namespace}sitemap"):
                loc = sitemap.findtext(f"{namespace}loc")
                if loc:
                    pages.extend(
                        await self._fetch_sitemap_recursive(
                            loc.strip(), headers=headers
                        )
                    )
            return pages

        pages = []
        for url_node in root.findall(f"{namespace}url"):
            loc = url_node.findtext(f"{namespace}loc")
            if not loc:
                continue
            lastmod_raw = url_node.findtext(f"{namespace}lastmod")
            pages.append(
                SitemapPage(
                    url=loc.strip(),
                    lastmod=self._parse_lastmod(lastmod_raw),
                )
            )
        return pages

    async def _fetch_page_content(
        self, *, config: WebsiteIntegrationConfig, page_url: str
    ) -> str:
        if config.markdown_endpoint_url:
            param_name = config.markdown_endpoint_url_param_name
            payload = {param_name: page_url}
            method = WebsiteIntegrationMarkdownMethod(config.markdown_endpoint_method)
            location = WebsiteIntegrationMarkdownUrlLocation(
                config.markdown_endpoint_url_location
            )
            endpoint = config.markdown_endpoint_url
            if location == WebsiteIntegrationMarkdownUrlLocation.QUERY:
                endpoint = self._append_query_param(
                    base_url=config.markdown_endpoint_url,
                    key=param_name,
                    value=page_url,
                )
                request = (
                    self.aiohttp_session.get
                    if method == WebsiteIntegrationMarkdownMethod.GET
                    else self.aiohttp_session.post
                )
                async with request(endpoint, headers=config.headers) as response:
                    response.raise_for_status()
                    return self._extract_markdown_response(await response.text())

            async with self.aiohttp_session.post(
                endpoint, headers=config.headers, json=payload
            ) as response:
                response.raise_for_status()
                return self._extract_markdown_response(await response.text())

        async with self.aiohttp_session.get(
            page_url, headers=config.headers
        ) as response:
            response.raise_for_status()
            html = await response.text()
        return self._html_to_markdown(html)

    async def _get_or_create_website(
        self, *, owner_space_id: UUID, page_url: str
    ) -> Website:
        stmt = sa.select(Websites).where(
            Websites.space_id == owner_space_id,
            Websites.url == page_url,
        )
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing is not None:
            return await self.website_crud_service.get_website(existing.id)

        website = await self.website_crud_service.create_website(
            space_id=owner_space_id,
            url=page_url,
            name=page_url,
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.NEVER,
            run_initial_crawl=False,
        )
        return website

    async def _cleanup_website_if_unreferenced(self, website_id: UUID) -> None:
        website_record = await self.session.get(Websites, website_id)
        if website_record is None:
            return

        mapping_count = await self.session.scalar(
            sa.select(sa.func.count(WebsiteIntegrationPage.id)).where(
                WebsiteIntegrationPage.website_id == website_id
            )
        )
        if mapping_count:
            return

        space_link_count = await self.session.scalar(
            sa.select(sa.func.count(WebsitesSpaces.website_id)).where(
                WebsitesSpaces.website_id == website_id
            )
        )
        if space_link_count and int(space_link_count) > 1:
            return

        await self.session.flush()
        await self.session.execute(
            sa.delete(WebsitesSpaces).where(WebsitesSpaces.website_id == website_id)
        )
        await self.session.execute(
            sa.delete(Websites).where(
                Websites.id == website_id,
                Websites.space_id == website_record.space_id,
            )
        )

    @staticmethod
    def _parse_lastmod(value: str | None) -> datetime | None:
        if not value:
            return None
        raw = value.strip()
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None

    @staticmethod
    def _page_needs_sync(
        existing: WebsiteIntegrationPage,
        page: SitemapPage,
    ) -> bool:
        if existing.last_synced_at is None:
            return True
        if page.lastmod is None:
            return True
        return (
            existing.sitemap_lastmod is None or page.lastmod > existing.sitemap_lastmod
        )

    @staticmethod
    def _html_to_markdown(html: str) -> str:
        from html2text import html2text

        return html2text(html).strip()

    @staticmethod
    def _resolve_root_url(*, url: str | None, sitemap_url: str) -> str:
        if url and url.strip():
            return url.strip()

        parsed = urlparse(sitemap_url)
        base_path = parsed.path
        if base_path.endswith(".xml") and "/" in base_path:
            base_path = base_path.rsplit("/", 1)[0] or "/"

        normalized = parsed._replace(
            path=base_path or "/", params="", query="", fragment=""
        )
        return normalized.geturl()

    @staticmethod
    def _append_query_param(*, base_url: str, key: str, value: str) -> str:
        separator = "&" if "?" in base_url else "?"
        encoded_key = quote(key, safe="")
        encoded_value = quote(value, safe="")
        return f"{base_url}{separator}{encoded_key}={encoded_value}"

    @staticmethod
    def _headers_to_dict(headers: list[WebsiteIntegrationHeader]) -> dict[str, str]:
        return _HEADER_ADAPTER.validate_python(
            {
                item.key.strip(): item.value.strip()
                for item in headers
                if item.key.strip()
            }
        )

    @staticmethod
    def _fingerprint(text: str) -> bytes:
        return hashlib.sha256(text.encode("utf-8")).digest()

    @staticmethod
    def _generate_ping_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _extract_markdown_response(response_text: str) -> str:
        stripped = response_text.strip()
        if not stripped:
            return ""

        if stripped[0] in {"{", "["}:
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return response_text

            if isinstance(parsed, dict):
                parsed_dict = cast(dict[str, Any], parsed)
                for key in ("markdown", "content", "data"):
                    value = parsed_dict.get(key)
                    if isinstance(value, str):
                        return value

                raise BadRequestException(
                    "Markdown endpoint JSON responses must include one of: markdown, content, data"
                )

        return response_text

    @staticmethod
    def _build_page_content_webhook_config(
        *,
        page_content_webhook_url: str | None,
        page_content_webhook_method: WebsiteIntegrationMarkdownMethod,
        page_content_webhook_url_location: WebsiteIntegrationMarkdownUrlLocation,
        page_content_webhook_url_param_name: str,
    ) -> SimpleMarkdownConfig:
        endpoint_url = (
            page_content_webhook_url.strip() if page_content_webhook_url else None
        )
        param_name = page_content_webhook_url_param_name.strip()

        if endpoint_url is None:
            return SimpleMarkdownConfig(
                endpoint_url=None,
                method=WebsiteIntegrationMarkdownMethod.GET,
                url_location=WebsiteIntegrationMarkdownUrlLocation.QUERY,
                param_name="url",
            )

        if not param_name:
            raise BadRequestException(
                "Markdown endpoint URL parameter name is required"
            )
        if (
            page_content_webhook_method == WebsiteIntegrationMarkdownMethod.GET
            and page_content_webhook_url_location
            == WebsiteIntegrationMarkdownUrlLocation.BODY
        ):
            raise BadRequestException(
                "Markdown endpoint GET requests must send the URL as a query parameter"
            )

        return SimpleMarkdownConfig(
            endpoint_url=endpoint_url,
            method=page_content_webhook_method,
            url_location=page_content_webhook_url_location,
            param_name=param_name,
        )

    @staticmethod
    def _to_public(config: WebsiteIntegrationConfig) -> WebsiteIntegrationConfigPublic:
        return WebsiteIntegrationConfigPublic(
            id=config.id,
            tenant_integration_id=config.tenant_integration_id,
            webhook_url=(
                f"/api/v1/integrations/websites/{config.id}/sync/"
                f"?webhook_token={config.ping_token}"
            ),
            owner_type=cast(Literal["tenant", "user", "space"], config.owner_type),
            owner_user_id=config.owner_user_id,
            owner_space_id=config.owner_space_id,
            created_by_user_id=config.created_by_user_id,
            name=config.name,
            sitemap_url=config.sitemap_url,
            page_content_webhook_url=config.markdown_endpoint_url,
            page_content_webhook_method=WebsiteIntegrationMarkdownMethod(
                config.markdown_endpoint_method
            ),
            page_content_webhook_url_location=WebsiteIntegrationMarkdownUrlLocation(
                config.markdown_endpoint_url_location
            ),
            page_content_webhook_url_param_name=config.markdown_endpoint_url_param_name,
            headers=[
                WebsiteIntegrationHeader(key=key, value=value)
                for key, value in (config.headers or {}).items()
            ],
            webhook_status=config.sync_status,
            last_sitemap_fetched_at=config.last_sitemap_fetched_at,
            last_successful_sync_at=config.last_successful_sync_at,
            last_sync_error=config.last_sync_error,
            last_sync_queued_at=config.last_sync_queued_at,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

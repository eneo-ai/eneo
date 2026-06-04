from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode
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

logger = get_logger(__name__)

_HEADER_ADAPTER = TypeAdapter(dict[str, str])


@dataclass
class SitemapPage:
    url: str
    lastmod: datetime | None


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
        tenant_integration = await self._get_enabled_website_tenant_integration()
        owner_space_id, owner_user_id = await self._resolve_owner(owner_type)
        name = payload.name.strip()
        sitemap_url = payload.sitemap_url.strip()
        if not name:
            raise BadRequestException("Website integration name is required")
        if not sitemap_url:
            raise BadRequestException("Sitemap URL is required")

        config = WebsiteIntegrationConfig(
            tenant_integration_id=tenant_integration.id,
            tenant_id=self.user.tenant_id,
            owner_type=owner_type,
            owner_user_id=owner_user_id,
            owner_space_id=owner_space_id,
            created_by_user_id=self.user.id,
            name=name,
            sitemap_url=sitemap_url,
            markdown_endpoint_url=(
                str(payload.markdown_endpoint_url).strip()
                if payload.markdown_endpoint_url
                else None
            ),
            headers=self._headers_to_dict(payload.headers),
            sync_status="idle",
        )
        self.session.add(config)
        await self.session.flush()
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
                raise BadRequestException("Website integration name is required")
            config.name = name
        if is_provided(payload.sitemap_url):
            sitemap_url = payload.sitemap_url.strip()
            if not sitemap_url:
                raise BadRequestException("Sitemap URL is required")
            config.sitemap_url = sitemap_url
        if is_provided(payload.markdown_endpoint_url):
            config.markdown_endpoint_url = (
                payload.markdown_endpoint_url.strip()
                if payload.markdown_endpoint_url
                else None
            )
        if is_provided(payload.headers):
            config.headers = self._headers_to_dict(payload.headers)
        config.last_sync_error = None
        await self.session.flush()
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
            name=f"Website integration sync: {config.name}",
            task_params=WebsiteIntegrationSyncTaskParam(
                user_id=self.user.id,
                id=config.id,
                website_integration_config_id=config.id,
            ),
        )

    async def sync_config(self, *, config_id: UUID) -> WebsiteIntegrationConfigPublic:
        config = await self._get_config_by_id(config_id)
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

            for page_url, page in pages_by_url.items():
                existing = existing_by_url.get(page_url)
                if existing and not self._page_needs_sync(existing, page):
                    existing.last_checked_at = now
                    continue

                website = await self._get_or_create_website(
                    owner_space_id=config.owner_space_id,
                    page_url=page_url,
                )
                markdown = await self._fetch_page_content(
                    config=config, page_url=page_url
                )
                digest = self._fingerprint(markdown)
                fingerprint = digest.hex()
                existing_hash = await self.info_blob_repo.get_content_hash(
                    website.id, page_url
                )
                if existing_hash != digest:
                    await self.text_processor.process_text(
                        text=markdown,
                        title=page_url,
                        embedding_model=website.embedding_model,
                        website_id=website.id,
                        url=page_url,
                        content_hash=digest,
                    )

                if existing is None:
                    existing = WebsiteIntegrationPage(
                        website_integration_config_id=config.id,
                        page_url=page_url,
                        website_id=website.id,
                    )
                    self.session.add(existing)

                existing.website_id = website.id
                existing.sitemap_lastmod = page.lastmod
                existing.content_fingerprint = fingerprint
                existing.last_checked_at = now
                existing.last_synced_at = now

            stale_urls = set(existing_by_url) - set(pages_by_url)
            if stale_urls:
                stale_pages = [existing_by_url[url] for url in stale_urls]
                stale_website_ids = {page.website_id for page in stale_pages}
                for stale_page in stale_pages:
                    await self.session.delete(stale_page)
                await self.session.flush()
                for website_id in stale_website_ids:
                    await self._cleanup_website_if_unreferenced(website_id)

            config.sync_status = "complete"
            config.last_successful_sync_at = now
            await self.session.flush()
            return self._to_public(config)
        except Exception as exc:
            logger.exception(
                "Website integration sync failed", extra={"config_id": str(config_id)}
            )
            config.sync_status = "failed"
            config.last_sync_error = str(exc)
            await self.session.flush()
            raise

    async def _get_enabled_website_tenant_integration(self) -> TenantIntegration:
        stmt = (
            sa.select(TenantIntegration)
            .join(IntegrationDB, TenantIntegration.integration_id == IntegrationDB.id)
            .where(TenantIntegration.tenant_id == self.user.tenant_id)
            .where(IntegrationDB.integration_type == IntegrationType.Website.value)
        )
        result = (await self.session.execute(stmt)).scalars().first()
        if result is None:
            raise BadRequestException(
                "Website integration is not enabled for this tenant"
            )
        return result

    async def _resolve_owner(
        self, owner_type: Literal["tenant", "user"]
    ) -> tuple[UUID, UUID | None]:
        if owner_type == "tenant":
            space = await self.space_service.get_or_create_tenant_space()
            return space.id, None

        space = await self.space_service.get_personal_space()
        if space is None:
            space = await self.space_service.create_personal_space()
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
            raise NotFoundException("Website integration not found")
        if owner_type is not None and config.owner_type != owner_type:
            raise NotFoundException("Website integration not found")
        if config.owner_type == "user" and config.owner_user_id != self.user.id:
            raise NotFoundException("Website integration not found")
        if (
            config.owner_type == "tenant"
            and Permission.ADMIN not in self.user.permissions
        ):
            raise UnauthorizedException("Admin permission is required")
        return config

    async def _get_config_by_id(self, config_id: UUID) -> WebsiteIntegrationConfig:
        config = await self.session.get(WebsiteIntegrationConfig, config_id)
        if config is None:
            raise NotFoundException("Website integration not found")
        return config

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
            query = urlencode({"url": page_url})
            endpoint = (
                f"{config.markdown_endpoint_url}&{query}"
                if "?" in config.markdown_endpoint_url
                else f"{config.markdown_endpoint_url}?{query}"
            )
            async with self.aiohttp_session.get(
                endpoint, headers=config.headers
            ) as response:
                response.raise_for_status()
                return await response.text()

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
    def _to_public(config: WebsiteIntegrationConfig) -> WebsiteIntegrationConfigPublic:
        return WebsiteIntegrationConfigPublic(
            id=config.id,
            tenant_integration_id=config.tenant_integration_id,
            owner_type=config.owner_type,
            owner_user_id=config.owner_user_id,
            owner_space_id=config.owner_space_id,
            created_by_user_id=config.created_by_user_id,
            name=config.name,
            sitemap_url=config.sitemap_url,
            markdown_endpoint_url=config.markdown_endpoint_url,
            headers=[
                {"key": key, "value": value}
                for key, value in (config.headers or {}).items()
            ],
            sync_status=config.sync_status,
            last_sitemap_fetched_at=config.last_sitemap_fetched_at,
            last_successful_sync_at=config.last_successful_sync_at,
            last_sync_error=config.last_sync_error,
            last_sync_queued_at=config.last_sync_queued_at,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

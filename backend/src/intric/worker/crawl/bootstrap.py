"""Builds primitive crawl bootstrap state from short-lived database reads."""

from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.websites_table import Websites
from intric.main.config import Settings
from intric.main.logging import get_logger
from intric.tenants.crawler_settings_helper import (
    TenantCrawlerSettings,
    get_crawler_setting,
)
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB
from intric.worker.crawl.persistence import ExistingBlobState
from intric.worker.crawl_context import CrawlContext, EmbeddingModelSpec

logger = get_logger(__name__)


class EmbeddingModelSpecError(RuntimeError):
    pass


class WebsiteNotFoundError(RuntimeError):
    def __init__(self, website_id: UUID) -> None:
        self.website_id = website_id
        super().__init__(f"Website {website_id} not found")


class TenantIsolationError(RuntimeError):
    def __init__(
        self,
        *,
        website_id: UUID,
        website_tenant_id: UUID,
        container_tenant_id: UUID,
    ) -> None:
        self.website_id = website_id
        self.website_tenant_id = website_tenant_id
        self.container_tenant_id = container_tenant_id
        super().__init__(
            f"Tenant isolation violation: website {website_id} "
            f"belongs to tenant {website_tenant_id}, not {container_tenant_id}"
        )


class HttpAuthDecryptionError(RuntimeError):
    def __init__(self, website_id: UUID) -> None:
        self.website_id = website_id
        super().__init__(
            f"HTTP auth decryption failed for website {website_id}. "
            "Check encryption_key configuration."
        )


@dataclass(frozen=True, slots=True)
class CrawlBootstrapResult:
    crawl_context: CrawlContext
    embedding_model: EmbeddingModelSpec | None
    existing_titles: tuple[str, ...]
    existing_blob_state_by_title: Mapping[str, ExistingBlobState]
    website_url: str
    website_name: str | None
    # Website owner is the audit actor; crawl_context.user_id is the job principal.
    website_owner_id: UUID
    website_last_source_verified_at: datetime | None


def build_existing_blob_lookup(
    rows: Iterable[tuple[str | None, bytes | None, UUID | None]],
) -> tuple[tuple[str, ...], dict[str, ExistingBlobState]]:
    existing_titles: list[str] = []
    existing_blob_state_by_title: dict[str, ExistingBlobState] = {}

    for title, content_hash, embedding_model_id in rows:
        if title is None:
            continue

        existing_titles.append(title)
        if content_hash is None:
            continue

        existing_blob_state_by_title[title] = ExistingBlobState(
            content_hash=content_hash,
            embedding_model_id=embedding_model_id,
        )

    return tuple(existing_titles), existing_blob_state_by_title


async def build_embedding_model_spec(
    session: AsyncSession,
    embedding_model: EmbeddingModels | None,
) -> EmbeddingModelSpec | None:
    if embedding_model is None:
        return None

    if embedding_model.max_input is None:
        raise EmbeddingModelSpecError(
            f"Embedding model '{embedding_model.name}' is missing max_input."
        )

    provider_type = None
    provider_credentials = None
    provider_config = None
    if embedding_model.provider_id is not None:
        provider_result = await session.execute(
            sa.select(ModelProviders).where(
                ModelProviders.id == embedding_model.provider_id
            )
        )
        provider = provider_result.scalar_one_or_none()
        if provider is None:
            # Keep the current silent fall-through; downstream adapter will fail if FK drift is real.
            pass
        elif provider.is_active:
            provider_type = provider.provider_type
            provider_credentials = provider.credentials
            provider_config = provider.config
        else:
            logger.warning(
                "Embedding model provider is inactive",
                extra={
                    "model_name": embedding_model.name,
                    "provider_id": str(embedding_model.provider_id),
                },
            )

    litellm_model_name = embedding_model.litellm_model_name
    if provider_type is not None:
        litellm_model_name = f"{provider_type}/{embedding_model.name}"

    return EmbeddingModelSpec(
        id=embedding_model.id,
        name=embedding_model.name,
        litellm_model_name=litellm_model_name,
        family=embedding_model.family or None,
        max_input=embedding_model.max_input,
        max_batch_size=embedding_model.max_batch_size,
        dimensions=embedding_model.dimensions,
        open_source=embedding_model.open_source,
        input_cost_per_token=embedding_model.input_cost_per_token,
        provider_id=embedding_model.provider_id,
        provider_type=provider_type,
        provider_credentials=provider_credentials,
        provider_config=provider_config,
    )


async def bootstrap_crawl(
    *,
    session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    website_id: UUID,
    run_id: UUID,
    tenant: TenantInDB,
    user: UserInDB,
    tenant_crawler_settings: TenantCrawlerSettings,
    settings: Settings,
    http_auth_password_decrypter: Callable[[str], str],
) -> CrawlBootstrapResult:
    async with session_scope() as session:
        website_stmt = (
            sa.select(Websites)
            .where(Websites.id == website_id)
            .options(selectinload(Websites.embedding_model))
        )
        result = await session.execute(website_stmt)
        website = result.scalar_one_or_none()

        if website is None:
            raise WebsiteNotFoundError(website_id)

        if website.tenant_id != tenant.id:
            logger.error(
                "Tenant isolation violation detected",
                extra={
                    "website_id": str(website_id),
                    "website_tenant_id": str(website.tenant_id),
                    "container_tenant_id": str(tenant.id),
                },
            )
            raise TenantIsolationError(
                website_id=website_id,
                website_tenant_id=website.tenant_id,
                container_tenant_id=tenant.id,
            )

        http_user: str | None = None
        http_pass: str | None = None
        if website.http_auth_username and website.encrypted_auth_password:
            try:
                http_user = website.http_auth_username
                http_pass = http_auth_password_decrypter(
                    website.encrypted_auth_password
                )
                logger.info(
                    "HTTP auth configured for website",
                    extra={
                        "website_id": str(website_id),
                        "tenant_id": str(tenant.id),
                    },
                )
            except Exception as exc:
                logger.error(
                    "Cannot crawl website: HTTP auth decryption failed. "
                    "Check encryption_key setting is correct.",
                    extra={
                        "website_id": str(website_id),
                        "tenant_id": str(website.tenant_id),
                        "error_type": type(exc).__name__,
                    },
                )
                raise HttpAuthDecryptionError(website_id) from exc

        embedding_model_spec = await build_embedding_model_spec(
            session,
            website.embedding_model,
        )
        embedding_model_id = (
            embedding_model_spec.id if embedding_model_spec is not None else None
        )
        embedding_model_name = (
            embedding_model_spec.name if embedding_model_spec is not None else None
        )
        embedding_model_open_source = (
            embedding_model_spec.open_source
            if embedding_model_spec is not None
            else False
        )
        embedding_model_family = (
            embedding_model_spec.family
            if embedding_model_spec is not None and embedding_model_spec.family
            else None
        )
        embedding_model_dimensions = (
            embedding_model_spec.dimensions
            if embedding_model_spec is not None
            else None
        )

        crawl_context = CrawlContext(
            website_id=website.id,
            run_id=run_id,
            tenant_id=website.tenant_id,
            tenant_slug=tenant.slug,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            embedding_model_name=embedding_model_name,
            embedding_model_open_source=embedding_model_open_source,
            embedding_model_family=embedding_model_family,
            embedding_model_dimensions=embedding_model_dimensions,
            http_auth_user=http_user,
            http_auth_pass=http_pass,
            batch_size=get_crawler_setting(
                "crawl_page_batch_size",
                tenant_crawler_settings,
                default=settings.crawl_page_batch_size,
            ),
        )

        blob_stmt = sa.select(
            InfoBlobs.title,
            InfoBlobs.content_hash,
            InfoBlobs.embedding_model_id,
        ).where(
            InfoBlobs.website_id == website_id,
            InfoBlobs.tenant_id == crawl_context.tenant_id,
        )
        blob_result = await session.execute(blob_stmt)
        existing_titles, existing_blob_state_by_title = build_existing_blob_lookup(
            blob_result.tuples()
        )

        return CrawlBootstrapResult(
            crawl_context=crawl_context,
            embedding_model=embedding_model_spec,
            existing_titles=existing_titles,
            existing_blob_state_by_title=existing_blob_state_by_title,
            website_url=website.url,
            website_name=website.name,
            website_owner_id=website.user_id,
            website_last_source_verified_at=website.last_source_verified_at,
        )

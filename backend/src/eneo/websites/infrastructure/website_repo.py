"""Website configuration and sharing. Crawl state is owned by CrawlRunRepository."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.websites_spaces_table import WebsitesSpaces
from eneo.database.tables.websites_table import Websites
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.websites.domain.crawl_run import CrawlType
from eneo.websites.domain.http_auth_credentials import (
    HttpAuthCredentials,
    HttpAuthDestinationError,
)
from eneo.websites.domain.website import UpdateInterval, Website
from eneo.websites.infrastructure.http_auth_encryption import HttpAuthEncryptionService


class WebsiteRepository:
    def __init__(
        self, session: AsyncSession, http_auth_encryption: HttpAuthEncryptionService
    ):
        self.session = session
        self.http_auth_encryption = http_auth_encryption

    def _auth_values(
        self, credentials: HttpAuthCredentials | None
    ) -> dict[str, str | None]:
        if credentials is None:
            return {
                "http_auth_username": None,
                "encrypted_auth_password": None,
                "http_auth_domain": None,
            }
        username, password, domain = self.http_auth_encryption.encrypt_credentials(
            credentials
        )
        return {
            "http_auth_username": username,
            "encrypted_auth_password": password,
            "http_auth_domain": domain,
        }

    async def add(self, website: Website) -> None:
        await self.session.execute(
            sa.insert(Websites).values(
                id=website.id,
                name=website.name,
                url=website.url,
                download_files=website.download_files,
                crawl_type=website.crawl_type,
                update_interval=website.update_interval,
                size=0,
                tenant_id=website.tenant_id,
                user_id=website.user_id,
                embedding_model_id=website.embedding_model.id,
                space_id=website.space_id,
                **self._auth_values(website.http_auth),
            )
        )

    async def update(
        self,
        website_id: UUID,
        owner_space_id: UUID,
        *,
        name: str | None | NotProvided = NOT_PROVIDED,
        url: str | NotProvided = NOT_PROVIDED,
        download_files: bool | NotProvided = NOT_PROVIDED,
        crawl_type: CrawlType | NotProvided = NOT_PROVIDED,
        update_interval: UpdateInterval | NotProvided = NOT_PROVIDED,
        http_auth: HttpAuthCredentials | None | NotProvided = NOT_PROVIDED,
    ) -> None:
        stored = (
            await self.session.execute(
                sa.select(
                    Websites.url,
                    Websites.encrypted_auth_password,
                    Websites.http_auth_domain,
                )
                .where(Websites.id == website_id, Websites.space_id == owner_space_id)
                .with_for_update()
            )
        ).one_or_none()
        if stored is None:
            raise NotFoundException("Website not found")
        # Enforce the destination against persisted credentials even when the
        # read projection could not decrypt them. Only an explicit auth update
        # may replace or remove them when changing the origin.
        if (
            is_provided(url)
            and not is_provided(http_auth)
            and stored.encrypted_auth_password
        ):
            try:
                if HttpAuthCredentials.origin_for_url(
                    url
                ) != HttpAuthCredentials.origin_for_url(stored.url):
                    raise HttpAuthDestinationError()
                HttpAuthCredentials.require_destination(stored.http_auth_domain, url)
            except ValueError as error:
                raise BadRequestException(str(error)) from error
        values: dict[str, object] = {
            key: value
            for key, value in {
                "name": name,
                "url": url,
                "download_files": download_files,
                "crawl_type": crawl_type,
                "update_interval": update_interval,
            }.items()
            if is_provided(value)
        }
        if is_provided(http_auth):
            values.update(self._auth_values(http_auth))
        if is_provided(update_interval):
            # A manual schedule change requests retry, as Website.update specifies.
            values["consecutive_failures"] = sa.case(
                (Websites.consecutive_failures >= 10, 0),
                else_=Websites.consecutive_failures,
            )
            values["next_retry_at"] = sa.case(
                (Websites.consecutive_failures >= 10, None),
                else_=Websites.next_retry_at,
            )
        if values:
            await self.session.execute(
                sa.update(Websites)
                .where(
                    Websites.id == website_id,
                    Websites.space_id == owner_space_id,
                )
                .values(**values)
            )

    async def link(self, website_id: UUID, space_id: UUID) -> None:
        await self.session.execute(
            pg_insert(WebsitesSpaces)
            .values(
                website_id=website_id,
                space_id=space_id,
            )
            .on_conflict_do_nothing()
        )

    async def delete(self, website_id: UUID, owner_space_id: UUID) -> None:
        # Foreign keys remove distributions and assistant links atomically.
        # Caller must first acquire CrawlRunRepository.lock_website_deletion.
        await self.session.execute(
            sa.delete(Websites).where(
                Websites.id == website_id,
                Websites.space_id == owner_space_id,
            )
        )

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.models import NOT_PROVIDED, NotProvided
from eneo.websites.domain.crawl_run_repo import (
    CrawlDeletionBlocker,
    WebsiteCrawlActiveError,
    WebsiteCrawlCleanupPendingError,
)
from eneo.websites.domain.website import UpdateInterval, Website

if TYPE_CHECKING:
    from eneo.actors.actor_manager import ActorManager
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user import UserInDB
    from eneo.websites.domain.crawl_run import CrawlRun, CrawlType
    from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
    from eneo.websites.domain.crawl_service import CrawlService


class WebsiteBulkErrorCode(StrEnum):
    NOT_AUTHORIZED = "not_authorized"
    NOT_FOUND = "not_found"
    CRAWL_STOP_REQUESTED = "crawl_stop_requested"
    CRAWL_ACTIVE = "crawl_active"
    CRAWL_CLEANUP_PENDING = "crawl_cleanup_pending"


@dataclass(frozen=True, slots=True)
class WebsiteBulkError:
    website_id: UUID
    error: WebsiteBulkErrorCode


def _ordered_website_ids(website_ids: list[UUID]) -> list[UUID]:
    """Use one lock order across bulk mutations to avoid reversed-order deadlocks."""
    return sorted(set(website_ids), key=lambda website_id: website_id.int)


class WebsiteCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        space_repo: "SpaceRepository",
        crawl_run_repo: "CrawlRunRepository",
        actor_manager: "ActorManager",
        crawl_service: "CrawlService",
    ):
        super().__init__()
        self.user = user
        self.space_service = space_service
        self.space_repo = space_repo
        self.crawl_run_repo = crawl_run_repo
        self.actor_manager = actor_manager
        self.crawl_service = crawl_service

    async def create_website(
        self,
        space_id: "UUID",
        url: str,
        name: Optional[str],
        download_files: bool,
        crawl_type: "CrawlType",
        update_interval: UpdateInterval,
        embedding_model_id: Optional["UUID"] = None,
        http_auth_username: Optional[str] = None,
        http_auth_password: Optional[str] = None,
    ) -> Website:
        space = await self.space_service.get_space(space_id)
        assert space.id is not None
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_websites():
            raise UnauthorizedException()

        if embedding_model_id is None:
            embedding_model = space.get_default_embedding_model()
            if embedding_model is None:
                raise BadRequestException("No embedding model found")
        else:
            embedding_model = space.get_embedding_model(embedding_model_id)

        website = Website.create(
            space_id=space.id,
            user=self.user,
            url=url,
            name=name,
            download_files=download_files,
            crawl_type=crawl_type,
            update_interval=update_interval,
            embedding_model=embedding_model,
            http_auth_username=http_auth_username,
            http_auth_password=http_auth_password,
        )

        space.add_website(website)
        updated_space = await self.space_repo.update(space=space)
        new_website = updated_space.get_website(website_id=website.id)

        await self.crawl_service.crawl(website=new_website)

        return new_website

    async def get_website(self, id: UUID) -> Website:
        space = await self.space_service.get_space_by_website(id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return space.get_website(website_id=id)

    async def update_website(
        self,
        id: UUID,
        url: Union[str, NotProvided] = NOT_PROVIDED,
        name: Union[str, None, NotProvided] = NOT_PROVIDED,
        download_files: Union[bool, NotProvided] = NOT_PROVIDED,
        crawl_type: Union["CrawlType", NotProvided] = NOT_PROVIDED,
        update_interval: Union[UpdateInterval, NotProvided] = NOT_PROVIDED,
        http_auth_username: Union[str, None, NotProvided] = NOT_PROVIDED,
        http_auth_password: Union[str, None, NotProvided] = NOT_PROVIDED,
    ) -> Website:
        space = await self.space_service.get_space_by_website(id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_websites():
            raise UnauthorizedException()

        website = space.get_website(website_id=id)

        website.update(
            name=name,
            url=url,
            download_files=download_files,
            crawl_type=crawl_type,
            update_interval=update_interval,
            http_auth_username=http_auth_username,
            http_auth_password=http_auth_password,
        )

        await self.space_repo.update(space=space)

        return website

    async def delete_website(self, id: UUID) -> Website:
        website, owner_space_id = await self._authorize_website_deletion(id)
        await self._delete_authorized_website(
            website=website,
            owner_space_id=owner_space_id,
        )
        return website

    async def _authorize_website_deletion(self, id: UUID) -> tuple[Website, UUID]:
        owner_space = await self.space_service.get_space_by_website(id)
        assert owner_space.id is not None
        owner_actor = self.actor_manager.get_space_actor_from_space(space=owner_space)

        if not owner_actor.can_delete_websites():
            raise UnauthorizedException()

        website = owner_space.get_website(website_id=id)
        return website, owner_space.id

    async def _delete_authorized_website(
        self,
        *,
        website: Website,
        owner_space_id: UUID,
    ) -> None:
        assert website.id is not None
        blocker = await self.crawl_run_repo.lock_website_deletion(website.id)
        if blocker == CrawlDeletionBlocker.ACTIVE_CRAWL:
            raise WebsiteCrawlActiveError()
        if blocker == CrawlDeletionBlocker.TRANSPORT_CLEANUP:
            raise WebsiteCrawlCleanupPendingError()
        await self.space_repo.hard_delete_website(
            website_id=website.id,
            owner_space_id=owner_space_id,
        )

    async def bulk_delete_websites(
        self, website_ids: list[UUID]
    ) -> tuple[list[Website], list[UUID], list[WebsiteBulkError]]:
        """Delete a bounded selection while reporting expected per-item misses."""
        if len(website_ids) > 50:
            raise BadRequestException("Cannot delete more than 50 websites at once")

        deleted: list[Website] = []
        not_found: list[UUID] = []
        errors: list[WebsiteBulkError] = []

        for website_id in _ordered_website_ids(website_ids):
            try:
                website, owner_space_id = await self._authorize_website_deletion(
                    website_id
                )
                active_run = await self.crawl_run_repo.get_active_for_website(
                    website_id
                )
                if active_run is not None:
                    assert active_run.id is not None
                    await self.crawl_service.cancel(active_run.id)
                    errors.append(
                        WebsiteBulkError(
                            website_id=website_id,
                            error=WebsiteBulkErrorCode.CRAWL_STOP_REQUESTED,
                        )
                    )
                    continue
                await self._delete_authorized_website(
                    website=website,
                    owner_space_id=owner_space_id,
                )
                deleted.append(website)
            except NotFoundException:
                not_found.append(website_id)
            except UnauthorizedException:
                errors.append(
                    WebsiteBulkError(
                        website_id=website_id,
                        error=WebsiteBulkErrorCode.NOT_AUTHORIZED,
                    )
                )
            except WebsiteCrawlActiveError:
                errors.append(
                    WebsiteBulkError(
                        website_id=website_id,
                        error=WebsiteBulkErrorCode.CRAWL_ACTIVE,
                    )
                )
            except WebsiteCrawlCleanupPendingError:
                errors.append(
                    WebsiteBulkError(
                        website_id=website_id,
                        error=WebsiteBulkErrorCode.CRAWL_CLEANUP_PENDING,
                    )
                )

        return deleted, not_found, errors

    async def crawl_website(self, id: UUID) -> "CrawlRun":
        space = await self.space_service.get_space_by_website(id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_websites():
            raise UnauthorizedException()

        website = space.get_website(website_id=id)

        return await self.crawl_service.crawl(website=website)

    async def get_crawl_run(self, id: UUID) -> "CrawlRun":
        crawl_run = await self.crawl_run_repo.one(id)
        space = await self.space_service.get_space_by_website(crawl_run.website_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return crawl_run

    async def cancel_crawl_run(self, id: UUID) -> "CrawlRun":
        crawl_run = await self.crawl_run_repo.one(id)
        space = await self.space_service.get_space_by_website(crawl_run.website_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_websites():
            raise UnauthorizedException(
                "You do not have permission to stop crawls in this space"
            )

        return await self.crawl_service.cancel(id)

    async def get_crawl_runs(self, website_id: UUID) -> list["CrawlRun"]:
        space = await self.space_service.get_space_by_website(website_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return await self.crawl_run_repo.get_crawl_runs(website_id=website_id)

    async def get_latest_crawl_run(self, website_id: UUID) -> "CrawlRun | None":
        access = await self.space_repo.get_website_access_facts(website_id)
        actor = self.actor_manager.get_space_actor(access)
        if not actor.can_read_space() or not actor.can_read_websites():
            raise UnauthorizedException(
                "You do not have permission to read crawls in this space"
            )
        return await self.crawl_run_repo.get_latest_for_website(website_id)

    async def bulk_crawl_websites(
        self, website_ids: list[UUID]
    ) -> tuple[list["CrawlRun"], list[WebsiteBulkError]]:
        """Trigger crawls for multiple websites in bulk.

        Why: Enables efficient batch operations for users managing many websites.
        Each website is processed independently - failures don't stop the batch.

        Args:
            website_ids: List of website IDs to crawl

        Returns:
            Tuple of (successful_crawl_runs, errors)
            - successful_crawl_runs: List of CrawlRun objects that were queued
            - errors: Website-scoped expected failures

        Raises:
            BadRequestException: If more than 50 websites requested (safety limit)
        """
        if len(website_ids) > 50:
            raise BadRequestException("Cannot crawl more than 50 websites at once")

        successful_runs: list["CrawlRun"] = []
        errors: list[WebsiteBulkError] = []

        for website_id in _ordered_website_ids(website_ids):
            try:
                # Reuse existing crawl_website method for consistent behavior
                crawl_run = await self.crawl_website(website_id)
                successful_runs.append(crawl_run)
            except UnauthorizedException:
                errors.append(
                    WebsiteBulkError(
                        website_id=website_id,
                        error=WebsiteBulkErrorCode.NOT_AUTHORIZED,
                    )
                )
            except NotFoundException:
                errors.append(
                    WebsiteBulkError(
                        website_id=website_id,
                        error=WebsiteBulkErrorCode.NOT_FOUND,
                    )
                )

        return successful_runs, errors

    async def bulk_stop_websites(
        self, website_ids: list[UUID]
    ) -> tuple[list["CrawlRun"], list[UUID], list[WebsiteBulkError]]:
        """Stop the active crawl for each website without failing the whole batch."""
        if len(website_ids) > 50:
            raise BadRequestException("Cannot stop more than 50 websites at once")

        stopped_runs: list["CrawlRun"] = []
        not_running: list[UUID] = []
        errors: list[WebsiteBulkError] = []

        for website_id in _ordered_website_ids(website_ids):
            try:
                space = await self.space_service.get_space_by_website(website_id)
                actor = self.actor_manager.get_space_actor_from_space(space=space)
                if not actor.can_create_websites():
                    raise UnauthorizedException(
                        "You do not have permission to stop crawls in this space"
                    )

                active_run = await self.crawl_run_repo.get_active_for_website(
                    website_id
                )
                if active_run is None:
                    not_running.append(website_id)
                    continue

                assert active_run.id is not None
                stopped_runs.append(await self.crawl_service.cancel(active_run.id))
            except UnauthorizedException:
                errors.append(
                    WebsiteBulkError(
                        website_id=website_id,
                        error=WebsiteBulkErrorCode.NOT_AUTHORIZED,
                    )
                )
            except NotFoundException:
                errors.append(
                    WebsiteBulkError(
                        website_id=website_id,
                        error=WebsiteBulkErrorCode.NOT_FOUND,
                    )
                )

        return stopped_runs, not_running, errors

    async def find_on_organization_space(self, url: str) -> dict[str, object] | None:
        """Find website with matching URL on the user's organization space.

        Why: Help users discover that a website is already being crawled on the
        organization space before they create a duplicate on their personal/shared space.

        Args:
            url: The URL to search for

        Returns:
            Dictionary with website info if found, None otherwise.
            Returns None if:
            - User has no organization space
            - URL not found on organization space
        """
        from eneo.spaces.space_service import TENANT_SPACE_NAME

        # Get the organization space for this tenant
        org_space = await self.space_repo.get_space_by_name_and_tenant(
            name=TENANT_SPACE_NAME, tenant_id=self.user.tenant_id
        )

        if org_space is None:
            return None

        # Search for matching URL in the organization space's websites
        for website in org_space.websites:
            if website.url == url:
                # Get crawl info from latest_crawl
                last_crawled_at = None
                pages_crawled = None
                pages_failed = None
                files_downloaded = None
                files_failed = None
                crawl_status = None

                if website.latest_crawl:
                    last_crawled_at = website.latest_crawl.finished_at
                    pages_crawled = website.latest_crawl.pages_crawled
                    pages_failed = website.latest_crawl.pages_failed
                    files_downloaded = website.latest_crawl.files_downloaded
                    files_failed = website.latest_crawl.files_failed
                    status = website.latest_crawl.status
                    crawl_status = status.value if hasattr(status, "value") else status

                return {
                    "website_id": website.id,
                    "space_id": org_space.id,
                    "space_name": org_space.name,
                    "url": website.url,
                    "name": website.name,
                    "update_interval": website.update_interval,
                    "last_crawled_at": last_crawled_at,
                    "pages_crawled": pages_crawled,
                    "pages_failed": pages_failed,
                    "files_downloaded": files_downloaded,
                    "files_failed": files_failed,
                    "crawl_status": crawl_status,
                }

        return None

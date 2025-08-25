from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from intric.main.exceptions import (
    BadRequestException,
    CrawlAlreadyRunningException,
    UnauthorizedException,
)
from intric.main.models import NOT_PROVIDED, NotProvided, Status
from intric.websites.domain.website import UpdateInterval, Website

if TYPE_CHECKING:
    from intric.actors.actor_manager import ActorManager
    from intric.spaces.space_repo import SpaceRepository
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB
    from intric.websites.domain.crawl_run import CrawlRun, CrawlType
    from intric.websites.domain.crawl_run_repo import CrawlRunRepository
    from intric.websites.domain.crawl_service import CrawlService


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
    ) -> Website:
        space = await self.space_service.get_space(space_id)
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
        )

        space.add_website(website)
        updated_space = await self.space_repo.update(space=space)
        new_website = updated_space.get_website(website_id=website.id)

        await self.crawl_service.crawl(website=new_website)

        refreshed_space = await self.space_repo.one(space_id)
        return refreshed_space.get_website(website_id=new_website.id)

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
        name: Union[str, NotProvided] = NOT_PROVIDED,
        download_files: Union[bool, NotProvided] = NOT_PROVIDED,
        crawl_type: Union["CrawlType", NotProvided] = NOT_PROVIDED,
        update_interval: Union[UpdateInterval, NotProvided] = NOT_PROVIDED,
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
        )

        await self.space_repo.update(space=space)

        return website

    async def delete_website(self, id: UUID) -> None:
        owner_space = await self.space_service.get_space_by_website(id)
        owner_actor = self.actor_manager.get_space_actor_from_space(space=owner_space)

        if not owner_actor.can_delete_websites():
            raise UnauthorizedException()

        await self.space_repo.hard_delete_website(website_id=id, owner_space_id=owner_space.id)
        

    async def crawl_website(self, id: UUID) -> bool:
        space = await self.space_service.get_space_by_website(id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_websites():
            raise UnauthorizedException()

        website = space.get_website(website_id=id)

        if website.latest_crawl.status in [Status.QUEUED, Status.IN_PROGRESS]:
            raise CrawlAlreadyRunningException()

        return await self.crawl_service.crawl(website=website)

    async def get_crawl_run(self, id: UUID) -> "CrawlRun":
        crawl_run = await self.crawl_run_repo.one(id)
        space = await self.space_service.get_space_by_website(crawl_run.website_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return crawl_run

    async def get_crawl_runs(self, website_id: UUID) -> list["CrawlRun"]:
        space = await self.space_service.get_space_by_website(website_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return await self.crawl_run_repo.get_crawl_runs(website_id=website_id)

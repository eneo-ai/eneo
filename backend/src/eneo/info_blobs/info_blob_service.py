from hashlib import sha256
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from eneo.actors import SpaceAction
from eneo.admin.quota_service import QuotaService
from eneo.groups_legacy.group_service import GroupService
from eneo.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobInDB,
    InfoBlobInDBNoText,
    InfoBlobMetadataFilter,
    InfoBlobMetadataFilterPublic,
    InfoBlobUpdate,
)
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.spaces.utils.space_utils import effective_space_ids
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.actors import ActorManager
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.embedding_models.infrastructure.datastore import Datastore
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.spaces.space_service import SpaceService
    from eneo.websites.infrastructure.update_website_size_service import (
        UpdateWebsiteSizeService,
    )


class InfoBlobService:
    def __init__(
        self,
        *,
        repo: InfoBlobRepository,
        space_repo: "SpaceRepository",
        user: UserInDB,
        quota_service: QuotaService,
        group_service: GroupService,
        update_website_size_service: "UpdateWebsiteSizeService",
        space_service: "SpaceService",
        actor_manager: "ActorManager",
        datastore: "Datastore",
    ) -> None:
        super().__init__()
        self.repo = repo
        self.space_repo = space_repo
        self.group_service = group_service
        self.update_website_size_service = update_website_size_service
        self.user = user
        self.quota_service = quota_service
        self.space_service = space_service
        self.actor_manager = actor_manager
        self.datastore = datastore

    async def _get_actor(
        self, info_blob: Optional[InfoBlobInDB], group_id: Optional[UUID]
    ):
        if info_blob is None and group_id is None:
            raise ValueError("One of info_blob and group_id has to exist")

        if group_id is not None:
            space = await self.space_repo.get_space_by_collection(
                collection_id=group_id
            )

        else:
            assert info_blob is not None
            if info_blob.group_id is not None:
                space = await self.space_repo.get_space_by_collection(
                    info_blob.group_id
                )
            elif info_blob.website_id is not None:
                space = await self.space_repo.get_space_by_website(info_blob.website_id)
            elif info_blob.integration_knowledge_id is not None:
                space = await self.space_repo.get_space_by_integration_knowledge(
                    info_blob.integration_knowledge_id
                )
            else:
                raise ValueError("InfoBlob missing scope reference")

        return self.actor_manager.get_space_actor_from_space(space)

    async def _validate(
        self,
        info_blob: Optional[InfoBlobInDB],
        action: SpaceAction = SpaceAction.READ,
    ):
        if info_blob is None:
            raise NotFoundException("InfoBlob not found")

        await self._can_perform_action(
            info_blob=info_blob, group_id=None, action=action
        )

    async def _can_perform_action(
        self,
        info_blob: Optional[InfoBlobInDB] = None,
        group_id: Optional[UUID] = None,
        action: SpaceAction = SpaceAction.READ,
    ):
        actor = await self._get_actor(info_blob=info_blob, group_id=group_id)
        match action:
            case SpaceAction.READ:
                if not actor.can_read_info_blobs():
                    raise UnauthorizedException()
            case SpaceAction.CREATE:
                if not actor.can_create_info_blobs():
                    raise UnauthorizedException()
            case SpaceAction.DELETE:
                if not actor.can_delete_info_blobs():
                    raise UnauthorizedException()
            case _:
                pass  # Other SpaceAction values are not applicable to info blobs

    async def publish_info_blob_without_validation(
        self,
        info_blob: InfoBlobAdd,
        *,
        embedding_model: "EmbeddingModel",
    ) -> InfoBlobInDB:
        if info_blob.content_hash is None:
            info_blob.content_hash = sha256(info_blob.text.encode("utf-8")).digest()

        async with self.repo.session.begin_nested():
            await self.repo.lock_publication_identity(info_blob)
            active = await self.repo.get_active_for_publication(info_blob)
            if active is not None and active.content_hash == info_blob.content_hash:
                return active

            source_id = active.source_id if active is not None else None
            if active is not None and not await self.repo.supersede(active.id):
                raise RuntimeError(
                    "The active knowledge version changed during publish"
                )

            size_of_text = await self.quota_service.add_text(info_blob.text)
            info_blob.size = size_of_text
            published = await self.repo.add(info_blob, source_id=source_id)
            await self.datastore.add(
                info_blob=published,
                embedding_model=embedding_model,
            )
            updated = await self.update_info_blob_size(published.id)
            return updated

    async def add_info_blobs(
        self,
        group_id: UUID,
        info_blobs: list[InfoBlobAdd],
        *,
        embedding_model: "EmbeddingModel",
    ) -> list[InfoBlobInDB]:
        await self._can_perform_action(group_id=group_id, action=SpaceAction.CREATE)

        return [
            await self.publish_info_blob_without_validation(
                blob,
                embedding_model=embedding_model,
            )
            for blob in info_blobs
        ]

    async def update_info_blob(self, info_blob: InfoBlobUpdate):
        current_info_blob = await self.repo.get(info_blob.id)
        assert current_info_blob is not None

        if info_blob.title:
            if current_info_blob.group_id is None:
                raise BadRequestException(
                    "Cannot update title for info blobs without a group."
                )
            info_blob_with_same_name = await self.repo.get_by_title_and_group(
                info_blob.title, current_info_blob.group_id
            )

            if info_blob_with_same_name is not None:
                raise NameCollisionException(
                    "Info blob with same name already exists in the same group"
                )

        info_blob_updated = await self.repo.update(info_blob)

        await self._validate(info_blob_updated, action=SpaceAction.EDIT)

        return info_blob_updated

    async def update_info_blob_size(self, info_blob_id: UUID):
        updated_info_blob = await self.repo.update_size(info_blob_id=info_blob_id)
        assert updated_info_blob is not None

        if updated_info_blob.group_id is not None:
            await self.group_service.update_group_size(updated_info_blob.group_id)
        if updated_info_blob.website_id is not None:
            await self.update_website_size_service.update_website_size(
                updated_info_blob.website_id
            )

        return updated_info_blob

    async def get_by_id(self, id: UUID):
        blob = await self.repo.get(id)

        await self._validate(blob)

        return blob

    async def get_by_user(
        self,
        metadata_filter: InfoBlobMetadataFilter | None = None,
        space_id_filter: UUID | None = None,
    ):
        if space_id_filter is not None:
            info_blobs = await self.repo.get_by_user_and_space(
                user_id=self.user.id, space_ids=[space_id_filter]
            )
        else:
            info_blobs = await self.repo.get_by_user(user_id=self.user.id)

        if metadata_filter:

            def filter_func(item: InfoBlobInDBNoText) -> bool:
                filter_dict = metadata_filter.model_dump(exclude_none=True)
                item_dict = item.model_dump()
                return filter_dict.items() <= item_dict.items()

            info_blobs = [blob for blob in info_blobs if filter_func(blob)]

        return [blob for blob in info_blobs]

    async def get_by_filter(
        self,
        metadata_filter: InfoBlobMetadataFilterPublic,
    ):
        metadata_filter_with_user = InfoBlobMetadataFilter(
            **metadata_filter.model_dump(exclude_none=True), user_id=self.user.id
        )
        return await self.get_by_user(metadata_filter_with_user)

    async def get_by_group(self, id: UUID) -> list[InfoBlobInDB]:
        group = await self.group_service.get_group(id)
        return await self.repo.get_by_group(group.id)

    async def get_by_website(self, id: UUID) -> list[InfoBlobInDB]:
        space = await self.space_service.get_space_by_website(website_id=id)
        actor = self.actor_manager.get_space_actor_from_space(space)

        if not actor.can_read_info_blobs():
            raise UnauthorizedException()

        return await self.repo.get_by_website(website_id=id)

    async def delete(self, id: UUID):
        # Fetch the blob first to validate authorization BEFORE deleting
        blob = await self.repo.get(id)

        # Validate authorization before performing deletion
        await self._validate(blob, action=SpaceAction.DELETE)

        # Only delete if authorization check passes
        info_blob_deleted = await self.repo.delete(id)

        return info_blob_deleted

    async def get_for_space(
        self, space_id: UUID, *, limit: int | None = None
    ) -> list[InfoBlobInDBNoText]:
        space = await self.space_repo.one(space_id)

        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_read_info_blobs():
            raise UnauthorizedException()

        space_ids = effective_space_ids(space)

        return await self.repo.list_by_space_ids(  # type: ignore[attr-defined]
            space_ids=space_ids,
            include_groups=True,
            include_websites=True,
            include_integrations=True,
            limit=limit,
            order_desc=True,
        )

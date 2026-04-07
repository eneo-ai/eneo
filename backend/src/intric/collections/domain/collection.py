from typing import TYPE_CHECKING, Optional, Union

from intric.base.base_entity import Entity
from intric.main.models import NOT_PROVIDED, NotProvided, is_provided

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.collections_table import CollectionsTable
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.users.user import UserInDB


class Collection(Entity):
    "Domain object for a collection of documents or files"

    def __init__(
        self,
        id: Optional["UUID"],
        created_at: Optional["datetime"],
        updated_at: Optional["datetime"],
        space_id: "UUID",
        user_id: "UUID",
        tenant_id: "UUID",
        name: str,
        size: int,
        num_info_blobs: int,
        embedding_model: "EmbeddingModel",
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.space_id = space_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.name = name
        self.size = size
        self.num_info_blobs = num_info_blobs
        self.embedding_model = embedding_model

    @classmethod
    def create(
        cls,
        space_id: "UUID",
        user: "UserInDB",
        name: str,
        embedding_model: "EmbeddingModel",
    ) -> "Collection":
        return cls(
            id=None,
            created_at=None,
            updated_at=None,
            space_id=space_id,
            user_id=user.id,
            tenant_id=user.tenant_id,
            name=name,
            size=0,
            num_info_blobs=0,
            embedding_model=embedding_model,
        )

    @classmethod
    def to_domain(
        cls,
        record: "CollectionsTable",
        embedding_model: "EmbeddingModel",
        num_info_blobs: int,
    ):
        return cls(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            space_id=record.space_id,
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            name=record.name,
            size=record.size,
            num_info_blobs=num_info_blobs,
            embedding_model=embedding_model,
        )

    def update(self, name: Union[str, NotProvided] = NOT_PROVIDED):
        if is_provided(name):
            self.name = name

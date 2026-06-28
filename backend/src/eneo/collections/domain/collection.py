from typing import TYPE_CHECKING, Optional, Union, cast, overload

from typing_extensions import override

from eneo.base.base_entity import Entity
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eneo.database.tables.collections_table import CollectionsTable
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.users.user import UserInDB


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

    @overload
    @classmethod
    def create(
        cls,
        space_id: "UUID",
        user: "UserInDB",
        name: str,
        embedding_model: "EmbeddingModel",
        /,
    ) -> "Collection": ...

    @overload
    @classmethod
    def create(
        cls,
        *,
        space_id: "UUID",
        user: "UserInDB",
        name: str,
        embedding_model: "EmbeddingModel",
    ) -> "Collection": ...

    @override
    @classmethod
    def create(cls, *args: object, **kwargs: object) -> "Collection":
        if args:
            space_id, user, name, embedding_model = args
        else:
            space_id = kwargs["space_id"]
            user = kwargs["user"]
            name = kwargs["name"]
            embedding_model = kwargs["embedding_model"]

        return cls(
            id=None,
            created_at=None,
            updated_at=None,
            space_id=cast("UUID", space_id),
            user_id=cast("UserInDB", user).id,
            tenant_id=cast("UserInDB", user).tenant_id,
            name=cast(str, name),
            size=0,
            num_info_blobs=0,
            embedding_model=cast("EmbeddingModel", embedding_model),
        )

    @overload
    @classmethod
    def to_domain(  # noqa: D102
        cls,
        db_model: "CollectionsTable",
        *,
        embedding_model: "EmbeddingModel",
        num_info_blobs: int,
    ) -> "Collection": ...

    @overload
    @classmethod
    def to_domain(
        cls,
        *,
        record: "CollectionsTable",
        embedding_model: "EmbeddingModel",
        num_info_blobs: int,
    ) -> "Collection": ...

    @override
    @classmethod
    def to_domain(
        cls,
        db_model: object = None,
        *args: object,
        **kwargs: object,
    ) -> "Collection":
        del args
        record = cast(
            "CollectionsTable",
            db_model if db_model is not None else kwargs["record"],
        )
        embedding_model = cast("EmbeddingModel", kwargs["embedding_model"])
        num_info_blobs = cast(int, kwargs["num_info_blobs"])

        return cls(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            space_id=cast(
                "UUID", record.space_id
            ),  # DB invariant: collection rows attached to spaces have non-null space_id
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

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel

from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from intric.main.models import BaseResponse, ResourcePermissionsMixin

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection


class CollectionMetadata(BaseModel):
    num_info_blobs: int
    size: int
    text_size: int = 0


class CollectionPublic(ResourcePermissionsMixin, BaseResponse):
    name: str
    description: Optional[str] = None
    embedding_model: EmbeddingModelPublic
    metadata: CollectionMetadata
    space_id: UUID
    pinned: Optional[bool] = None

    @classmethod
    def from_domain(cls, collection: "Collection"):
        return cls(
            id=collection.id,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
            name=collection.name,
            description=collection.description,
            embedding_model=EmbeddingModelPublic.from_domain(collection.embedding_model),
            metadata=CollectionMetadata(
                num_info_blobs=collection.num_info_blobs,
                size=collection.size,
                text_size=getattr(collection, 'text_size', 0),
            ),
            permissions=collection.permissions,
            space_id=collection.space_id,
            pinned=getattr(collection, 'pinned', None),
        )


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

from typing import TYPE_CHECKING
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


class CollectionPublic(ResourcePermissionsMixin, BaseResponse):
    name: str
    embedding_model: EmbeddingModelPublic
    metadata: CollectionMetadata
    space_id: UUID
    
    @classmethod
    def from_domain(cls, collection: "Collection"):
        return cls(
            id=collection.id,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
            name=collection.name,
            embedding_model=EmbeddingModelPublic.from_domain(collection.embedding_model),
            metadata=CollectionMetadata(
                num_info_blobs=collection.num_info_blobs,
                size=collection.size,
            ),
            permissions=collection.permissions,
            space_id=collection.space_id,
        )


class CollectionUpdate(BaseModel):
    name: str

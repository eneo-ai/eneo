from typing import Optional
from uuid import UUID

from pydantic import AliasChoices, AliasPath, BaseModel, Field

from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelLegacy,
)
from intric.embedding_models.presentation.embedding_model_models import EmbeddingModelPublic
from intric.main.models import InDB, ModelId, ResourcePermissionsMixin, partial_model


class GroupBase(BaseModel):
    name: str


class CreateGroupRequest(GroupBase):
    embedding_model: ModelId


@partial_model
class GroupUpdatePublic(GroupBase):
    pass


class GroupUpdate(GroupUpdatePublic):
    id: UUID


class GroupCreate(GroupBase):
    user_id: UUID
    tenant_id: UUID
    embedding_model_id: UUID = Field(
        validation_alias=AliasChoices(
            AliasPath("embedding_model", "id"), "embedding_model_id", "embedding_model"
        )
    )
    size: int = 0


class CreateSpaceGroup(GroupCreate):
    space_id: UUID
    embedding_model_id: UUID


class GroupInDBBase(InDB):
    space_id: Optional[UUID] = None
    size: int
    name: str
    embedding_model_id: UUID
    user_id: UUID
    tenant_id: UUID


class GroupMetadata(BaseModel):
    num_info_blobs: int
    size: int


# TODO: Make into real domain object
class Group(GroupInDBBase, ResourcePermissionsMixin):
    embedding_model: EmbeddingModelLegacy
    num_info_blobs: Optional[int] = None


class GroupPublicBase(InDB, GroupBase):
    pass


class GroupPublic(GroupPublicBase, ResourcePermissionsMixin):
    embedding_model: EmbeddingModelPublic
    space_id: UUID


class GroupPublicWithMetadata(GroupPublic):
    metadata: GroupMetadata


class DeletionInfo(BaseModel):
    success: bool


class DeleteGroupResponse(GroupPublic):
    deletion_info: DeletionInfo


class CreateGroupResponse(GroupPublic):
    pass


class GroupUpdateRequest(GroupBase):
    pass

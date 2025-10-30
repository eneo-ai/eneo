from typing import Optional
from uuid import UUID

from pydantic import BaseModel, computed_field, model_validator

from intric.groups_legacy.api.group_models import GroupInDBBase
from intric.main.models import InDB
from intric.websites.presentation.website_models import WebsiteInDBBase


class InfoBlobBase(BaseModel):
    text: str


class InfoBlobMetadataUpsertPublic(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None


class InfoBlobMetadata(InfoBlobMetadataUpsertPublic):
    embedding_model_id: UUID
    size: int


class InfoBlobAdd(InfoBlobBase, InfoBlobMetadataUpsertPublic):
    size: Optional[int] = None
    user_id: UUID
    group_id: Optional[UUID] = None
    website_id: Optional[UUID] = None
    tenant_id: UUID
    integration_knowledge_id: Optional[UUID] = None
    content_hash: Optional[bytes] = None  # SHA-256 hash for change detection

    @model_validator(mode="after")
    def require_one_of_group_id_and_website_id(self) -> "InfoBlobAdd":
        if (
            self.group_id is None
            and self.website_id is None
            and self.integration_knowledge_id is None
        ):
            raise ValueError(
                "One of 'group_id' and 'website_id' and 'integration_knowledge_id' is required"
            )

        return self


class InfoBlobAddToDB(InfoBlobAdd):
    embedding_model_id: UUID


class InfoBlobUpdatePublic(BaseModel):
    metadata: InfoBlobMetadataUpsertPublic


class InfoBlobUpdate(InfoBlobMetadataUpsertPublic):
    id: UUID
    user_id: UUID


class InfoBlobInDBNoText(InDB):
    url: Optional[str] = None
    title: Optional[str] = None
    embedding_model_id: UUID
    user_id: UUID
    tenant_id: UUID
    size: int

    group_id: Optional[UUID] = None
    website_id: Optional[UUID] = None
    integration_knowledge_id: Optional[UUID] = None

    group: Optional[GroupInDBBase] = None
    website: Optional[WebsiteInDBBase] = None


class InfoBlobInDB(InfoBlobInDBNoText):
    text: str


class InfoBlobInDBWithScore(InfoBlobInDB):
    score: float


class InfoBlobAddPublic(InfoBlobBase):
    metadata: InfoBlobMetadataUpsertPublic = None


class InfoBlobPublicNoText(InDB):
    metadata: InfoBlobMetadata
    group_id: Optional[UUID] = None
    website_id: Optional[UUID] = None


class InfoBlobAskAssistantPublic(InfoBlobPublicNoText):
    score: float


class InfoBlobPublic(InfoBlobPublicNoText):
    text: str


class InfoBlobMetadataFilterPublic(BaseModel):
    group_ids: Optional[list[UUID]] = None
    title: Optional[str] = None


class InfoBlobMetadataFilter(InfoBlobMetadataFilterPublic):
    user_id: Optional[int] = None
    group_ids: Optional[list[int]] = None


class InfoBlobChunk(BaseModel):
    text: str
    chunk_no: int
    info_blob_id: UUID
    tenant_id: UUID


class InfoBlobChunkWithEmbedding(InfoBlobChunk):
    embedding: list[float]

    @computed_field
    @property
    def size(self) -> int:
        # Size of chunk is number of bytes of text
        # + embedding dimension * 4
        # This is an empirically derived value which is not
        # obvious as to why it provides a good estimation
        return len(self.text.encode()) + len(self.embedding) * 4


class InfoBlobChunkInDB(InDB, InfoBlobChunkWithEmbedding):
    pass


class InfoBlobChunkInDBWithScore(InDB, InfoBlobChunk):
    info_blob_title: Optional[str]
    score: float


class Query(BaseModel):
    query: str
    top_k: int = 30


class QueryWithEmbedding(Query):
    embedding: list[float]

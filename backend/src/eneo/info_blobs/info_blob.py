from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from eneo.groups_legacy.api.group_models import GroupInDBBase
from eneo.main.models import InDB
from eneo.object_content.content import CapturedContent, StorageKind
from eneo.websites.presentation.website_models import WebsiteInDBBase


class InfoBlobOriginalUnavailableError(Exception):
    code = "info_blob_original_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "The exact original is not available for this knowledge source."
        )


if TYPE_CHECKING:
    from eneo.object_content.content_service import VerifiedObjectPublication


@dataclass(frozen=True, slots=True)
class CapturedKnowledgeOriginal:
    job_id: UUID
    original_filename: str
    policy_revision: int
    storage_kind: StorageKind
    captured: CapturedContent

    def __post_init__(self) -> None:
        if not 1 <= len(self.original_filename) <= 255:
            raise ValueError("original_filename must contain 1 to 255 characters")
        if self.policy_revision < 1:
            raise ValueError("policy_revision must be positive")


@dataclass(frozen=True, slots=True)
class PreparedKnowledgeOriginal(CapturedKnowledgeOriginal):
    publication: VerifiedObjectPublication | None = None

    def __post_init__(self) -> None:
        CapturedKnowledgeOriginal.__post_init__(self)
        if self.storage_kind is StorageKind.OBJECT_STORE and self.publication is None:
            raise ValueError("object-store originals require verified publication")
        if (
            self.storage_kind is StorageKind.POSTGRES_INLINE
            and self.publication is not None
        ):
            raise ValueError("inline originals cannot carry object publication")


SourceMetadataKind = Literal["text", "choice", "date", "number", "boolean", "url"]


class SourceMetadataEntry(BaseModel):
    """One document property from the source system, e.g. a SharePoint column.

    ``name`` is the source's stable identifier for the property, ``label`` the
    human readable name the source shows, ``value`` the normalised value as
    text (a list for multi-value properties). ``kind`` lets presentation format
    dates and booleans without re-parsing the value.
    """

    name: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    value: str | list[str]
    kind: SourceMetadataKind = "text"


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
    content_hash: Optional[bytes] = None
    sharepoint_item_id: Optional[str] = None
    source_metadata: Optional[list[SourceMetadataEntry]] = None

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
    source_id: UUID
    version_state: str

    @model_validator(mode="after")
    def require_content_hash(self) -> "InfoBlobAddToDB":
        if self.content_hash is None:
            raise ValueError("Published InfoBlob content requires a SHA-256 digest")
        return self


class InfoBlobUpdatePublic(BaseModel):
    metadata: InfoBlobMetadataUpsertPublic


class InfoBlobUpdate(InfoBlobMetadataUpsertPublic):
    id: UUID
    user_id: UUID
    source_metadata: Optional[list[SourceMetadataEntry]] = None


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
    sharepoint_item_id: Optional[str] = None
    source_metadata: Optional[list[SourceMetadataEntry]] = None
    content_hash: Optional[bytes] = None
    source_id: UUID
    version_state: str
    # Availability is derived at public read boundaries, not persisted here.
    # None distinguishes an unprojected internal model from a confirmed absence.
    original_available: bool | None = None

    group: Optional[GroupInDBBase] = None
    website: Optional[WebsiteInDBBase] = None


class InfoBlobInDB(InfoBlobInDBNoText):
    text: str


class InfoBlobInDBWithScore(InfoBlobInDB):
    score: float


class InfoBlobAddPublic(InfoBlobBase):
    metadata: InfoBlobMetadataUpsertPublic = None  # type: ignore[assignment]


class InfoBlobPublicNoText(InDB):
    metadata: InfoBlobMetadata
    group_id: Optional[UUID] = None
    website_id: Optional[UUID] = None
    original_available: bool
    # Properties the source system keeps about the document (SharePoint
    # columns). Empty for sources without such properties.
    source_metadata: list[SourceMetadataEntry] = []

    @field_validator("source_metadata", mode="before")
    @classmethod
    def _none_as_empty(cls, value: object) -> object:
        # Stored as NULL for sources without properties; the API always
        # answers with a list so clients need no null check.
        return [] if value is None else value


class InfoBlobAskAssistantPublic(InfoBlobPublicNoText):
    score: float


class InfoBlobPublic(InfoBlobPublicNoText):
    text: str


class InfoBlobMetadataFilterPublic(BaseModel):
    group_ids: Optional[list[UUID]] = None
    title: Optional[str] = None


class InfoBlobMetadataFilter(InfoBlobMetadataFilterPublic):
    user_id: Optional[UUID] = None


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
    info_blob_source_metadata: list[SourceMetadataEntry] = []
    score: float


class Query(BaseModel):
    query: str
    top_k: int = 30


class QueryWithEmbedding(Query):
    embedding: list[float]

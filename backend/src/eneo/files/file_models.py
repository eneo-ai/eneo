from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.config import JsonDict

from eneo.authentication.principal_types import PrincipalType
from eneo.main.models import InDB


class ContentDisposition(str, Enum):
    ATTACHMENT = "attachment"
    INLINE = "inline"


class FileType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"


FILE_PUBLIC_EXAMPLE: JsonDict = {
    "id": "00000000-0000-0000-0000-000000000701",
    "name": "review-audio.mp3",
    "mimetype": "audio/mpeg",
    "size": 1843200,
    "created_at": "2026-03-17T10:04:00Z",
    "updated_at": "2026-03-17T10:04:00Z",
}

SIGNED_URL_RESPONSE_EXAMPLE: JsonDict = {
    "url": (
        "https://api.example.com/api/v1/files/"
        "00000000-0000-0000-0000-000000000701/download/?token=signed-token"
    ),
    "expires_at": 1773742500,
}


class FileContentVariant(StrEnum):
    ORIGINAL = "original"
    EXTRACTED_TEXT = "extracted_text"
    TRANSCRIPTION = "transcription"
    DERIVED_PAGE = "derived_page"
    MODEL_INPUT = "model_input"
    GENERATED_ARTIFACT = "generated_artifact"
    LEGACY_IMAGE = "legacy_image"
    PREVIEW = "preview"


class FileUsageKind(StrEnum):
    CHAT_ATTACHMENT = "chat_attachment"
    ASSISTANT_ATTACHMENT = "assistant_attachment"
    APP_ATTACHMENT = "app_attachment"
    APP_RUN_INPUT = "app_run_input"


class FileUsageSummary(BaseModel):
    kind: FileUsageKind
    count: int


class FileDeletionPreview(BaseModel):
    file_id: UUID
    can_delete: bool
    affected_file_count: int
    blockers: list[FileUsageSummary]


class FileInUseError(Exception):
    code = "file_in_use"

    def __init__(self, preview: FileDeletionPreview) -> None:
        self.preview = preview
        self.details = preview.model_dump(mode="json")
        super().__init__("File is still used and cannot be deleted.")


class FileOriginalNotFoundError(Exception):
    code = "file_original_not_found"

    def __init__(self) -> None:
        super().__init__("The exact original is not available for this file.")


class FileContentRangeError(Exception):
    code = "object_content_range_invalid"

    def __init__(self, message: str, *, total_size: int) -> None:
        self.total_size = total_size
        super().__init__(message)


class FileBase(BaseModel):
    name: str
    checksum: str
    size: int
    mimetype: Optional[str] = None

    file_type: FileType


class FileBaseWithContent(FileBase):
    text: Optional[str] = None
    blob: Optional[bytes] = None
    transcription: Optional[str] = None

    @model_validator(mode="after")
    def require_one_of_text_or_image(self) -> "FileBaseWithContent":
        if self.text is None and self.blob is None:
            raise ValueError("One of 'text' or 'blob' is required")

        return self


class FileInfo(InDB, FileBase):
    owner_type: PrincipalType | None = None
    owner_user_id: UUID | None = None
    owner_service_id: UUID | None = None
    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class FileOwner:
    """One authenticated principal that owns a File family."""

    tenant_id: UUID
    owner_type: PrincipalType
    owner_user_id: UUID | None = None
    owner_service_id: UUID | None = None

    def __post_init__(self) -> None:
        user_owner = (
            self.owner_type is PrincipalType.USER
            and self.owner_user_id is not None
            and self.owner_service_id is None
        )
        service_owner = (
            self.owner_type is PrincipalType.SERVICE_KEY
            and self.owner_user_id is None
            and self.owner_service_id is not None
        )
        if not (user_owner or service_owner):
            raise ValueError("File owner identity does not match its principal type")

    @property
    def created_by_user_id(self) -> UUID | None:
        return self.owner_user_id

    def matches(self, file: "FileMetadata | FileInfo") -> bool:
        return (
            file.tenant_id == self.tenant_id
            and file.owner_type is self.owner_type
            and file.owner_user_id == self.owner_user_id
            and file.owner_service_id == self.owner_service_id
        )


class FileMetadataCreate(BaseModel):
    name: str
    file_type: FileType
    mimetype: Optional[str] = None
    owner_type: PrincipalType
    owner_user_id: UUID | None = None
    owner_service_id: UUID | None = None
    tenant_id: UUID
    parent_file_id: Optional[UUID] = None

    @model_validator(mode="after")
    def validate_owner_identity(self) -> "FileMetadataCreate":
        FileOwner(
            tenant_id=self.tenant_id,
            owner_type=self.owner_type,
            owner_user_id=self.owner_user_id,
            owner_service_id=self.owner_service_id,
        )
        return self


class FileMetadata(InDB, FileMetadataCreate):
    pass


class File(InDB, FileBaseWithContent):
    owner_type: PrincipalType
    owner_user_id: UUID | None = None
    owner_service_id: UUID | None = None
    tenant_id: UUID
    parent_file_id: Optional[UUID] = None


class FilePublic(InDB):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FILE_PUBLIC_EXAMPLE},
    )

    name: str
    mimetype: str
    size: int
    transcription: Optional[str] = None
    token_count: Optional[int] = None  # Token count for the file's content


class AcceptedFileType(BaseModel):
    mimetype: str
    size_limit: int


class Limit(BaseModel):
    max_files: int
    max_size: int


class FileRestrictions(BaseModel):
    accepted_file_types: list[AcceptedFileType]
    limit: Limit


class SignedURLRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "expires_in": 3600,
                "content_disposition": "attachment",
            }
        }
    )

    expires_in: int = Field(default=3600, gt=0, le=86400)
    content_disposition: ContentDisposition = ContentDisposition.ATTACHMENT


FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS = 60 * 60


class OriginalSignedURLRequest(SignedURLRequest):
    expires_in: int = Field(
        default=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        ge=1,
        le=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    )


class SignedURLResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": SIGNED_URL_RESPONSE_EXAMPLE}
    )

    url: str
    expires_at: int  # Unix timestamp when the URL will expire

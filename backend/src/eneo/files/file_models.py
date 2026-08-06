from enum import Enum, StrEnum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from eneo.main.models import InDB


class ContentDisposition(str, Enum):
    ATTACHMENT = "attachment"
    INLINE = "inline"


class FileType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"


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
    user_id: UUID
    tenant_id: UUID


class FileMetadataCreate(BaseModel):
    name: str
    file_type: FileType
    mimetype: Optional[str] = None
    user_id: UUID
    tenant_id: UUID
    parent_file_id: Optional[UUID] = None


class FileMetadata(InDB, FileMetadataCreate):
    pass


class File(InDB, FileBaseWithContent):
    user_id: UUID
    tenant_id: UUID
    parent_file_id: Optional[UUID] = None
    # True when the exact original upload is durably stored (an ORIGINAL content
    # reference exists), i.e. a signed original-download URL can serve it. False
    # for rows predating durable originals and for generated files.
    original_available: bool = False


class FilePublic(InDB):
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
    # Default 1 hour; capped at 7 days so a leaked URL cannot stay valid
    # indefinitely (tokens are stateless and cannot be revoked).
    expires_in: int = Field(default=3600, ge=1, le=604_800)
    content_disposition: ContentDisposition = ContentDisposition.ATTACHMENT


FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS = 60 * 60


class OriginalSignedURLRequest(SignedURLRequest):
    expires_in: int = Field(
        default=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        ge=1,
        le=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    )


class SignedURLResponse(BaseModel):
    url: str
    expires_at: int  # Unix timestamp when the URL will expire

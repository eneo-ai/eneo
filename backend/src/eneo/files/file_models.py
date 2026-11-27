from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from eneo.authentication.principal_types import PrincipalType
from eneo.files.extensions import MIMETYPE_EXTENSIONS_MAPPER
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
        super().__init__(
            "File is still in use and cannot be deleted. "
            "See details.blockers for the remaining references; "
            "retry only after those references have been removed."
        )


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
    # Bytes of the primary representation: for a text file its extracted text,
    # which is what attachment budgets count.
    size: int
    mimetype: Optional[str] = None
    # Bytes of the exact original (what a download delivers), when one is
    # stored. Differs from ``size`` for documents, whose primary
    # representation is extracted text.
    original_size: Optional[int] = None

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
    owner_type: PrincipalType
    owner_user_id: UUID | None = None
    owner_service_id: UUID | None = None
    tenant_id: UUID
    revises_file_id: Optional[UUID] = None


@dataclass(frozen=True, slots=True)
class FileOwner:
    """The one principal that owns a file and the files derived from it: a
    person, or the service principal behind a service key."""

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
    revises_file_id: Optional[UUID] = None

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
    # The earlier version of a conversation document this file was saved
    # from, when a user edited it in Eneo.
    revises_file_id: Optional[UUID] = None
    # True when a signed original-download URL can serve this file: the exact
    # original upload is durably stored, or (for images) the generated artifact
    # that is the file's only original. False for rows predating durable
    # originals and for derived images (rendered pages, embedded images).
    original_available: bool = False


class FileContentNotLoadedError(RuntimeError):
    """Code read the content of a file that was loaded for its facts only."""


class FileWithoutContent(File):
    """An attachment's facts, for reads that never use its content.

    Reading ``text`` or ``blob`` raises: ``None`` would pass as an empty file
    and a model would silently get nothing.
    """

    @model_validator(mode="after")
    def require_one_of_text_or_image(self) -> "FileWithoutContent":
        return self

    def __getattribute__(self, name: str) -> Any:
        if name in ("text", "blob"):
            raise FileContentNotLoadedError(f"File content was not loaded: {name}")
        return super().__getattribute__(name)


class FilePublic(InDB):
    name: str
    mimetype: str
    size: int
    # Size of the file as downloaded, when its exact original is stored; show
    # this to users rather than ``size``.
    original_size: Optional[int] = None
    transcription: Optional[str] = None
    token_count: Optional[int] = None  # Token count for the file's content
    # Public capability signal only; never expose storage internals. The chat
    # composer uses this to show the built-in files tool only when a
    # conversation attachment can actually be represented by a signed URL
    # (a TEXT file whose exact original is durably stored).
    has_download_reference: bool = False
    # The earlier version of a conversation document this file was saved
    # from; clients chain a document's versions by it.
    revises_file_id: Optional[UUID] = None


class AcceptedFileType(BaseModel):
    mimetype: str
    size_limit: int
    extensions: list[str]

    @classmethod
    def for_mimetype(cls, mimetype: str, size_limit: int) -> "AcceptedFileType":
        # Every producer goes through here so the advertised extensions always
        # match the mimetype; the frontend renders these instead of mimetypes.
        return cls(
            mimetype=mimetype,
            size_limit=size_limit,
            extensions=list(MIMETYPE_EXTENSIONS_MAPPER.get(mimetype, [])),
        )


class Limit(BaseModel):
    max_files: int
    max_size: int


class FileRestrictions(BaseModel):
    accepted_file_types: list[AcceptedFileType]
    limit: Limit


# Signed links are stateless bearer credentials and cannot be revoked, so
# every purpose has a hard maximum lifetime enforced at mint and at redemption.
FILE_PROCESSING_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS = 7 * 24 * 60 * 60
FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS = 60 * 60


class SignedURLRequest(BaseModel):
    # Default 1 hour; capped at 7 days so a leaked URL cannot stay valid
    # indefinitely.
    expires_in: int = Field(
        default=3600, ge=1, le=FILE_PROCESSING_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS
    )
    content_disposition: ContentDisposition = ContentDisposition.ATTACHMENT


class OriginalSignedURLRequest(SignedURLRequest):
    expires_in: int = Field(
        default=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        ge=1,
        le=FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    )


class SignedURLResponse(BaseModel):
    url: str
    expires_at: int  # Unix timestamp when the URL will expire

from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.config import JsonDict

from intric.authentication.principal_types import PrincipalType
from intric.main.models import InDB


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
    owner_api_key_id: UUID | None = None
    tenant_id: UUID


class FileCreate(FileBaseWithContent):
    owner_type: PrincipalType | None = None
    owner_user_id: UUID | None = None
    owner_api_key_id: UUID | None = None
    tenant_id: UUID


class File(InDB, FileCreate):
    pass


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
                "expires_in": 900,
                "content_disposition": "attachment",
            }
        }
    )

    expires_in: int = 3600  # Default expiration time in seconds (1 hour)
    content_disposition: ContentDisposition = ContentDisposition.ATTACHMENT


class SignedURLResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": SIGNED_URL_RESPONSE_EXAMPLE}
    )

    url: str
    expires_at: int  # Unix timestamp when the URL will expire

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResourcePackageImportSource(StrEnum):
    FILE_UPLOAD = "file_upload"


class ResourcePackageImportStatus(StrEnum):
    DRAFT_CREATED = "draft_created"
    FAILED = "failed"


class ResourcePackageImportFailurePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    message: str
    context: dict[str, str | int] = Field(default_factory=dict)

    @field_validator("code", "message")
    @classmethod
    def normalize_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Package import failure text must not be empty.")
        return normalized

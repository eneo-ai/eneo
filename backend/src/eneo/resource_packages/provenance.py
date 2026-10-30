from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.json_types import JsonObject
from eneo.resource_packages.checksum import json_object_from_model


class ResourcePackageOmissionKind(StrEnum):
    MCP_ATTACHMENT = "mcp_attachment"


class ResourcePackageOmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal[ResourcePackageOmissionKind.MCP_ATTACHMENT]
    count: int = Field(ge=1, strict=True)

    @classmethod
    def mcp_attachment(cls, *, count: int) -> ResourcePackageOmission:
        return cls(kind=ResourcePackageOmissionKind.MCP_ATTACHMENT, count=count)


class ResourcePackageProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    exported_at: datetime
    source_instance_id: str | None = None
    exported_by: str | None = None
    lineage: list[str] = Field(default_factory=list)
    omissions: list[ResourcePackageOmission] = Field(max_length=1)

    @classmethod
    def for_portable_export(
        cls,
        *,
        exported_at: datetime,
        omissions: list[ResourcePackageOmission],
    ) -> ResourcePackageProvenance:
        return cls(
            schema_version=1,
            exported_at=exported_at,
            omissions=omissions,
        )

    @field_validator("source_instance_id", "exported_by")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("lineage")
    @classmethod
    def normalize_lineage(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    def canonical_hash_input(self) -> JsonObject:
        return json_object_from_model(self)

    @property
    def omitted_mcp_assistant_count(self) -> int | None:
        if not self.omissions:
            return None
        return self.omissions[0].count

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported schema version.")
        return value

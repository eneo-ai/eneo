from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intric.flow_packages.domain.flow_package_checksum import json_object_from_model
from intric.flow_packages.domain.flow_package_manifest import JsonObject


class FlowPackageProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    exported_at: datetime
    source_instance_id: str | None = None
    exported_by: str | None = None
    lineage: list[str] = Field(default_factory=list)

    @classmethod
    def for_portable_export(
        cls,
        *,
        exported_at: datetime,
    ) -> "FlowPackageProvenance":
        return cls(schema_version=1, exported_at=exported_at)

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

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported schema version.")
        return value

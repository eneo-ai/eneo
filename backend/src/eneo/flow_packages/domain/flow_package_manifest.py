from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eneo.json_types import JsonObject

_PACKAGE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_REPEATED_DOTS_RE = re.compile(r"\.{2,}")
_PACKAGE_FILENAME_STEM_MAX_LENGTH = 160
MAX_FLOW_PACKAGE_VERSION_LENGTH = 64


class EneoPackageKind(StrEnum):
    FLOW = "flow"
    ASSISTANT = "assistant"
    APP = "app"


FLOW_PACKAGE_PAYLOAD_SCHEMA = "eneo.flow_package.v1"
ASSISTANT_PACKAGE_PAYLOAD_SCHEMA = "eneo.assistant_package.v1"
APP_PACKAGE_PAYLOAD_SCHEMA = "eneo.app_package.v1"

PACKAGE_PAYLOAD_SCHEMA_BY_KIND = {
    EneoPackageKind.FLOW: FLOW_PACKAGE_PAYLOAD_SCHEMA,
    EneoPackageKind.ASSISTANT: ASSISTANT_PACKAGE_PAYLOAD_SCHEMA,
    EneoPackageKind.APP: APP_PACKAGE_PAYLOAD_SCHEMA,
}


class FlowPackageManifestMetadataFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    package_id: str
    package_version: str = Field(max_length=MAX_FLOW_PACKAGE_VERSION_LENGTH)
    name: str
    description: str = ""

    @field_validator("package_id")
    @classmethod
    def validate_package_id(cls, value: str) -> str:
        normalized = value.strip()
        if (
            len(normalized) < 3
            or len(normalized) > 128
            or not _PACKAGE_ID_RE.fullmatch(normalized)
            or ".." in normalized
            or ".-" in normalized
            or "-." in normalized
        ):
            raise ValueError(
                "Package ID must be lowercase dot or hyphen separated segments."
            )
        return normalized

    @field_validator("package_version")
    @classmethod
    def validate_package_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > MAX_FLOW_PACKAGE_VERSION_LENGTH:
            raise ValueError("Package version must be between 1 and 64 characters.")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be empty.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()


class FlowPackageManifestMetadata(FlowPackageManifestMetadataFields):
    schema_version: Literal[1]
    kind: EneoPackageKind
    payload_schema: str = FLOW_PACKAGE_PAYLOAD_SCHEMA

    def canonical_hash_input(self) -> JsonObject:
        return {
            "description": self.description,
            "name": self.name,
            "kind": self.kind.value,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "payload_schema": self.payload_schema,
            "schema_version": self.schema_version,
        }

    def with_content_checksum(self, content_checksum: str) -> "FlowPackageManifest":
        return FlowPackageManifest(
            schema_version=self.schema_version,
            package_id=self.package_id,
            package_version=self.package_version,
            name=self.name,
            description=self.description,
            kind=self.kind,
            payload_schema=self.payload_schema,
            content_checksum=content_checksum,
        )

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported schema version.")
        return value

    @field_validator("payload_schema")
    @classmethod
    def normalize_payload_schema(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Package payload schema must not be empty.")
        return normalized

    @model_validator(mode="after")
    def validate_payload_schema_for_kind(self) -> "FlowPackageManifestMetadata":
        expected = PACKAGE_PAYLOAD_SCHEMA_BY_KIND[self.kind]
        if self.payload_schema != expected:
            raise ValueError(
                f"{self.kind.value} packages must use payload schema {expected}."
            )
        return self


class FlowPackageManifest(FlowPackageManifestMetadata):
    content_checksum: str

    @field_validator("content_checksum")
    @classmethod
    def validate_content_checksum(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _SHA256_HEX_RE.fullmatch(normalized):
            raise ValueError("Content checksum must be a lowercase SHA-256 hex digest.")
        return normalized

    def canonical_hash_input(self) -> JsonObject:
        return FlowPackageManifestMetadata(
            schema_version=self.schema_version,
            package_id=self.package_id,
            package_version=self.package_version,
            name=self.name,
            description=self.description,
            kind=self.kind,
            payload_schema=self.payload_schema,
        ).canonical_hash_input()


def flow_package_filename(manifest: FlowPackageManifestMetadataFields) -> str:
    stem = f"{manifest.package_id}-{manifest.package_version}"
    ascii_stem = (
        unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    )
    safe_stem = _UNSAFE_FILENAME_CHARS_RE.sub("_", ascii_stem).strip("._-")
    safe_stem = _REPEATED_DOTS_RE.sub(".", safe_stem).strip("._-")
    if not safe_stem:
        safe_stem = "flow-package"
    if len(safe_stem) > _PACKAGE_FILENAME_STEM_MAX_LENGTH:
        safe_stem = (
            safe_stem[:_PACKAGE_FILENAME_STEM_MAX_LENGTH].rstrip("._-")
            or "flow-package"
        )
    return f"{safe_stem}.eneopkg"

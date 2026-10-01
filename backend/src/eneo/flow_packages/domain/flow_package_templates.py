from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_limits import MAX_FLOW_PACKAGE_BYTES


class FlowPackageTemplateField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=255)
    kind: Literal["text", "rich"]


def validate_template_filename(value: str) -> str:
    """The one rule for a package template's filename: a DOCX basename."""

    if not value.lower().endswith(".docx") or any(
        character in value for character in ("/", "\\", "\x00")
    ):
        raise ValueError("A package template filename must be a DOCX basename.")
    return value


class FlowPackageTemplateDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    filename: str = Field(min_length=1, max_length=255)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(strict=True, gt=0, le=MAX_FLOW_PACKAGE_BYTES)
    fields: list[FlowPackageTemplateField] = Field(min_length=1, max_length=512)
    asset_path: str | None = None

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return validate_template_filename(value)

    @model_validator(mode="after")
    def validate_contract(self) -> "FlowPackageTemplateDescriptor":
        names = [field.name for field in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("Package template field names must be unique.")
        if self.asset_path is not None and self.asset_path != self.content_path:
            raise ValueError("Package template path must match its content checksum.")
        return self

    @property
    def content_path(self) -> str:
        return f"templates/{self.checksum}.docx"


@dataclass(frozen=True, slots=True)
class FlowPackageTemplateFile:
    filename: str
    content: bytes
    checksum: str


def require_package_template_fields(
    expected: FlowPackageTemplateDescriptor,
    actual: FlowPackageTemplateDescriptor,
    *,
    slot_ref: str,
) -> None:
    expected_fields = {field.name: field.kind for field in expected.fields}
    actual_fields = {field.name: field.kind for field in actual.fields}
    if actual_fields != expected_fields:
        raise FlowPackageValidationError(
            code=FlowPackageErrorCode.TEMPLATE_FIELDS_MISMATCH,
            message="The Word template fields do not match the package.",
            context={
                "slot_ref": slot_ref,
                "filename": actual.filename,
                "missing_fields": ", ".join(
                    sorted(expected_fields.keys() - actual_fields.keys())[:8]
                ),
                "added_fields": ", ".join(
                    sorted(actual_fields.keys() - expected_fields.keys())[:8]
                ),
                "changed_fields": ", ".join(
                    name
                    for name in sorted(expected_fields.keys() & actual_fields.keys())
                    if expected_fields[name] != actual_fields[name]
                )[:640],
            },
        )


def validate_package_template_payloads(
    descriptors: Mapping[str, FlowPackageTemplateDescriptor],
    payloads: Mapping[str, bytes],
) -> None:
    expected_paths = {
        descriptor.asset_path
        for descriptor in descriptors.values()
        if descriptor.asset_path is not None
    }
    if set(payloads) != expected_paths:
        raise FlowPackageValidationError(
            code=FlowPackageErrorCode.TEMPLATE_FILE_INVALID,
            message="Package template files do not match the declared template resources.",
        )
    verified: set[str] = set()
    for descriptor in descriptors.values():
        if descriptor.asset_path is None:
            continue
        content = payloads[descriptor.asset_path]
        # The path is the checksum, so a payload shared by several slots is
        # hashed once, not once per slot.
        if descriptor.asset_path not in verified:
            if hashlib.sha256(content).hexdigest() != descriptor.checksum:
                raise FlowPackageValidationError(
                    code=FlowPackageErrorCode.CHECKSUM_MISMATCH,
                    message="A package Word template checksum does not match.",
                    context={"filename": descriptor.filename},
                )
            verified.add(descriptor.asset_path)
        if len(content) != descriptor.size_bytes:
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.CHECKSUM_MISMATCH,
                message="A package Word template checksum does not match.",
                context={"filename": descriptor.filename},
            )

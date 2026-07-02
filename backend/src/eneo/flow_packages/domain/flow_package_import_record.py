from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorContextValue,
)
from eneo.flows.flow_resource_bindings import LocalResourceBinding


class FlowPackageImportSource(StrEnum):
    FILE_UPLOAD = "file_upload"


class FlowPackageImportStatus(StrEnum):
    DRAFT_CREATED = "draft_created"
    FAILED = "failed"


def _empty_bindings() -> list[LocalResourceBinding]:
    return []


def _empty_failure_context() -> dict[str, FlowPackageErrorContextValue]:
    return {}


class FlowPackageImportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_bindings: list[LocalResourceBinding] = Field(
        default_factory=_empty_bindings,
        description="Local target resources selected for package dependency slots.",
    )

    def bindings_tuple(self) -> tuple[LocalResourceBinding, ...]:
        return tuple(self.selected_bindings)


class FlowPackageImportFailurePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    message: str
    context: dict[str, FlowPackageErrorContextValue] = Field(
        default_factory=_empty_failure_context
    )

    @field_validator("code", "message")
    @classmethod
    def normalize_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Flow package import failure text must not be empty.")
        return normalized

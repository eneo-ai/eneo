"""Live progress of a running SharePoint sync, as the worker stores it in
Redis and the API serves it."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Optional, cast
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from eneo.integration.domain.skip_reasons import SkipReasonCode, visible_skip


class IntegrationSyncProgressFile(BaseModel):
    """A file or page a running sync has finished with."""

    name: str
    outcome: Literal["indexed", "unchanged", "skipped"]
    reason: Optional[str] = Field(
        default=None, description="Why a skipped file was skipped, when known"
    )
    code: Optional[SkipReasonCode] = Field(
        default=None, description="The skip reason's code, when known"
    )
    params: dict[str, str | int] = Field(default_factory=dict)
    retry: bool = Field(default=False, description="The next sync tries the file again")

    @model_validator(mode="before")
    @classmethod
    def _user_visible(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        entry = cast(Mapping[str, Any], value)
        if not isinstance(entry.get("reason"), str):
            return entry
        visible = visible_skip({**entry, "file": str(entry.get("name", ""))})
        return {
            **entry,
            "reason": visible["reason"],
            "code": visible.get("code"),
            "params": visible.get("params", {}),
            "retry": bool(visible.get("retry")),
        }


def _no_finished_files() -> list[IntegrationSyncProgressFile]:
    return []


class IntegrationSyncProgress(BaseModel):
    """Live progress of a SharePoint sync that is running now.

    `total` counts the files and site pages the sync has listed so far. A full
    sync lists each folder when it reaches it, so `total` is null until the
    first listing returns and then grows as subfolders are found; it never
    drops below `done`. A delta sync cannot cheaply tell which of its changes
    are files in scope, so its `total` stays null.
    """

    integration_knowledge_id: UUID
    sync_type: Literal["full", "delta"]
    phase: Literal["discovering", "processing", "finishing"] = Field(
        description="discovering: resolving scope and listing changes before "
        "files are handled; processing: handling files; finishing: orphan "
        "cleanup, delta token and summary"
    )
    started_at: datetime
    updated_at: datetime = Field(description="When this progress was last written")
    total: Optional[int] = Field(
        description="Files and pages listed so far; null while unknown"
    )
    done: int = Field(description="Files finished: indexed + unchanged + skipped")
    indexed: int = Field(description="Files and pages embedded in this sync")
    unchanged: int
    skipped: int
    deleted: int = Field(description="Local documents removed in this sync")
    current: Optional[str] = Field(
        default=None,
        description="Name of the file or page being handled now; never a folder",
    )
    recent: list[IntegrationSyncProgressFile] = Field(
        default_factory=_no_finished_files,
        description="Files and pages finished most recently, newest first, at most 8",
    )

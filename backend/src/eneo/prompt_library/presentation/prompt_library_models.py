# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.main.models import NOT_PROVIDED, NotProvided


class PromptLibraryEntryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    text: str = Field(min_length=1)


class PromptLibraryEntryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None | NotProvided = NOT_PROVIDED
    text: str | None = Field(default=None, min_length=1)


class PromptLibraryEntryPublic(BaseModel):
    id: UUID
    name: str
    description: str | None
    text: str
    current_version: int
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class PromptLibraryEntrySparse(BaseModel):
    """List view — text excluded for payload size."""

    id: UUID
    name: str
    description: str | None
    current_version: int
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class PromptLibraryVersionPublic(BaseModel):
    id: UUID
    prompt_library_id: UUID
    version: int
    name: str
    description: str | None
    text: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

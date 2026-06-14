# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from intric.main.exceptions import BadRequestException
from intric.main.models import NOT_PROVIDED, NotProvided, is_provided


@dataclass
class PromptLibraryEntry:
    id: UUID | None
    tenant_id: UUID
    name: str
    description: str | None
    text: str
    current_version: int
    created_by_user_id: UUID
    created_at: datetime | None
    updated_at: datetime | None

    def update(
        self,
        *,
        name: str | None = None,
        description: str | None | NotProvided = NOT_PROVIDED,
        text: str | None = None,
    ) -> None:
        if name is not None:
            if not name.strip():
                raise BadRequestException("name cannot be empty")
            self.name = name
        if is_provided(description):
            self.description = description
        if text is not None:
            if not text.strip():
                raise BadRequestException("text cannot be empty")
            self.text = text


@dataclass
class PromptLibraryVersion:
    id: UUID | None
    prompt_library_id: UUID
    tenant_id: UUID
    version: int
    name: str
    description: str | None
    text: str
    created_by_user_id: UUID
    created_at: datetime | None
    updated_at: datetime | None

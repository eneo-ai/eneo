# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eneo.users.user import UserSparse


@dataclass
class Prompt:
    created_at: datetime | None
    updated_at: datetime | None
    id: UUID | None
    text: str
    description: str | None
    # Detached execution prompts need not have an author record.
    user_id: UUID | None
    tenant_id: UUID
    is_selected: bool | None
    user: UserSparse | None

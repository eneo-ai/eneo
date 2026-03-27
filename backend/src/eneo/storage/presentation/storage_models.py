# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.


from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StorageSpaceMemberModel(BaseModel):
    created_at: datetime
    updated_at: datetime
    id: UUID
    email: str
    role: str


class StorageSpaceInfoModel(BaseModel):
    created_at: datetime
    update_at: datetime
    id: UUID
    name: str
    size: int
    members: list[StorageSpaceMemberModel]


class StorageInfoModel(BaseModel):
    count: int
    items: list[StorageSpaceInfoModel]


class StorageModel(BaseModel):
    total_used: int
    personal_used: int
    shared_used: int
    limit: int

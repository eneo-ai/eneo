# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Optional

from pydantic import BaseModel

from intric.main.models import InDB, ResourcePermissionsMixin
from intric.users.user import UserSparse


class PromptCreate(BaseModel):
    text: str
    description: Optional[str] = None


class PromptUpdateRequest(BaseModel):
    description: Optional[str] = None


class PromptSparse(InDB, ResourcePermissionsMixin):
    description: Optional[str] = None
    is_selected: bool

    user: UserSparse


class PromptPublic(PromptSparse):
    text: str
    is_selected: Optional[bool] = None  # type: ignore[assignment]  # intentionally widens parent's non-optional is_selected to Optional for public API

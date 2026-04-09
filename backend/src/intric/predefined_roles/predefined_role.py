# MIT License

from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from intric.main.models import DateTimeModelMixin
from intric.roles.permissions import Permission


class PredefinedRoleName(str, Enum):
    USER = "User"
    AI_CONFIGURATOR = "AI Configurator"
    OWNER = "Owner"


class PredefinedRoleBase(BaseModel):
    name: str
    permissions: list[Permission]


class PredefinedRoleCreate(PredefinedRoleBase):
    pass


class PredefinedRoleUpdateRequest(BaseModel):
    name: Optional[str] = None
    permissions: Optional[list[Permission]] = None


class PredefinedRoleUpdate(PredefinedRoleUpdateRequest):
    id: UUID


class PredefinedRoleInDB(PredefinedRoleBase, DateTimeModelMixin):
    id: UUID

    model_config = ConfigDict(from_attributes=True)


class PredefinedRolePublic(PredefinedRoleInDB):
    pass

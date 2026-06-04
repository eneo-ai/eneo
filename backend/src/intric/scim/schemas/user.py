from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class ScimUserState(str, Enum):
    """Internal Eneo user states — not exposed in SCIM responses."""

    INVITED = "invited"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"


class ScimEmail(BaseModel):
    value: str
    primary: bool = False


class ScimMeta(BaseModel):
    resourceType: str
    created: datetime | None = None
    lastModified: datetime | None = None
    location: str | None = None


class ScimUser(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    id: str
    externalId: str | None = None
    userName: str
    emails: list[ScimEmail] = []
    active: bool = True
    meta: ScimMeta


class ScimUserRequest(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    externalId: str | None = None
    userName: str
    emails: list[ScimEmail] = []
    active: bool = True


class PatchOperation(BaseModel):
    op: str
    path: str | None = None
    value: Any = None


class PatchRequest(BaseModel):
    schemas: list[str]
    Operations: list[PatchOperation]

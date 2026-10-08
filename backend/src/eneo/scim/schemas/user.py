from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eneo.scim.constants import SCIM_CORE_USER_URN, SCIM_ENTERPRISE_USER_URN


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


def _is_none(value: object) -> bool:
    return value is None


class ScimManager(BaseModel):
    """Stored manager reference. ``displayName`` is readOnly per RFC 7643 §4.3
    and is never echoed: Eneo does not resolve it."""

    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    value: str | None = Field(default=None, exclude_if=_is_none)
    ref: str | None = Field(default=None, alias="$ref", exclude_if=_is_none)


class ScimEnterpriseUser(BaseModel):
    employeeNumber: str | None = Field(default=None, exclude_if=_is_none)
    costCenter: str | None = Field(default=None, exclude_if=_is_none)
    organization: str | None = Field(default=None, exclude_if=_is_none)
    division: str | None = Field(default=None, exclude_if=_is_none)
    department: str | None = Field(default=None, exclude_if=_is_none)
    manager: ScimManager | None = Field(default=None, exclude_if=_is_none)


class ScimUser(BaseModel):
    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    schemas: list[str] = [SCIM_CORE_USER_URN]
    id: str
    externalId: str | None = None
    userName: str
    emails: list[ScimEmail] = []
    active: bool = True
    meta: ScimMeta
    # Echoes what was stored, not what was sent: omitted entirely when nothing
    # is stored, so responses for users without the extension are unchanged.
    enterprise_user: ScimEnterpriseUser | None = Field(
        default=None,
        validation_alias=SCIM_ENTERPRISE_USER_URN,
        serialization_alias=SCIM_ENTERPRISE_USER_URN,
        exclude_if=_is_none,
    )


class ScimUserRequest(BaseModel):
    # Extension objects arrive as top-level URN keys; keep them so the service
    # can persist the enterprise one and ignore the rest.
    model_config = ConfigDict(extra="allow")

    schemas: list[str] = [SCIM_CORE_USER_URN]
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

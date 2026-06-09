from pydantic import BaseModel

from intric.scim.schemas.user import ScimMeta


class ScimGroupMember(BaseModel):
    value: str
    display: str | None = None


class ScimGroup(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:Group"]
    id: str
    externalId: str | None = None
    displayName: str
    members: list[ScimGroupMember] = []
    meta: ScimMeta


class ScimGroupRequest(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:Group"]
    externalId: str | None = None
    displayName: str
    members: list[ScimGroupMember] = []

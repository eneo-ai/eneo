from uuid import UUID

from pydantic import BaseModel

from intric.main.models import InDB


class IconBase(BaseModel):
    blob: bytes
    mimetype: str
    size: int


class IconCreate(IconBase):
    tenant_id: UUID


class Icon(InDB, IconCreate):
    pass

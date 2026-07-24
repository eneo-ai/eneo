from uuid import UUID

from pydantic import BaseModel

from eneo.main.models import InDB


class IconBase(BaseModel):
    blob: bytes
    mimetype: str
    size: int


class Icon(InDB, IconBase):
    tenant_id: UUID


class IconMetadataCreate(BaseModel):
    tenant_id: UUID


class IconMetadata(InDB, IconMetadataCreate):
    pass

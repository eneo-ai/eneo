from uuid import UUID

from pydantic import BaseModel

from eneo.main.models import InDB


class IconMetadataCreate(BaseModel):
    tenant_id: UUID


class IconMetadata(InDB, IconMetadataCreate):
    pass

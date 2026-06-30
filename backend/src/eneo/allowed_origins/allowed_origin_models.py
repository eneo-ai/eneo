from uuid import UUID

from pydantic import BaseModel

from eneo.main.models import InDB


class AllowedOrigin(BaseModel):
    url: str


class AllowedOriginCreate(AllowedOrigin):
    tenant_id: UUID


class AllowedOriginInDB(AllowedOriginCreate, InDB):
    pass


class AllowedOriginPublic(AllowedOrigin, InDB):
    pass

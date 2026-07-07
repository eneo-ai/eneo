from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from eneo.main.config import validate_redirect_uri
from eneo.main.models import InDB


class Modules(str, Enum):
    """
    Any change to these enums will result in database changes
    """

    ENEO_APPLICATIONS = "eneo-applications"


class ModuleBase(BaseModel):
    name: Modules | str


class ModuleClientConfig(BaseModel):
    """Auth-broker client config for a module: which callback URLs are allowed
    and which sk_ key alone may exchange the module's login tickets."""

    redirect_uris: Optional[list[str]] = None
    service_key_id: Optional[UUID] = None

    @field_validator("redirect_uris")
    @classmethod
    def normalize_redirect_uris(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None

        normalized: list[str] = []
        for uri in value:
            redirect_uri = validate_redirect_uri(uri)
            if redirect_uri is None:
                raise ValueError(f"Invalid redirect URI: {uri}")
            if redirect_uri not in normalized:
                normalized.append(redirect_uri)
        return normalized


class ModuleTenantClientConfig(ModuleClientConfig):
    tenant_id: UUID
    module_id: UUID


class ModuleInDB(InDB, ModuleBase):
    pass

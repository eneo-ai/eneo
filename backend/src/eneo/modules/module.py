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

    def update_values(self) -> dict[str, object]:
        """Return only fields explicitly supplied by the PATCH caller.

        An explicit ``null`` remains an update while an omitted field is left
        untouched. Keeping this distinction on the request model prevents
        persistence adapters from accidentally turning PATCH into PUT.
        """
        values: dict[str, object] = {}
        if "redirect_uris" in self.model_fields_set:
            values["redirect_uris"] = self.redirect_uris
        if "service_key_id" in self.model_fields_set:
            values["service_key_id"] = self.service_key_id
        return values


class ModuleTenantClientConfig(ModuleClientConfig):
    tenant_id: UUID
    module_id: UUID


class ModuleInDB(InDB, ModuleBase):
    pass

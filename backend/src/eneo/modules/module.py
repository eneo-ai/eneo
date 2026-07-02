from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

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


class ModuleInDB(InDB, ModuleBase):
    redirect_uris: Optional[list[str]] = None
    service_key_id: Optional[UUID] = None

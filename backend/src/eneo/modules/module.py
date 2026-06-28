from enum import Enum

from pydantic import BaseModel

from eneo.main.models import InDB


class Modules(str, Enum):
    """
    Any change to these enums will result in database changes
    """

    ENEO_APPLICATIONS = "eneo-applications"


class ModuleBase(BaseModel):
    name: Modules | str


class ModuleInDB(InDB, ModuleBase):
    pass

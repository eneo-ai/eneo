from enum import Enum

from pydantic import BaseModel

from intric.main.models import InDB


class Modules(str, Enum):
    """
    Any change to these enums will result in database changes
    """

    INTRIC_APPLICATIONS = "intric-applications"


class ModuleBase(BaseModel):
    name: Modules | str


class ModuleInDB(InDB, ModuleBase):
    pass

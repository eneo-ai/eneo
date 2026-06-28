from typing import Optional
from uuid import UUID

from eneo.base.base_entity import Entity


class Integration(Entity):
    def __init__(
        self,
        name: str,
        description: str,
        integration_type: str,
        id: Optional[UUID] = None,
    ):
        super().__init__(id=id)
        self.name = name
        self.description = description
        self.integration_type = integration_type

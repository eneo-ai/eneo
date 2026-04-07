from typing import TYPE_CHECKING, Sequence, cast
from uuid import UUID

from intric.integration.domain.entities.integration import Integration

if TYPE_CHECKING:
    from intric.database.tables.integration_table import (
        Integration as IntegrationDBModel,
    )


class IntegrationFactory:
    @classmethod
    def create_entity(cls, record: "IntegrationDBModel") -> "Integration":
        return Integration(
            id=cast(UUID, record.id),
            name=record.name,
            description=record.description,
            integration_type=record.integration_type,
        )

    @classmethod
    def create_entities(
        cls, records: Sequence["IntegrationDBModel"]
    ) -> list["Integration"]:
        return [cls.create_entity(record=record) for record in records]

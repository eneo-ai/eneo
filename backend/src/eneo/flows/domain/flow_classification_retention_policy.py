from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FlowClassificationRetentionPolicy:
    tenant_id: UUID
    security_classification_id: UUID
    data_retention_days: int | None
    minimum_retention_days: int | None = None
    no_purge: bool = False

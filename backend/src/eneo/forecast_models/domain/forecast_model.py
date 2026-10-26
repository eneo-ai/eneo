from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from eneo.ai_models.ai_model import AIModel
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eneo.database.tables.ai_models_table import (
        ForecastModels as ForecastModelsDB,
    )
    from eneo.users.user import UserInDB


@dataclass(frozen=True)
class ForecastModelUsage:
    """A Forecast source (``mcp_servers`` row) that runs on the model."""

    id: UUID
    name: str
    purpose: str


class ForecastModel(AIModel):
    """A checkpoint a tool service runs, governed like any catalog model.

    ``name`` is the key the tool service knows the checkpoint by; only the
    display name (``nickname``), enablement and classification are the
    tenant's to change.
    """

    def __init__(
        self,
        user: UserInDB,
        id: UUID,
        created_at: datetime,
        updated_at: datetime,
        nickname: str,
        name: str,
        org: Optional[str],
        open_source: bool,
        description: Optional[str],
        is_deprecated: bool,
        is_org_enabled: bool,
        tenant_id: UUID,
        provider_id: UUID,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
        security_classification: Optional[SecurityClassification] = None,
        used_by_mcp_servers: Optional[list[ForecastModelUsage]] = None,
    ):
        super().__init__(
            user=user,
            id=id,
            created_at=created_at,
            updated_at=updated_at,
            nickname=nickname,
            name=name,
            family=None,
            hosting=None,
            org=org,
            stability=None,
            open_source=open_source,
            description=description,
            hf_link=None,
            is_deprecated=is_deprecated,
            is_org_enabled=is_org_enabled,
            security_classification=security_classification,
        )
        self.tenant_id = tenant_id
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.provider_type = provider_type
        self.used_by_mcp_servers: list[ForecastModelUsage] = list(
            used_by_mcp_servers or []
        )

    @classmethod
    def create_from_db(
        cls,
        forecast_model_db: ForecastModelsDB,
        user: UserInDB,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
    ) -> ForecastModel:
        return cls(
            user=user,
            id=forecast_model_db.id,
            created_at=forecast_model_db.created_at,
            updated_at=forecast_model_db.updated_at,
            nickname=forecast_model_db.nickname,
            name=forecast_model_db.name,
            org=forecast_model_db.org,
            open_source=forecast_model_db.open_source or False,
            description=forecast_model_db.description,
            is_deprecated=forecast_model_db.is_deprecated,
            is_org_enabled=forecast_model_db.is_enabled,
            tenant_id=forecast_model_db.tenant_id,
            provider_id=forecast_model_db.provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=forecast_model_db.security_classification
            ),
        )

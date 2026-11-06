from typing import Annotated, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from eneo.forecast_models.domain.forecast_model import ForecastModel
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided
from eneo.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)


class ForecastModelUsedByPublic(BaseModel):
    """A Forecast source that runs on the model."""

    id: UUID
    name: str
    purpose: str


class ForecastModelPublic(BaseModel):
    id: UUID
    name: str = Field(
        description="The key the tool service knows the checkpoint by; set by Eneo."
    )
    nickname: str
    org: Optional[str] = None
    open_source: Optional[bool] = None
    description: Optional[str] = None
    is_deprecated: bool = False
    can_access: bool = False
    is_org_enabled: bool = False
    security_classification: Optional[SecurityClassificationPublic] = None
    tenant_id: UUID
    provider_id: UUID
    provider_name: Optional[str] = None
    provider_type: Optional[str] = None
    # The Forecast sources that run on this model.
    used_by_mcp_servers: list[ForecastModelUsedByPublic] = []

    @classmethod
    def from_domain(cls, model: ForecastModel):
        return cls(
            id=model.id,
            name=model.name,
            nickname=model.nickname or "",
            org=model.org,
            open_source=model.open_source,
            description=model.description,
            is_deprecated=model.is_effectively_deprecated,
            can_access=model.can_access,
            is_org_enabled=model.is_org_enabled,
            security_classification=SecurityClassificationPublic.from_domain(
                model.security_classification,
                return_none_if_not_enabled=False,
            ),
            tenant_id=model.tenant_id,
            provider_id=model.provider_id,
            provider_name=model.provider_name,
            provider_type=model.provider_type,
            used_by_mcp_servers=[
                ForecastModelUsedByPublic(id=u.id, name=u.name, purpose=u.purpose)
                for u in model.used_by_mcp_servers
            ],
        )


class ForecastModelSecurityStatus(ForecastModelPublic):
    meets_security_classification: Optional[bool] = None


class ForecastModelUpdate(BaseModel):
    """Turn the model on or off, classify it or rename it; absent fields stay."""

    is_org_enabled: Optional[bool] = None
    security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED
    display_name: Optional[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
        ]
    ] = None

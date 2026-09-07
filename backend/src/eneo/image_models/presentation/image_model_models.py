from decimal import Decimal
from typing import Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from eneo.image_models.domain.image_model import ImageModel
from eneo.main.models import NOT_PROVIDED, ModelId, NotProvided
from eneo.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)

# Kept in sync with IMAGE_SIZES / IMAGE_QUALITIES in the domain (unit-tested).
ImageSize = Literal["auto", "1024x1024", "1536x1024", "1024x1536"]
ImageQuality = Literal["auto", "low", "medium", "high"]


class ImageModelPublic(BaseModel):
    id: UUID
    name: str
    nickname: str
    family: Optional[str] = None
    is_deprecated: bool
    stability: Optional[str] = None
    hosting: Optional[str] = None
    open_source: Optional[bool] = None
    description: Optional[str] = None
    hf_link: Optional[str] = None
    org: Optional[str] = None
    cost_per_image: Optional[Decimal] = None
    default_size: str = "auto"
    default_quality: str = "auto"
    can_access: bool = False
    is_locked: bool = True
    lock_reason: Optional[str] = None
    is_org_enabled: bool = False
    is_org_default: bool = False
    credential_provider: Optional[str] = None
    security_classification: Optional[SecurityClassificationPublic] = None
    tenant_id: Optional[UUID] = None
    provider_id: Optional[UUID] = None
    provider_name: Optional[str] = None
    provider_type: Optional[str] = None
    deprecation_date: Optional[str] = None

    @classmethod
    def from_domain(cls, model: ImageModel):
        return cls(
            id=model.id,
            name=model.name,
            nickname=model.nickname or "",
            family=model.family,
            is_deprecated=model.is_effectively_deprecated,
            stability=model.stability,
            hosting=model.hosting,
            open_source=model.open_source,
            description=model.description,
            hf_link=model.hf_link,
            org=model.org,
            cost_per_image=model.cost_per_image,
            default_size=model.default_size,
            default_quality=model.default_quality,
            can_access=model.can_access,
            is_locked=model.is_locked,
            lock_reason=model.lock_reason,
            is_org_enabled=model.is_org_enabled,
            is_org_default=model.is_org_default,
            credential_provider=model.get_credential_provider_name(),
            security_classification=SecurityClassificationPublic.from_domain(
                model.security_classification,
                return_none_if_not_enabled=False,
            ),
            tenant_id=model.tenant_id,
            provider_id=model.provider_id,
            provider_name=model.provider_name,
            provider_type=model.provider_type,
            deprecation_date=model.litellm_deprecation_date,
        )


class ImageModelSecurityStatus(ImageModelPublic):
    meets_security_classification: Optional[bool] = None


class ImageModelUpdate(BaseModel):
    is_org_enabled: Optional[bool] = None
    is_org_default: Optional[bool] = None
    security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED

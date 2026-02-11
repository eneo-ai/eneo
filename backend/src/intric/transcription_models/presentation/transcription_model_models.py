from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel

from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.main.models import NOT_PROVIDED, ModelId, NotProvided
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)
from intric.transcription_models.domain.transcription_model import TranscriptionModel


class TranscriptionModelPublic(BaseModel):
    id: UUID
    name: str
    nickname: str
    family: ModelFamily
    is_deprecated: bool
    stability: ModelStability
    hosting: ModelHostingLocation
    open_source: Optional[bool] = None
    description: Optional[str] = None
    hf_link: Optional[str] = None
    org: Optional[ModelOrg] = None
    can_access: bool = False
    is_locked: bool = True
    lock_reason: Optional[str] = None
    is_org_enabled: bool = False
    is_org_default: bool = False
    credential_provider: Optional[str] = None
    security_classification: Optional[SecurityClassificationPublic] = None
    # Tenant model fields
    tenant_id: Optional[UUID] = None
    provider_id: Optional[UUID] = None
    # Provider info for grouped display in UI
    provider_name: Optional[str] = None
    provider_type: Optional[str] = None

    @classmethod
    def from_domain(cls, model: TranscriptionModel):
        return cls(
            id=model.id,
            name=model.name,
            nickname=model.nickname,
            family=model.family,
            is_deprecated=model.is_deprecated,
            stability=model.stability,
            hosting=model.hosting,
            open_source=model.open_source,
            description=model.description,
            hf_link=model.hf_link,
            org=model.org,
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
        )


class TranscriptionModelSecurityStatus(TranscriptionModelPublic):
    meets_security_classification: Optional[bool] = None


class TranscriptionModelUpdate(BaseModel):
    is_org_enabled: Optional[bool] = None
    is_org_default: Optional[bool] = None
    security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED

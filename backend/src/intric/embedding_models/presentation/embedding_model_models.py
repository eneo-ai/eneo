from typing import Optional

from pydantic import BaseModel

from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelStability,
)
from intric.ai_models.model_enums import ModelOrg as Orgs
from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.main.models import NOT_PROVIDED, BaseResponse, ModelId, NotProvided
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)


class EmbeddingModelPublic(BaseResponse):
    name: str
    family: ModelFamily
    is_deprecated: bool
    open_source: bool
    dimensions: Optional[int] = None
    max_input: Optional[int] = None
    hf_link: Optional[str] = None
    stability: ModelStability
    hosting: ModelHostingLocation
    description: Optional[str] = None
    org: Optional[Orgs] = None
    litellm_model_name: Optional[str] = None
    can_access: bool = False
    is_locked: bool = True
    lock_reason: Optional[str] = None
    is_org_enabled: bool = False
    credential_provider: Optional[str] = None
    security_classification: Optional[SecurityClassificationPublic] = None

    @classmethod
    def from_domain(cls, model: EmbeddingModel):
        security_classification = None
        if model.security_classification:
            security_classification = SecurityClassificationPublic.from_domain(
                model.security_classification,
                return_none_if_not_enabled=False,
            )

        return cls(
            id=model.id,
            created_at=model.created_at,
            updated_at=model.updated_at,
            name=model.name,
            family=model.family,
            is_deprecated=model.is_deprecated,
            open_source=model.open_source,
            max_input=model.max_input,
            hf_link=model.hf_link,
            stability=model.stability,
            hosting=model.hosting,
            description=model.description,
            org=model.org,
            litellm_model_name=model.litellm_model_name,
            dimensions=model.dimensions,
            can_access=model.can_access,
            is_locked=model.is_locked,
            lock_reason=model.lock_reason,
            is_org_enabled=model.is_org_enabled,
            credential_provider=model.get_credential_provider_name(),
            security_classification=security_classification,
        )


class EmbeddingModelSecurityStatus(EmbeddingModelPublic):
    meets_security_classification: Optional[bool] = None


class EmbeddingModelUpdate(BaseModel):
    is_org_enabled: bool | NotProvided = NOT_PROVIDED
    security_classification: ModelId | None | NotProvided = NOT_PROVIDED

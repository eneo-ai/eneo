from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from eneo.ai_models.ai_model import AIModel
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eneo.database.tables.ai_models_table import RerankModels as RerankModelsDB
    from eneo.users.user import UserInDB


class RerankModel(AIModel):
    def __init__(
        self,
        user: UserInDB,
        id: UUID,
        created_at: datetime,
        updated_at: datetime,
        nickname: str,
        name: str,
        family: Optional[str],
        hosting: Optional[str],
        org: Optional[str],
        stability: Optional[str],
        open_source: bool,
        description: Optional[str],
        hf_link: Optional[str],
        is_deprecated: bool,
        is_org_enabled: bool,
        is_org_default: bool,
        security_classification: Optional["SecurityClassification"] = None,
        tenant_id: Optional[UUID] = None,
        provider_id: Optional[UUID] = None,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
    ):
        super().__init__(
            user=user,
            id=id,
            created_at=created_at,
            updated_at=updated_at,
            nickname=nickname,
            name=name,
            family=family,
            hosting=hosting,
            org=org,
            stability=stability,
            open_source=open_source,
            description=description,
            hf_link=hf_link,
            is_deprecated=is_deprecated,
            is_org_enabled=is_org_enabled,
        )

        self.is_org_default = is_org_default
        self.security_classification = security_classification
        self.tenant_id = tenant_id
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.provider_type = provider_type

    @classmethod
    def create_from_db(
        cls,
        rerank_model_db: RerankModelsDB,
        user: UserInDB,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
    ) -> RerankModel:
        return cls(
            user=user,
            id=rerank_model_db.id,
            created_at=rerank_model_db.created_at,
            updated_at=rerank_model_db.updated_at,
            nickname=rerank_model_db.nickname,
            name=rerank_model_db.name,
            family=rerank_model_db.family,
            hosting=rerank_model_db.hosting,
            org=rerank_model_db.org,
            stability=rerank_model_db.stability,
            open_source=rerank_model_db.open_source or False,
            description=rerank_model_db.description,
            hf_link=rerank_model_db.hf_link,
            is_deprecated=rerank_model_db.is_deprecated,
            is_org_enabled=rerank_model_db.is_enabled,
            is_org_default=rerank_model_db.is_default,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=rerank_model_db.security_classification
            ),
            tenant_id=rerank_model_db.tenant_id,
            provider_id=rerank_model_db.provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
        )

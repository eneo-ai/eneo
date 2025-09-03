from typing import TYPE_CHECKING, Optional, Union

from intric.ai_models.ai_model import AIModel
from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.main.models import NOT_PROVIDED
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.ai_models_table import (
        EmbeddingModels as EmbeddingModelDB,
    )
    from intric.database.tables.ai_models_table import EmbeddingModelSettings
    from intric.main.models import NotProvided
    from intric.users.user import UserInDB


class EmbeddingModel(AIModel):
    def __init__(
        self,
        id: Optional["UUID"],
        created_at: Optional["datetime"],
        updated_at: Optional["datetime"],
        user: "UserInDB",
        nickname: Optional[str],
        name: str,
        family: ModelFamily,
        hosting: ModelHostingLocation,
        org: Optional[ModelOrg],
        stability: ModelStability,
        open_source: bool,
        description: Optional[str],
        hf_link: Optional[str],
        is_deprecated: bool,
        is_org_enabled: bool,
        max_input: int,
        dimensions: Optional[int],
        security_classification: Optional[SecurityClassification],
        litellm_model_name: Optional[str] = None,
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
            security_classification=security_classification,
        )

        self.max_input = max_input
        self.dimensions = dimensions
        self.litellm_model_name = litellm_model_name

    @classmethod
    def to_domain(
        cls,
        db_model: "EmbeddingModelDB",
        embedding_model_settings: Optional["EmbeddingModelSettings"],
        user: "UserInDB",
    ):

        if embedding_model_settings is None:
            is_org_enabled = False
            updated_at = db_model.updated_at
            security_classification = None
        else:
            is_org_enabled = embedding_model_settings.is_org_enabled
            updated_at = embedding_model_settings.updated_at
            security_classification = embedding_model_settings.security_classification

        return cls(
            id=db_model.id,
            created_at=db_model.created_at,
            updated_at=updated_at,
            user=user,
            name=db_model.name,
            nickname=None,
            family=db_model.family,
            hosting=db_model.hosting,
            org=db_model.org,
            stability=db_model.stability,
            open_source=db_model.open_source,
            description=db_model.description,
            hf_link=db_model.hf_link,
            is_deprecated=db_model.is_deprecated,
            is_org_enabled=is_org_enabled,
            max_input=db_model.max_input,
            dimensions=db_model.dimensions,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=security_classification
            ),
            litellm_model_name=db_model.litellm_model_name,
        )

    def update(self, is_org_enabled: Union[bool, "NotProvided"]):
        if is_org_enabled is not NOT_PROVIDED:
            self.is_org_enabled = is_org_enabled

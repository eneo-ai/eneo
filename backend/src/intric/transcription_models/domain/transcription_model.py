from typing import TYPE_CHECKING, Optional, Union

from intric.ai_models.ai_model import AIModel
from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.ai_models_table import (
        TranscriptionModels as TranscriptionModelsDB,
    )
    from intric.database.tables.ai_models_table import (
        TranscriptionModelSettings,
    )
    from intric.users.user import UserInDB


class TranscriptionModel(AIModel):
    def __init__(
        self,
        user: "UserInDB",
        id: "UUID",
        created_at: "datetime",
        updated_at: "datetime",
        nickname: str,
        name: str,
        family: Union[ModelFamily, str],
        hosting: Union[ModelHostingLocation, str],
        org: Optional[Union[ModelOrg, str]],
        stability: Union[ModelStability, str],
        open_source: bool,
        description: Optional[str],
        hf_link: Optional[str],
        base_url: str,
        is_deprecated: bool,
        is_org_enabled: bool,
        is_org_default: bool,
        security_classification: Optional["SecurityClassification"] = None,
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

        self.base_url = base_url
        self.is_org_default = is_org_default
        self.security_classification = security_classification

    @classmethod
    def create_from_db(
        cls,
        transcription_model_db: "TranscriptionModelsDB",
        transcription_model_settings: Optional["TranscriptionModelSettings"],
        user: "UserInDB",
    ):
        if transcription_model_settings is None:
            is_org_enabled = False
            is_org_default = False
            updated_at = transcription_model_db.updated_at
            security_classification = None
        else:
            is_org_enabled = transcription_model_settings.is_org_enabled
            is_org_default = transcription_model_settings.is_org_default
            updated_at = transcription_model_settings.updated_at
            security_classification = (
                transcription_model_settings.security_classification
            )

        # Pass raw string values - parent class will convert to enum if valid
        return cls(
            user=user,
            id=transcription_model_db.id,
            created_at=transcription_model_db.created_at,
            updated_at=updated_at,
            nickname=transcription_model_db.name,
            name=transcription_model_db.model_name,
            family=transcription_model_db.family,
            hosting=transcription_model_db.hosting,
            org=transcription_model_db.org,
            stability=transcription_model_db.stability,
            open_source=transcription_model_db.open_source,
            description=transcription_model_db.description,
            hf_link=transcription_model_db.hf_link,
            base_url=transcription_model_db.base_url,
            is_deprecated=transcription_model_db.is_deprecated,
            is_org_enabled=is_org_enabled,
            is_org_default=is_org_default,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=security_classification
            ),
        )

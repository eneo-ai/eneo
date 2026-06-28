from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from eneo.ai_models.ai_model import AIModel
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eneo.database.tables.ai_models_table import (
        TranscriptionModels as TranscriptionModelsDB,
    )
    from eneo.users.user import UserInDB


class TranscriptionModel(AIModel):
    def __init__(
        self,
        user: "UserInDB",
        id: "UUID",
        created_at: "datetime",
        updated_at: "datetime",
        nickname: str,
        name: str,
        family: Optional[str],
        hosting: Optional[str],
        org: Optional[str],
        stability: Optional[str],
        open_source: bool,
        description: Optional[str],
        hf_link: Optional[str],
        base_url: str,
        is_deprecated: bool,
        is_org_enabled: bool,
        is_org_default: bool,
        cost_per_minute: Optional[Decimal] = None,
        security_classification: Optional["SecurityClassification"] = None,
        tenant_id: Optional["UUID"] = None,
        provider_id: Optional["UUID"] = None,
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
        migrated_to_model_id: Optional["UUID"] = None,
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
        self.cost_per_minute = cost_per_minute
        self.security_classification = security_classification
        self.tenant_id = tenant_id
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.provider_type = provider_type
        self.migrated_to_model_id = migrated_to_model_id

    @property
    def model_name(self) -> str:
        """Return the actual model name (e.g., 'whisper-1', 'kb-whisper-large').

        This is the model identifier used with the API, stored as 'name' in the domain
        but as 'model_name' in the database.
        """
        return self.name

    @classmethod
    def create_from_db(
        cls,
        transcription_model_db: "TranscriptionModelsDB",
        user: "UserInDB",
        provider_name: Optional[str] = None,
        provider_type: Optional[str] = None,
    ):
        # Settings are now directly on the model table
        return cls(
            user=user,
            id=transcription_model_db.id,
            created_at=transcription_model_db.created_at,
            updated_at=transcription_model_db.updated_at,
            # Display name now lives in `nickname` (parity with
            # completion/embedding); fall back to `name` for rows written
            # before nickname was synced. The DB `name`/`model_name` inversion
            # is left untouched until a later normalization phase.
            nickname=transcription_model_db.nickname or transcription_model_db.name,
            name=transcription_model_db.model_name,
            family=transcription_model_db.family,
            hosting=transcription_model_db.hosting,
            org=transcription_model_db.org,
            stability=transcription_model_db.stability,
            open_source=transcription_model_db.open_source or False,
            description=transcription_model_db.description,
            hf_link=transcription_model_db.hf_link,
            base_url=transcription_model_db.base_url,
            is_deprecated=transcription_model_db.is_deprecated,
            is_org_enabled=transcription_model_db.is_enabled,
            is_org_default=transcription_model_db.is_default,
            cost_per_minute=transcription_model_db.cost_per_minute,
            security_classification=SecurityClassification.to_domain(
                db_security_classification=transcription_model_db.security_classification
            ),
            tenant_id=transcription_model_db.tenant_id,
            provider_id=transcription_model_db.provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
            migrated_to_model_id=transcription_model_db.migrated_to_model_id,
        )

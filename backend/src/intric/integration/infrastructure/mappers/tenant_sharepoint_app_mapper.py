from typing import Any, Dict, List, Optional

from intric.base.base_entity import EntityMapper
from intric.database.tables.tenant_sharepoint_app_table import (
    TenantSharePointApp as TenantSharePointAppDBModel,
)
from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
from intric.settings.encryption_service import EncryptionService


class TenantSharePointAppMapper(EntityMapper[TenantSharePointApp, TenantSharePointAppDBModel]):
    """Mapper for TenantSharePointApp with automatic secret encryption/decryption."""

    def __init__(self, encryption_service: EncryptionService):
        self.encryption_service = encryption_service

    def _encrypt_optional(self, value: Optional[str]) -> Optional[str]:
        """Encrypt a value if it's not None."""
        if value is None:
            return None
        return self.encryption_service.encrypt(value)

    def _decrypt_optional(self, value: Optional[str]) -> Optional[str]:
        """Decrypt a value if it's not None."""
        if value is None:
            return None
        return self.encryption_service.decrypt(value)

    def to_db_dict(self, entity: TenantSharePointApp) -> Dict[str, Any]:
        """Convert entity to database dict with encrypted secrets."""
        db_dict = {
            "id": entity.id,
            "tenant_id": entity.tenant_id,
            "client_id": entity.client_id,
            "client_secret_encrypted": self.encryption_service.encrypt(entity.client_secret),
            "certificate_path": entity.certificate_path,
            "tenant_domain": entity.tenant_domain,
            "is_active": entity.is_active,
            "auth_method": entity.auth_method,
            "service_account_refresh_token_encrypted": self._encrypt_optional(
                entity.service_account_refresh_token
            ),
            "service_account_email": entity.service_account_email,
            "created_by": entity.created_by,
        }

        # Only include timestamps if they exist (for updates)
        # For new entities, let the database use its default values
        if entity.created_at is not None:
            db_dict["created_at"] = entity.created_at
        if entity.updated_at is not None:
            db_dict["updated_at"] = entity.updated_at

        return db_dict

    def to_entity(self, db_model: TenantSharePointAppDBModel) -> TenantSharePointApp:
        """Convert database model to entity with decrypted secrets."""
        return TenantSharePointApp(
            id=db_model.id,
            tenant_id=db_model.tenant_id,
            client_id=db_model.client_id,
            client_secret=self.encryption_service.decrypt(db_model.client_secret_encrypted),
            certificate_path=db_model.certificate_path,
            tenant_domain=db_model.tenant_domain,
            is_active=db_model.is_active,
            auth_method=db_model.auth_method,
            service_account_refresh_token=self._decrypt_optional(
                db_model.service_account_refresh_token_encrypted
            ),
            service_account_email=db_model.service_account_email,
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )

    def to_entities(
        self, db_models: List[TenantSharePointAppDBModel]
    ) -> List[TenantSharePointApp]:
        """Convert list of database models to entities."""
        return [self.to_entity(db_model) for db_model in db_models]

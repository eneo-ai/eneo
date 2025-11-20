from typing import Any, Dict, List

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

    def to_db_dict(self, entity: TenantSharePointApp) -> Dict[str, Any]:
        """Convert entity to database dict with encrypted secret."""
        db_dict = {
            "id": entity.id,
            "tenant_id": entity.tenant_id,
            "client_id": entity.client_id,
            "client_secret_encrypted": self.encryption_service.encrypt(entity.client_secret),
            "certificate_path": entity.certificate_path,
            "tenant_domain": entity.tenant_domain,
            "is_active": entity.is_active,
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
        """Convert database model to entity with decrypted secret."""
        return TenantSharePointApp(
            id=db_model.id,
            tenant_id=db_model.tenant_id,
            client_id=db_model.client_id,
            client_secret=self.encryption_service.decrypt(db_model.client_secret_encrypted),
            certificate_path=db_model.certificate_path,
            tenant_domain=db_model.tenant_domain,
            is_active=db_model.is_active,
            created_by=db_model.created_by,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
        )

    def to_entities(
        self, db_models: List[TenantSharePointAppDBModel]
    ) -> List[TenantSharePointApp]:
        """Convert list of database models to entities."""
        return [self.to_entity(db_model) for db_model in db_models]

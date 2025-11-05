from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.exceptions import NotFoundException
from intric.main.models import ModelId
from intric.tenants.tenant import (
    TenantBase,
    TenantInDB,
    TenantUpdate,
    TenantUpdatePublic,
)
from intric.tenants.tenant_repo import TenantRepository

if TYPE_CHECKING:
    from intric.ai_models.completion_models.completion_models_repo import (
        CompletionModelsRepository,
    )
    from intric.ai_models.embedding_models.embedding_models_repo import (
        AdminEmbeddingModelsService,
    )
    from intric.transcription_models.infrastructure import (
        TranscriptionModelEnableService,
    )


class TenantService:
    def __init__(
        self,
        repo: TenantRepository,
        completion_model_repo: "CompletionModelsRepository",
        embedding_model_repo: "AdminEmbeddingModelsService",
        transcription_model_enable_service: "TranscriptionModelEnableService",
    ):
        self.repo = repo
        self.completion_model_repo = completion_model_repo
        self.embedding_model_repo = embedding_model_repo
        self.transcription_models_enable_service = transcription_model_enable_service

    @staticmethod
    def _validate(tenant: TenantInDB | None, id: UUID):
        if not tenant:
            raise NotFoundException(f"Tenant {id} not found")

    async def get_all_tenants(self, domain: str | None) -> list[TenantInDB]:
        return await self.repo.get_all_tenants(domain=domain)

    async def get_tenant_by_id(self, id: UUID) -> TenantInDB:
        tenant = await self.repo.get(id)
        self._validate(tenant, id)

        return tenant

    async def create_tenant(self, tenant: TenantBase) -> TenantInDB:
        tenant_in_db = await self.repo.add(tenant)

        # Note: Models are now managed via API/UI by admins
        # New tenants start with no pre-enabled models

        return tenant_in_db

    async def delete_tenant(self, tenant_id: UUID) -> TenantInDB:
        tenant = await self.get_tenant_by_id(tenant_id)
        self._validate(tenant, tenant_id)

        return await self.repo.delete_tenant_by_id(tenant_id)

    async def update_tenant(self, tenant_update: TenantUpdatePublic, id: UUID) -> TenantInDB:
        tenant = await self.get_tenant_by_id(id)
        self._validate(tenant, id)

        tenant_update = TenantUpdate(**tenant_update.model_dump(exclude_unset=True), id=tenant.id)
        return await self.repo.update_tenant(tenant_update)

    async def add_modules(self, list_of_module_ids: list[ModelId], tenant_id: UUID):
        return await self.repo.add_modules(list_of_module_ids, tenant_id)

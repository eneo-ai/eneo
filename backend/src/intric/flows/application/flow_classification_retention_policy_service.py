from uuid import UUID

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.domain.flow_classification_retention_policy import (
    FlowClassificationRetentionPolicy,
)
from intric.flows.infrastructure.flow_classification_retention_policy_repo import (
    FlowClassificationRetentionPolicyRepository,
)
from intric.main.exceptions import NotFoundException
from intric.roles.permissions import Permission, validate_permissions
from intric.users.user import UserInDB


class FlowClassificationRetentionPolicyService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repo: FlowClassificationRetentionPolicyRepository,
        audit_service: AuditService,
    ) -> None:
        self.user = user
        self.repo = repo
        self.audit_service = audit_service

    @validate_permissions(Permission.ADMIN)
    async def list_policies(self) -> list[FlowClassificationRetentionPolicy]:
        return await self.repo.list_for_tenant(tenant_id=self.user.tenant_id)

    @validate_permissions(Permission.ADMIN)
    async def set_policy(
        self, *, security_classification_id: UUID, data_retention_days: int
    ) -> FlowClassificationRetentionPolicy:
        await self._ensure_security_classification_exists(security_classification_id)
        previous = await self.repo.get(
            tenant_id=self.user.tenant_id,
            security_classification_id=security_classification_id,
        )
        updated = await self.repo.upsert(
            FlowClassificationRetentionPolicy(
                tenant_id=self.user.tenant_id,
                security_classification_id=security_classification_id,
                data_retention_days=data_retention_days,
            )
        )
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated Flow classification retention policy",
            metadata={
                "setting": "flow_classification_retention_policy",
                "security_classification_id": str(security_classification_id),
                "changes": {
                    "data_retention_days": {
                        "old": (
                            previous.data_retention_days
                            if previous is not None
                            else None
                        ),
                        "new": updated.data_retention_days,
                    }
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def delete_policy(self, *, security_classification_id: UUID) -> None:
        await self._ensure_security_classification_exists(security_classification_id)
        previous = await self.repo.get(
            tenant_id=self.user.tenant_id,
            security_classification_id=security_classification_id,
        )
        deleted = await self.repo.delete(
            tenant_id=self.user.tenant_id,
            security_classification_id=security_classification_id,
        )
        await self.audit_service.log_async(
            tenant_id=self.user.tenant_id,
            actor_id=self.user.id,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Deleted Flow classification retention policy",
            metadata={
                "setting": "flow_classification_retention_policy",
                "security_classification_id": str(security_classification_id),
                "deleted": deleted,
                "old_data_retention_days": (
                    previous.data_retention_days if previous is not None else None
                ),
            },
        )

    async def _ensure_security_classification_exists(
        self, security_classification_id: UUID
    ) -> None:
        exists = await self.repo.security_classification_exists(
            tenant_id=self.user.tenant_id,
            security_classification_id=security_classification_id,
        )
        if not exists:
            raise NotFoundException("Security classification not found.")

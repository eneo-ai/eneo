from datetime import datetime, timezone
from uuid import UUID

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
    FlowRetentionChangeConfirmation,
    FlowRetentionClassificationProposal,
    FlowRetentionImpactPreview,
)
from eneo.flows.domain.flow_classification_retention_policy import (
    FlowClassificationRetentionPolicy,
)
from eneo.flows.infrastructure.flow_classification_retention_policy_repo import (
    FlowClassificationRetentionPolicyRepository,
)
from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission, validate_permissions
from eneo.users.user import UserInDB


class FlowClassificationRetentionPolicyService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repo: FlowClassificationRetentionPolicyRepository,
        audit_service: AuditService,
        data_retention_service: DataRetentionService,
    ) -> None:
        self.user = user
        self.repo = repo
        self.audit_service = audit_service
        self.data_retention_service = data_retention_service

    @validate_permissions(Permission.ADMIN)
    async def list_policies(self) -> list[FlowClassificationRetentionPolicy]:
        return await self.repo.list_for_tenant(tenant_id=self.user.tenant_id)

    @validate_permissions(Permission.ADMIN)
    async def preview_policy(
        self,
        *,
        security_classification_id: UUID,
        data_retention_days: int,
    ) -> FlowRetentionImpactPreview:
        await self._ensure_security_classification_exists(security_classification_id)
        return await self.data_retention_service.preview_flow_retention_classification_change(
            tenant_id=self.user.tenant_id,
            proposal=FlowRetentionClassificationProposal(
                security_classification_id=security_classification_id,
                data_retention_days=data_retention_days,
            ),
        )

    @validate_permissions(Permission.ADMIN)
    async def set_policy(
        self,
        *,
        security_classification_id: UUID,
        data_retention_days: int,
        confirmation: FlowRetentionChangeConfirmation | None,
    ) -> FlowClassificationRetentionPolicy:
        await self._ensure_security_classification_exists(security_classification_id)
        decision = await self.data_retention_service.prepare_flow_retention_classification_change(
            tenant_id=self.user.tenant_id,
            proposal=FlowRetentionClassificationProposal(
                security_classification_id=security_classification_id,
                data_retention_days=data_retention_days,
            ),
            confirmation=confirmation,
        )
        await self._ensure_security_classification_exists(
            security_classification_id,
            lock=True,
        )
        updated = await self.repo.upsert(
            FlowClassificationRetentionPolicy(
                tenant_id=self.user.tenant_id,
                security_classification_id=security_classification_id,
                data_retention_days=data_retention_days,
            )
        )
        await self.audit_service.log(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Updated Flow classification retention policy",
            metadata={
                "old_policy": {
                    "security_classification_id": str(security_classification_id),
                    "data_retention_days": (
                        decision.old_policy.data_retention_days
                        if decision.old_policy is not None
                        else None
                    ),
                },
                "new_policy": {
                    "security_classification_id": str(security_classification_id),
                    "data_retention_days": updated.data_retention_days,
                },
                "preview": (
                    decision.preview.audit_summary()
                    if decision.preview is not None
                    else None
                ),
                "activation": {
                    "destructive_change": decision.destructive_change,
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
        return updated

    @validate_permissions(Permission.ADMIN)
    async def delete_policy(self, *, security_classification_id: UUID) -> None:
        await self._ensure_security_classification_exists(security_classification_id)
        await self.data_retention_service.get_flow_retention_control_plane_state(
            tenant_id=self.user.tenant_id,
            lock=True,
        )
        await self._ensure_security_classification_exists(
            security_classification_id,
            lock=True,
        )
        previous = await self.repo.get(
            tenant_id=self.user.tenant_id,
            security_classification_id=security_classification_id,
        )
        deleted = await self.repo.delete(
            tenant_id=self.user.tenant_id,
            security_classification_id=security_classification_id,
        )
        await self.audit_service.log(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.TENANT_SETTINGS_UPDATED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=self.user.tenant_id,
            description="Deleted Flow classification retention policy",
            metadata={
                "old_policy": {
                    "security_classification_id": str(security_classification_id),
                    "data_retention_days": (
                        previous.data_retention_days if previous is not None else None
                    ),
                },
                "new_policy": None,
                "preview": None,
                "activation": {
                    "destructive_change": False,
                    "activated_at": datetime.now(timezone.utc).isoformat(),
                    "deleted": deleted,
                },
            },
        )

    async def _ensure_security_classification_exists(
        self,
        security_classification_id: UUID,
        *,
        lock: bool = False,
    ) -> None:
        exists = await self.repo.security_classification_exists(
            tenant_id=self.user.tenant_id,
            security_classification_id=security_classification_id,
            lock=lock,
        )
        if not exists:
            raise NotFoundException("Security classification not found.")

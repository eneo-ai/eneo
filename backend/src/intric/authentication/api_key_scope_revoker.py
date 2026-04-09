from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_models import (
    ApiKeyState,
    ApiKeyStateReasonCode,
    ApiKeyScopeType,
)
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.users.user import UserInDB


logger = get_logger(__name__)


class ApiKeyScopeRevoker:
    def __init__(
        self,
        api_key_repo: ApiKeysV2Repository,
        audit_service: "AuditService | None",
        user: "UserInDB | None",
    ):
        self.api_key_repo = api_key_repo
        self.audit_service = audit_service
        self.user = user

    async def revoke_scope(
        self,
        *,
        scope_type: ApiKeyScopeType,
        scope_id: UUID,
        reason_code: ApiKeyStateReasonCode,
        reason_text: str | None = None,
    ) -> int:
        if self.user is None:
            logger.warning(
                "API key scope revocation skipped: user context missing",
                extra={"scope_type": scope_type.value, "scope_id": str(scope_id)},
            )
            return 0

        keys = await self.api_key_repo.list_by_scope(
            tenant_id=self.user.tenant_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        if not keys:
            return 0

        now = datetime.now(timezone.utc)
        revoked = 0
        for key in keys:
            if key.revoked_at is not None:
                continue
            updated = await self.api_key_repo.update(
                key_id=key.id,
                tenant_id=key.tenant_id,
                state=ApiKeyState.REVOKED.value,
                revoked_at=now,
                revoked_reason_code=reason_code.value,
                revoked_reason_text=reason_text,
            )
            updated_key = updated or key
            revoked += 1

            if self.audit_service is not None:
                await self.audit_service.log_async(
                    tenant_id=self.user.tenant_id,
                    actor_id=self.user.id,
                    action=ActionType.API_KEY_REVOKED,
                    entity_type=EntityType.API_KEY,
                    entity_id=updated_key.id,
                    description=f"Revoked API key '{updated_key.name}'",
                    metadata=AuditMetadata.standard(
                        actor=self.user,
                        target=updated_key,
                        changes={
                            "state": {
                                "old": key.state,
                                "new": ApiKeyState.REVOKED.value,
                            }
                        },
                        extra={
                            "reason_code": reason_code.value,
                            "reason_text": reason_text,
                        },
                    ),
                )

        return revoked

    async def revoke_by_owner(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        reason_code: ApiKeyStateReasonCode,
        reason_text: str | None = None,
    ) -> int:
        keys = await self.api_key_repo.list_filtered(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            ownership="user",
        )
        return await self._revoke_keys(
            keys=keys,
            reason_code=reason_code,
            reason_text=reason_text,
        )

    async def revoke_member_keys(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        space_id: UUID,
        assistant_ids: list[UUID],
        app_ids: list[UUID],
        reason_code: ApiKeyStateReasonCode,
        reason_text: str | None = None,
    ) -> int:
        keys: list = []
        keys.extend(
            await self.api_key_repo.list_filtered(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                scope_type=ApiKeyScopeType.SPACE,
                scope_id=space_id,
                ownership="user",
            )
        )
        for assistant_id in assistant_ids:
            keys.extend(
                await self.api_key_repo.list_filtered(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    scope_type=ApiKeyScopeType.ASSISTANT,
                    scope_id=assistant_id,
                    ownership="user",
                )
            )
        for app_id in app_ids:
            keys.extend(
                await self.api_key_repo.list_filtered(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    scope_type=ApiKeyScopeType.APP,
                    scope_id=app_id,
                    ownership="user",
                )
            )
        return await self._revoke_keys(
            keys=keys,
            reason_code=reason_code,
            reason_text=reason_text,
        )

    async def _revoke_keys(
        self,
        *,
        keys: list,
        reason_code: ApiKeyStateReasonCode,
        reason_text: str | None,
    ) -> int:
        if not keys or self.user is None:
            return 0

        now = datetime.now(timezone.utc)
        revoked = 0
        for key in keys:
            if key.revoked_at is not None:
                continue
            updated = await self.api_key_repo.update(
                key_id=key.id,
                tenant_id=key.tenant_id,
                state=ApiKeyState.REVOKED.value,
                revoked_at=now,
                revoked_reason_code=reason_code.value,
                revoked_reason_text=reason_text,
            )
            updated_key = updated or key
            revoked += 1

            if self.audit_service is not None:
                await self.audit_service.log_async(
                    tenant_id=self.user.tenant_id,
                    actor_id=self.user.id,
                    action=ActionType.API_KEY_REVOKED,
                    entity_type=EntityType.API_KEY,
                    entity_id=updated_key.id,
                    description=f"Revoked API key '{updated_key.name}'",
                    metadata=AuditMetadata.standard(
                        actor=self.user,
                        target=updated_key,
                        changes={
                            "state": {
                                "old": key.state,
                                "new": ApiKeyState.REVOKED.value,
                            }
                        },
                        extra={
                            "reason_code": reason_code.value,
                            "reason_text": reason_text,
                        },
                    ),
                )

        return revoked

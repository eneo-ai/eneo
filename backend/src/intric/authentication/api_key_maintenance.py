from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_models import (
    ApiKeyState,
    ApiKeyStateReasonCode,
    ApiKeyV2InDB,
)
from intric.main.logging import get_logger
from intric.tenants.tenant_repo import TenantRepository

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.tenants.tenant import TenantInDB


logger = get_logger(__name__)


class ApiKeyMaintenanceService:
    def __init__(
        self,
        api_key_repo: ApiKeysV2Repository,
        tenant_repo: TenantRepository,
        audit_service: "AuditService | None",
    ):
        self.api_key_repo = api_key_repo
        self.tenant_repo = tenant_repo
        self.audit_service = audit_service

    async def run_daily_maintenance(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        errors: list[dict[str, str]] = []

        expired = await self._expire_due_keys(now=now, errors=errors)
        auto_expired = await self._auto_expire_unused(now=now, errors=errors)
        rotated_revoked = await self._revoke_rotation_grace(now=now, errors=errors)

        return {
            "expired": expired,
            "auto_expired": auto_expired,
            "rotation_revoked": rotated_revoked,
            "errors": errors,
        }

    async def _expire_due_keys(
        self, *, now: datetime, errors: list[dict[str, str]]
    ) -> int:
        keys = await self.api_key_repo.list_expired_candidates(now=now)
        expired = 0
        for key in keys:
            try:
                await self._mark_expired(
                    key=key,
                    now=now,
                    reason="expires_at",
                )
                expired += 1
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(
                    {
                        "key_id": str(key.id),
                        "tenant_id": str(key.tenant_id),
                        "error": str(exc),
                    }
                )
                logger.exception(
                    "Failed to expire API key",
                    extra={"api_key_id": str(key.id), "tenant_id": str(key.tenant_id)},
                )
        return expired

    async def _auto_expire_unused(
        self, *, now: datetime, errors: list[dict[str, str]]
    ) -> int:
        tenants = await self.tenant_repo.get_all_tenants()
        expired = 0
        for tenant in tenants:
            days = self._get_auto_expire_days(tenant)
            if days is None:
                continue
            cutoff = now - timedelta(days=days)
            keys = await self.api_key_repo.list_unused_before(
                tenant_id=tenant.id, cutoff=cutoff
            )
            for key in keys:
                try:
                    await self._mark_expired(
                        key=key,
                        now=now,
                        reason="unused",
                        extra={"cutoff": cutoff.isoformat(), "days": str(days)},
                    )
                    expired += 1
                except Exception as exc:  # pragma: no cover - defensive
                    errors.append(
                        {
                            "key_id": str(key.id),
                            "tenant_id": str(key.tenant_id),
                            "error": str(exc),
                        }
                    )
                    logger.exception(
                        "Failed to auto-expire API key",
                        extra={
                            "api_key_id": str(key.id),
                            "tenant_id": str(key.tenant_id),
                        },
                    )
        return expired

    async def _revoke_rotation_grace(
        self, *, now: datetime, errors: list[dict[str, str]]
    ) -> int:
        keys = await self.api_key_repo.list_rotation_grace_candidates(now=now)
        revoked = 0
        for key in keys:
            try:
                await self._mark_revoked_for_rotation(key=key, now=now)
                revoked += 1
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(
                    {
                        "key_id": str(key.id),
                        "tenant_id": str(key.tenant_id),
                        "error": str(exc),
                    }
                )
                logger.exception(
                    "Failed to revoke API key after rotation grace",
                    extra={"api_key_id": str(key.id), "tenant_id": str(key.tenant_id)},
                )
        return revoked

    def _get_auto_expire_days(self, tenant: "TenantInDB") -> int | None:
        policy = tenant.api_key_policy or {}
        value = policy.get("auto_expire_unused_days")
        if value is None:
            return None
        try:
            days = int(value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid auto_expire_unused_days value; skipping",
                extra={"tenant_id": str(tenant.id), "value": str(value)},
            )
            return None
        if days <= 0:
            return None
        return days

    async def _mark_expired(
        self,
        *,
        key: ApiKeyV2InDB,
        now: datetime,
        reason: str,
        extra: dict[str, str] | None = None,
    ) -> None:
        expires_at = key.expires_at or now
        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            state=ApiKeyState.EXPIRED.value,
            expires_at=expires_at,
        )
        updated_key = updated or key

        if self.audit_service is not None:
            metadata = AuditMetadata.system_action(
                description="API key expired",
                target=updated_key,
                extra={
                    "expires_at": expires_at.isoformat(),
                    "reason": reason,
                    **(extra or {}),
                },
            )
            await self.audit_service.log_async(
                tenant_id=updated_key.tenant_id,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                action=ActionType.API_KEY_EXPIRED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Expired API key '{updated_key.name}'",
                metadata=metadata,
            )

    async def _mark_revoked_for_rotation(
        self,
        *,
        key: ApiKeyV2InDB,
        now: datetime,
    ) -> None:
        updated = await self.api_key_repo.update(
            key_id=key.id,
            tenant_id=key.tenant_id,
            state=ApiKeyState.REVOKED.value,
            revoked_at=now,
            revoked_reason_code=ApiKeyStateReasonCode.ROTATION_COMPLETED.value,
            revoked_reason_text="Rotation grace period ended.",
        )
        updated_key = updated or key

        if self.audit_service is not None:
            metadata = AuditMetadata.system_action(
                description="API key revoked after rotation",
                target=updated_key,
                extra={
                    "reason_code": ApiKeyStateReasonCode.ROTATION_COMPLETED.value,
                    "rotation_grace_until": updated_key.rotation_grace_until.isoformat()
                    if updated_key.rotation_grace_until
                    else None,
                },
            )
            await self.audit_service.log_async(
                tenant_id=updated_key.tenant_id,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                action=ActionType.API_KEY_REVOKED,
                entity_type=EntityType.API_KEY,
                entity_id=updated_key.id,
                description=f"Revoked API key '{updated_key.name}' after rotation grace",
                metadata=metadata,
            )

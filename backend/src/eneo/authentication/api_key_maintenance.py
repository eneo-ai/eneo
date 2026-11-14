from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import sqlalchemy as sa

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import (
    ApiKeyStateReasonCode,
    ApiKeyV2InDB,
)
from eneo.main.logging import get_logger
from eneo.tenants.tenant_repo import TenantRepository

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.tenants.tenant import TenantInDB


logger = get_logger(__name__)


class ApiKeyMaintenanceService:
    def __init__(
        self,
        api_key_repo: ApiKeysV2Repository,
        tenant_repo: TenantRepository,
        audit_service: "AuditService | None",
    ):
        super().__init__()
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
        condition = self.api_key_repo.due_for_expiry(now=now)
        keys = await self.api_key_repo.list_matching(condition)
        expired = 0
        for key in keys:
            try:
                expired += await self._mark_expired(
                    condition,
                    key=key,
                    now=now,
                    reason="expires_at",
                )
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
            condition = self.api_key_repo.unused_since(
                tenant_id=tenant.id, cutoff=cutoff
            )
            keys = await self.api_key_repo.list_matching(condition)
            for key in keys:
                try:
                    expired += await self._mark_expired(
                        condition,
                        key=key,
                        now=now,
                        reason="unused",
                        extra={"cutoff": cutoff.isoformat(), "days": str(days)},
                    )
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
        condition = self.api_key_repo.rotation_grace_over(now=now)
        keys = await self.api_key_repo.list_matching(condition)
        revoked = 0
        for key in keys:
            try:
                revoked += await self._mark_revoked_for_rotation(
                    condition, key=key, now=now
                )
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
        condition: sa.ColumnElement[bool],
        *,
        key: ApiKeyV2InDB,
        now: datetime,
        reason: str,
        extra: dict[str, str] | None = None,
    ) -> int:
        """Expire ``key`` if it still matches ``condition``: 1 if it did,
        0 if it changed after it was selected."""
        # Sign-in judges a key by its end date alone, so ending access means
        # moving a later (or missing) end date to now; a passed one is kept.
        expires_at = min(key.expires_at or now, now)
        updated_key = await self.api_key_repo.expire_matching(
            condition, key=key, expires_at=expires_at
        )
        if updated_key is None:
            return 0

        if self.audit_service is not None:
            metadata = AuditMetadata.system_action(
                description="API key expired",
                target=updated_key,
                extra={
                    "expires_at": expires_at.isoformat(),
                    "previous_expires_at": key.expires_at.isoformat()
                    if key.expires_at
                    else None,
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
        return 1

    async def _mark_revoked_for_rotation(
        self,
        condition: sa.ColumnElement[bool],
        *,
        key: ApiKeyV2InDB,
        now: datetime,
    ) -> int:
        """Revoke ``key`` if its grace period has still ended: 1 if it did,
        0 if it was revoked or given a new grace period after selection."""
        updated_key = await self.api_key_repo.revoke_matching(
            condition,
            key=key,
            revoked_at=now,
            revoked_reason_code=ApiKeyStateReasonCode.ROTATION_COMPLETED.value,
            revoked_reason_text="Rotation grace period ended.",
        )
        if updated_key is None:
            return 0

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
        return 1

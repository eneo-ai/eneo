from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

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

# Keys one selection takes per run, oldest first. The unit is the selection:
# per step for keys past their end date, for keys recorded as expired but
# still open, and for rotated keys; per tenant for unused keys. It is not a
# cap for the whole run. A selection that reaches it leaves the rest to the
# next night's run.
API_KEY_MAINTENANCE_BATCH_LIMIT = 500


def _connection_lost(exc: BaseException) -> bool:
    """Whether the database connection is gone, which no savepoint survives."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
        current = current.__cause__ or current.__context__
    return False


class _Run:
    """What one run did: counts per step, failures and full selections."""

    def __init__(self) -> None:
        self.errors: list[dict[str, str]] = []
        self.limit_reached: list[dict[str, str]] = []

    def failed(self, exc: Exception, *, step: str, **where: str) -> None:
        if _connection_lost(exc):
            raise exc
        # The type only: a message can echo row values.
        self.errors.append({"step": step, **where, "error": type(exc).__name__})
        logger.exception(
            "API key maintenance step failed", extra={"step": step, **where}
        )


class ApiKeyMaintenanceService:
    def __init__(
        self,
        api_key_repo: ApiKeysV2Repository,
        tenant_repo: TenantRepository,
        audit_service: "AuditService",
    ):
        super().__init__()
        self.api_key_repo = api_key_repo
        self.tenant_repo = tenant_repo
        self.audit_service = audit_service

    async def run_daily_maintenance(self) -> dict[str, object]:
        """Run every step; a failing key, selection or tenant is reported in
        ``errors`` and the rest goes on. A lost connection fails the run."""
        now = datetime.now(timezone.utc)
        run = _Run()
        repo = self.api_key_repo

        expired = await self._change_selected(
            run,
            step="expires_at",
            condition=repo.due_for_expiry(now=now),
            change=partial(self._mark_expired, now=now, reason="expires_at"),
        )
        # Expiry already decided, whatever the policy says now; the key only
        # kept working because its end date was left open.
        expired_state_closed = await self._change_selected(
            run,
            step="stale_expired_state",
            condition=repo.expired_but_open(now=now),
            change=partial(self._mark_expired, now=now, reason="stale_expired_state"),
        )
        auto_expired = await self._expire_unused(run, now=now)
        rotation_revoked = await self._change_selected(
            run,
            step="rotation_grace",
            condition=repo.rotation_grace_over(now=now),
            change=partial(self._mark_revoked_for_rotation, now=now),
        )

        return {
            "expired": expired,
            "expired_state_closed": expired_state_closed,
            "auto_expired": auto_expired,
            "rotation_revoked": rotation_revoked,
            "batch_limit_per_selection": API_KEY_MAINTENANCE_BATCH_LIMIT,
            "limit_reached": run.limit_reached,
            "errors": run.errors,
        }

    async def _expire_unused(self, run: _Run, *, now: datetime) -> int:
        """Apply each tenant's unused-key policy, one tenant at a time, so a
        tenant that cannot be loaded stops only its own keys."""
        step = "unused"
        session = self.api_key_repo.session
        try:
            async with session.begin_nested():
                tenant_ids = await self.tenant_repo.get_all_tenant_ids()
        except Exception as exc:
            run.failed(exc, step=step)
            return 0

        expired = 0
        for tenant_id in tenant_ids:
            try:
                async with session.begin_nested():
                    tenant = await self.tenant_repo.get(tenant_id)
            except Exception as exc:
                run.failed(exc, step=step, tenant_id=str(tenant_id))
                continue
            days = None if tenant is None else self._get_auto_expire_days(tenant)
            if days is None:
                continue
            cutoff = now - timedelta(days=days)
            expired += await self._change_selected(
                run,
                step=step,
                tenant_id=tenant_id,
                condition=self.api_key_repo.unused_since(
                    tenant_id=tenant_id, cutoff=cutoff
                ),
                change=partial(
                    self._mark_expired,
                    now=now,
                    reason="unused",
                    extra={"cutoff": cutoff.isoformat(), "days": str(days)},
                ),
            )
        return expired

    async def _change_selected(
        self,
        run: _Run,
        *,
        step: str,
        condition: sa.ColumnElement[bool],
        change: Callable[[sa.ColumnElement[bool], ApiKeyV2InDB], Awaitable[int]],
        tenant_id: UUID | None = None,
    ) -> int:
        """Select the oldest keys matching ``condition`` and ``change`` each.

        The selection and every key run in their own savepoint and the error
        is caught outside it, so a failure undoes only that key or selection
        and leaves the transaction usable for the rest.
        """
        where = {} if tenant_id is None else {"tenant_id": str(tenant_id)}
        limit = API_KEY_MAINTENANCE_BATCH_LIMIT
        session = self.api_key_repo.session
        try:
            async with session.begin_nested():
                keys = await self.api_key_repo.list_matching(condition, limit=limit)
        except Exception as exc:
            run.failed(exc, step=step, **where)
            return 0
        if len(keys) >= limit:
            run.limit_reached.append({"step": step, **where})
            logger.info(
                "API key maintenance reached its limit; further keys wait for the next run",
                extra={"step": step, "limit": limit, **where},
            )

        changed = 0
        for key in keys:
            try:
                async with session.begin_nested():
                    changed += await change(condition, key)
            except Exception as exc:
                run.failed(
                    exc, step=step, key_id=str(key.id), tenant_id=str(key.tenant_id)
                )
        return changed

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
        key: ApiKeyV2InDB,
        *,
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

        # Written in the key's savepoint whatever the tenant's audit settings,
        # so the transition and its audit row commit or roll back together.
        await self.audit_service.log(
            required=True,
            tenant_id=updated_key.tenant_id,
            actor_type=ActorType.SYSTEM,
            action=ActionType.API_KEY_EXPIRED,
            entity_type=EntityType.API_KEY,
            entity_id=updated_key.id,
            description=f"Expired API key '{updated_key.name}'",
            metadata=AuditMetadata.system_action(
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
            ),
        )
        return 1

    async def _mark_revoked_for_rotation(
        self,
        condition: sa.ColumnElement[bool],
        key: ApiKeyV2InDB,
        *,
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

        await self.audit_service.log(
            required=True,
            tenant_id=updated_key.tenant_id,
            actor_type=ActorType.SYSTEM,
            action=ActionType.API_KEY_REVOKED,
            entity_type=EntityType.API_KEY,
            entity_id=updated_key.id,
            description=f"Revoked API key '{updated_key.name}' after rotation grace",
            metadata=AuditMetadata.system_action(
                description="API key revoked after rotation",
                target=updated_key,
                extra={
                    "reason_code": ApiKeyStateReasonCode.ROTATION_COMPLETED.value,
                    "rotation_grace_until": updated_key.rotation_grace_until.isoformat()
                    if updated_key.rotation_grace_until
                    else None,
                },
            ),
        )
        return 1

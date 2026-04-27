import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from intric.database.tables.tenant_table import Tenants
from intric.jobs.job_manager import job_manager
from intric.jobs.job_models import Task
from intric.main.exceptions import NotFoundException

_SYSADMIN_ACTOR = {"type": "sysadmin", "via": "eneo_super_api_key"}


class SysAdminService:
    async def run_crawl_on_weekly_websites(self):
        return await job_manager.enqueue_jobless(Task.CRAWL_ALL_WEBSITES)


class ScimTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_token(self, tenant_id: UUID) -> str:
        result = await self._session.execute(
            sa.select(Tenants.id).where(Tenants.id == tenant_id)
        )
        if result.scalar_one_or_none() is None:
            raise NotFoundException(f"Tenant {tenant_id} not found")

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        await self._session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(scim_token_hash=token_hash, updated_at=datetime.now(timezone.utc))
        )
        await self._log_audit(tenant_id, ActionType.SCIM_TOKEN_CREATED, "Sysadmin generated SCIM bearer token for tenant")
        return token

    async def get_status(self, tenant_id: UUID) -> bool:
        result = await self._session.execute(
            sa.select(Tenants.scim_token_hash).where(Tenants.id == tenant_id)
        )
        row = result.one_or_none()
        if row is None:
            raise NotFoundException(f"Tenant {tenant_id} not found")
        return row[0] is not None

    async def revoke_token(self, tenant_id: UUID) -> None:
        result = await self._session.execute(
            sa.select(Tenants.id).where(Tenants.id == tenant_id)
        )
        if result.scalar_one_or_none() is None:
            raise NotFoundException(f"Tenant {tenant_id} not found")

        await self._session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(scim_token_hash=None, updated_at=datetime.now(timezone.utc))
        )
        await self._log_audit(tenant_id, ActionType.SCIM_TOKEN_REVOKED, "Sysadmin revoked SCIM bearer token for tenant")

    async def _log_audit(self, tenant_id: UUID, action: ActionType, description: str) -> None:
        audit = AuditService(repository=AuditLogRepositoryImpl(session=self._session))
        await audit.log(
            tenant_id=tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=action,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=tenant_id,
            description=description,
            metadata={"actor": _SYSADMIN_ACTOR},
        )

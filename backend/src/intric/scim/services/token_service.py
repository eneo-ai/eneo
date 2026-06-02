from __future__ import annotations

import hashlib
import secrets
from typing import TYPE_CHECKING
from uuid import UUID

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.scim.repositories.token_repository import ScimTokenRepository

_SYSADMIN_ACTOR = {"type": "sysadmin", "via": "eneo_super_api_key"}


class ScimTokenService:
    def __init__(
        self,
        repository: ScimTokenRepository,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._audit = audit_service

    async def create_token(self, tenant_id: UUID) -> str:
        if not await self._repository.tenant_exists(tenant_id):
            raise NotFoundException(f"Tenant {tenant_id} not found")

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        await self._repository.set_token_hash(tenant_id, token_hash)
        await self._log_audit(
            tenant_id,
            ActionType.SCIM_TOKEN_CREATED,
            "Sysadmin generated SCIM bearer token for tenant",
        )
        return token

    async def get_status(self, tenant_id: UUID) -> bool:
        exists, token_hash = await self._repository.get_token_hash(tenant_id)
        if not exists:
            raise NotFoundException(f"Tenant {tenant_id} not found")
        return token_hash is not None

    async def revoke_token(self, tenant_id: UUID) -> None:
        if not await self._repository.tenant_exists(tenant_id):
            raise NotFoundException(f"Tenant {tenant_id} not found")

        await self._repository.set_token_hash(tenant_id, None)
        await self._log_audit(
            tenant_id,
            ActionType.SCIM_TOKEN_REVOKED,
            "Sysadmin revoked SCIM bearer token for tenant",
        )

    async def _log_audit(
        self, tenant_id: UUID, action: ActionType, description: str
    ) -> None:
        await self._audit.log(
            tenant_id=tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=action,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=tenant_id,
            description=description,
            metadata={"actor": _SYSADMIN_ACTOR},
        )

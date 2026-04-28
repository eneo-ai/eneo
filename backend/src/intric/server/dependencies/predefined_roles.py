import os
import pathlib
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import yaml

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from intric.database.database import sessionmanager
from intric.main.logging import get_logger
from intric.roles.role import RoleCreate
from intric.roles.roles_repo import RolesRepository

PREDEFINED_ROLES_FILE_NAME = "predefined_roles.yml"

# Stable int64 key for pg_advisory_lock — ensures only one gunicorn worker
# seeds at a time during concurrent boot. Value is bytes of "ENEO_SED"
# interpreted big-endian: a chosen constant, memorable in `pg_locks`.
_SEED_ADVISORY_LOCK_KEY = int.from_bytes(b"ENEO_SED", "big", signed=True)

logger = get_logger(__name__)


def load_predefined_roles_from_config() -> list[dict[str, Any]]:
    config_path = os.path.join(
        pathlib.Path(__file__).parent.resolve(), PREDEFINED_ROLES_FILE_NAME
    )
    with open(config_path, "r") as file:
        data = yaml.safe_load(file)
        return data["roles"]


async def _seed_tenant_roles(
    tenant_id: UUID,
    default_role_id: UUID | None,
    templates: list[dict[str, Any]],
) -> None:
    """Seed templates for one tenant in its own transaction.

    Committing per-tenant means a failure on tenant N does not roll back
    successful seeds for tenants 1..N-1.

    Audit rows are written via the same session so role mutations and
    their audit trail share one atomic commit — a half-written trail is
    worse than none. Tenant-scoped audit config (disabled categories,
    feature flag) is intentionally bypassed (None/None): system-initiated
    convergence events must always be recorded, regardless of what a
    tenant may have toggled off for their user-facing audit view.
    """
    from intric.database.tables.roles_table import Roles
    from intric.database.tables.tenant_table import Tenants

    async with sessionmanager.session() as session, session.begin():
        repo = RolesRepository(session=session)
        audit_service = AuditService(
            repository=AuditLogRepositoryImpl(session=session),
            audit_config_service=None,
            feature_flag_service=None,
        )
        existing_roles = await repo.get_by_tenant(tenant_id)
        existing_sources = {
            r.predefined_source for r in existing_roles if r.predefined_source
        }

        user_role_id: UUID | None = None

        for template in templates:
            name = template["name"]

            if name in existing_sources:
                if name == "User":
                    user_role_id = next(
                        r.id for r in existing_roles if r.predefined_source == "User"
                    )
                continue

            # If a role with matching name exists but no predefined_source, tag it
            matching = next(
                (
                    r
                    for r in existing_roles
                    if r.name == name and not r.predefined_source
                ),
                None,
            )
            if matching:
                stmt = (
                    sa.update(Roles)
                    .where(Roles.id == matching.id)
                    .values(predefined_source=name)
                )
                await session.execute(stmt)
                if name == "User":
                    user_role_id = matching.id
                await audit_service.log(
                    tenant_id=tenant_id,
                    actor_id=None,
                    actor_type=ActorType.SYSTEM,
                    action=ActionType.ROLE_MODIFIED,
                    entity_type=EntityType.ROLE,
                    entity_id=matching.id,
                    description=(
                        f"Seeder tagged existing role '{name}' with "
                        f"predefined_source='{name}'"
                    ),
                    metadata={
                        "actor": {"type": "system", "via": "boot_seeder"},
                        "target": {
                            "tenant_id": str(tenant_id),
                            "role_id": str(matching.id),
                            "role_name": name,
                        },
                        "changes": {
                            "predefined_source": {"before": None, "after": name},
                        },
                    },
                )
                continue

            role = RoleCreate(
                name=name,
                permissions=template["permissions"],
                tenant_id=tenant_id,
                predefined_source=name,
            )
            created = await repo.create_role(role)
            if name == "User":
                user_role_id = created.id
            await audit_service.log(
                tenant_id=tenant_id,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                action=ActionType.ROLE_CREATED,
                entity_type=EntityType.ROLE,
                entity_id=created.id,
                description=f"Seeder created predefined role '{name}'",
                metadata={
                    "actor": {"type": "system", "via": "boot_seeder"},
                    "target": {
                        "tenant_id": str(tenant_id),
                        "role_id": str(created.id),
                        "role_name": name,
                        "predefined_source": name,
                        "permissions": list(template["permissions"]),
                    },
                },
            )

        if default_role_id is None and user_role_id is not None:
            stmt = (
                sa.update(Tenants)
                .where(Tenants.id == tenant_id)
                .values(default_role_id=user_role_id)
            )
            await session.execute(stmt)
            await audit_service.log(
                tenant_id=tenant_id,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                action=ActionType.TENANT_SETTINGS_UPDATED,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=tenant_id,
                description=(
                    "Seeder set tenant default_role_id to the 'User' predefined role"
                ),
                metadata={
                    "actor": {"type": "system", "via": "boot_seeder"},
                    "target": {
                        "tenant_id": str(tenant_id),
                        "default_role_id": str(user_role_id),
                    },
                    "changes": {
                        "default_role_id": {
                            "before": None,
                            "after": str(user_role_id),
                        },
                    },
                },
            )


async def seed_roles_for_all_tenants() -> None:
    """Ensure all tenants have all template roles from config.

    Serialized across workers via a Postgres session-scoped advisory lock:
    only one worker holds the lock at a time; others wait and then find
    the seeds already applied. Session-scoped (not transaction-scoped) so
    that it spans the per-tenant commit loop below. Exceptions propagate
    so boot fails fast rather than silently starting with partial state.
    """
    from intric.database.tables.tenant_table import Tenants

    templates = load_predefined_roles_from_config()

    # Dedicated connection for the advisory lock — NOT the pooled session
    # used for writes — so the lock is held across the whole function and
    # released via pg_advisory_unlock regardless of transaction boundaries.
    async with sessionmanager.connect() as conn:
        await conn.execute(
            sa.text("SELECT pg_advisory_lock(:key)").bindparams(
                key=_SEED_ADVISORY_LOCK_KEY
            )
        )
        try:
            result = await conn.execute(sa.select(Tenants.id, Tenants.default_role_id))
            tenants = result.all()

            for tenant_id, default_role_id in tenants:
                try:
                    await _seed_tenant_roles(tenant_id, default_role_id, templates)
                except Exception:
                    # Log with tenant_id so operators can recover the one
                    # tenant that failed instead of debugging a blanket
                    # traceback. Then re-raise so boot fails fast.
                    logger.exception("Failed to seed roles for tenant %s", tenant_id)
                    raise
        finally:
            await conn.execute(
                sa.text("SELECT pg_advisory_unlock(:key)").bindparams(
                    key=_SEED_ADVISORY_LOCK_KEY
                )
            )


async def init_predefined_roles():
    await seed_roles_for_all_tenants()

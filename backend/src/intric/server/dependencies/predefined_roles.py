import os
import pathlib

import yaml

from intric.database.database import sessionmanager
from intric.main.logging import get_logger
from intric.roles.role import RoleCreate
from intric.roles.roles_repo import RolesRepository

PREDEFINED_ROLES_FILE_NAME = "predefined_roles.yml"

logger = get_logger(__name__)


def load_predefined_roles_from_config():
    config_path = os.path.join(
        pathlib.Path(__file__).parent.resolve(), PREDEFINED_ROLES_FILE_NAME
    )
    with open(config_path, "r") as file:
        data = yaml.safe_load(file)
        return data["roles"]


async def seed_roles_for_all_tenants():
    """Ensure all tenants have all template roles from config."""
    try:
        templates = load_predefined_roles_from_config()
        async with sessionmanager.session() as session, session.begin():
            import sqlalchemy as sa
            from intric.database.tables.tenant_table import Tenants
            from intric.database.tables.roles_table import Roles

            # Get all tenants (id + default_role_id)
            result = await session.execute(
                sa.select(Tenants.id, Tenants.default_role_id)
            )
            tenants = result.all()

            repo = RolesRepository(session=session)

            for tenant_id, default_role_id in tenants:
                # Get existing roles for this tenant
                existing_roles = await repo.get_by_tenant(tenant_id)
                existing_sources = {
                    r.predefined_source for r in existing_roles if r.predefined_source
                }

                user_role_id = None

                for template in templates:
                    name = template["name"]

                    # If a role with this predefined_source already exists, skip
                    if name in existing_sources:
                        # But track "User" role id for default_role_id
                        if name == "User":
                            user_role_id = next(
                                r.id for r in existing_roles if r.predefined_source == "User"
                            )
                        continue

                    # If a role with matching name exists but no predefined_source, tag it
                    matching = next(
                        (r for r in existing_roles if r.name == name and not r.predefined_source),
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
                        continue

                    # Create new role
                    role = RoleCreate(
                        name=name,
                        permissions=template["permissions"],
                        tenant_id=tenant_id,
                        predefined_source=name,
                    )
                    created = await repo.create_role(role)
                    if name == "User":
                        user_role_id = created.id

                # Set default_role_id if not already set
                if default_role_id is None and user_role_id is not None:
                    stmt = (
                        sa.update(Tenants)
                        .where(Tenants.id == tenant_id)
                        .values(default_role_id=user_role_id)
                    )
                    await session.execute(stmt)

    except Exception as e:
        logger.exception(f"Seeding tenant roles crashed with error: {str(e)}")


async def init_predefined_roles():
    await seed_roles_for_all_tenants()

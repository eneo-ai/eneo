import os
import pathlib
from typing import Any, cast

import yaml

from intric.database.database import sessionmanager
from intric.main.logging import get_logger
from intric.main.models import IdAndName
from intric.predefined_roles.predefined_role import (
    PredefinedRoleCreate,
    PredefinedRoleUpdate,
)
from intric.predefined_roles.predefined_roles_repo import PredefinedRolesRepository

PREDEFINED_ROLES_FILE_NAME = "predefined_roles.yml"

logger = get_logger(__name__)


def load_predefined_roles_from_config() -> list[dict[str, Any]]:
    config_path = os.path.join(
        pathlib.Path(__file__).parent.resolve(), PREDEFINED_ROLES_FILE_NAME
    )
    with open(config_path, "r") as file:
        data = yaml.safe_load(file)
        return data["roles"]


async def init_predefined_roles() -> None:
    try:
        predefined_roles = load_predefined_roles_from_config()
        async with sessionmanager.session() as session, session.begin():
            repository = PredefinedRolesRepository(session=session)

            existing_roles = cast(list[IdAndName], await repository.get_ids_and_names())
            existing_role_names = {role.name: role.id for role in existing_roles}
            new_role_names = [role["name"] for role in predefined_roles]

            # remove roles
            for role in existing_roles:
                if role.name not in new_role_names:
                    await repository.delete_predefined_role_by_id(role.id)

            # create new roles or update existing
            for role in predefined_roles:
                role = PredefinedRoleCreate(**role)
                if role.name not in existing_role_names:
                    await repository.create_predefined_role(role)
                else:
                    role = PredefinedRoleUpdate(
                        **role.model_dump(), id=existing_role_names[role.name]
                    )
                    await repository.update_predefined_role(role)
    except Exception as e:
        logger.exception(f"Creating predefined roles crashed with next error: {str(e)}")

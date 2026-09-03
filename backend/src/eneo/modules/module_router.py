from typing import Annotated

from fastapi import APIRouter, Depends, Path

from eneo.authentication.auth_dependencies import (
    require_permission,
    require_session_auth,
)
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.modules.module import (
    MODULE_KEY_MAX_LENGTH,
    MODULE_KEY_PATTERN,
    ModuleInstallation,
    ModuleInstallationChange,
    ModuleInstallationConfig,
)
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter(
    dependencies=[
        Depends(require_permission(Permission.MODULES)),
        Depends(require_session_auth),
    ],
    responses=responses.get_responses([401, 403]),
)

_MutationContainer = Annotated[
    Container,
    Depends(get_container(with_user=True, transaction_scope="function")),
]
_ReadContainer = Annotated[Container, Depends(get_container(with_user=True))]
_ModuleKey = Annotated[
    str, Path(pattern=MODULE_KEY_PATTERN, max_length=MODULE_KEY_MAX_LENGTH)
]


@router.get(
    "/",
    response_model=PaginatedResponse[ModuleInstallation],
    description=(
        "List modules installed for the authenticated user's organization. "
        "The tenant identity is derived from the session and is never accepted "
        "from the client."
    ),
    responses=responses.get_responses([]),
)
async def list_module_installations(
    container: _ReadContainer,
) -> PaginatedResponse[ModuleInstallation]:
    installations = await container.module_installation_service().list_installations()
    return PaginatedResponse[ModuleInstallation](items=installations)


@router.put(
    "/{module_key}/",
    response_model=ModuleInstallation,
    description=(
        "Idempotently register, enable and fully configure one module for the "
        "authenticated user's organization. The service key must already exist "
        "in that organization and be an active, service-owned sk_ key with write "
        "or admin permission. An explicit null service_key_id keeps the module "
        "installed but severs ticket exchange until a key is bound again."
    ),
    responses=responses.get_responses([400]),
)
async def install_module(
    module_key: _ModuleKey,
    config: ModuleInstallationConfig,
    container: _MutationContainer,
) -> ModuleInstallation:
    return await container.module_installation_service().install(
        module_key=module_key,
        config=config,
    )


@router.delete(
    "/{module_key}/",
    response_model=ModuleInstallationChange,
    description=(
        "Uninstall one module from the authenticated user's organization. "
        "Removing the assignment also deletes its callback and service-key "
        "binding. A module that is not installed for the organization returns "
        "404 whether or not the key exists elsewhere; concurrent retries are "
        "safe and report changed=false."
    ),
    responses=responses.get_responses([404]),
)
async def uninstall_module(
    module_key: _ModuleKey,
    container: _MutationContainer,
) -> ModuleInstallationChange:
    return await container.module_installation_service().uninstall(
        module_key=module_key
    )

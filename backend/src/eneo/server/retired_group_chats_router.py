"""The retired group chat API: every call answers 410 Gone.

Group chats were replaced by assistants that consult specialists. Each group
became an assistant with the same id, so a client holding a group chat id can
use it as an assistant id against the assistant endpoints.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container

router = APIRouter()

RETIRED_DETAIL = {
    "code": "group_chats_retired",
    "message": (
        "Group chats were replaced by assistants with specialists. The group "
        "became an assistant with the same id; use the assistant endpoints."
    ),
}

_ACCESS_REASON = (
    "Retired group chat endpoints answer 410 for signed-in users so clients "
    "built against the old API learn where the resource went."
)


def _gone() -> None:
    raise HTTPException(status_code=410, detail=RETIRED_DETAIL)


_RESPONSES: dict[int | str, dict[str, Any]] = {
    410: {"description": "Group chats are retired."}
}
_DESCRIPTION = "Retired: group chats became assistants with specialists. Always 410."


@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ACCESS_REASON,
)
async def retired_group_chats_collection(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    _gone()


@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ACCESS_REASON,
)
async def retired_group_chats_item(
    path: str,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    _gone()


# One route per method keeps every OpenAPI operation id unique.
for _method in ("GET", "POST"):
    router.add_api_route(
        "/",
        retired_group_chats_collection,
        methods=[_method],
        operation_id=f"retired_group_chats_collection_{_method.lower()}",
        responses=_RESPONSES,
        description=_DESCRIPTION,
        deprecated=True,
    )
for _method in ("GET", "POST", "PATCH", "PUT", "DELETE"):
    router.add_api_route(
        "/{path:path}",
        retired_group_chats_item,
        methods=[_method],
        operation_id=f"retired_group_chats_item_{_method.lower()}",
        responses=_RESPONSES,
        description=_DESCRIPTION,
        deprecated=True,
    )

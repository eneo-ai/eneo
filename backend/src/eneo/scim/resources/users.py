from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, Response

from eneo.scim.auth import require_scim_auth
from eneo.scim.deps import get_scim_user_service
from eneo.scim.domain.errors import (
    ScimHttpError,
    ScimUserConflictError,
    ScimUserNotFoundError,
)
from eneo.scim.openapi import scim_responses
from eneo.scim.schemas.common import ListResponse
from eneo.scim.schemas.user import PatchRequest, ScimUser, ScimUserRequest
from eneo.scim.services.user_service import ScimUserService

router = APIRouter(dependencies=[Depends(require_scim_auth)], tags=["SCIM Users"])


@router.post(
    "/Users",
    status_code=status.HTTP_201_CREATED,
    response_model=ScimUser,
    description="Provision a SCIM user.",
    responses=scim_responses(400, 401, 409, 500),
)
async def create_user(
    payload: ScimUserRequest,
    service: Annotated[ScimUserService, Depends(get_scim_user_service)],
) -> Response:
    try:
        user = await service.create_user(payload)
        location = f"/scim/v2/Users/{user.id}"
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=user.model_dump(mode="json"),
            headers={"Location": location},
        )
    except ScimUserConflictError as e:
        raise ScimHttpError(409, str(e), scim_type="uniqueness") from e


@router.get(
    "/Users",
    description="List and filter SCIM users.",
    responses=scim_responses(400, 401, 500),
    response_model=ListResponse,
)
async def list_users(
    service: Annotated[ScimUserService, Depends(get_scim_user_service)],
    filter: str | None = None,
    startIndex: int = 1,
    count: int | None = None,
    sortBy: str | None = None,
    sortOrder: str | None = None,
) -> ListResponse:
    start = max(1, startIndex)
    users, total = await service.list_users(
        filter_str=filter,
        sort_by=sortBy,
        sort_order=sortOrder,
        start_index=start,
        count=count,
    )
    return ListResponse(
        totalResults=total,
        startIndex=start,
        itemsPerPage=len(users),
        Resources=[u.model_dump() for u in users],
    )


@router.get(
    "/Users/{user_id}",
    description="Get a SCIM user by identifier.",
    responses=scim_responses(400, 401, 404, 500),
    response_model=ScimUser,
)
async def get_user(
    user_id: UUID,
    service: Annotated[ScimUserService, Depends(get_scim_user_service)],
) -> ScimUser:
    try:
        return await service.get_user(user_id)
    except ScimUserNotFoundError as e:
        raise ScimHttpError(404, "User not found") from e


@router.put(
    "/Users/{user_id}",
    description="Replace a SCIM user.",
    responses=scim_responses(400, 401, 404, 409, 500),
    response_model=ScimUser,
)
async def replace_user(
    user_id: UUID,
    payload: ScimUserRequest,
    service: Annotated[ScimUserService, Depends(get_scim_user_service)],
) -> ScimUser:
    try:
        return await service.replace_user(user_id, payload)
    except ScimUserNotFoundError as e:
        raise ScimHttpError(404, "User not found") from e
    except ScimUserConflictError as e:
        raise ScimHttpError(409, str(e), scim_type="uniqueness") from e


@router.patch(
    "/Users/{user_id}",
    description="Apply SCIM patch operations to a user.",
    responses=scim_responses(400, 401, 404, 409, 500),
    response_model=ScimUser,
)
async def patch_user(
    user_id: UUID,
    payload: PatchRequest,
    service: Annotated[ScimUserService, Depends(get_scim_user_service)],
) -> ScimUser:
    try:
        return await service.patch_user(user_id, payload.Operations)
    except ScimUserNotFoundError as e:
        raise ScimHttpError(404, "User not found") from e
    except ScimUserConflictError as e:
        raise ScimHttpError(409, str(e), scim_type="uniqueness") from e


@router.delete(
    "/Users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Delete a SCIM user.",
    responses=scim_responses(400, 401, 404, 500),
    response_model=None,
)
async def delete_user(
    user_id: UUID,
    service: Annotated[ScimUserService, Depends(get_scim_user_service)],
) -> Response:
    try:
        await service.delete_user(user_id)
    except ScimUserNotFoundError as e:
        raise ScimHttpError(404, "User not found") from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)

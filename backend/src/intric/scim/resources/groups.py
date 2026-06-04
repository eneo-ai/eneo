from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, Response

from intric.scim.auth import require_scim_auth
from intric.scim.deps import get_scim_group_service
from intric.scim.domain.errors import (
    ScimGroupConflictError,
    ScimGroupNotFoundError,
    ScimHttpError,
)
from intric.scim.schemas.common import ListResponse
from intric.scim.schemas.group import ScimGroup, ScimGroupRequest
from intric.scim.schemas.user import PatchRequest
from intric.scim.services.group_service import ScimGroupService

router = APIRouter(dependencies=[Depends(require_scim_auth)], tags=["SCIM Groups"])


@router.post("/Groups", status_code=status.HTTP_201_CREATED, response_model=ScimGroup)
async def create_group(
    payload: ScimGroupRequest,
    service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
) -> Response:
    try:
        group = await service.create_group(payload)
        location = f"/scim/v2/Groups/{group.id}"
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=group.model_dump(mode="json"),
            headers={"Location": location},
        )
    except ScimGroupConflictError as e:
        raise ScimHttpError(409, str(e), scim_type="uniqueness") from e


@router.get("/Groups")
async def list_groups(
    service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
    filter: str | None = None,
    startIndex: int = 1,
    count: int | None = None,
    sortBy: str | None = None,
    sortOrder: str | None = None,
) -> ListResponse:
    start = max(1, startIndex)
    groups, total = await service.list_groups(
        filter_str=filter,
        sort_by=sortBy,
        sort_order=sortOrder,
        start_index=start,
        count=count,
    )
    return ListResponse(
        totalResults=total,
        startIndex=start,
        itemsPerPage=len(groups),
        Resources=[g.model_dump() for g in groups],
    )


@router.get("/Groups/{group_id}")
async def get_group(
    group_id: UUID,
    service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
) -> ScimGroup:
    try:
        return await service.get_group(group_id)
    except ScimGroupNotFoundError as e:
        raise ScimHttpError(404, "Group not found") from e


@router.put("/Groups/{group_id}")
async def replace_group(
    group_id: UUID,
    payload: ScimGroupRequest,
    service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
) -> ScimGroup:
    try:
        return await service.replace_group(group_id, payload)
    except ScimGroupNotFoundError as e:
        raise ScimHttpError(404, "Group not found") from e
    except ScimGroupConflictError as e:
        raise ScimHttpError(409, str(e), scim_type="uniqueness") from e


@router.patch("/Groups/{group_id}")
async def patch_group(
    group_id: UUID,
    payload: PatchRequest,
    service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
) -> ScimGroup:
    try:
        return await service.patch_group(group_id, payload.Operations)
    except ScimGroupNotFoundError as e:
        raise ScimHttpError(404, "Group not found") from e
    except ScimGroupConflictError as e:
        raise ScimHttpError(409, str(e), scim_type="uniqueness") from e


@router.delete("/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID,
    service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
) -> Response:
    try:
        await service.delete_group(group_id)
    except ScimGroupNotFoundError as e:
        raise ScimHttpError(404, "Group not found") from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.database import get_session_with_transaction
from intric.scim.auth import require_scim_auth
from intric.scim.deps import get_scim_group_service, get_scim_user_service
from intric.scim.domain.errors import (
    ScimGroupConflictError,
    ScimGroupNotFoundError,
    ScimHttpError,
    ScimUserConflictError,
    ScimUserNotFoundError,
    ScimValidationError,
)
from intric.scim.schemas.bulk import BulkOperation, BulkOperationResponse, BulkRequest, BulkResponse
from intric.scim.schemas.group import ScimGroupRequest
from intric.scim.schemas.user import PatchRequest, ScimUserRequest
from intric.scim.services.group_service import ScimGroupService
from intric.scim.services.user_service import ScimUserService

router = APIRouter(dependencies=[Depends(require_scim_auth)], tags=["SCIM Bulk"])

_BULK_ID_RE = re.compile(r"bulkId:(\S+)")
_PATH_RE = re.compile(r"^/(Users|Groups)(?:/([^/]+))?$")


def _resolve_path(path: str, bulk_id_map: dict[str, str]) -> str:
    return _BULK_ID_RE.sub(lambda m: bulk_id_map.get(m.group(1), m.group(0)), path)


def _scim_error_response(method: str, bulk_id: str | None, status: int, detail: str, scim_type: str | None = None) -> BulkOperationResponse:
    body: dict = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": str(status),
        "detail": detail,
    }
    if scim_type:
        body["scimType"] = scim_type
    return BulkOperationResponse(method=method, bulkId=bulk_id, status=str(status), response=body)


@router.post("/Bulk")
async def bulk_operations(
    payload: BulkRequest,
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    user_service: Annotated[ScimUserService, Depends(get_scim_user_service)],
    group_service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
) -> BulkResponse:
    results: list[BulkOperationResponse] = []
    bulk_id_map: dict[str, str] = {}
    error_count = 0

    for op in payload.Operations:
        if payload.failOnErrors and error_count >= payload.failOnErrors:
            break

        result = await _execute_operation(op, bulk_id_map, user_service, group_service, session)
        results.append(result)

        if int(result.status) >= 400:
            error_count += 1

    return BulkResponse(Operations=results)


async def _execute_operation(
    op: BulkOperation,
    bulk_id_map: dict[str, str],
    user_service: ScimUserService,
    group_service: ScimGroupService,
    session: AsyncSession,
) -> BulkOperationResponse:
    method = op.method.upper()
    path = _resolve_path(op.path, bulk_id_map)
    match = _PATH_RE.match(path)
    if not match:
        return _scim_error_response(method, op.bulkId, 400, f"Invalid path: {op.path}")

    resource_type = match.group(1)   # "Users" or "Groups"
    resource_id = match.group(2)     # UUID string or None

    try:
        async with session.begin_nested():
            if resource_type == "Users":
                return await _handle_user_op(method, resource_id, op, bulk_id_map, user_service)
            else:
                return await _handle_group_op(method, resource_id, op, bulk_id_map, group_service)
    except ScimHttpError as e:
        return _scim_error_response(method, op.bulkId, e.status_code, e.detail, e.scim_type)
    except ScimValidationError as e:
        return _scim_error_response(method, op.bulkId, 400, str(e), "invalidValue")
    except Exception as e:
        return _scim_error_response(method, op.bulkId, 500, str(e))


async def _handle_user_op(
    method: str,
    resource_id: str | None,
    op: BulkOperation,
    bulk_id_map: dict[str, str],
    service: ScimUserService,
) -> BulkOperationResponse:
    try:
        if method == "POST":
            data = ScimUserRequest.model_validate(op.data)
            user = await service.create_user(data)
            location = f"/scim/v2/Users/{user.id}"
            if op.bulkId:
                bulk_id_map[op.bulkId] = user.id
            return BulkOperationResponse(method=method, bulkId=op.bulkId, location=location, status="201")

        if resource_id is None:
            return _scim_error_response(method, op.bulkId, 400, "Resource ID required")
        uid = UUID(resource_id)

        if method == "PUT":
            data = ScimUserRequest.model_validate(op.data)
            user = await service.replace_user(uid, data)
            return BulkOperationResponse(method=method, location=f"/scim/v2/Users/{user.id}", status="200")

        if method == "PATCH":
            data = PatchRequest.model_validate(op.data)
            user = await service.patch_user(uid, data.Operations)
            return BulkOperationResponse(method=method, location=f"/scim/v2/Users/{user.id}", status="200")

        if method == "DELETE":
            await service.delete_user(uid)
            return BulkOperationResponse(method=method, status="204")

    except ScimUserNotFoundError:
        raise ScimHttpError(404, "User not found")
    except ScimUserConflictError as e:
        raise ScimHttpError(409, str(e), "uniqueness")

    return _scim_error_response(method, op.bulkId, 405, f"Method {method} not allowed")


async def _handle_group_op(
    method: str,
    resource_id: str | None,
    op: BulkOperation,
    bulk_id_map: dict[str, str],
    service: ScimGroupService,
) -> BulkOperationResponse:
    try:
        if method == "POST":
            data = ScimGroupRequest.model_validate(op.data)
            group = await service.create_group(data)
            location = f"/scim/v2/Groups/{group.id}"
            if op.bulkId:
                bulk_id_map[op.bulkId] = group.id
            return BulkOperationResponse(method=method, bulkId=op.bulkId, location=location, status="201")

        if resource_id is None:
            return _scim_error_response(method, op.bulkId, 400, "Resource ID required")
        gid = UUID(resource_id)

        if method == "PUT":
            data = ScimGroupRequest.model_validate(op.data)
            group = await service.replace_group(gid, data)
            return BulkOperationResponse(method=method, location=f"/scim/v2/Groups/{group.id}", status="200")

        if method == "PATCH":
            data = PatchRequest.model_validate(op.data)
            group = await service.patch_group(gid, data.Operations)
            return BulkOperationResponse(method=method, location=f"/scim/v2/Groups/{group.id}", status="200")

        if method == "DELETE":
            await service.delete_group(gid)
            return BulkOperationResponse(method=method, status="204")

    except ScimGroupNotFoundError:
        raise ScimHttpError(404, "Group not found")
    except ScimGroupConflictError as e:
        raise ScimHttpError(409, str(e), "uniqueness")

    return _scim_error_response(method, op.bulkId, 405, f"Method {method} not allowed")

from __future__ import annotations

import re
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.database import get_session_with_transaction
from intric.main.logging import get_logger
from intric.scim.auth import require_scim_auth
from intric.scim.constants import (
    SCIM_BULK_MAX_OPERATIONS,
    SCIM_BULK_MAX_PAYLOAD_BYTES,
)
from intric.scim.deps import get_scim_group_service, get_scim_user_service
from intric.scim.domain.errors import (
    ScimGroupConflictError,
    ScimGroupNotFoundError,
    ScimHttpError,
    ScimUserConflictError,
    ScimUserNotFoundError,
    ScimValidationError,
)
from intric.scim.schemas.bulk import (
    BulkOperation,
    BulkOperationResponse,
    BulkRequest,
    BulkResponse,
)
from intric.scim.schemas.group import ScimGroupRequest
from intric.scim.schemas.user import PatchRequest, ScimUserRequest
from intric.scim.services.group_service import ScimGroupService
from intric.scim.services.user_service import ScimUserService

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_scim_auth)], tags=["SCIM Bulk"])

_BULK_ID_RE = re.compile(r"bulkId:(\S+)")
_PATH_RE = re.compile(r"^/(Users|Groups)(?:/([^/]+))?$")


def _resolve_path(path: str, bulk_id_map: dict[str, str]) -> str:
    return _BULK_ID_RE.sub(lambda m: bulk_id_map.get(m.group(1), m.group(0)), path)


def _resolve_bulk_ids(value: Any, bulk_id_map: dict[str, str]) -> Any:
    """Recursively resolve ``bulkId:<temp-id>`` references inside operation data.

    RFC 7644 §3.7.2 lets one operation reference a resource created earlier in
    the same request via a ``bulkId:<temp-id>`` token wherever a resource
    identifier is expected — most importantly ``Group.members[].value``, so a
    single request can create a user and add it to a group. Resolving only the
    URL/path (``_resolve_path``) misses those in-body references, leaving the
    group service to choke on ``UUID("bulkId:u1")``. We substitute against the
    same map; an unresolved token is left untouched so the downstream UUID
    parse fails with a clear error rather than silently dropping the member.
    """
    if isinstance(value, str):
        return _BULK_ID_RE.sub(lambda m: bulk_id_map.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        items: list[Any] = cast("list[Any]", value)
        return [_resolve_bulk_ids(item, bulk_id_map) for item in items]
    if isinstance(value, dict):
        entries: dict[str, Any] = cast("dict[str, Any]", value)
        return {
            key: _resolve_bulk_ids(val, bulk_id_map) for key, val in entries.items()
        }
    return value


def _scim_error_response(
    method: str,
    bulk_id: str | None,
    status: int,
    detail: str,
    scim_type: str | None = None,
) -> BulkOperationResponse:
    body: dict[str, object] = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": str(status),
        "detail": detail,
    }
    if scim_type:
        body["scimType"] = scim_type
    return BulkOperationResponse(
        method=method, bulkId=bulk_id, status=str(status), response=body
    )


@router.post("/Bulk")
async def bulk_operations(
    request: Request,
    payload: BulkRequest,
    session: Annotated[AsyncSession, Depends(get_session_with_transaction)],
    user_service: Annotated[ScimUserService, Depends(get_scim_user_service)],
    group_service: Annotated[ScimGroupService, Depends(get_scim_group_service)],
) -> BulkResponse:
    # Enforce the limits advertised in ServiceProviderConfig (RFC 7644 §3.7.3).
    # The Content-Length check catches oversized payloads from well-behaved
    # clients before the body is parsed further; FastAPI/Starlette has already
    # buffered the body by the time we get here, but rejecting fast is still
    # better than processing operations we know we'll have to abort.
    content_length_header = request.headers.get("content-length")
    if content_length_header is not None:
        try:
            content_length = int(content_length_header)
        except ValueError:
            content_length = 0
        if content_length > SCIM_BULK_MAX_PAYLOAD_BYTES:
            raise ScimHttpError(
                413,
                (
                    f"Bulk payload size {content_length} exceeds "
                    f"maxPayloadSize ({SCIM_BULK_MAX_PAYLOAD_BYTES} bytes)"
                ),
            )

    if len(payload.Operations) > SCIM_BULK_MAX_OPERATIONS:
        raise ScimHttpError(
            413,
            (
                f"Bulk request has {len(payload.Operations)} operations, "
                f"exceeds maxOperations ({SCIM_BULK_MAX_OPERATIONS})"
            ),
            "tooMany",
        )

    results: list[BulkOperationResponse] = []
    bulk_id_map: dict[str, str] = {}
    error_count = 0

    for op in payload.Operations:
        if payload.failOnErrors and error_count >= payload.failOnErrors:
            break

        result = await _execute_operation(
            op, bulk_id_map, user_service, group_service, session
        )
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
    # Resolve bulkId references in the body too (e.g. Group.members[].value),
    # not just the path — see _resolve_bulk_ids.
    op.data = _resolve_bulk_ids(op.data, bulk_id_map)
    match = _PATH_RE.match(path)
    if not match:
        return _scim_error_response(method, op.bulkId, 400, f"Invalid path: {op.path}")

    resource_type = match.group(1)  # "Users" or "Groups"
    resource_id = match.group(2)  # UUID string or None

    try:
        async with session.begin_nested():
            if resource_type == "Users":
                return await _handle_user_op(
                    method, resource_id, op, bulk_id_map, user_service
                )
            else:
                return await _handle_group_op(
                    method, resource_id, op, bulk_id_map, group_service
                )
    except ScimHttpError as e:
        return _scim_error_response(
            method, op.bulkId, e.status_code, e.detail, e.scim_type
        )
    except ScimValidationError as e:
        return _scim_error_response(method, op.bulkId, 400, str(e), "invalidValue")
    except Exception:
        # Log the full exception (including traceback) so operators can debug,
        # but return a generic message — `str(e)` on a SQLAlchemy
        # IntegrityError or DBAPIError exposes constraint names, column names,
        # the SQL statement, and bound parameter values, none of which belong
        # in an HTTP response body. Matches the non-bulk endpoint behaviour in
        # scim_app's unhandled_exception_handler.
        logger.exception(
            "scim.bulk.operation_failed",
            extra={"method": method, "path": op.path, "bulk_id": op.bulkId},
        )
        return _scim_error_response(method, op.bulkId, 500, "Internal server error")


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
            return BulkOperationResponse(
                method=method, bulkId=op.bulkId, location=location, status="201"
            )

        if resource_id is None:
            return _scim_error_response(method, op.bulkId, 400, "Resource ID required")
        uid = UUID(resource_id)

        if method == "PUT":
            data = ScimUserRequest.model_validate(op.data)
            user = await service.replace_user(uid, data)
            return BulkOperationResponse(
                method=method, location=f"/scim/v2/Users/{user.id}", status="200"
            )

        if method == "PATCH":
            data = PatchRequest.model_validate(op.data)
            user = await service.patch_user(uid, data.Operations)
            return BulkOperationResponse(
                method=method, location=f"/scim/v2/Users/{user.id}", status="200"
            )

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
            return BulkOperationResponse(
                method=method, bulkId=op.bulkId, location=location, status="201"
            )

        if resource_id is None:
            return _scim_error_response(method, op.bulkId, 400, "Resource ID required")
        gid = UUID(resource_id)

        if method == "PUT":
            data = ScimGroupRequest.model_validate(op.data)
            group = await service.replace_group(gid, data)
            return BulkOperationResponse(
                method=method, location=f"/scim/v2/Groups/{group.id}", status="200"
            )

        if method == "PATCH":
            data = PatchRequest.model_validate(op.data)
            group = await service.patch_group(gid, data.Operations)
            return BulkOperationResponse(
                method=method, location=f"/scim/v2/Groups/{group.id}", status="200"
            )

        if method == "DELETE":
            await service.delete_group(gid)
            return BulkOperationResponse(method=method, status="204")

    except ScimGroupNotFoundError:
        raise ScimHttpError(404, "Group not found")
    except ScimGroupConflictError as e:
        raise ScimHttpError(409, str(e), "uniqueness")

    return _scim_error_response(method, op.bulkId, 405, f"Method {method} not allowed")

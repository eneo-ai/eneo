from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from eneo.authentication.auth_dependencies import (
    get_current_active_user,
    get_scope_filter,
    require_user_identity,
)
from eneo.info_blobs.info_blob import (
    InfoBlobPublic,
    InfoBlobPublicNoText,
    InfoBlobUpdate,
    InfoBlobUpdatePublic,
)
from eneo.info_blobs.info_blob_protocol import (
    to_info_blob_public,
    to_info_blob_public_no_text,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.main.models import PaginatedResponse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.users.user import UserInDB

logger = get_logger(__name__)

router = APIRouter()

ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]
CurrentUserDep = Annotated[UserInDB, Depends(get_current_active_user)]


@router.get(
    "/",
    response_model=PaginatedResponse[InfoBlobPublicNoText],
    responses=responses.get_responses([]),
)
async def get_info_blob_ids(
    request: Request,
    container: ContainerDep,
):
    """Returns a list of info-blobs.

    Does not return the text of each info-blob, 'text' will be null.
    """
    scope_filter = get_scope_filter(request)
    service = container.info_blob_service()
    info_blobs_in_db = await service.get_by_user(
        space_id_filter=scope_filter.space_id,
    )

    info_blobs_public = [to_info_blob_public_no_text(blob) for blob in info_blobs_in_db]

    return protocol.to_paginated_response(info_blobs_public)


@router.get(
    "/{id}/",
    response_model=InfoBlobPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_info_blob(
    id: Annotated[UUID, Path()],
    container: ContainerDep,
):
    service = container.info_blob_service()

    info_blob_in_db = await service.get_by_id(id)

    return to_info_blob_public(info_blob_in_db)


@router.post(
    "/{id}/",
    response_model=InfoBlobPublic,
    description="Updates an info-blob by id. Omitted fields are not updated.",
    responses=responses.get_responses([400, 403, 404, 409]),
)
async def update_info_blob(
    id: Annotated[UUID, Path()],
    info_blob: InfoBlobUpdatePublic,
    container: ContainerDep,
    current_user: CurrentUserDep,
    _user_identity_guard: None = Depends(require_user_identity),
):
    """Omitted fields are not updated."""

    info_blob_upsert = InfoBlobUpdate(
        id=id,
        **info_blob.metadata.model_dump(),
        user_id=current_user.id,
    )

    service = container.info_blob_service()
    updated_blob = await service.update_info_blob(info_blob_upsert)

    return to_info_blob_public(updated_blob)


@router.delete(
    "/{id}/",
    response_model=InfoBlobPublic,
    description="Deletes an info-blob by id. Returns the deleted object.",
    responses=responses.get_responses([403, 404]),
)
async def delete_info_blob(
    id: Annotated[UUID, Path()],
    container: ContainerDep,
):
    """Returns the deleted object."""
    service = container.info_blob_service()
    group_service = container.group_service()
    info_blob_deleted = await service.delete(id)
    assert info_blob_deleted is not None

    # Update group size
    if info_blob_deleted.group_id is not None:
        await group_service.update_group_size(info_blob_deleted.group_id)

    return to_info_blob_public(info_blob_deleted)


@router.get(
    "/spaces/{space_id}/info-blobs/",
    response_model=PaginatedResponse[InfoBlobPublicNoText],
    description="Returns the info-blobs of a space (without text).",
    responses=responses.get_responses([]),
)
async def get_space_info_blobs(
    space_id: Annotated[UUID, Path()],
    container: ContainerDep,
):
    service = container.info_blob_service()
    blobs = await service.get_for_space(space_id)
    return protocol.to_paginated_response(
        [to_info_blob_public_no_text(b) for b in blobs]
    )

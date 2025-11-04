from fastapi import APIRouter, Depends, Path

from intric.authentication.auth_dependencies import get_current_active_user
from intric.info_blobs.info_blob import (
    InfoBlobPublic,
    InfoBlobPublicNoText,
    InfoBlobUpdate,
    InfoBlobUpdatePublic,
)
from intric.info_blobs.info_blob_protocol import (
    to_info_blob_public,
    to_info_blob_public_no_text,
)
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.users.user import UserInDB

logger = get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[InfoBlobPublicNoText],
)
async def get_info_blob_ids(
    container: Container = Depends(get_container(with_user=True)),
):
    """Returns a list of info-blobs.

    Does not return the text of each info-blob, 'text' will be null.
    """
    service = container.info_blob_service()
    info_blobs_in_db = await service.get_by_user()

    info_blobs_public = [to_info_blob_public_no_text(blob) for blob in info_blobs_in_db]

    return protocol.to_paginated_response(info_blobs_public)


@router.get(
    "/{id}/",
    response_model=InfoBlobPublic,
    responses=responses.get_responses([404]),
)
async def get_info_blob(
    id: str = Path(...),
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.info_blob_service()

    info_blob_in_db = await service.get_by_id(id)

    return to_info_blob_public(info_blob_in_db)


@router.post(
    "/{id}/",
    response_model=InfoBlobPublic,
    responses=responses.get_responses([404]),
)
async def update_info_blob(
    id: str,
    info_blob: InfoBlobUpdatePublic,
    container: Container = Depends(get_container(with_user=True)),
    current_user: UserInDB = Depends(get_current_active_user),
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
    responses=responses.get_responses([404]),
)
async def delete_info_blob(
    id: str = Path(...),
    container: Container = Depends(get_container(with_user=True)),
):
    """Returns the deleted object."""
    service = container.info_blob_service()
    group_service = container.group_service()
    info_blob_deleted = await service.delete(id)

    # Update group size
    if info_blob_deleted.group_id is not None:
        await group_service.update_group_size(info_blob_deleted.group_id)

    return to_info_blob_public(info_blob_deleted)


@router.get(
    "/spaces/{space_id}/info-blobs/",
    response_model=PaginatedResponse[InfoBlobPublicNoText],
)
async def get_space_info_blobs(
    space_id: str = Path(...),
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.info_blob_service()
    blobs = await service.get_for_space(space_id)
    return protocol.to_paginated_response([to_info_blob_public_no_text(b) for b in blobs])
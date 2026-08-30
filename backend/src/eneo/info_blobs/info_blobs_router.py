import base64
import time
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import (
    get_current_active_user,
    get_scope_filter,
    require_user_identity,
)
from eneo.authentication.signed_urls import (
    generate_info_blob_original_download_token,
    verify_info_blob_original_download_token,
)
from eneo.files.file_models import (
    ContentDisposition,
    OriginalSignedURLRequest,
    SignedURLResponse,
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
from eneo.main.exceptions import AuthenticationException, UnauthorizedException
from eneo.main.logging import get_logger
from eneo.main.models import PaginatedResponse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.server.protocol.downloads import (
    ClosingStreamingResponse,
    content_disposition_header,
)
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
    "/{id}/original/signed-url/",
    response_model=SignedURLResponse,
    responses=responses.get_responses([403, 404]),
    summary="Generate a signed URL for an uploaded knowledge original",
    description=(
        "Checks knowledge read access and original availability, then returns a "
        "short-lived URL for the exact uploaded bytes."
    ),
)
async def generate_original_signed_url(
    id: UUID,
    request: Request,
    signed_url_req: OriginalSignedURLRequest,
    container: ContainerDep,
) -> SignedURLResponse:
    service = container.info_blob_service()
    blob = await service.ensure_original_available(id)
    user = container.user()
    expires_at = int(time.time()) + signed_url_req.expires_in
    token = generate_info_blob_original_download_token(
        info_blob_id=id,
        expires_at=expires_at,
        content_disposition=signed_url_req.content_disposition,
        tenant_id=user.tenant_id,
    )
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.INFO_BLOB_ORIGINAL_DOWNLOAD_LINK_CREATED,
        entity_type=EntityType.INFO_BLOB,
        entity_id=id,
        description="Created an original download link for knowledge",
        metadata=AuditMetadata.standard(
            actor=user,
            target=blob,
            extra={
                "content_disposition": signed_url_req.content_disposition.value,
                "expires_at": expires_at,
                "expires_in_seconds": signed_url_req.expires_in,
            },
        ),
    )
    download_url = request.url_for("download_original", id=str(id))
    return SignedURLResponse(
        url=f"{download_url}?{urlencode({'token': token})}",
        expires_at=expires_at,
    )


def _validate_original_claims(id: UUID, token: str) -> tuple[ContentDisposition, UUID]:
    payload = verify_info_blob_original_download_token(token)
    if payload is None:
        raise AuthenticationException("Invalid or expired token")
    if str(id) != payload.get("info_blob_id"):
        raise UnauthorizedException("Token not valid for this InfoBlob")
    try:
        return ContentDisposition(str(payload["content_disposition"])), UUID(
            str(payload["tenant_id"])
        )
    except (KeyError, ValueError):
        raise AuthenticationException("Invalid token claims") from None


@router.get(
    "/{id}/original/download/",
    response_class=Response,
    response_model=None,
    responses={
        200: {
            "description": "Exact uploaded bytes",
            "content": {"*/*": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Content-Disposition": {
                    "description": "Requested inline or attachment disposition",
                    "schema": {"type": "string"},
                },
                "Content-Length": {
                    "description": "Original size in bytes",
                    "schema": {"type": "integer"},
                },
                "Repr-Digest": {
                    "description": "SHA-256 digest of the original representation",
                    "schema": {"type": "string"},
                },
            },
        },
        **responses.get_responses([401, 403, 404, 409, 503]),
    },
    summary="Download an uploaded knowledge original",
    description=(
        "Streams the exact uploaded bytes using a short-lived, purpose-separated "
        "signed token."
    ),
)
async def download_original(
    id: UUID,
    token: Annotated[str, Query()],
    container: Annotated[Container, Depends(get_container(with_transaction=False))],
) -> ClosingStreamingResponse:
    disposition, tenant_id = _validate_original_claims(id, token)
    download = await container.info_blob_service(
        user=None
    ).get_original_download_no_auth(id, expected_tenant_id=tenant_id)
    headers = {
        "Content-Disposition": content_disposition_header(
            disposition.value, download.filename
        ),
        "Content-Length": str(download.content_length),
        "Repr-Digest": f"sha-256=:{base64.b64encode(download.sha256).decode('ascii')}:",
    }

    return ClosingStreamingResponse(
        download.chunks,
        close=download.aclose,
        media_type=download.media_type,
        headers=headers,
    )


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

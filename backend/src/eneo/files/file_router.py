import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.signed_urls import generate_signed_token, verify_signed_token
from eneo.files.file_models import (
    ContentDisposition,
    FilePublic,
    SignedURLRequest,
    SignedURLResponse,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    AuthenticationException,
    UnauthorizedException,
)
from eneo.main.models import PaginatedResponse
from eneo.object_content.content import InvalidContentRangeError
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.post(
    "/",
    response_model=FilePublic,
    responses=responses.get_responses([400, 403, 413, 415]),
    description="Upload a file; rejects unsupported media types and oversized files.",
)
async def upload_file(
    upload_file: UploadFile,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_for_creation: None = Depends(require_user_for_creation),
):
    service = container.file_service()
    current_user = container.user()

    # Upload file
    file = await service.save_file(upload_file)

    # Build extra context with file details
    extra = {
        "size_bytes": file.size,
        "mimetype": getattr(file, "mimetype", None),
        "file_type": file.file_type.value
        if hasattr(file, "file_type") and file.file_type
        else None,
    }

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.FILE_UPLOADED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description=f"Uploaded file '{file.name}' ({file.size} bytes)",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=file,
            extra=extra,
        ),
    )

    return file


@router.get(
    "/",
    response_model=PaginatedResponse[FilePublic],
    status_code=200,
    responses=responses.get_responses([]),
    description="List the current user's uploaded files.",
)
async def get_files(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.file_service()
    files = await service.get_public_files()

    return protocol.to_paginated_response(files)


@router.get(
    "/{id}/",
    response_model=FilePublic,
    status_code=200,
    responses=responses.get_responses([403, 404]),
    description="Fetch a single file's metadata by id.",
)
async def get_file(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.file_service()
    return await service.get_public_file_by_id(file_id=id)


@router.delete(
    "/{id}/",
    status_code=204,
    response_class=Response,
    description="Delete a file owned by the current user.",
    responses={
        204: {
            "description": "File deleted successfully. No response body is returned."
        },
        **responses.get_responses([403, 404]),
    },
)
async def delete_file(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.file_service()
    current_user = container.user()

    # Delete atomically by owner; the returned row is kept for audit metadata.
    file = await service.delete_file(id)

    # Build extra context capturing what was deleted
    extra = {
        "size_bytes": getattr(file, "size", None),
        "mimetype": getattr(file, "mimetype", None),
        "file_type": file.file_type.value
        if hasattr(file, "file_type") and file.file_type
        else None,
        "created_at": file.created_at.isoformat()
        if hasattr(file, "created_at") and file.created_at
        else None,
    }

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.FILE_DELETED,
        entity_type=EntityType.FILE,
        entity_id=id,
        description=f"Deleted file '{file.name}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=file,
            extra=extra,
        ),
    )


@router.post(
    "/{id}/signed-url/",
    response_model=SignedURLResponse,
    status_code=200,
    responses=responses.get_responses([403, 404]),
    summary="Generate a signed URL for file download",
    description="""
    Generates a signed URL that can be used to download a file without authentication.
    The URL will expire after the specified time period.

    This is useful for sharing files with third parties or for embedding in emails.
    """,
)
async def generate_signed_url(
    id: UUID,
    request: Request,
    signed_url_req: SignedURLRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    # Verify the file exists and the user has access to it
    service = container.file_service()
    await service.get_file_infos(file_ids=[id])

    # Calculate expiration time
    expires_at = int(time.time()) + signed_url_req.expires_in

    # Generate the signed token
    token = generate_signed_token(
        file_id=id,
        expires_at=expires_at,
        content_disposition=signed_url_req.content_disposition,
    )

    # Build the full URL
    # Get the base URL from the request
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/api/v1/files/{id}/download/?token={token}"

    return SignedURLResponse(url=url, expires_at=expires_at)


@router.get(
    "/{id}/download/",
    status_code=200,
    response_class=Response,
    response_model=None,
    summary="Download a file using a signed URL",
    description="""
    Allows downloading a file using a pre-signed URL token.
    No authentication is required, but the token must be valid and not expired.
    """,
    responses={
        200: {"description": "Successfully downloaded the entire file"},
        206: {
            "description": "Successfully downloaded a partial content (range request)"
        },
        400: {
            "description": "Bad request - Invalid token or range requests not supported for this file type"  # noqa
        },
        401: {"description": "Unauthorized - Token is invalid or has expired"},
        403: {"description": "Unauthorized - Not authorized to view this file"},
        404: {"description": "File content not found or file does not exist"},
        416: {"description": "Range not satisfiable"},
    },
)
async def download_file_signed(
    id: UUID,
    token: Annotated[str, Query(description="The signed token for file access")],
    container: Annotated[Container, Depends(get_container())],
    range: Annotated[str | None, Header()] = None,
):
    payload = verify_signed_token(token)
    if not payload:
        raise AuthenticationException("Invalid or expired token")

    # Verify the file ID in the token matches the requested file ID
    if str(id) != payload["file_id"]:
        raise UnauthorizedException("Token not valid for this file")

    # Get the content disposition from the token
    content_disposition = ContentDisposition(payload["content_disposition"])

    service = container.file_service(user=None)
    try:
        download = await service.get_download_no_auth(id, range_header=range)
    except InvalidContentRangeError:
        whole = await service.get_download_no_auth(id)
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{whole.content_length}"},
        )

    headers = {
        "Content-Disposition": (
            f'{content_disposition.value}; filename="{download.filename}"'
        ),
        "Accept-Ranges": "bytes",
        "Content-Length": str(download.content_length),
    }
    if download.content_range is not None:
        headers["Content-Range"] = download.content_range
    return StreamingResponse(
        download.chunks,
        status_code=206 if download.content_range is not None else 200,
        media_type=download.media_type,
        headers=headers,
    )

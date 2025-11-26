import io
import re
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from intric.authentication.signed_urls import generate_signed_token, verify_signed_token
from intric.files.file_models import (
    ContentDisposition,
    FilePublic,
    FileType,
    SignedURLRequest,
    SignedURLResponse,
)
from intric.main.container.container import Container
from intric.main.exceptions import (
    AuthenticationException,
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.post(
    "/", response_model=FilePublic, responses=responses.get_responses([415, 413])
)
async def upload_file(
    upload_file: UploadFile,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.file_service()
    current_user = container.user()

    # Upload file
    file = await service.save_file(upload_file)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.FILE_UPLOADED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description=f"Uploaded file '{file.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(file.id),
                "filename": file.name,
                "size": file.size,
            },
        },
    )

    return file


@router.get(
    "/",
    response_model=PaginatedResponse[FilePublic],
    status_code=200,
)
async def get_files(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.file_service()
    files = await service.get_files()

    return protocol.to_paginated_response(
        [FilePublic(**item.model_dump()) for item in files]
    )


@router.get(
    "/{id}/",
    response_model=FilePublic,
    status_code=200,
)
async def get_file(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.file_service()
    return await service.get_file_by_id(file_id=id)


@router.delete("/{id}/", status_code=204)
async def delete_file(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.file_service()
    current_user = container.user()

    # Get file details BEFORE deletion
    file = await service.get_file(id)

    # Delete file
    await service.delete_file(id)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.FILE_DELETED,
        entity_type=EntityType.FILE,
        entity_id=id,
        description=f"Deleted file '{file.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(file.id),
                "filename": file.name,
            },
        },
    )


@router.post(
    "/{id}/signed-url/",
    response_model=SignedURLResponse,
    status_code=200,
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
    container: Container = Depends(get_container(with_user=True)),
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
    token: str = Query(..., description="The signed token for file access"),
    range: str = Header(None),
    container: Container = Depends(get_container()),
):
    payload = verify_signed_token(token)
    if not payload:
        raise AuthenticationException("Invalid or expired token")

    # Verify the file ID in the token matches the requested file ID
    if str(id) != payload["file_id"]:
        raise UnauthorizedException("Token not valid for this file")

    # Get the content disposition from the token
    content_disposition = ContentDisposition(payload["content_disposition"])

    # Get the file without auth
    file_repo = container.file_repo()
    file = await file_repo.get_by_id(file_id=payload["file_id"])

    if file.text is None and file.blob is None:
        raise NotFoundException(detail="File content not found")

    content_bytes = None
    if file.file_type == FileType.TEXT and file.text:
        content_bytes = file.text.encode("utf-8")
    elif file.blob:
        content_bytes = file.blob
    else:
        return Response(status_code=404, content="File content not found")

    total_size = len(content_bytes)
    headers = {
        "Content-Disposition": f"{content_disposition.value}; filename=\"{file.name}\"",
        "Accept-Ranges": "bytes",
    }

    # Handle range request
    if range:
        # Only allow range requests for audio files
        if file.file_type != FileType.AUDIO:
            raise BadRequestException("Range is only allowed for audio files")

        try:
            range_match = re.match(r'bytes=(\d+)-(\d*)', range)
            if range_match:
                start = int(range_match.group(1))
                end = (
                    int(range_match.group(2))
                    if range_match.group(2)
                    else total_size - 1
                )

                # Validate range
                if start >= total_size or end >= total_size or start > end:
                    return Response(
                        status_code=416,  # Range Not Satisfiable
                        headers={"Content-Range": f"bytes */{total_size}"},
                    )

                # Create partial response
                content = io.BytesIO(content_bytes[start : end + 1])

                headers.update(
                    {
                        "Content-Range": f"bytes {start}-{end}/{total_size}",
                        "Content-Length": str(end - start + 1),
                    }
                )

                return StreamingResponse(
                    content,
                    status_code=206,  # Partial Content
                    media_type=file.mimetype,
                    headers=headers,
                )
        except Exception:
            # If range parsing fails, fall back to full content
            pass

    # Return full content if range is not specified or invalid
    headers["Content-Length"] = str(total_size)
    content = io.BytesIO(content_bytes)

    return StreamingResponse(content, media_type=file.mimetype, headers=headers)

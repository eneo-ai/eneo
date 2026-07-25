import base64
import time
import unicodedata
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.signed_urls import (
    generate_file_original_download_token,
    generate_signed_token,
    verify_file_original_download_token,
    verify_signed_token,
)
from eneo.files.file_models import (
    ContentDisposition,
    FileContentRangeError,
    FileDeletionPreview,
    FilePublic,
    OriginalSignedURLRequest,
    SignedURLRequest,
    SignedURLResponse,
)
from eneo.files.file_service import FileDownload
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    AuthenticationException,
    ErrorCodes,
    UnauthorizedException,
)
from eneo.main.models import GeneralError, PaginatedResponse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.post(
    "/",
    response_model=FilePublic,
    responses=responses.get_responses([400, 403, 413, 415, 503]),
    description="Upload a file; rejects unsupported media types and oversized files.",
)
async def upload_file(
    upload_file: UploadFile,
    container: Annotated[
        Container,
        Depends(
            get_container(
                with_user=True,
                with_transaction=False,
                with_upload_admission=True,
            )
        ),
    ],
    _user_for_creation: None = Depends(require_user_for_creation),
):
    service = container.file_service()
    current_user = container.user()
    file = await service.save_file(upload_file)

    extra = {
        "size_bytes": file.size,
        "mimetype": getattr(file, "mimetype", None),
        "file_type": file.file_type.value
        if hasattr(file, "file_type") and file.file_type
        else None,
    }

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
        **responses.get_responses([403, 404, 409]),
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


@router.get(
    "/{id}/deletion-preview/",
    response_model=FileDeletionPreview,
    status_code=200,
    responses=responses.get_responses([403, 404]),
    description=(
        "Preview whether deleting this File would remove active chat, Assistant, "
        "App, or App-run attachments."
    ),
)
async def get_file_deletion_preview(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FileDeletionPreview:
    return await container.file_service().get_deletion_preview(id)


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


@router.post(
    "/{id}/original/signed-url/",
    response_model=SignedURLResponse,
    status_code=200,
    responses=responses.get_responses([403, 404]),
    summary="Generate a signed URL for the exact original file",
    description=(
        "Checks ownership and exact-original availability, then returns a "
        "short-lived URL that cannot be used for a processing download."
    ),
)
async def generate_original_signed_url(
    id: UUID,
    request: Request,
    signed_url_req: OriginalSignedURLRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> SignedURLResponse:
    service = container.file_service()
    file = await service.ensure_original_available(id)
    current_user = container.user()

    expires_at = int(time.time()) + signed_url_req.expires_in
    token = generate_file_original_download_token(
        file_id=id,
        expires_at=expires_at,
        content_disposition=signed_url_req.content_disposition,
    )
    await container.audit_service().log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.FILE_ORIGINAL_DOWNLOAD_LINK_CREATED,
        entity_type=EntityType.FILE,
        entity_id=id,
        description=f"Created an original download link for '{file.name}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=file,
            extra={
                "content_disposition": signed_url_req.content_disposition.value,
                "expires_at": expires_at,
                "expires_in_seconds": signed_url_req.expires_in,
            },
        ),
    )
    base_url = str(request.base_url).rstrip("/")
    return SignedURLResponse(
        url=f"{base_url}/api/v1/files/{id}/original/download/?token={token}",
        expires_at=expires_at,
    )


def _validate_download_claims(
    *,
    file_id: UUID,
    payload: dict[str, object] | None,
) -> ContentDisposition:
    if not payload:
        raise AuthenticationException("Invalid or expired token")
    if str(file_id) != payload["file_id"]:
        raise UnauthorizedException("Token not valid for this file")
    return ContentDisposition(str(payload["content_disposition"]))


def _content_disposition_header(
    disposition: ContentDisposition,
    filename: str,
) -> str:
    safe_ascii = bool(filename) and all(
        0x20 <= ord(character) <= 0x7E and character not in {'"', "\\"}
        for character in filename
    )
    if safe_ascii:
        return f'{disposition.value}; filename="{filename}"'

    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", errors="ignore")
        .decode("ascii")
    )
    fallback = "".join(
        character
        if 0x20 <= ord(character) <= 0x7E and character not in {'"', "\\"}
        else "_"
        for character in ascii_name
    )
    fallback = fallback or "download"
    encoded = quote(filename, safe="", encoding="utf-8", errors="strict")
    return f"{disposition.value}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _download_response(
    download: FileDownload,
    *,
    content_disposition: ContentDisposition,
    include_repr_digest: bool = False,
) -> StreamingResponse:
    headers = {
        "Content-Disposition": _content_disposition_header(
            content_disposition,
            download.filename,
        ),
        "Content-Length": str(download.content_length),
    }
    if download.range_supported:
        headers["Accept-Ranges"] = "bytes"
    if include_repr_digest:
        digest = base64.b64encode(download.sha256).decode("ascii")
        headers["Repr-Digest"] = f"sha-256=:{digest}:"
    if download.content_range is not None:
        headers["Content-Range"] = download.content_range

    async def response_chunks():
        try:
            async for chunk in download.chunks:
                yield chunk
        finally:
            await download.aclose()

    return StreamingResponse(
        response_chunks(),
        status_code=206 if download.content_range is not None else 200,
        media_type=download.media_type,
        headers=headers,
    )


def _range_not_satisfiable_response(exc: FileContentRangeError) -> JSONResponse:
    return JSONResponse(
        status_code=416,
        headers={"Content-Range": f"bytes */{exc.total_size}"},
        content=GeneralError(
            message=str(exc),
            eneo_error_code=ErrorCodes.BAD_REQUEST,
        ).model_dump(exclude_none=True, mode="json"),
    )


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
    content_disposition = _validate_download_claims(
        file_id=id,
        payload=verify_signed_token(token),
    )

    service = container.file_service(user=None)
    try:
        download = await service.get_download_no_auth(id, range_header=range)
    except FileContentRangeError as exc:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{exc.total_size}"},
        )
    return _download_response(
        download,
        content_disposition=content_disposition,
    )


@router.get(
    "/{id}/original/download/",
    status_code=200,
    response_class=Response,
    response_model=None,
    summary="Download the exact original file using a signed URL",
    responses={
        200: {"description": "Successfully downloaded the entire original file"},
        206: {"description": "Successfully downloaded part of the original audio"},
        **responses.get_responses([400, 401, 403, 404, 409, 416, 503]),
    },
)
async def download_original_file_signed(
    id: UUID,
    token: Annotated[str, Query(description="The signed original-download token")],
    container: Annotated[
        Container,
        Depends(get_container(with_transaction=False)),
    ],
    range: Annotated[str | None, Header()] = None,
) -> StreamingResponse | Response:
    content_disposition = _validate_download_claims(
        file_id=id,
        payload=verify_file_original_download_token(token),
    )
    service = container.file_service(user=None)
    try:
        download = await service.get_original_download_no_auth(
            id,
            range_header=range,
        )
    except FileContentRangeError as exc:
        return _range_not_satisfiable_response(exc)
    return _download_response(
        download,
        content_disposition=content_disposition,
        include_repr_digest=True,
    )

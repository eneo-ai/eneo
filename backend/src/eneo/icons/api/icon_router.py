from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, UploadFile

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.icons.api.icon_models import IconPublic
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.server.protocol.downloads import ClosingStreamingResponse

router = APIRouter()

_NonTransactionalContainer = Annotated[
    Container, Depends(get_container(with_transaction=False))
]
_ContainerWithUser = Annotated[
    Container, Depends(get_container(with_user=True, with_transaction=False))
]
_ContainerWithUploadAdmission = Annotated[
    Container,
    Depends(
        get_container(
            with_user=True,
            with_transaction=False,
            with_upload_admission=True,
        )
    ),
]


@router.get(
    "/{id}/",
    response_class=Response,
    response_model=None,
    summary="Get icon image",
    description="Returns icon as binary data. Public endpoint for img tags. Cached for 1 year.",
    responses={
        200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}},
        404: {"description": "Icon not found"},
        **responses.get_responses([503]),
    },
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Public icon content is used in shared and login views.",
)
async def get_icon(id: UUID, container: _NonTransactionalContainer) -> Response:
    icon_service = container.icon_service()
    download = await icon_service.open_icon(id)

    return ClosingStreamingResponse(
        download.chunks,
        close=download.aclose,
        media_type=download.media_type,
        headers={
            "Cache-Control": "public, max-age=31536000",
            "Content-Length": str(download.content_length),
        },
    )


@router.post(
    "/",
    response_model=IconPublic,
    responses=responses.get_responses([400, 413, 415, 503]),
    summary="Upload icon",
    description=(
        "Upload an icon image (PNG, JPEG, WebP) within the active deployment "
        "image limit. Returns the icon ID."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="IconService authorizes mutations for the caller and target icon.",
)
async def create_icon(
    file: UploadFile,
    container: _ContainerWithUploadAdmission,
) -> IconPublic:
    icon_service = container.icon_service()
    user = container.user()
    icon = await icon_service.create_icon(
        file,
        tenant_id=user.tenant_id,
        created_by_user_id=user.id,
    )
    return IconPublic.model_validate(icon)


@router.delete(
    "/{id}/",
    status_code=204,
    summary="Delete icon",
    description="Delete an icon by ID. Requires authentication and ownership.",
    responses={204: {"description": "Deleted"}, 404: {"description": "Not found"}},
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="IconService authorizes mutations for the caller and target icon.",
)
async def delete_icon(id: UUID, container: _ContainerWithUser) -> None:
    icon_service = container.icon_service()
    user = container.user()
    await icon_service.delete_icon(id, user.tenant_id)

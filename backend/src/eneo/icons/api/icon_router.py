from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, UploadFile
from fastapi.responses import StreamingResponse

from eneo.icons.api.icon_models import IconPublic
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

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
async def get_icon(id: UUID, container: _NonTransactionalContainer) -> Response:
    icon_service = container.icon_service()
    download = await icon_service.open_icon(id)

    async def response_chunks():
        try:
            async for chunk in download.chunks:
                yield chunk
        finally:
            await download.aclose()

    return StreamingResponse(
        response_chunks(),
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
async def delete_icon(id: UUID, container: _ContainerWithUser) -> None:
    icon_service = container.icon_service()
    user = container.user()
    await icon_service.delete_icon(id, user.tenant_id)

from uuid import UUID

from fastapi import APIRouter, Depends, Response, UploadFile

from intric.icons.api.icon_models import IconPublic
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.get(
    "/{id}/",
    response_class=Response,
    summary="Get icon image",
    description="Returns icon as binary data. Public endpoint for img tags. Cached for 1 year.",
    responses={
        200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}},
        404: {"description": "Icon not found"},
    },
)
async def get_icon(id: UUID, container: Container = Depends(get_container())):
    icon_service = container.icon_service()
    icon = await icon_service.get_icon(id)
    return Response(
        content=icon.blob,
        media_type=icon.mimetype,
        headers={"Cache-Control": "public, max-age=31536000", "Content-Length": str(icon.size)},
    )


@router.post(
    "/",
    response_model=IconPublic,
    responses=responses.get_responses([415, 413]),
    summary="Upload icon",
    description="Upload icon image (PNG, JPEG, WebP). Max 256 KB. Returns icon ID.",
)
async def create_icon(file: UploadFile, container: Container = Depends(get_container(with_user=True))):
    icon_service = container.icon_service()
    user = container.user()
    icon = await icon_service.create_icon(file, user.tenant_id)
    return IconPublic.model_validate(icon)


@router.delete(
    "/{id}/",
    status_code=204,
    summary="Delete icon",
    description="Delete an icon by ID. Requires authentication and ownership.",
    responses={204: {"description": "Deleted"}, 404: {"description": "Not found"}},
)
async def delete_icon(id: UUID, container: Container = Depends(get_container(with_user=True))):
    icon_service = container.icon_service()
    user = container.user()
    await icon_service.delete_icon(id, user.tenant_id)

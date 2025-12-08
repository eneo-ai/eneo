# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from uuid import UUID

from fastapi import APIRouter, Depends

from intric.image_models.presentation.image_model_models import (
    GeneratedImagePublic,
    IconGenerationRequest,
    IconGenerationResponse,
    ImageGenerationRequest,
    ImageModelPublic,
    ImageModelUpdate,
    ImageVariant,
    PromptPreviewRequest,
    PromptPreviewResponse,
)
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[ImageModelPublic],
)
async def get_image_models(
    container: Container = Depends(get_container(with_user=True)),
):
    """Get all image generation models with tenant-specific settings."""
    service = container.image_model_crud_service()
    models = await service.get_image_models()

    return PaginatedResponse(
        items=[ImageModelPublic.from_domain(model) for model in models]
    )


@router.post(
    "/{id}/",
    response_model=ImageModelPublic,
    responses=responses.get_responses([404]),
)
async def update_image_model(
    id: UUID,
    update_flags: ImageModelUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """Update tenant-specific settings for an image model (admin only)."""
    service = container.image_model_crud_service()

    image_model = await service.update_image_model(
        model_id=id,
        is_org_enabled=update_flags.is_org_enabled,
        is_org_default=update_flags.is_org_default,
        security_classification=update_flags.security_classification,
    )

    return ImageModelPublic.from_domain(image_model)


@router.post(
    "/generate",
    response_model=list[GeneratedImagePublic],
    responses=responses.get_responses([400, 401, 503]),
)
async def generate_images(
    request: ImageGenerationRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Generate images from a text prompt.

    Returns generated images with base64-encoded blob data.
    """
    service = container.image_generation_service()
    user = container.user()

    images = await service.generate_images(
        prompt=request.prompt,
        model_id=request.model_id,
        n=request.n,
        size=request.size,
        quality=request.quality,
        user_id=user.id,
        save_to_db=True,
    )

    return [GeneratedImagePublic.from_domain(image) for image in images]


@router.post(
    "/generate-icon-variants",
    response_model=IconGenerationResponse,
    responses=responses.get_responses([400, 401, 503]),
)
async def generate_icon_variants(
    request: IconGenerationRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Generate icon variants for a resource (assistant, app, space).

    Returns the generated prompt and base64-encoded image variants.
    The variants are not persisted - only the final selected icon will be saved.
    """
    service = container.image_generation_service()
    user = container.user()

    result = await service.generate_icon_variants(
        resource_name=request.resource_name,
        resource_description=request.resource_description,
        system_prompt=request.system_prompt,
        custom_prompt=request.custom_prompt,
        num_variants=request.num_variants,
        model_id=request.model_id,
        user_id=user.id,
    )

    variants = [
        ImageVariant.from_result(i, variant) for i, variant in enumerate(result.variants)
    ]

    return IconGenerationResponse(
        generated_prompt=result.generated_prompt,
        variants=variants,
    )


@router.post(
    "/preview-prompt",
    response_model=PromptPreviewResponse,
)
async def preview_prompt(
    request: PromptPreviewRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Generate a preview of the auto-generated prompt without generating images.

    Useful for showing users what prompt will be used before generation.
    """
    service = container.image_generation_service()

    prompt = service.generate_prompt_preview(
        resource_name=request.resource_name,
        resource_description=request.resource_description,
        system_prompt=request.system_prompt,
    )

    return PromptPreviewResponse(prompt=prompt)

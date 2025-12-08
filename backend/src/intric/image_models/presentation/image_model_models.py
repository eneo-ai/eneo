# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

import base64
from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.image_models.domain.image_model import ImageModel
from intric.image_models.infrastructure.adapters.litellm_image_adapter import (
    ImageGenerationResult,
)
from intric.main.models import NOT_PROVIDED, ModelId, NotProvided
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)


class ImageModelPublic(BaseModel):
    """Public representation of an image generation model."""

    id: UUID
    name: str
    nickname: str
    family: ModelFamily
    is_deprecated: bool
    stability: ModelStability
    hosting: ModelHostingLocation
    open_source: Optional[bool] = None
    description: Optional[str] = None
    hf_link: Optional[str] = None
    org: Optional[ModelOrg] = None
    can_access: bool = False
    is_locked: bool = True
    lock_reason: Optional[str] = None
    is_org_enabled: bool = False
    is_org_default: bool = False
    credential_provider: Optional[str] = None
    security_classification: Optional[SecurityClassificationPublic] = None

    # Image-specific fields
    max_resolution: Optional[str] = None
    supported_sizes: list[str] = []
    supported_qualities: list[str] = []
    max_images_per_request: int = 4

    @classmethod
    def from_domain(cls, model: ImageModel) -> "ImageModelPublic":
        return cls(
            id=model.id,
            name=model.name,
            nickname=model.nickname,
            family=model.family,
            is_deprecated=model.is_deprecated,
            stability=model.stability,
            hosting=model.hosting,
            open_source=model.open_source,
            description=model.description,
            hf_link=model.hf_link,
            org=model.org,
            can_access=model.can_access,
            is_locked=model.is_locked,
            lock_reason=model.lock_reason,
            is_org_enabled=model.is_org_enabled,
            is_org_default=model.is_org_default,
            credential_provider=model.get_credential_provider_name(),
            security_classification=SecurityClassificationPublic.from_domain(
                model.security_classification,
                return_none_if_not_enabled=False,
            ),
            max_resolution=model.max_resolution,
            supported_sizes=model.supported_sizes,
            supported_qualities=model.supported_qualities,
            max_images_per_request=model.max_images_per_request,
        )


class ImageModelUpdate(BaseModel):
    """Request model for updating image model settings."""

    is_org_enabled: Optional[bool] = None
    is_org_default: Optional[bool] = None
    security_classification: Union[ModelId, None, NotProvided] = NOT_PROVIDED


class ImageGenerationRequest(BaseModel):
    """Request model for generating images."""

    prompt: str = Field(..., min_length=1, max_length=4000)
    model_id: Optional[UUID] = None
    n: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024")
    quality: str = Field(default="standard")


class IconGenerationRequest(BaseModel):
    """Request model for generating icon variants."""

    resource_name: str = Field(..., min_length=1, max_length=200)
    resource_description: Optional[str] = Field(default=None, max_length=2000)
    system_prompt: Optional[str] = Field(default=None, max_length=10000)
    custom_prompt: Optional[str] = Field(default=None, max_length=4000)
    num_variants: int = Field(default=4, ge=1, le=4)
    model_id: Optional[UUID] = None


class PromptPreviewRequest(BaseModel):
    """Request model for generating a prompt preview."""

    resource_name: str = Field(..., min_length=1, max_length=200)
    resource_description: Optional[str] = Field(default=None, max_length=2000)
    system_prompt: Optional[str] = Field(default=None, max_length=10000)


class PromptPreviewResponse(BaseModel):
    """Response model for prompt preview."""

    prompt: str


class ImageVariant(BaseModel):
    """A single generated image variant."""

    index: int
    blob_base64: str
    mimetype: str
    revised_prompt: Optional[str] = None

    @classmethod
    def from_result(cls, index: int, result: ImageGenerationResult) -> "ImageVariant":
        return cls(
            index=index,
            blob_base64=base64.b64encode(result.blob).decode("utf-8"),
            mimetype=result.mimetype,
            revised_prompt=result.revised_prompt,
        )


class IconGenerationResponse(BaseModel):
    """Response model for icon variant generation."""

    generated_prompt: str
    variants: list[ImageVariant]


class GeneratedImagePublic(BaseModel):
    """Public representation of a generated image."""

    id: UUID
    created_at: datetime
    prompt: str
    revised_prompt: Optional[str] = None
    size: Optional[str] = None
    quality: Optional[str] = None
    mimetype: str
    file_size: int
    blob_base64: str

    @classmethod
    def from_domain(cls, image) -> "GeneratedImagePublic":
        return cls(
            id=image.id,
            created_at=image.created_at,
            prompt=image.prompt,
            revised_prompt=image.revised_prompt,
            size=image.size,
            quality=image.quality,
            mimetype=image.mimetype,
            file_size=image.file_size,
            blob_base64=base64.b64encode(image.blob).decode("utf-8"),
        )


class GeneratedImageSparse(BaseModel):
    """Sparse representation of a generated image (without blob)."""

    id: UUID
    created_at: datetime
    prompt: str
    revised_prompt: Optional[str] = None
    size: Optional[str] = None
    quality: Optional[str] = None
    mimetype: str
    file_size: int

    @classmethod
    def from_domain(cls, image) -> "GeneratedImageSparse":
        return cls(
            id=image.id,
            created_at=image.created_at,
            prompt=image.prompt,
            revised_prompt=image.revised_prompt,
            size=image.size,
            quality=image.quality,
            mimetype=image.mimetype,
            file_size=image.file_size,
        )

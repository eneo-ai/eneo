# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from intric.image_models.infrastructure.adapters.litellm_image_adapter import (
    ImageGenerationResult,
    LiteLLMImageAdapter,
)
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.main.logging import get_logger
from intric.settings.credential_resolver import CredentialResolver

if TYPE_CHECKING:
    from intric.image_models.domain.image_model import ImageModel
    from intric.image_models.domain.image_model_repo import ImageModelRepository
    from intric.image_models.infrastructure.generated_image_repo import (
        GeneratedImage,
        GeneratedImageRepository,
    )
    from intric.main.config import Settings
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB

logger = get_logger(__name__)


@dataclass
class IconGenerationResult:
    """Result from icon variant generation."""

    generated_prompt: str
    variants: list[ImageGenerationResult]


class ImageGenerationService:
    """
    General-purpose image generation service.

    This service handles:
    - Image generation using configured models
    - Icon variant generation for resources (assistants, apps, spaces)
    - Automatic prompt generation from resource metadata
    """

    def __init__(
        self,
        tenant: Optional["TenantInDB"],
        settings: "Settings",
        encryption_service: "EncryptionService",
        image_model_repo: "ImageModelRepository",
        generated_image_repo: "GeneratedImageRepository",
    ):
        self.tenant = tenant
        self.settings = settings
        self.encryption_service = encryption_service
        self.image_model_repo = image_model_repo
        self.generated_image_repo = generated_image_repo

    def _get_adapter(self, model: "ImageModel") -> LiteLLMImageAdapter:
        """Create a LiteLLM adapter for the given model with tenant credentials."""
        credential_resolver = None
        if self.tenant:
            credential_resolver = CredentialResolver(
                tenant=self.tenant,
                settings=self.settings,
                encryption_service=self.encryption_service,
            )
        return LiteLLMImageAdapter(model, credential_resolver)

    async def _get_model(self, model_id: Optional[UUID] = None) -> "ImageModel":
        """Get the specified model or the default model."""
        if model_id:
            model = await self.image_model_repo.one(model_id)
        else:
            # Get available models and find default
            models = [m for m in await self.image_model_repo.all() if m.can_access]
            model = next((m for m in models if m.is_org_default), models[0] if models else None)

        if not model:
            raise NotFoundException("No image generation model available")

        if not model.can_access:
            raise UnauthorizedException("You do not have access to this image model")

        return model

    async def generate_images(
        self,
        prompt: str,
        model_id: Optional[UUID] = None,
        n: int = 1,
        size: str = "1024x1024",
        quality: str = "standard",
        user_id: Optional[UUID] = None,
        save_to_db: bool = True,
    ) -> list["GeneratedImage"]:
        """
        Generate images from a prompt.

        Args:
            prompt: Text prompt for image generation
            model_id: Specific model to use (or use default)
            n: Number of images to generate (1-4)
            size: Image size
            quality: Image quality
            user_id: User requesting generation
            save_to_db: Whether to persist generated images

        Returns:
            List of GeneratedImage objects with blob data
        """
        model = await self._get_model(model_id)
        adapter = self._get_adapter(model)

        logger.info(
            f"Generating {n} images with model {model.name}",
            extra={
                "model_id": str(model.id),
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "user_id": str(user_id) if user_id else None,
            },
        )

        # Generate images
        results = await adapter.generate_images(
            prompt=prompt,
            n=n,
            size=size,
            quality=quality,
        )

        if not save_to_db:
            # Return results without persisting
            from intric.image_models.infrastructure.generated_image_repo import GeneratedImage
            from datetime import datetime
            from uuid import uuid4

            return [
                GeneratedImage(
                    id=uuid4(),
                    created_at=datetime.now(),
                    tenant_id=self.tenant.id if self.tenant else uuid4(),
                    user_id=user_id,
                    image_model_id=model.id,
                    prompt=prompt,
                    revised_prompt=result.revised_prompt,
                    size=size,
                    quality=quality,
                    blob=result.blob,
                    mimetype=result.mimetype,
                    file_size=len(result.blob),
                    metadata={"model_name": model.name},
                )
                for result in results
            ]

        # Save to database
        generated_images = []
        for result in results:
            image = await self.generated_image_repo.save(
                tenant_id=self.tenant.id,
                user_id=user_id,
                image_model_id=model.id,
                prompt=prompt,
                blob=result.blob,
                mimetype=result.mimetype,
                revised_prompt=result.revised_prompt,
                size=size,
                quality=quality,
                metadata={"model_name": model.name},
            )
            generated_images.append(image)

        logger.info(
            f"Generated {len(generated_images)} images successfully",
            extra={
                "model_id": str(model.id),
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            },
        )

        return generated_images

    async def generate_icon_variants(
        self,
        resource_name: str,
        resource_description: Optional[str] = None,
        system_prompt: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        num_variants: int = 4,
        model_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> IconGenerationResult:
        """
        Generate icon variants for a resource (assistant, app, space).

        If custom_prompt is provided, use it directly.
        Otherwise, auto-generate a prompt from resource metadata.

        Args:
            resource_name: Name of the resource
            resource_description: Optional description
            system_prompt: Optional system prompt (for assistants)
            custom_prompt: Optional custom prompt (overrides auto-generation)
            num_variants: Number of variants to generate (1-4)
            model_id: Specific model to use (or use default)
            user_id: User requesting generation

        Returns:
            IconGenerationResult with generated prompt and image variants
        """
        if custom_prompt:
            prompt = custom_prompt
        else:
            prompt = self._generate_icon_prompt(
                resource_name, resource_description, system_prompt
            )

        logger.info(
            f"Generating {num_variants} icon variants for '{resource_name}'",
            extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "user_id": str(user_id) if user_id else None,
                "has_custom_prompt": custom_prompt is not None,
            },
        )

        model = await self._get_model(model_id)
        adapter = self._get_adapter(model)

        # Generate at icon-appropriate size (512x512 is good for icons)
        results = await adapter.generate_images(
            prompt=prompt,
            n=min(num_variants, model.max_images_per_request),
            size="512x512" if "512x512" in model.supported_sizes else model.supported_sizes[0],
            quality="standard",
        )

        return IconGenerationResult(
            generated_prompt=prompt,
            variants=results,
        )

    def _generate_icon_prompt(
        self,
        name: str,
        description: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate an icon prompt from resource metadata.

        Creates a prompt optimized for generating professional app icons.
        """
        context_parts = [
            f"Create a professional, minimalist app icon for an AI assistant called '{name}'."
        ]

        if description:
            # Truncate description if too long
            desc = description[:300] if len(description) > 300 else description
            context_parts.append(f"The assistant is described as: {desc}")

        if system_prompt:
            # Extract key themes from system prompt (first 200 chars)
            sp = system_prompt[:200] if len(system_prompt) > 200 else system_prompt
            context_parts.append(f"Its purpose is: {sp}")

        # Add style guidelines
        context_parts.append(
            "Style requirements: "
            "Clean, modern, flat design suitable for a software application icon. "
            "Use simple geometric shapes and a limited color palette. "
            "No text, letters, or words. "
            "Professional and corporate-friendly appearance. "
            "The icon should be recognizable at small sizes."
        )

        return " ".join(context_parts)

    def generate_prompt_preview(
        self,
        resource_name: str,
        resource_description: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate a preview of the auto-generated prompt without generating images.

        Useful for showing users what prompt will be used before generation.
        """
        return self._generate_icon_prompt(resource_name, resource_description, system_prompt)

from typing import TYPE_CHECKING, Optional, Protocol
from uuid import UUID

from eneo.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from eneo.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobChunk
from eneo.main.config import SETTINGS, Settings
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession
    from eneo.settings.encryption_service import EncryptionService
    from eneo.tenants.tenant import TenantInDB

logger = get_logger(__name__)


class EmbeddingModelLike(Protocol):
    """Protocol defining the interface for embedding model objects.

    This allows both ORM EmbeddingModel and frozen EmbeddingModelSpec DTO
    to be used interchangeably via duck typing. The adapters only access
    these attributes, so any object providing them will work.
    """

    id: UUID
    name: str
    provider_id: UUID | None
    litellm_model_name: str | None
    family: str | None
    max_input: int | None
    max_batch_size: int | None
    dimensions: int | None
    open_source: bool


class CreateEmbeddingsService:
    def __init__(
        self,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
        session: Optional["AsyncSession"] = None,
    ) -> None:
        super().__init__()
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service
        self.session = session

    async def _get_adapter(self, model: EmbeddingModelLike) -> EmbeddingModelAdapter:
        """Get the appropriate adapter for the embedding model.

        All models must have a provider_id linking to a ModelProvider.
        Uses LiteLLMEmbeddingAdapter which routes through LiteLLM.

        Supports two paths for provider resolution:
        1. Pre-resolved: If model carries provider_type/provider_credentials
           (e.g. EmbeddingModelSpec from crawl bootstrap), skip DB lookup.
        2. DB lookup: Load provider from database using provider_id + session.

        Args:
            model: Either an EmbeddingModel ORM object or EmbeddingModelSpec DTO.
                   Both satisfy the EmbeddingModelLike protocol.
        """
        from eneo.model_providers.infrastructure.litellm_provider import (
            build_litellm_model_name,
            load_active_litellm_provider,
        )
        from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
            TenantModelCredentialResolver,
        )

        # All models must have provider_id
        if not hasattr(model, "provider_id") or not model.provider_id:
            raise ValueError(
                f"Model '{model.name}' is missing required provider_id. "
                "All models must be associated with a ModelProvider."
            )

        # Check if provider data is pre-resolved on the model (e.g. from crawl bootstrap)
        provider_type = getattr(model, "provider_type", None)
        provider_credentials = getattr(model, "provider_credentials", None)
        provider_config = getattr(model, "provider_config", None)

        if provider_type and provider_credentials is not None:
            # Pre-resolved path: no DB session needed
            if self.encryption_service is None:
                raise ValueError(
                    "CreateEmbeddingsService requires an encryption_service to resolve credentials."
                )
            credential_resolver = TenantModelCredentialResolver(
                provider_id=model.provider_id,
                provider_type=provider_type,
                credentials=provider_credentials,
                config=provider_config or {},
                encryption_service=self.encryption_service,
            )
            litellm_model_name = build_litellm_model_name(provider_type, model.name)
        else:
            # DB lookup path: requires active session
            if not self.session:
                logger.error(
                    "Model requires database session but none available",
                    extra={
                        "model_id": str(model.id) if hasattr(model, "id") else None,
                        "model_name": model.name,
                        "provider_id": str(model.provider_id),
                        "tenant_id": str(self.tenant.id) if self.tenant else None,
                    },
                )
                raise ValueError(
                    f"Model '{model.name}' requires database session to load provider credentials. "
                    "Please ensure the CreateEmbeddingsService is initialized with a database session."
                )

            if self.encryption_service is None:
                raise ValueError(
                    "CreateEmbeddingsService requires an encryption_service to resolve credentials."
                )
            if self.tenant is None:
                raise ValueError(
                    f"Model '{model.name}' requires tenant context to load its provider."
                )
            provider = await load_active_litellm_provider(
                session=self.session,
                provider_id=model.provider_id,
                tenant_id=self.tenant.id,
            )
            credential_resolver = provider.create_credential_resolver(
                self.encryption_service
            )
            litellm_model_name = build_litellm_model_name(
                provider.provider_type, model.name
            )
            provider_type = provider.provider_type

        logger.info(
            f"Using LiteLLMEmbeddingAdapter for model '{model.name}'",
            extra={
                "model_id": str(model.id) if hasattr(model, "id") else None,
                "model_name": model.name,
                "provider_id": str(model.provider_id),
                "provider_type": provider_type,
                "litellm_model_name": litellm_model_name,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            },
        )

        return LiteLLMEmbeddingAdapter(
            model,
            credential_resolver=credential_resolver,
            litellm_model_name=litellm_model_name,
        )

    async def get_embeddings(
        self,
        model: EmbeddingModelLike,
        chunks: list[InfoBlobChunk],
    ) -> ChunkEmbeddingList:
        """Generate embeddings for text chunks.

        Args:
            model: Either an EmbeddingModel ORM object or EmbeddingModelSpec DTO.
            chunks: List of InfoBlobChunk objects to embed.
        """
        adapter = await self._get_adapter(model)
        return await adapter.get_embeddings(chunks)

    async def get_embedding_for_query(
        self,
        model: EmbeddingModelLike,
        query: str,
    ) -> list[float]:
        """Generate embedding for a search query.

        Args:
            model: Either an EmbeddingModel ORM object or EmbeddingModelSpec DTO.
            query: Search query string to embed.
        """
        adapter = await self._get_adapter(model)
        return await adapter.get_embedding_for_query(query)

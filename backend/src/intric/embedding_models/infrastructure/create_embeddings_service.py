from typing import TYPE_CHECKING, Optional, Protocol
from uuid import UUID

from intric.ai_models.model_enums import ModelFamily
from intric.embedding_models.infrastructure.adapters.base import EmbeddingModelAdapter
from intric.embedding_models.infrastructure.adapters.e5_embeddings import E5Adapter
from intric.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from intric.embedding_models.infrastructure.adapters.openai_embeddings import (
    OpenAIEmbeddingAdapter,
)
from intric.files.chunk_embedding_list import ChunkEmbeddingList
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.config import SETTINGS, Settings
from intric.settings.credential_resolver import CredentialResolver

if TYPE_CHECKING:
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB


class EmbeddingModelLike(Protocol):
    """Protocol defining the interface for embedding model objects.

    This allows both ORM EmbeddingModel and frozen EmbeddingModelSpec DTO
    to be used interchangeably via duck typing. The adapters only access
    these attributes, so any object providing them will work.
    """
    id: UUID
    name: str
    litellm_model_name: str | None
    family: ModelFamily | None
    max_input: int
    max_batch_size: int | None
    dimensions: int | None
    open_source: bool


class CreateEmbeddingsService:
    def __init__(
        self,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
    ):
        self._adapters = {
            ModelFamily.OPEN_AI: OpenAIEmbeddingAdapter,
            ModelFamily.E5: E5Adapter,
        }
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service

    def _get_adapter(self, model: EmbeddingModelLike) -> EmbeddingModelAdapter:
        """Get the appropriate adapter for the embedding model.

        Args:
            model: Either an EmbeddingModel ORM object or EmbeddingModelSpec DTO.
                   Both satisfy the EmbeddingModelLike protocol.
        """
        # Create credential resolver with tenant context if tenant is available
        credential_resolver = None
        if self.tenant:
            credential_resolver = CredentialResolver(
                tenant=self.tenant,
                settings=self.config,
                encryption_service=self.encryption_service,
            )

        # Check for LiteLLM model first
        if model.litellm_model_name:
            return LiteLLMEmbeddingAdapter(
                model, credential_resolver=credential_resolver
            )

        # Fall back to existing family-based selection
        # Handle both enum (with .value) and string (from legacy code paths)
        family = model.family
        family_value = family.value if hasattr(family, "value") else family
        adapter_class = self._adapters.get(family_value)
        if not adapter_class:
            raise ValueError(f"No adapter found for hosting {family_value}")

        return adapter_class(model, credential_resolver=credential_resolver)

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
        adapter = self._get_adapter(model)
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
        adapter = self._get_adapter(model)
        return await adapter.get_embedding_for_query(query)

from typing import TYPE_CHECKING, Optional

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
    from intric.database.database import AsyncSession
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.settings.encryption_service import EncryptionService
    from intric.tenants.tenant import TenantInDB


class CreateEmbeddingsService:
    def __init__(
        self,
        tenant: Optional["TenantInDB"] = None,
        config: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
        session: Optional["AsyncSession"] = None,
    ):
        self._adapters = {
            ModelFamily.OPEN_AI: OpenAIEmbeddingAdapter,
            ModelFamily.E5: E5Adapter,
        }
        self.tenant = tenant
        self.config = config or SETTINGS
        self.encryption_service = encryption_service
        self.session = session

    async def _get_adapter(self, model: "EmbeddingModel") -> EmbeddingModelAdapter:
        # PRIORITY 1: Check for tenant model (has provider_id)
        # Tenant models use LiteLLMEmbeddingAdapter with auto-generated LiteLLM names
        if (hasattr(model, 'provider_id') and
            model.provider_id):

            # Check if session is available
            if not self.session:
                from intric.main.logging import get_logger
                logger = get_logger(__name__)
                logger.error(
                    "Tenant embedding model requires database session but none available",
                    extra={
                        "model_id": str(model.id) if hasattr(model, 'id') else None,
                        "model_name": model.name,
                        "provider_id": str(model.provider_id),
                        "tenant_id": str(self.tenant.id) if self.tenant else None,
                    }
                )
                raise ValueError(
                    f"Tenant model '{model.name}' requires database session to load provider credentials. "
                    "Please ensure the CreateEmbeddingsService is initialized with a database session."
                )

            # Load provider data from database
            import sqlalchemy as sa
            from intric.database.tables.model_providers_table import ModelProviders
            from intric.model_providers.infrastructure.tenant_model_credential_resolver import (
                TenantModelCredentialResolver,
            )

            stmt = sa.select(ModelProviders).where(ModelProviders.id == model.provider_id)
            result = await self.session.execute(stmt)
            provider_db = result.scalar_one_or_none()

            if provider_db is None:
                raise ValueError(f"Model provider {model.provider_id} not found")

            if not provider_db.is_active:
                raise ValueError(f"Model provider {model.provider_id} is not active")

            # Create tenant model credential resolver
            credential_resolver = TenantModelCredentialResolver(
                provider_id=provider_db.id,
                provider_type=provider_db.provider_type,
                credentials=provider_db.credentials,
                config=provider_db.config,
                encryption_service=self.encryption_service,
            )

            # Construct LiteLLM model name with provider prefix
            # This is what TenantModelAdapter does for completion models
            litellm_model_name = f"{provider_db.provider_type}/{model.name}"

            # Temporarily set litellm_model_name on the model for the adapter
            # (the model object is not persisted, so this is safe)
            model.litellm_model_name = litellm_model_name

            from intric.main.logging import get_logger
            logger = get_logger(__name__)
            logger.info(
                f"Using LiteLLMEmbeddingAdapter for tenant model '{model.name}'",
                extra={
                    "model_id": str(model.id) if hasattr(model, 'id') else None,
                    "model_name": model.name,
                    "provider_id": str(model.provider_id),
                    "provider_type": provider_db.provider_type,
                    "litellm_model_name": litellm_model_name,
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                }
            )

            # Use LiteLLMEmbeddingAdapter for all tenant models
            return LiteLLMEmbeddingAdapter(
                model, credential_resolver=credential_resolver
            )

        # PRIORITY 2: Global models
        # Create credential resolver for tenant's global credentials
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

        # Fall back to existing family-based selection for global models
        adapter_class = self._adapters.get(model.family.value)
        if not adapter_class:
            raise ValueError(f"No adapter found for hosting {model.family.value}")

        return adapter_class(model, credential_resolver=credential_resolver)

    async def get_embeddings(
        self,
        model: "EmbeddingModel",
        chunks: list[InfoBlobChunk],
    ) -> ChunkEmbeddingList:
        adapter = await self._get_adapter(model)
        return await adapter.get_embeddings(chunks)

    async def get_embedding_for_query(
        self,
        model: "EmbeddingModel",
        query: str,
    ) -> list[float]:
        adapter = await self._get_adapter(model)
        return await adapter.get_embedding_for_query(query)

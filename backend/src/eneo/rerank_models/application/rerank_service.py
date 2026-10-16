from typing import TYPE_CHECKING, Optional
from uuid import UUID

from eneo.main.config import get_settings
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    ProviderInactiveException,
    ProviderNotFoundException,
    ProviderRejectedRequestException,
)
from eneo.main.logging import get_logger
from eneo.model_providers.domain.model_route import resolve_model_route
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_provider_kwargs,
    load_active_litellm_provider,
)
from eneo.rerank_models.domain.rerank_spec import RerankSpec
from eneo.rerank_models.infrastructure.litellm_reranker import LiteLLMReranker
from eneo.tenants.provider_field_config import get_canonical_provider_type

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession
    from eneo.rerank_models.domain.rerank_model import RerankModel
    from eneo.rerank_models.domain.rerank_model_repo import RerankModelRepository
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from eneo.settings.encryption_service import EncryptionService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)

# Refusals already logged, so a busy installation logs once per model.
_refusals_logged: set[UUID] = set()


class RerankService:
    """Builds the ``RerankSpec`` a search may use; ``None`` keeps today's path."""

    def __init__(
        self,
        session: "AsyncSession",
        user: "UserInDB",
        rerank_model_repo: "RerankModelRepository",
        encryption_service: "EncryptionService",
    ) -> None:
        self.session = session
        self.user = user
        self.rerank_model_repo = rerank_model_repo
        self.encryption_service = encryption_service

    async def spec_for_default(
        self,
        query: str,
        security_classification: Optional["SecurityClassification"],
    ) -> RerankSpec | None:
        """The installation's default reranker as a spec, or ``None`` when there
        is none, it is disabled, or the space's classification is above its."""
        model = next(
            (
                m
                for m in await self.rerank_model_repo.all()
                if m.is_org_default and m.can_access
            ),
            None,
        )
        if model is None:
            return None
        if not self._allowed(model, security_classification):
            return None
        try:
            reranker = await self._reranker(model)
        except (
            ProviderNotFoundException,
            ProviderInactiveException,
            APIKeyNotConfiguredException,
            ProviderRejectedRequestException,
        ) as exc:
            # A disabled or misconfigured provider keeps its models in the
            # catalogue; the search must still answer, in vector order.
            logger.warning(
                "Rerank model %s is not usable (%s); searching without it",
                model.name,
                exc,
            )
            return None
        return RerankSpec(reranker=reranker, query=query, model_name=model.name)

    def _allowed(
        self,
        model: "RerankModel",
        security_classification: Optional["SecurityClassification"],
    ) -> bool:
        if not self.user.tenant.security_enabled or security_classification is None:
            return True
        if not security_classification.is_greater_than(model.security_classification):
            return True
        if model.id not in _refusals_logged:
            _refusals_logged.add(model.id)
            logger.warning(
                "Rerank model %s does not meet the space's security classification; "
                "searching without it",
                model.name,
            )
        return False

    async def _reranker(self, model: "RerankModel") -> LiteLLMReranker:
        assert model.provider_id is not None
        provider = await load_active_litellm_provider(
            session=self.session,
            provider_id=model.provider_id,
            tenant_id=self.user.tenant_id,
        )
        credential_resolver = provider.create_credential_resolver(
            self.encryption_service
        )
        return LiteLLMReranker(
            route=resolve_model_route(
                provider_type=get_canonical_provider_type(provider.provider_type),
                model_name=model.name,
            ),
            provider_kwargs=build_litellm_provider_kwargs(credential_resolver),
            outbound_headers=provider.create_outbound_headers(
                self.encryption_service, self.user
            ),
            timeout_seconds=get_settings().rerank_request_timeout_seconds,
        )

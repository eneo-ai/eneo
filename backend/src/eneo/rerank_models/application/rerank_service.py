"""Resolves the reranker a search may use and hands semantic search a spec.

A spec is built only when a reranker is registered, enabled, chosen as the
default, and allowed by the space's security classification. Otherwise the
answer is ``None`` and semantic search runs today's path; that is the opt-in
contract of #1035.
"""

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from eneo.main.config import get_settings
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    ProviderInactiveException,
    ProviderNotFoundException,
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

# Models already reported as refused by a classification, so a busy
# installation logs the refusal once per process rather than once per search.
_refusals_logged: set[UUID] = set()


class RerankService:
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
        """A spec for the installation's default reranker, or ``None``.

        ``security_classification`` is the space's. A reranker receives the
        question and the chunk texts, so a space may only use one that meets
        its classification, like every other model type.
        """
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
        ) as exc:
            # A disabled or misconfigured provider leaves its models in the
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

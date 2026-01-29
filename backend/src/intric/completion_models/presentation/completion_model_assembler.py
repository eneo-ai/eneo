from typing import TYPE_CHECKING

from intric.ai_models.completion_models.completion_model import CompletionModelSparse
from intric.completion_models.presentation.completion_model_models import (
    CompletionModelPublic,
)
from intric.security_classifications.presentation.security_classification_models import (
    SecurityClassificationPublic,
)
from intric.server import protocol

if TYPE_CHECKING:
    from intric.completion_models.domain import CompletionModel


class CompletionModelAssembler:
    def from_completion_model_to_model(self, completion_model: "CompletionModel"):
        return CompletionModelPublic(
            id=completion_model.id,
            created_at=completion_model.created_at,
            updated_at=completion_model.updated_at,
            name=completion_model.name,
            nickname=completion_model.nickname,
            token_limit=completion_model.token_limit,
            vision=completion_model.vision,
            family=completion_model.family,
            hosting=completion_model.hosting,
            org=completion_model.org,
            stability=completion_model.stability,
            open_source=completion_model.open_source,
            description=completion_model.description,
            nr_billion_parameters=completion_model.nr_billion_parameters,
            hf_link=completion_model.hf_link,
            is_deprecated=completion_model.is_deprecated,
            deployment_name=completion_model.deployment_name,
            is_org_enabled=completion_model.is_org_enabled,
            is_org_default=completion_model.is_org_default,
            can_access=completion_model.can_access,
            is_locked=completion_model.is_locked,
            lock_reason=completion_model.lock_reason,
            reasoning=completion_model.reasoning,
            supports_tool_calling=completion_model.supports_tool_calling,
            base_url=completion_model.base_url,
            security_classification=SecurityClassificationPublic.from_domain(
                completion_model.security_classification,
                return_none_if_not_enabled=False,
            ),
        )

    @staticmethod
    def from_completion_model_to_sparse(completion_model: "CompletionModel"):
        """
        Converts a domain CompletionModel to a CompletionModelSparse instance.
        CompletionModelSparse is used for lightweight representations where
        calculated properties and organizational settings are not needed.
        """
        return CompletionModelSparse(
            created_at=completion_model.created_at,
            updated_at=completion_model.updated_at,
            id=completion_model.id,
            name=completion_model.name,
            nickname=completion_model.nickname,
            family=completion_model.family,
            token_limit=completion_model.token_limit,
            is_deprecated=completion_model.is_deprecated,
            nr_billion_parameters=completion_model.nr_billion_parameters,
            hf_link=completion_model.hf_link,
            stability=completion_model.stability,
            hosting=completion_model.hosting,
            open_source=completion_model.open_source,
            description=completion_model.description,
            deployment_name=completion_model.deployment_name,
            org=completion_model.org,
            vision=completion_model.vision,
            reasoning=completion_model.reasoning,
            supports_tool_calling=completion_model.supports_tool_calling,
            base_url=completion_model.base_url,
        )

    def from_completion_models_to_models(self, completion_models: list["CompletionModel"]):
        completion_models_public = [
            self.from_completion_model_to_model(completion_model=completion_model)
            for completion_model in completion_models
        ]

        return protocol.to_paginated_response(completion_models_public)

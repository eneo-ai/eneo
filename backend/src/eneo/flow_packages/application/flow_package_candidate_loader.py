from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
)
from eneo.flow_packages.domain.flow_package_import_plan import (
    FlowPackageLocalCandidate,
    FlowPackageModelCandidate,
)
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageModelIdentity,
    FlowPackageModelKind,
)
from eneo.flows.flow_resource_bindings import LocalResourceKind

if TYPE_CHECKING:
    from eneo.collections.domain.collection import Collection
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )
    from eneo.spaces.space import Space
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from eneo.websites.domain.website import Website


def build_flow_package_import_planner_candidates(
    *,
    completion_models: Sequence[CompletionModel],
    transcription_models: Sequence[TranscriptionModel],
    collections: Sequence[Collection],
    websites: Sequence[Website],
    integration_knowledge: Sequence[IntegrationKnowledge],
) -> FlowPackageImportPlannerCandidates:
    return FlowPackageImportPlannerCandidates(
        models=[
            candidate
            for candidate in (
                [_completion_model_candidate(model) for model in completion_models]
                + [
                    _transcription_model_candidate(model)
                    for model in transcription_models
                ]
            )
            if candidate is not None
        ],
        knowledge=[
            candidate
            for candidate in (
                [_collection_candidate(collection) for collection in collections]
                + [_website_candidate(website) for website in websites]
                + [
                    _integration_knowledge_candidate(knowledge)
                    for knowledge in integration_knowledge
                ]
            )
            if candidate is not None
        ],
        template_assets=[],
    )


def build_flow_package_import_planner_candidates_for_space(
    space: Space,
) -> FlowPackageImportPlannerCandidates:
    return build_flow_package_import_planner_candidates(
        completion_models=space.completion_models,
        transcription_models=space.transcription_models,
        collections=space.collections,
        websites=space.websites,
        integration_knowledge=space.integration_knowledge_list,
    )


def _completion_model_candidate(
    model: CompletionModel,
) -> FlowPackageModelCandidate | None:
    local_id = _runtime_local_id(model.id)
    if local_id is None or not model.can_access:
        return None
    return FlowPackageModelCandidate(
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_id,
        label=_first_non_empty_text(model.nickname, model.name),
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
        identity=_completion_model_identity(model),
        security_level=_security_level(model.security_classification),
        max_context_tokens=model.max_input_tokens,
        supports_vision=model.vision,
        supports_reasoning=model.reasoning,
        supports_tool_calling=model.supports_tool_calling,
    )


def _transcription_model_candidate(
    model: TranscriptionModel,
) -> FlowPackageModelCandidate | None:
    local_id = _runtime_local_id(model.id)
    if local_id is None or not model.can_access:
        return None
    return FlowPackageModelCandidate(
        local_kind=LocalResourceKind.TRANSCRIPTION_MODEL,
        local_id=local_id,
        label=_first_non_empty_text(model.nickname, model.name),
        model_kind=FlowPackageModelKind.TRANSCRIPTION_MODEL,
        identity=_transcription_model_identity(model),
        security_level=_security_level(model.security_classification),
    )


def _completion_model_identity(model: CompletionModel) -> FlowPackageModelIdentity:
    return FlowPackageModelIdentity(
        provider=_provider_identity(
            provider_type=model.provider_type,
            credential_provider_name=model.get_credential_provider_name(),
            provider_name=model.provider_name,
        ),
        model=_first_non_empty_text(
            _bare_litellm_model_name(model.litellm_model_name),
            model.deployment_name,
            model.name,
        ),
    )


def _transcription_model_identity(
    model: TranscriptionModel,
) -> FlowPackageModelIdentity:
    return FlowPackageModelIdentity(
        provider=_provider_identity(
            provider_type=model.provider_type,
            credential_provider_name=model.get_credential_provider_name(),
            provider_name=model.provider_name,
        ),
        model=model.model_name,
    )


def _provider_identity(
    *,
    provider_type: str | None,
    credential_provider_name: str,
    provider_name: str | None,
) -> str:
    return _first_non_empty_text(
        provider_type,
        credential_provider_name,
        provider_name,
        "unknown",
    )


def _bare_litellm_model_name(litellm_model_name: str | None) -> str | None:
    normalized = _optional_text(litellm_model_name)
    if normalized is None:
        return None
    _provider, separator, model_name = normalized.partition("/")
    if not separator:
        return normalized
    return _optional_text(model_name)


def _collection_candidate(collection: Collection) -> FlowPackageLocalCandidate | None:
    return _local_candidate(
        local_kind=LocalResourceKind.COLLECTION,
        local_id=collection.id,
        label=collection.name,
    )


def _website_candidate(website: Website) -> FlowPackageLocalCandidate | None:
    return _local_candidate(
        local_kind=LocalResourceKind.WEBSITE,
        local_id=website.id,
        label=_first_non_empty_text(website.name, website.url),
    )


def _integration_knowledge_candidate(
    knowledge: IntegrationKnowledge,
) -> FlowPackageLocalCandidate | None:
    return _local_candidate(
        local_kind=LocalResourceKind.INTEGRATION_KNOWLEDGE,
        local_id=knowledge.id,
        label=_first_non_empty_text(knowledge.wrapper_name, knowledge.name),
    )


def _local_candidate(
    *,
    local_kind: LocalResourceKind,
    local_id: UUID | None,
    label: str,
) -> FlowPackageLocalCandidate | None:
    if local_id is None:
        return None
    return FlowPackageLocalCandidate(
        local_kind=local_kind,
        local_id=local_id,
        label=label,
    )


def _security_level(
    classification: SecurityClassification | None,
) -> int | None:
    if classification is None:
        return None
    return classification.security_level


def _runtime_local_id(local_id: object) -> UUID | None:
    if local_id is None or isinstance(local_id, UUID):
        return local_id
    raise TypeError("Local resource id must be a UUID or None.")


def _first_non_empty_text(*values: str | None) -> str:
    normalized = next(
        (normalized for value in values if (normalized := _optional_text(value))),
        None,
    )
    if normalized is None:
        raise ValueError("Expected at least one non-empty text value.")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None

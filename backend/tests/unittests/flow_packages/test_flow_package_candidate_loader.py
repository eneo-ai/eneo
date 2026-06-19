from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from uuid import UUID

import pytest

from intric.collections.domain.collection import Collection
from intric.completion_models.domain.completion_model import CompletionModel
from intric.flow_packages.application.flow_package_candidate_loader import (
    build_flow_package_import_planner_candidates,
    build_flow_package_import_planner_candidates_for_space,
)
from intric.flow_packages.application.flow_package_import_planner import (
    build_flow_package_import_plan,
)
from intric.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from intric.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from intric.flow_packages.domain.flow_package_import_plan import (
    FlowPackageImportPlanStatus,
    FlowPackageModelDependencyResolution,
)
from intric.flow_packages.domain.flow_package_manifest import FlowPackageManifest
from intric.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageModelRequirement,
    FlowPackageRequirementEntry,
    FlowPackageRequirementSet,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.spaces.space import Space
from intric.transcription_models.domain.transcription_model import TranscriptionModel
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval, Website

if TYPE_CHECKING:
    from intric.embedding_models.domain.embedding_model import EmbeddingModel
    from intric.integration.domain.entities.user_integration import UserIntegration
    from intric.users.user import UserInDB

_NOW = datetime(2026, 5, 18, tzinfo=timezone.utc)
_TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
_SPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
_USER_ID = UUID("00000000-0000-4000-8000-000000000003")


def test_completion_model_candidate_carries_matching_metadata() -> None:
    model = _completion_model(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        nickname="Structured",
        name="Fallback Name",
        litellm_model_name="azure/gpt-4o",
        provider_type=None,
        provider_name="Ignored Provider",
        security_level=0,
        max_input_tokens=128_000,
        vision=True,
        reasoning=True,
        supports_tool_calling=True,
    )

    candidates = build_flow_package_import_planner_candidates(
        completion_models=[model],
        transcription_models=[],
        collections=[],
        websites=[],
        integration_knowledge=[],
    )

    candidate = candidates.models[0]
    assert candidate.local_kind is LocalResourceKind.COMPLETION_MODEL
    assert candidate.model_kind is FlowPackageModelKind.COMPLETION_MODEL
    assert candidate.local_id == model.id
    assert candidate.label == "Structured"
    assert candidate.identity == FlowPackageModelIdentity(
        provider="azure",
        model="gpt-4o",
    )
    assert candidate.security_level == 0
    assert candidate.max_context_tokens == 128_000
    assert candidate.supports_vision is True
    assert candidate.supports_reasoning is True
    assert candidate.supports_tool_calling is True


def test_loader_omits_inaccessible_and_unsaved_models() -> None:
    saved_completion = _completion_model(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        name="Saved completion",
    )
    unsaved_completion = _completion_model(id=None, name="Unsaved completion")
    disabled_completion = _completion_model(
        id=UUID("33333333-3333-4333-8333-333333333333"),
        name="Disabled completion",
        is_org_enabled=False,
    )
    saved_transcription = _transcription_model(
        id=UUID("44444444-4444-4444-8444-444444444444"),
        name="whisper-1",
    )
    deprecated_transcription = _transcription_model(
        id=UUID("55555555-5555-4555-8555-555555555555"),
        name="deprecated-whisper",
        is_deprecated=True,
    )

    candidates = build_flow_package_import_planner_candidates(
        completion_models=[
            saved_completion,
            unsaved_completion,
            disabled_completion,
        ],
        transcription_models=[saved_transcription, deprecated_transcription],
        collections=[],
        websites=[],
        integration_knowledge=[],
    )

    assert [candidate.local_id for candidate in candidates.models] == [
        saved_completion.id,
        saved_transcription.id,
    ]


def test_transcription_model_candidate_uses_model_name_and_security() -> None:
    model = _transcription_model(
        id=UUID("66666666-6666-4666-8666-666666666666"),
        nickname="Swedish audio",
        name="whisper-large-v3",
        provider_type="OpenAI",
        security_level=3,
    )

    candidates = build_flow_package_import_planner_candidates(
        completion_models=[],
        transcription_models=[model],
        collections=[],
        websites=[],
        integration_knowledge=[],
    )

    candidate = candidates.models[0]
    assert candidate.local_kind is LocalResourceKind.TRANSCRIPTION_MODEL
    assert candidate.model_kind is FlowPackageModelKind.TRANSCRIPTION_MODEL
    assert candidate.identity == FlowPackageModelIdentity(
        provider="openai",
        model="whisper-large-v3",
    )
    assert candidate.security_level == 3


def test_knowledge_candidates_use_domain_labels_and_fallbacks() -> None:
    collection = _collection(
        id=UUID("77777777-7777-4777-8777-777777777777"),
        name="Policy library",
    )
    website = _website(
        id=UUID("88888888-8888-4888-8888-888888888888"),
        name=None,
        url="https://example.test/rules",
    )
    wrapped_integration = _integration_knowledge(
        id=UUID("99999999-9999-4999-8999-999999999999"),
        name="Raw SharePoint",
        wrapper_name="SharePoint policy folder",
    )
    named_integration = _integration_knowledge(
        id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        name="Plain SharePoint",
        wrapper_name=None,
    )

    candidates = build_flow_package_import_planner_candidates(
        completion_models=[],
        transcription_models=[],
        collections=[collection],
        websites=[website],
        integration_knowledge=[wrapped_integration, named_integration],
    )

    assert {
        (candidate.local_kind, candidate.label) for candidate in candidates.knowledge
    } == {
        (LocalResourceKind.WEBSITE, "https://example.test/rules"),
        (LocalResourceKind.INTEGRATION_KNOWLEDGE, "Plain SharePoint"),
        (LocalResourceKind.COLLECTION, "Policy library"),
        (LocalResourceKind.INTEGRATION_KNOWLEDGE, "SharePoint policy folder"),
    }


def test_loaded_candidates_feed_import_plan_exact_model_resolution() -> None:
    model = _completion_model(
        id=UUID("15151515-1515-4515-8515-151515151515"),
        name="Local GPT",
        litellm_model_name="azure/gpt-4o",
        provider_type=None,
    )

    candidates = build_flow_package_import_planner_candidates(
        completion_models=[model],
        transcription_models=[],
        collections=[],
        websites=[],
        integration_knowledge=[],
    )
    plan = build_flow_package_import_plan(
        _envelope(
            requirements=[
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                    matching_preferences=FlowPackageModelMatchingPreferences(
                        tested_with=[
                            FlowPackageModelIdentity(
                                provider="azure",
                                model="gpt-4o",
                            )
                        ]
                    ),
                )
            ]
        ),
        candidates=candidates,
    )

    resolution = plan.dependency_resolutions[0]
    assert isinstance(resolution, FlowPackageModelDependencyResolution)
    assert resolution.status is FlowPackageImportPlanStatus.RESOLVED_EXACT
    assert resolution.suggestions[0].local_id == model.id


@pytest.mark.parametrize(
    ("provider_type", "litellm_model_name", "family", "provider_name", "expected"),
    [
        ("OpenAI", "azure/gpt-4o", "claude", "Ignored", "openai"),
        (None, "azure/gpt-4o", "claude", "Ignored", "azure"),
        (None, None, "claude", "Ignored", "anthropic"),
        (None, None, None, "Local Provider", "local provider"),
        (None, None, None, None, "unknown"),
    ],
)
def test_provider_identity_uses_first_non_empty_fallback(
    provider_type: str | None,
    litellm_model_name: str | None,
    family: str | None,
    provider_name: str | None,
    expected: str,
) -> None:
    model = _completion_model(
        id=UUID("16161616-1616-4616-8616-161616161616"),
        name="Provider fallback model",
        provider_type=provider_type,
        litellm_model_name=litellm_model_name,
        family=family,
        provider_name=provider_name,
    )

    candidates = build_flow_package_import_planner_candidates(
        completion_models=[model],
        transcription_models=[],
        collections=[],
        websites=[],
        integration_knowledge=[],
    )

    assert candidates.models[0].identity.provider == expected


@pytest.mark.parametrize(
    ("litellm_model_name", "deployment_name", "model_name", "expected"),
    [
        ("azure/gpt-4o", "deployment", "base", "gpt-4o"),
        ("gpt-4o", "deployment", "base", "gpt-4o"),
        ("azure/", "deployment", "base", "deployment"),
        (None, "deployment", "base", "deployment"),
        (None, None, "base", "base"),
    ],
)
def test_completion_model_identity_uses_first_non_empty_model_name(
    litellm_model_name: str | None,
    deployment_name: str | None,
    model_name: str,
    expected: str,
) -> None:
    model = _completion_model(
        id=UUID("17171717-1717-4717-8717-171717171717"),
        name=model_name,
        litellm_model_name=litellm_model_name,
        deployment_name=deployment_name,
    )

    candidates = build_flow_package_import_planner_candidates(
        completion_models=[model],
        transcription_models=[],
        collections=[],
        websites=[],
        integration_knowledge=[],
    )

    assert candidates.models[0].identity.model == expected


def test_empty_resource_lists_return_empty_candidate_buckets() -> None:
    candidates = build_flow_package_import_planner_candidates(
        completion_models=[],
        transcription_models=[],
        collections=[],
        websites=[],
        integration_knowledge=[],
    )

    assert candidates.models == []
    assert candidates.knowledge == []
    assert candidates.template_assets == []


def test_space_adapter_keeps_template_assets_empty() -> None:
    candidates = build_flow_package_import_planner_candidates_for_space(
        _space(
            completion_models=[],
            transcription_models=[],
            collections=[],
            websites=[],
            integration_knowledge=[],
        )
    )

    assert candidates.template_assets == []


def test_space_adapter_matches_narrow_resource_list_loader() -> None:
    completion_model = _completion_model(
        id=UUID("18181818-1818-4818-8818-181818181818"),
        name="Completion",
    )
    transcription_model = _transcription_model(
        id=UUID("19191919-1919-4919-8919-191919191919"),
        name="whisper",
    )
    collection = _collection(
        id=UUID("20202020-2020-4020-8020-202020202020"),
        name="Collection",
    )
    website = _website(
        id=UUID("21212121-2121-4121-8121-212121212121"),
        name="Website",
        url="https://example.test",
    )
    integration = _integration_knowledge(
        id=UUID("23232323-2323-4323-8323-232323232323"),
        name="Integration",
    )
    space = _space(
        completion_models=[completion_model],
        transcription_models=[transcription_model],
        collections=[collection],
        websites=[website],
        integration_knowledge=[integration],
    )

    direct = build_flow_package_import_planner_candidates(
        completion_models=[completion_model],
        transcription_models=[transcription_model],
        collections=[collection],
        websites=[website],
        integration_knowledge=[integration],
    )
    via_space = build_flow_package_import_planner_candidates_for_space(space)

    assert via_space == direct


def _completion_model(
    *,
    id: UUID | None,
    name: str,
    nickname: str | None = None,
    litellm_model_name: str | None = "openai/gpt-4o",
    deployment_name: str | None = None,
    provider_type: str | None = None,
    provider_name: str | None = None,
    family: str | None = "openai",
    security_level: int | None = None,
    max_input_tokens: int = 32_000,
    vision: bool = False,
    reasoning: bool = False,
    supports_tool_calling: bool = False,
    is_deprecated: bool = False,
    is_org_enabled: bool = True,
) -> CompletionModel:
    model = CompletionModel(
        tenant=_user().tenant,
        id=cast(UUID, id),
        created_at=_NOW,
        updated_at=_NOW,
        nickname=cast(str, nickname),
        name=name,
        max_input_tokens=max_input_tokens,
        max_output_tokens=4096,
        vision=vision,
        family=family,
        hosting=None,
        org=None,
        stability=None,
        open_source=False,
        description=None,
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=is_deprecated,
        deployment_name=deployment_name,
        is_org_enabled=is_org_enabled,
        is_org_default=False,
        reasoning=reasoning,
        supports_tool_calling=supports_tool_calling,
        litellm_model_name=litellm_model_name,
        security_classification=_security_classification(security_level),
        tenant_id=_TENANT_ID,
        provider_name=provider_name,
        provider_type=provider_type,
    )
    if id is None:
        model.id = None
    return model


def _transcription_model(
    *,
    id: UUID | None,
    name: str,
    nickname: str | None = None,
    provider_type: str | None = None,
    provider_name: str | None = None,
    family: str | None = "openai",
    security_level: int | None = None,
    is_deprecated: bool = False,
    is_org_enabled: bool = True,
) -> TranscriptionModel:
    model = TranscriptionModel(
        tenant=_user().tenant,
        id=cast(UUID, id),
        created_at=_NOW,
        updated_at=_NOW,
        nickname=cast(str, nickname),
        name=name,
        family=family,
        hosting=None,
        org=None,
        stability=None,
        open_source=False,
        description=None,
        hf_link=None,
        base_url="https://example.test",
        is_deprecated=is_deprecated,
        is_org_enabled=is_org_enabled,
        is_org_default=False,
        security_classification=_security_classification(security_level),
        tenant_id=_TENANT_ID,
        provider_name=provider_name,
        provider_type=provider_type,
    )
    if id is None:
        model.id = None
    return model


def _collection(*, id: UUID | None, name: str) -> Collection:
    collection = Collection(
        id=id,
        created_at=_NOW,
        updated_at=_NOW,
        space_id=_SPACE_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        name=name,
        size=0,
        num_info_blobs=0,
        embedding_model=_embedding_model(),
    )
    if id is None:
        collection.id = None
    return collection


def _website(*, id: UUID | None, name: str | None, url: str) -> Website:
    website = Website(
        id=id,
        created_at=_NOW,
        updated_at=_NOW,
        space_id=_SPACE_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        url=url,
        name=name,
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
        embedding_model=_embedding_model(),
        size=0,
        latest_crawl=None,
    )
    if id is None:
        website.id = None
    return website


def _integration_knowledge(
    *,
    id: UUID | None,
    name: str,
    wrapper_name: str | None = None,
) -> IntegrationKnowledge:
    knowledge = IntegrationKnowledge(
        id=id,
        name=name,
        user_integration=cast("UserIntegration", SimpleNamespace()),
        embedding_model=_embedding_model(),
        tenant_id=_TENANT_ID,
        space_id=_SPACE_ID,
        wrapper_name=wrapper_name,
    )
    if id is None:
        knowledge.id = None
    return knowledge


def _space(
    *,
    completion_models: list[CompletionModel],
    transcription_models: list[TranscriptionModel],
    collections: list[Collection],
    websites: list[Website],
    integration_knowledge: list[IntegrationKnowledge],
) -> Space:
    return Space(
        id=_SPACE_ID,
        tenant_id=_TENANT_ID,
        tenant_space_id=None,
        user_id=None,
        name="Target space",
        description=None,
        embedding_models=[],
        completion_models=completion_models,
        transcription_models=transcription_models,
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=websites,
        collections=collections,
        integration_knowledge_list=integration_knowledge,
        members={},
    )


def _user() -> UserInDB:
    return cast(
        "UserInDB",
        SimpleNamespace(
            tenant=SimpleNamespace(
                api_credentials={
                    "": object(),
                    "anthropic": object(),
                    "azure": object(),
                    "openai": object(),
                }
            )
        ),
    )


def _embedding_model() -> EmbeddingModel:
    return cast("EmbeddingModel", SimpleNamespace())


def _security_classification(level: int | None) -> SecurityClassification | None:
    if level is None:
        return None
    return SecurityClassification(
        tenant_id=_TENANT_ID,
        name=f"Class {level}",
        security_level=level,
    )


def _envelope(
    *,
    requirements: list[FlowPackageRequirementEntry],
) -> FlowPackageEnvelope:
    spec = FlowDraftSpecCore(
        flow_name="Demo",
        steps=[
            StepSpec(
                plan_step_ref="extract",
                name="Extract",
                assistant_spec=AssistantSpec(
                    instructions="Extract facts.",
                    model_ref="model.structured",
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )
    return FlowPackageEnvelope(
        manifest=FlowPackageManifest(
            schema_version=1,
            package_id="se.demo.flow",
            package_version="1.0.0",
            name="Demo",
            content_checksum="0" * 64,
        ),
        draft=FlowPackageFlowDraft(schema_version=1, spec=spec),
        requirements=FlowPackageRequirementSet(
            schema_version=1,
            requirements=requirements,
        ),
        provenance=FlowPackageProvenance(
            schema_version=1,
            exported_at=_NOW,
        ),
        spec_hash="0" * 64,
        manifest_hash="0" * 64,
        requirements_hash="0" * 64,
        provenance_hash="0" * 64,
        content_checksum="0" * 64,
    )


def _slot_ref(kind: ResourceSlotKind, slot: str) -> ResourceSlotRef:
    return ResourceSlotRef(kind=kind, slot=slot, label=slot.replace("-", " ").title())

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from intric.flow_packages.application.flow_package_model_matching import (
    hard_model_candidate_rejection_reasons,
    resolve_model_requirement,
)
from intric.flow_packages.domain.flow_package_import_plan import (
    FlowPackageDependencyResolutionEntry,
    FlowPackageImportPlanStatus,
    FlowPackageModelCandidate,
    FlowPackageModelDependencyResolution,
    FlowPackageModelMatchIssue,
    FlowPackagePolicyStatus,
)
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageCompletionModelConstraints,
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageModelRequirement,
    FlowPackageRequirementDataSensitivity,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


def test_exact_model_identity_can_be_auto_selected_when_policy_is_allowed() -> None:
    requirement = _requirement(
        tested_with=[_identity("openai", "gpt-5.4-mini")],
    )
    candidate = _completion_model(
        "11111111-1111-4111-8111-111111111111",
        "Structured Mini",
        provider="openai",
        model="gpt-5.4-mini",
    )

    resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(candidate,),
    )

    assert resolution.status is FlowPackageImportPlanStatus.RESOLVED_EXACT
    assert resolution.install_blocks is False
    assert resolution.publish_blocks is False
    assert resolution.selection_required_for_install is True
    assert resolution.auto_select_allowed is True
    assert resolution.policy_status is FlowPackagePolicyStatus.ALLOWED
    assert resolution.suggestions == [candidate]
    assert resolution.selection_warnings == []
    assert resolution.eligible_candidate_count == 1
    assert resolution.total_candidate_count == 1


def test_publisher_suggested_model_requires_human_confirmation() -> None:
    requirement = _requirement(
        publisher_suggested=[_identity("openai", "gpt-5.4-mini")],
    )
    candidate = _completion_model(
        "22222222-2222-4222-8222-222222222222",
        "Structured Mini",
        provider="openai",
        model="gpt-5.4-mini",
    )

    resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(candidate,),
    )

    assert resolution.status is FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION
    assert resolution.install_blocks is False
    assert resolution.publish_blocks is True
    assert resolution.selection_required_for_install is True
    assert resolution.auto_select_allowed is False
    assert resolution.selection_warnings == []
    assert resolution.suggestions == [candidate]


def test_unknown_but_eligible_model_requires_confirmation_with_warning() -> None:
    requirement = _requirement(
        tested_with=[_identity("openai", "gpt-5.4")],
        publisher_suggested=[_identity("anthropic", "claude-opus-4-7")],
    )
    candidate = _completion_model(
        "33333333-3333-4333-8333-333333333333",
        "Local Model",
        provider="azure-openai",
        model="municipality-model",
    )

    resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(candidate,),
    )

    assert resolution.status is FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION
    assert resolution.install_blocks is False
    assert resolution.selection_required_for_install is True
    assert resolution.auto_select_allowed is False
    assert resolution.selection_warnings == [
        FlowPackageModelMatchIssue.MODEL_IDENTITY_NOT_PREFERRED
    ]


def test_data_sensitivity_prevents_exact_match_auto_selection() -> None:
    requirement = _requirement(
        tested_with=[_identity("openai", "gpt-5.4-mini")],
        data_sensitivity=FlowPackageRequirementDataSensitivity(
            handles_personal_data=True,
            publisher_classification_label="Kommun A klass 3",
        ),
    )
    candidate = _completion_model(
        "44444444-4444-4444-8444-444444444444",
        "Structured Mini",
        provider="openai",
        model="gpt-5.4-mini",
    )

    resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(candidate,),
    )

    assert resolution.status is FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION
    assert resolution.install_blocks is False
    assert resolution.publish_blocks is True
    assert resolution.selection_required_for_install is True
    assert resolution.auto_select_allowed is False
    assert resolution.policy_status is FlowPackagePolicyStatus.UNKNOWN


def test_optional_eligible_model_is_never_auto_selected() -> None:
    requirement = _requirement(
        required=False,
        publisher_suggested=[_identity("openai", "gpt-5.4-mini")],
    )
    candidate = _completion_model(
        "55555555-5555-4555-8555-555555555555",
        "Optional Model",
        provider="openai",
        model="gpt-5.4-mini",
    )

    resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(candidate,),
    )

    assert resolution.status is FlowPackageImportPlanStatus.SKIPPED_OPTIONAL
    assert resolution.install_blocks is False
    assert resolution.publish_blocks is False
    assert resolution.selection_required_for_install is False
    assert resolution.auto_select_allowed is False
    assert resolution.suggestions == [candidate]


def test_required_model_without_eligible_candidate_blocks_publish() -> None:
    requirement = _requirement()
    candidate = _completion_model(
        "66666666-6666-4666-8666-666666666666",
        "Small Model",
        max_context_tokens=16000,
    )

    resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(candidate,),
    )

    assert resolution.status is FlowPackageImportPlanStatus.UNRESOLVED_REQUIRED
    assert resolution.install_blocks is True
    assert resolution.publish_blocks is True
    assert resolution.selection_required_for_install is True
    assert resolution.auto_select_allowed is False
    assert resolution.suggestions == []
    assert resolution.selection_warnings == []
    assert resolution.eligible_candidate_count == 0
    assert resolution.rejected_candidates[0].reasons == [
        FlowPackageModelMatchIssue.MODEL_CONTEXT_TOO_SMALL
    ]


def test_completion_constraints_create_deterministic_rejection_reasons() -> None:
    requirement = _requirement(
        completion_constraints=FlowPackageCompletionModelConstraints(
            minimum_context_tokens=32000,
            requires_vision=True,
            requires_reasoning=True,
            requires_tool_calling=True,
        )
    )
    candidate = _completion_model(
        "77777777-7777-4777-8777-777777777777",
        "Small Model",
        max_context_tokens=16000,
        supports_vision=False,
        supports_reasoning=False,
        supports_tool_calling=False,
    )

    assert hard_model_candidate_rejection_reasons(
        requirement=requirement,
        candidate=candidate,
    ) == (
        FlowPackageModelMatchIssue.MODEL_CONTEXT_TOO_SMALL,
        FlowPackageModelMatchIssue.MODEL_REASONING_REQUIRED,
        FlowPackageModelMatchIssue.MODEL_TOOL_CALLING_REQUIRED,
        FlowPackageModelMatchIssue.MODEL_VISION_REQUIRED,
    )


def test_ranking_is_deterministic_for_equal_tested_candidates() -> None:
    requirement = _requirement(
        tested_with=[_identity("openai", "gpt-5.4-mini")],
    )
    first = _completion_model(
        "88888888-8888-4888-8888-888888888888",
        "Alpha",
        provider="openai",
        model="gpt-5.4-mini",
        max_context_tokens=32000,
    )
    second = _completion_model(
        "99999999-9999-4999-8999-999999999999",
        "Beta",
        provider="openai",
        model="gpt-5.4-mini",
        max_context_tokens=32000,
    )

    first_resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(second, first),
    )
    second_resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(first, second),
    )

    assert first_resolution.suggestions[0] == first
    assert first_resolution.model_dump(mode="json") == second_resolution.model_dump(
        mode="json"
    )


def test_multiple_requirements_keep_identity_preferences_isolated() -> None:
    first_requirement = _requirement(
        tested_with=[_identity("openai", "gpt-5.4-mini")],
    )
    second_requirement = _requirement(
        tested_with=[_identity("anthropic", "claude-opus-4-7")],
    )
    openai_candidate = _completion_model(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "OpenAI",
        provider="openai",
        model="gpt-5.4-mini",
    )
    anthropic_candidate = _completion_model(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "Claude",
        provider="anthropic",
        model="claude-opus-4-7",
    )

    first_resolution = resolve_model_requirement(
        requirement=first_requirement,
        candidates=(anthropic_candidate, openai_candidate),
    )
    second_resolution = resolve_model_requirement(
        requirement=second_requirement,
        candidates=(anthropic_candidate, openai_candidate),
    )

    assert first_resolution.suggestions[0] == openai_candidate
    assert second_resolution.suggestions[0] == anthropic_candidate


def test_transcription_and_completion_model_kinds_do_not_cross_match() -> None:
    transcription_requirement = _requirement(
        model_kind=FlowPackageModelKind.TRANSCRIPTION_MODEL,
        completion_constraints=None,
    )
    completion_requirement = _requirement(
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
    )
    completion_candidate = _completion_model(
        "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "Completion",
    )
    transcription_candidate = _transcription_model(
        "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        "Transcription",
    )

    transcription_resolution = resolve_model_requirement(
        requirement=transcription_requirement,
        candidates=(completion_candidate, transcription_candidate),
    )
    completion_resolution = resolve_model_requirement(
        requirement=completion_requirement,
        candidates=(completion_candidate, transcription_candidate),
    )

    assert transcription_resolution.suggestions == [transcription_candidate]
    assert (
        transcription_resolution.rejected_candidates[0].candidate
        == completion_candidate
    )
    assert transcription_resolution.rejected_candidates[0].reasons == [
        FlowPackageModelMatchIssue.MODEL_KIND_MISMATCH
    ]
    assert completion_resolution.suggestions == [completion_candidate]
    assert (
        completion_resolution.rejected_candidates[0].candidate
        == transcription_candidate
    )
    assert completion_resolution.rejected_candidates[0].reasons == [
        FlowPackageModelMatchIssue.MODEL_KIND_MISMATCH
    ]


def test_model_resolution_round_trip_preserves_model_specific_fields() -> None:
    requirement = _requirement(
        completion_constraints=FlowPackageCompletionModelConstraints(
            minimum_context_tokens=128000,
            requires_vision=True,
        )
    )
    eligible_candidate = _completion_model(
        "abababab-abab-4aba-8aba-abababababab",
        "Unknown but eligible",
        max_context_tokens=256000,
    )
    rejected_candidate = _completion_model(
        "bcbcbcbc-bcbc-4bcb-8bcb-bcbcbcbcbcbc",
        "Small",
        max_context_tokens=16000,
        supports_vision=False,
    )

    resolution = resolve_model_requirement(
        requirement=requirement,
        candidates=(eligible_candidate, rejected_candidate),
    )
    adapter = TypeAdapter(FlowPackageDependencyResolutionEntry)
    reparsed = adapter.validate_json(resolution.model_dump_json())

    assert isinstance(reparsed, FlowPackageModelDependencyResolution)
    assert reparsed.status is FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION
    assert reparsed.auto_select_allowed is False
    assert reparsed.eligible_candidate_count == 1
    assert reparsed.suggestions[0].max_context_tokens == 256000
    assert reparsed.selection_warnings == [
        FlowPackageModelMatchIssue.MODEL_IDENTITY_NOT_PREFERRED
    ]
    assert reparsed.rejected_candidates[0].candidate == rejected_candidate
    assert reparsed.rejected_candidates[0].reasons == [
        FlowPackageModelMatchIssue.MODEL_CONTEXT_TOO_SMALL,
        FlowPackageModelMatchIssue.MODEL_VISION_REQUIRED,
    ]


def test_model_resolution_rejects_invalid_auto_select_contract() -> None:
    with pytest.raises(ValidationError, match="auto-selection"):
        FlowPackageModelDependencyResolution(
            kind="model",
            slot_ref=_slot_ref(),
            required=True,
            status=FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION,
            install_blocks=False,
            publish_blocks=True,
            selection_required_for_install=True,
            auto_select_allowed=True,
            suggestions=[],
            total_candidate_count=0,
            model_kind=FlowPackageModelKind.COMPLETION_MODEL,
            matching_preferences=FlowPackageModelMatchingPreferences(),
            completion_constraints=None,
            eligible_candidate_count=0,
            policy_status=FlowPackagePolicyStatus.ALLOWED,
        )


def test_model_candidate_rejects_incompatible_local_kind() -> None:
    with pytest.raises(ValueError, match="completion_model package model"):
        FlowPackageModelCandidate(
            local_kind=LocalResourceKind.TRANSCRIPTION_MODEL,
            local_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
            label="Wrong",
            model_kind=FlowPackageModelKind.COMPLETION_MODEL,
            identity=_identity("openai", "gpt-5.4"),
        )


def _requirement(
    *,
    required: bool = True,
    model_kind: FlowPackageModelKind = FlowPackageModelKind.COMPLETION_MODEL,
    tested_with: list[FlowPackageModelIdentity] | None = None,
    publisher_suggested: list[FlowPackageModelIdentity] | None = None,
    completion_constraints: FlowPackageCompletionModelConstraints | None = (
        FlowPackageCompletionModelConstraints(minimum_context_tokens=32000)
    ),
    data_sensitivity: FlowPackageRequirementDataSensitivity | None = None,
) -> FlowPackageModelRequirement:
    return FlowPackageModelRequirement(
        slot_ref=_slot_ref(),
        required=required,
        data_sensitivity=data_sensitivity,
        model_kind=model_kind,
        matching_preferences=FlowPackageModelMatchingPreferences(
            tested_with=tested_with or [],
            publisher_suggested=publisher_suggested or [],
        ),
        completion_constraints=completion_constraints,
    )


def _completion_model(
    local_id: str,
    label: str,
    *,
    provider: str = "local",
    model: str = "completion",
    security_level: int | None = 3,
    max_context_tokens: int | None = 64000,
    supports_vision: bool = True,
    supports_reasoning: bool = True,
    supports_tool_calling: bool = True,
) -> FlowPackageModelCandidate:
    return FlowPackageModelCandidate(
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=UUID(local_id),
        label=label,
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
        identity=_identity(provider, model),
        security_level=security_level,
        max_context_tokens=max_context_tokens,
        supports_vision=supports_vision,
        supports_reasoning=supports_reasoning,
        supports_tool_calling=supports_tool_calling,
    )


def _transcription_model(
    local_id: str,
    label: str,
    *,
    provider: str = "local",
    model: str = "transcription",
    security_level: int | None = 3,
) -> FlowPackageModelCandidate:
    return FlowPackageModelCandidate(
        local_kind=LocalResourceKind.TRANSCRIPTION_MODEL,
        local_id=UUID(local_id),
        label=label,
        model_kind=FlowPackageModelKind.TRANSCRIPTION_MODEL,
        identity=_identity(provider, model),
        security_level=security_level,
    )


def _slot_ref() -> ResourceSlotRef:
    return ResourceSlotRef(
        kind=ResourceSlotKind.MODEL,
        slot="structured",
        label="Structured",
    )


def _identity(provider: str, model: str) -> FlowPackageModelIdentity:
    return FlowPackageModelIdentity(provider=provider, model=model)

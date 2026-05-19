from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from intric.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
    build_flow_package_import_plan,
)
from intric.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from intric.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from intric.flow_packages.domain.flow_package_import_plan import (
    MAX_IMPORT_PLAN_SUGGESTIONS,
    FlowPackageDependencyResolutionEntry,
    FlowPackageImportPlanStatus,
    FlowPackageLocalCandidate,
    FlowPackageMcpToolDependencyResolution,
    FlowPackageModelCandidate,
    FlowPackageModelDependencyResolution,
    FlowPackageModelMatchIssue,
)
from intric.flow_packages.domain.flow_package_manifest import FlowPackageManifest
from intric.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageKnowledgeRequirement,
    FlowPackageMcpToolRequirement,
    FlowPackageModelGuidance,
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageModelRequirement,
    FlowPackageRequirementEntry,
    FlowPackageRequirementKind,
    FlowPackageRequirementSet,
    FlowPackageTemplateAssetRequirement,
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


def test_planner_returns_unresolved_required_when_no_matching_model_exists() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured")
            )
        ]
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(),
    )

    assert len(plan.dependency_resolutions) == 1
    resolution = plan.dependency_resolutions[0]
    assert resolution.status is FlowPackageImportPlanStatus.UNRESOLVED_REQUIRED
    assert resolution.publish_blocks is True
    assert resolution.auto_select_allowed is False
    assert resolution.suggestions == []
    assert plan.can_publish_after_import is False


def test_planner_resolves_required_model_when_exact_candidate_exists() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                used_by_steps=["extract"],
                guidance=FlowPackageModelGuidance(
                    summary="Use a strong structured extraction model."
                ),
                matching_preferences=FlowPackageModelMatchingPreferences(
                    tested_with=[_identity("openai", "gpt-5.4-mini")]
                ),
            )
        ]
    )
    candidate = _model_candidate(
        local_id="11111111-1111-4111-8111-111111111111",
        label="Structured model",
        provider="openai",
        model="gpt-5.4-mini",
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(models=[candidate]),
    )

    resolution = plan.dependency_resolutions[0]
    assert resolution.status is FlowPackageImportPlanStatus.RESOLVED_EXACT
    assert resolution.publish_blocks is False
    assert resolution.auto_select_allowed is True
    assert resolution.required is True
    assert resolution.used_by_steps == ["extract"]
    assert isinstance(resolution, FlowPackageModelDependencyResolution)
    assert resolution.guidance is not None
    assert resolution.guidance.summary == "Use a strong structured extraction model."
    assert resolution.suggestions == [candidate]
    assert resolution.eligible_candidate_count == 1
    assert resolution.selection_warnings == []
    assert resolution.total_candidate_count == 1
    assert plan.can_publish_after_import is True


def test_planner_preserves_model_rejection_telemetry() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
            )
        ]
    )
    candidate = _model_candidate(
        local_id="12121212-1212-4212-8212-121212121212",
        label="Unknown model",
        provider="local",
        model="unknown",
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(models=[candidate]),
    )

    resolution = plan.dependency_resolutions[0]
    assert isinstance(resolution, FlowPackageModelDependencyResolution)
    assert resolution.status is FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION
    assert resolution.publish_blocks is True
    assert resolution.auto_select_allowed is False
    assert resolution.selection_warnings == [
        FlowPackageModelMatchIssue.MODEL_IDENTITY_NOT_PREFERRED
    ]


def test_planner_skips_optional_requirement_without_candidates() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy"),
                required=False,
            )
        ]
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(),
    )

    resolution = plan.dependency_resolutions[0]
    assert resolution.status is FlowPackageImportPlanStatus.SKIPPED_OPTIONAL
    assert resolution.publish_blocks is False
    assert resolution.auto_select_allowed is False
    assert resolution.suggestions == []
    assert plan.can_publish_after_import is True


def test_planner_skips_optional_requirement_with_suggestions() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy"),
                required=False,
            )
        ]
    )
    candidate = _candidate(
        local_kind=LocalResourceKind.COLLECTION,
        local_id="22222222-2222-4222-8222-222222222222",
        label="Local policy",
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(knowledge=[candidate]),
    )

    resolution = plan.dependency_resolutions[0]
    assert resolution.status is FlowPackageImportPlanStatus.SKIPPED_OPTIONAL
    assert resolution.publish_blocks is False
    assert resolution.auto_select_allowed is False
    assert resolution.suggestions == [candidate]
    assert resolution.total_candidate_count == 1
    assert plan.can_publish_after_import is True


def test_planner_marks_mcp_requirements_as_manual_setup_unsupported() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageMcpToolRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MCP_TOOL, "case-lookup"),
            )
        ]
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(),
    )

    resolution = plan.dependency_resolutions[0]
    assert resolution.status is FlowPackageImportPlanStatus.UNSUPPORTED
    assert resolution.publish_blocks is True
    assert resolution.auto_select_allowed is False
    assert resolution.suggestions == []


def test_planner_marks_template_assets_as_unsupported_until_installer_exists() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageTemplateAssetRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.TEMPLATE_ASSET, "report-docx"),
            )
        ]
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(),
    )

    resolution = plan.dependency_resolutions[0]
    assert resolution.status is FlowPackageImportPlanStatus.UNSUPPORTED
    assert resolution.publish_blocks is True
    assert resolution.auto_select_allowed is False
    assert resolution.suggestions == []


def test_import_plan_resolutions_are_discriminated_by_requirement_kind() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
            ),
            FlowPackageMcpToolRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MCP_TOOL, "lookup"),
                server_slot_ref=_slot_ref(ResourceSlotKind.MCP_SERVER, "case-system"),
            ),
        ]
    )

    plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(),
    )
    resolution_adapter = TypeAdapter(FlowPackageDependencyResolutionEntry)
    reparsed_resolutions = [
        resolution_adapter.validate_json(resolution.model_dump_json())
        for resolution in plan.dependency_resolutions
    ]

    assert isinstance(reparsed_resolutions[0], FlowPackageModelDependencyResolution)
    assert isinstance(
        reparsed_resolutions[1],
        FlowPackageMcpToolDependencyResolution,
    )
    assert reparsed_resolutions[1].status is FlowPackageImportPlanStatus.UNSUPPORTED
    assert reparsed_resolutions[1].server_slot_ref is not None
    assert reparsed_resolutions[1].server_slot_ref.ref == "mcp_server.case-system"


def test_planner_caps_and_orders_suggestions_deterministically() -> None:
    envelope = _envelope(
        requirements=[
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy"),
            )
        ]
    )
    candidates = [
        _candidate(
            local_kind=LocalResourceKind.COLLECTION,
            local_id=f"11111111-1111-4111-8111-{index:012d}",
            label=f"Policy {60 - index:02d}",
        )
        for index in range(60)
    ]

    first_plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(knowledge=candidates),
    )
    second_plan = build_flow_package_import_plan(
        envelope,
        candidates=FlowPackageImportPlannerCandidates(
            knowledge=list(reversed(candidates))
        ),
    )

    first_resolution = first_plan.dependency_resolutions[0]
    assert len(first_resolution.suggestions) == MAX_IMPORT_PLAN_SUGGESTIONS
    assert first_resolution.total_candidate_count == 60
    assert [candidate.label for candidate in first_resolution.suggestions] == [
        f"Policy {index:02d}" for index in range(1, 11)
    ]
    assert first_plan.model_dump(mode="json") == second_plan.model_dump(mode="json")


def test_planner_accepts_zero_requirements_as_publishable() -> None:
    plan = build_flow_package_import_plan(
        _envelope(requirements=[]),
        candidates=FlowPackageImportPlannerCandidates(),
    )

    assert plan.package_summary.name == "Demo"
    assert plan.package_kind == "flow"
    assert plan.payload_schema == "eneo.flow_package.v1"
    assert plan.package_summary.description == ""
    assert plan.package_summary.spec_hash == "0" * 64
    assert plan.package_summary.steps_count == 1
    assert plan.package_summary.requirements_count == 0
    assert plan.package_summary.requirements_by_kind == {}
    assert plan.dependency_resolutions == []
    assert plan.can_publish_after_import is True


def test_planner_summary_counts_requirements_by_kind() -> None:
    plan = build_flow_package_import_plan(
        _envelope(
            requirements=[
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                ),
                FlowPackageKnowledgeRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy"),
                ),
                FlowPackageKnowledgeRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "guidance"),
                    required=False,
                ),
            ]
        ),
        candidates=FlowPackageImportPlannerCandidates(),
    )

    assert plan.package_summary.requirements_count == 3
    assert plan.package_summary.requirements_by_kind == {
        FlowPackageRequirementKind.MODEL: 1,
        FlowPackageRequirementKind.KNOWLEDGE: 2,
    }


def test_candidate_bucket_rejects_wrong_non_model_local_resource_kind() -> None:
    with pytest.raises(
        ValidationError,
        match="cannot satisfy knowledge package candidates",
    ):
        FlowPackageImportPlannerCandidates(
            knowledge=[
                FlowPackageLocalCandidate(
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                    local_id=UUID("44444444-4444-4444-8444-444444444444"),
                    label="Wrong bucket",
                )
            ]
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
            exported_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        ),
        spec_hash="0" * 64,
        manifest_hash="0" * 64,
        requirements_hash="0" * 64,
        provenance_hash="0" * 64,
        content_checksum="0" * 64,
    )


def _slot_ref(kind: ResourceSlotKind, slot: str) -> ResourceSlotRef:
    return ResourceSlotRef(kind=kind, slot=slot, label=slot.replace("-", " ").title())


def _candidate(
    *,
    local_kind: LocalResourceKind,
    local_id: str,
    label: str,
) -> FlowPackageLocalCandidate:
    return FlowPackageLocalCandidate(
        local_kind=local_kind,
        local_id=UUID(local_id),
        label=label,
    )


def _model_candidate(
    *,
    local_id: str,
    label: str,
    provider: str = "local",
    model: str = "model",
    model_kind: FlowPackageModelKind = FlowPackageModelKind.COMPLETION_MODEL,
) -> FlowPackageModelCandidate:
    local_kind = (
        LocalResourceKind.COMPLETION_MODEL
        if model_kind is FlowPackageModelKind.COMPLETION_MODEL
        else LocalResourceKind.TRANSCRIPTION_MODEL
    )
    return FlowPackageModelCandidate(
        local_kind=local_kind,
        local_id=UUID(local_id),
        label=label,
        model_kind=model_kind,
        identity=_identity(provider, model),
    )


def _identity(provider: str, model: str) -> FlowPackageModelIdentity:
    return FlowPackageModelIdentity(provider=provider, model=model)

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from eneo.flow_packages.domain.flow_package_checksum import hash_json_value
from eneo.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from eneo.flow_packages.domain.flow_package_manifest import (
    APP_PACKAGE_PAYLOAD_SCHEMA,
    ASSISTANT_PACKAGE_PAYLOAD_SCHEMA,
    FLOW_PACKAGE_PAYLOAD_SCHEMA,
    EneoPackageKind,
    FlowPackageManifest,
    FlowPackageManifestMetadata,
    flow_package_filename,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageCompletionModelConstraints,
    FlowPackageKnowledgeGuidance,
    FlowPackageKnowledgeRequirement,
    FlowPackageModelGuidance,
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageModelRequirement,
    FlowPackageRequirementDataSensitivity,
    FlowPackageRequirementSet,
    FlowPackageTemplateAssetGuidance,
    FlowPackageTemplateAssetRequirement,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import ResourceSlotKind, ResourceSlotRef


def test_manifest_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        FlowPackageManifest(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            package_id="se.demo.flow",
            package_version="1.0.0",
            name="Demo",
            content_checksum="0" * 64,
            unexpected=True,
        )


def test_manifest_requires_kind_discriminator() -> None:
    with pytest.raises(ValidationError):
        FlowPackageManifest(
            schema_version=1,
            package_id="se.demo.flow",
            package_version="1.0.0",
            name="Demo",
            content_checksum="0" * 64,
        )


def test_manifest_rejects_legacy_package_kind_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FlowPackageManifest.model_validate(
            {
                "schema_version": 1,
                "package_id": "se.demo.flow",
                "package_version": "1.0.0",
                "name": "Demo",
                "package_kind": "flow",
                "payload_schema": FLOW_PACKAGE_PAYLOAD_SCHEMA,
                "content_checksum": "0" * 64,
            }
        )

    errors_by_location = {
        error["loc"]: error["type"] for error in exc_info.value.errors()
    }
    assert errors_by_location[("kind",)] == "missing"
    assert errors_by_location[("package_kind",)] == "extra_forbidden"


@pytest.mark.parametrize(
    "package_id",
    [
        "se.demo.flow",
        "se-demo-flow",
        "a12.flow-2",
    ],
)
def test_manifest_accepts_portable_package_ids(package_id: str) -> None:
    manifest = FlowPackageManifest(
        schema_version=1,
        kind=EneoPackageKind.FLOW,
        package_id=package_id,
        package_version="1.0.0",
        name="Demo",
        content_checksum="0" * 64,
    )

    assert manifest.package_id == package_id


@pytest.mark.parametrize(
    "package_id",
    [
        "AB.demo",
        ".se.demo",
        "se.demo.",
        "se..demo",
        "se_demo",
        "se demo",
        "a",
    ],
)
def test_manifest_rejects_ambiguous_package_ids(package_id: str) -> None:
    with pytest.raises(ValidationError):
        FlowPackageManifest(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            package_id=package_id,
            package_version="1.0.0",
            name="Demo",
            content_checksum="0" * 64,
        )


def test_manifest_hash_input_excludes_content_checksum() -> None:
    manifest = FlowPackageManifest(
        schema_version=1,
        kind=EneoPackageKind.FLOW,
        package_id="se.demo.flow",
        package_version="1.0.0",
        name="Demo",
        description="First",
        content_checksum="0" * 64,
    )
    same_metadata = manifest.model_copy(update={"content_checksum": "1" * 64})
    changed_metadata = manifest.model_copy(update={"description": "Second"})
    changed_kind = manifest.model_copy(
        update={
            "kind": EneoPackageKind.ASSISTANT,
            "payload_schema": ASSISTANT_PACKAGE_PAYLOAD_SCHEMA,
        }
    )

    assert "content_checksum" not in manifest.canonical_hash_input()
    assert hash_json_value(manifest.canonical_hash_input()) == hash_json_value(
        same_metadata.canonical_hash_input()
    )
    assert hash_json_value(manifest.canonical_hash_input()) != hash_json_value(
        changed_metadata.canonical_hash_input()
    )
    assert hash_json_value(manifest.canonical_hash_input()) != hash_json_value(
        changed_kind.canonical_hash_input()
    )


@pytest.mark.parametrize(
    ("kind", "payload_schema"),
    [
        (EneoPackageKind.FLOW, FLOW_PACKAGE_PAYLOAD_SCHEMA),
        (EneoPackageKind.ASSISTANT, ASSISTANT_PACKAGE_PAYLOAD_SCHEMA),
        (EneoPackageKind.APP, APP_PACKAGE_PAYLOAD_SCHEMA),
    ],
)
def test_manifest_validates_kind_payload_schema_pairs(
    kind: EneoPackageKind,
    payload_schema: str,
) -> None:
    manifest = FlowPackageManifestMetadata(
        schema_version=1,
        package_id="se.demo.flow",
        package_version="1.0.0",
        name="Demo",
        kind=kind,
        payload_schema=payload_schema,
    )

    assert manifest.kind is kind
    assert manifest.payload_schema == payload_schema


def test_manifest_rejects_payload_schema_for_wrong_kind() -> None:
    with pytest.raises(ValidationError, match="payload schema"):
        FlowPackageManifestMetadata(
            schema_version=1,
            package_id="se.demo.flow",
            package_version="1.0.0",
            name="Demo",
            kind=EneoPackageKind.ASSISTANT,
            payload_schema=FLOW_PACKAGE_PAYLOAD_SCHEMA,
        )


def test_portable_export_provenance_excludes_source_instance_identity() -> None:
    exported_at = datetime(2026, 5, 18, tzinfo=timezone.utc)

    provenance = FlowPackageProvenance.for_portable_export(exported_at=exported_at)

    assert provenance.exported_at == exported_at
    assert provenance.source_instance_id is None
    assert provenance.exported_by is None
    assert provenance.lineage == []


@pytest.mark.parametrize(
    ("package_version", "expected_fragment"),
    [
        ("../../etc/passwd", "etc_passwd"),
        ("Ångström 1.0", "Angstrom_1.0"),
        ("release candidate", "release_candidate"),
    ],
)
def test_package_filename_removes_unsafe_or_non_ascii_characters(
    package_version: str,
    expected_fragment: str,
) -> None:
    filename = flow_package_filename(
        FlowPackageManifestMetadata(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            package_id="se.demo.flow",
            package_version=package_version,
            name="Demo",
        )
    )

    assert expected_fragment in filename
    assert "/" not in filename
    assert "\\" not in filename
    assert ".." not in filename
    assert filename.endswith(".eneopkg")


def test_manifest_rejects_package_version_larger_than_persisted_contract() -> None:
    with pytest.raises(ValidationError):
        FlowPackageManifestMetadata(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            package_id="se.demo.flow",
            package_version="v" * 65,
            name="Demo",
        )


def test_package_filename_caps_longest_valid_identity() -> None:
    filename = flow_package_filename(
        FlowPackageManifestMetadata(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            package_id="a" * 128,
            package_version="v" * 64,
            name="Demo",
        )
    )

    assert len(filename) <= 160 + len(".eneopkg")
    assert filename.endswith(".eneopkg")


def test_flow_draft_wraps_authoring_spec() -> None:
    spec = _flow_spec()

    draft = FlowPackageFlowDraft(schema_version=1, spec=spec)

    assert draft.spec == spec


def test_model_requirement_rejects_wrong_slot_kind() -> None:
    with pytest.raises(ValidationError, match="must be a model slot"):
        FlowPackageModelRequirement(
            slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy"),
        )


def test_model_requirement_round_trips_typed_guidance_sensitivity_and_preferences() -> (
    None
):
    requirement = FlowPackageModelRequirement(
        slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
        guidance=FlowPackageModelGuidance(
            summary=" Use a strong model. ",
            quality_notes=" Handles long cases. ",
            minimum_expected_quality=" Must follow contracts. ",
        ),
        data_sensitivity=FlowPackageRequirementDataSensitivity(
            handles_personal_data=True,
            publisher_classification_label=" Sekretessklass 3 ",
            publisher_classification_description=" Sensitive source data. ",
            notes=" Confirm local policy. ",
        ),
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
        matching_preferences=FlowPackageModelMatchingPreferences(
            tested_with=[
                FlowPackageModelIdentity(provider=" OPENAI ", model=" gpt-5.4 ")
            ],
            publisher_suggested=[
                FlowPackageModelIdentity(provider="Azure", model="gpt-5.4")
            ],
        ),
        completion_constraints=FlowPackageCompletionModelConstraints(
            minimum_context_tokens=16000,
            requires_vision=True,
            requires_reasoning=True,
            requires_tool_calling=True,
        ),
    )

    reparsed = FlowPackageModelRequirement.model_validate_json(
        requirement.model_dump_json()
    )

    assert reparsed.guidance is not None
    assert reparsed.guidance.summary == "Use a strong model."
    assert reparsed.data_sensitivity is not None
    assert (
        reparsed.data_sensitivity.publisher_classification_label == "Sekretessklass 3"
    )
    assert reparsed.data_sensitivity.notes == "Confirm local policy."
    assert reparsed.matching_preferences.tested_with[0] == FlowPackageModelIdentity(
        provider="openai",
        model="gpt-5.4",
    )
    assert reparsed.completion_constraints is not None
    assert reparsed.completion_constraints.minimum_context_tokens == 16000


def test_transcription_model_requirement_rejects_completion_constraints() -> None:
    with pytest.raises(ValidationError, match="completion constraints"):
        FlowPackageModelRequirement(
            slot_ref=_slot_ref(ResourceSlotKind.MODEL, "transcription"),
            model_kind=FlowPackageModelKind.TRANSCRIPTION_MODEL,
            completion_constraints=FlowPackageCompletionModelConstraints(
                minimum_context_tokens=16000,
            ),
        )


def test_model_identity_normalization_and_equality_are_explicit() -> None:
    upper_provider = FlowPackageModelIdentity(provider="AZURE", model=" GPT-4 ")
    lower_provider = FlowPackageModelIdentity(provider="azure", model="GPT-4")
    lower_model = FlowPackageModelIdentity(provider="azure", model="gpt-4")

    assert upper_provider == lower_provider
    assert upper_provider != lower_model


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("", "gpt-4"),
        ("openai", ""),
        ("   ", "gpt-4"),
        ("openai", "   "),
    ],
)
def test_model_identity_rejects_empty_identity_parts(
    provider: str,
    model: str,
) -> None:
    with pytest.raises(ValidationError):
        FlowPackageModelIdentity(provider=provider, model=model)


def test_model_matching_preferences_cap_identity_lists() -> None:
    identities = [
        FlowPackageModelIdentity(provider="local", model=f"model-{index}")
        for index in range(51)
    ]

    with pytest.raises(ValidationError):
        FlowPackageModelMatchingPreferences(tested_with=identities)

    with pytest.raises(ValidationError):
        FlowPackageModelMatchingPreferences(publisher_suggested=identities)


def test_guidance_lists_normalize_text_entries() -> None:
    guidance = FlowPackageKnowledgeGuidance(
        summary=" Local policy ",
        recommended_sources=[" delegation order ", "", " handbook "],
        do_not_include=[" old routines ", " "],
        setup_notes=" Upload current local policy. ",
    )

    assert guidance.summary == "Local policy"
    assert guidance.recommended_sources == ["delegation order", "handbook"]
    assert guidance.do_not_include == ["old routines"]
    assert guidance.setup_notes == "Upload current local policy."


def test_data_sensitivity_normalizes_optional_text() -> None:
    sensitivity = FlowPackageRequirementDataSensitivity(
        publisher_classification_label=" Klass 3 ",
        publisher_classification_description=" Sensitive cases. ",
        notes=" Review local policy. ",
    )

    assert sensitivity.publisher_classification_label == "Klass 3"
    assert sensitivity.publisher_classification_description == "Sensitive cases."
    assert sensitivity.notes == "Review local policy."


def test_requirement_set_keeps_discriminated_entries() -> None:
    requirements = FlowPackageRequirementSet(
        schema_version=1,
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured")
            ),
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy")
            ),
        ],
    )

    assert [requirement.kind for requirement in requirements.requirements] == [
        "model",
        "knowledge",
    ]


def test_requirement_set_rejects_duplicate_slot_refs() -> None:
    with pytest.raises(ValidationError, match="Duplicate package requirement slot"):
        FlowPackageRequirementSet(
            schema_version=1,
            requirements=[
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured")
                ),
                FlowPackageModelRequirement(
                    slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured")
                ),
            ],
        )


def test_requirement_set_allows_same_slot_name_across_kinds() -> None:
    requirements = FlowPackageRequirementSet(
        schema_version=1,
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "policy")
            ),
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy")
            ),
        ],
    )

    assert [requirement.slot_ref.ref for requirement in requirements.requirements] == [
        "model.policy",
        "knowledge.policy",
    ]


def test_requirement_set_keeps_per_kind_typed_guidance() -> None:
    requirements = FlowPackageRequirementSet(
        schema_version=1,
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured"),
                guidance=FlowPackageModelGuidance(summary="Model setup"),
            ),
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy"),
                guidance=FlowPackageKnowledgeGuidance(
                    recommended_sources=["local handbook"]
                ),
            ),
            FlowPackageTemplateAssetRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.TEMPLATE_ASSET, "report"),
                guidance=FlowPackageTemplateAssetGuidance(
                    placeholder_notes="Contains case_summary."
                ),
            ),
        ],
    )

    assert isinstance(requirements.requirements[0], FlowPackageModelRequirement)
    assert isinstance(requirements.requirements[1], FlowPackageKnowledgeRequirement)
    assert isinstance(
        requirements.requirements[2],
        FlowPackageTemplateAssetRequirement,
    )


def test_provenance_structural_validation_normalizes_text() -> None:
    provenance = FlowPackageProvenance(
        schema_version=1,
        exported_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        source_instance_id=" source ",
        exported_by=" admin ",
        lineage=[" first ", "", "second"],
    )

    assert provenance.source_instance_id == "source"
    assert provenance.exported_by == "admin"
    assert provenance.lineage == ["first", "second"]


def _flow_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
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


def _slot_ref(kind: ResourceSlotKind, slot: str) -> ResourceSlotRef:
    return ResourceSlotRef(kind=kind, slot=slot, label=slot.replace("-", " ").title())

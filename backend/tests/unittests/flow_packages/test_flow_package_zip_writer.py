from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from io import BytesIO

import pytest

from intric.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from intric.flow_packages.domain.flow_package_envelope import (
    MANIFEST_PATH,
    PACKAGE_DOCUMENT_PATHS,
    FlowPackageEnvelope,
)
from intric.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from intric.flow_packages.domain.flow_package_manifest import (
    FlowPackageManifest,
    FlowPackageManifestMetadata,
)
from intric.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageKnowledgeRequirement,
    FlowPackageModelRequirement,
    FlowPackageRequirementSet,
)
from intric.flow_packages.infrastructure.flow_package_zip_reader import (
    read_flow_package,
)
from intric.flow_packages.infrastructure.flow_package_zip_writer import (
    write_flow_package,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from intric.flows.flow_resource_bindings import ResourceSlotKind, ResourceSlotRef


def test_write_flow_package_round_trips_through_reader_with_utf8_text() -> None:
    envelope = _envelope(flow_name="Anställningsbeslut", package_name="Mötesflöde")

    reparsed = read_flow_package(write_flow_package(envelope))

    assert reparsed == envelope
    assert reparsed.spec.flow_name == "Anställningsbeslut"
    assert reparsed.manifest.name == "Mötesflöde"


def test_write_flow_package_is_byte_stable_in_current_runtime() -> None:
    envelope = _envelope()

    first = write_flow_package(envelope)
    second = write_flow_package(envelope)

    assert first == second


def test_write_flow_package_pins_member_order_to_package_contract() -> None:
    envelope = _envelope()

    with zipfile.ZipFile(BytesIO(write_flow_package(envelope))) as package:
        assert package.namelist() == list(PACKAGE_DOCUMENT_PATHS)


def test_write_flow_package_manifest_bytes_match_envelope_checksum() -> None:
    envelope = _envelope()

    with zipfile.ZipFile(BytesIO(write_flow_package(envelope))) as package:
        manifest = FlowPackageManifest.model_validate_json(package.read(MANIFEST_PATH))

    assert manifest.content_checksum == envelope.content_checksum


def test_verify_from_subdocuments_rejects_checksum_mismatch() -> None:
    envelope = _envelope()
    mismatched_manifest = envelope.manifest.model_copy(
        update={"content_checksum": "f" * 64}
    )

    with pytest.raises(FlowPackageValidationError) as exc_info:
        FlowPackageEnvelope.verify_from_subdocuments(
            manifest=mismatched_manifest,
            draft=envelope.draft,
            requirements=envelope.requirements,
            provenance=envelope.provenance,
        )

    assert exc_info.value.code is FlowPackageErrorCode.CHECKSUM_MISMATCH


@pytest.mark.parametrize(
    ("mutation", "changed_hash"),
    [
        ("manifest", "manifest_hash"),
        ("spec", "spec_hash"),
        ("requirements", "requirements_hash"),
        ("provenance", "provenance_hash"),
    ],
)
def test_build_for_export_hashes_only_changed_subdocument(
    mutation: str,
    changed_hash: str,
) -> None:
    base = _envelope()
    changed = _mutated_envelope(base, mutation)

    hash_fields = (
        "manifest_hash",
        "spec_hash",
        "requirements_hash",
        "provenance_hash",
    )
    for field in hash_fields:
        if field == changed_hash:
            assert getattr(changed, field) != getattr(base, field)
        else:
            assert getattr(changed, field) == getattr(base, field)
    assert changed.content_checksum != base.content_checksum


def _mutated_envelope(
    base: FlowPackageEnvelope,
    mutation: str,
) -> FlowPackageEnvelope:
    match mutation:
        case "manifest":
            metadata = FlowPackageManifestMetadata(
                schema_version=1,
                package_id=base.manifest.package_id,
                package_version=base.manifest.package_version,
                name="Changed package",
                description=base.manifest.description,
            )
            return FlowPackageEnvelope.build_for_export(
                manifest_metadata=metadata,
                draft=base.draft,
                requirements=base.requirements,
                provenance=base.provenance,
            )
        case "spec":
            return FlowPackageEnvelope.build_for_export(
                manifest_metadata=_metadata_from_manifest(base.manifest),
                draft=FlowPackageFlowDraft(
                    schema_version=1,
                    spec=_flow_spec(flow_name="Changed flow"),
                ),
                requirements=base.requirements,
                provenance=base.provenance,
            )
        case "requirements":
            return FlowPackageEnvelope.build_for_export(
                manifest_metadata=_metadata_from_manifest(base.manifest),
                draft=base.draft,
                requirements=_requirements(include_knowledge=True),
                provenance=base.provenance,
            )
        case "provenance":
            return FlowPackageEnvelope.build_for_export(
                manifest_metadata=_metadata_from_manifest(base.manifest),
                draft=base.draft,
                requirements=base.requirements,
                provenance=FlowPackageProvenance(
                    schema_version=1,
                    exported_at=base.provenance.exported_at,
                    source_instance_id="changed-source",
                ),
            )
        case _:
            raise AssertionError(f"Unknown mutation {mutation}.")


def _metadata_from_manifest(
    manifest: FlowPackageManifest,
) -> FlowPackageManifestMetadata:
    return FlowPackageManifestMetadata(
        schema_version=manifest.schema_version,
        package_id=manifest.package_id,
        package_version=manifest.package_version,
        name=manifest.name,
        description=manifest.description,
    )


def _envelope(
    *,
    flow_name: str = "Demo Flow",
    package_name: str = "Demo Package",
) -> FlowPackageEnvelope:
    return FlowPackageEnvelope.build_for_export(
        manifest_metadata=FlowPackageManifestMetadata(
            schema_version=1,
            package_id="se.demo.flow",
            package_version="1.0.0",
            name=package_name,
            description="Reusable package",
        ),
        draft=FlowPackageFlowDraft(
            schema_version=1,
            spec=_flow_spec(flow_name=flow_name),
        ),
        requirements=_requirements(),
        provenance=FlowPackageProvenance(
            schema_version=1,
            exported_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            source_instance_id="source-instance",
            lineage=["first export"],
        ),
    )


def _flow_spec(flow_name: str) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name=flow_name,
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


def _requirements(*, include_knowledge: bool = False) -> FlowPackageRequirementSet:
    requirements = [
        FlowPackageModelRequirement(
            slot_ref=_slot_ref(ResourceSlotKind.MODEL, "structured")
        )
    ]
    if include_knowledge:
        requirements.append(
            FlowPackageKnowledgeRequirement(
                slot_ref=_slot_ref(ResourceSlotKind.KNOWLEDGE, "policy")
            )
        )
    return FlowPackageRequirementSet(schema_version=1, requirements=requirements)


def _slot_ref(kind: ResourceSlotKind, slot: str) -> ResourceSlotRef:
    return ResourceSlotRef(kind=kind, slot=slot, label=slot.replace("-", " ").title())

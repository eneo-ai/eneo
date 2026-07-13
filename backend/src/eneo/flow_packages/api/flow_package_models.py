from __future__ import annotations

from collections import Counter
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_import_plan import (
    FlowPackageImportTargetState,
)
from eneo.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportSelection,
)
from eneo.flow_packages.domain.flow_package_manifest import (
    EneoPackageKind,
    FlowPackageManifestMetadata,
    FlowPackageManifestMetadataFields,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageOmission
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageRequirementKind,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)

FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER = (
    "Eneo-Package-Omitted-Mcp-Assistant-Count"
)


class FlowPackageExportRequest(FlowPackageManifestMetadataFields):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "example": {
                "package_id": "se.demo.case-report",
                "package_version": "1.0.0",
                "name": "Case Report",
                "description": (
                    "Creates a structured case report from approved local material."
                ),
            }
        },
    )

    package_id: str = Field(
        description=(
            "Portable package identifier. Use a stable lowercase dot or hyphen "
            "separated name owned by the publisher, for example `se.demo.case-report`."
        )
    )
    package_version: str = Field(
        description="Publisher-assigned package version for the exported template."
    )
    name: str = Field(description="Human-readable package name shown on import.")
    description: str = Field(
        default="",
        description=(
            "Publisher-supplied package description shown before import planning."
        ),
    )

    def to_manifest_metadata(self) -> FlowPackageManifestMetadata:
        return FlowPackageManifestMetadata(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            package_id=self.package_id,
            package_version=self.package_version,
            name=self.name,
            description=self.description,
        )


class FlowPackageValidationPublic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "example": {
                "package_id": "se.demo.case-report",
                "package_version": "1.0.0",
                "kind": "flow",
                "payload_schema": "eneo.flow_package.v1",
                "name": "Case Report",
                "description": "Creates a structured case report from approved local material.",
                "content_checksum": "0" * 64,
                "spec_hash": "1" * 64,
                "steps_count": 4,
                "requirements_count": 3,
                "requirements_by_kind": {
                    "model": 1,
                    "knowledge": 1,
                },
                "omissions": [
                    {"kind": "mcp_attachment", "count": 2},
                ],
            }
        },
    )

    package_id: str = Field(
        description="Portable package identifier from the package manifest."
    )
    package_version: str = Field(
        description="Publisher-assigned package version from the package manifest."
    )
    kind: EneoPackageKind = Field(
        description="Generic package kind. Flow package import accepts only `flow` payloads."
    )
    payload_schema: str = Field(
        description="Payload schema identifier used by the package kind."
    )
    name: str = Field(description="Human-readable package name.")
    description: str = Field(description="Publisher-supplied package description.")
    content_checksum: str = Field(
        description="SHA-256 based checksum covering the portable package content."
    )
    spec_hash: str = Field(
        description="Hash of the portable flow draft spec inside the package."
    )
    steps_count: int = Field(
        ge=0,
        description="Number of flow draft steps included in the package.",
    )
    requirements_count: int = Field(
        ge=0,
        description="Number of dependency requirements declared by the package.",
    )
    requirements_by_kind: dict[FlowPackageRequirementKind, int] = Field(
        description="Requirement counts keyed by package requirement kind."
    )
    omissions: list[FlowPackageOmission] = Field(
        max_length=1,
        description=(
            "Source-local package dependencies deliberately omitted from the "
            "portable archive."
        ),
    )

    @classmethod
    def from_envelope(
        cls,
        envelope: FlowPackageEnvelope,
    ) -> "FlowPackageValidationPublic":
        requirement_counts = Counter(
            requirement.kind for requirement in envelope.requirements.requirements
        )
        return cls(
            package_id=envelope.manifest.package_id,
            package_version=envelope.manifest.package_version,
            kind=envelope.manifest.kind,
            payload_schema=envelope.manifest.payload_schema,
            name=envelope.manifest.name,
            description=envelope.manifest.description,
            content_checksum=envelope.content_checksum,
            spec_hash=envelope.spec_hash,
            steps_count=len(envelope.spec.steps),
            requirements_count=len(envelope.requirements.requirements),
            requirements_by_kind=dict(requirement_counts),
            omissions=list(envelope.provenance.omissions),
        )


class FlowPackageImportResourceSlotRefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ResourceSlotKind = Field(
        description="Portable dependency slot kind declared by the package."
    )
    slot: str = Field(description="Portable dependency slot identifier.")
    label: str = Field(description="Human-readable dependency slot label.")

    def to_domain(self) -> ResourceSlotRef:
        return ResourceSlotRef(kind=self.kind, slot=self.slot, label=self.label)


class FlowPackageImportResourceBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_ref: FlowPackageImportResourceSlotRefRequest = Field(
        description="Package dependency slot selected by the importer."
    )
    local_kind: LocalResourceKind = Field(
        description="Kind of the local target resource selected for the slot."
    )
    local_id: UUID = Field(
        description="Identifier of the local target resource selected for the slot."
    )

    def to_domain(self) -> LocalResourceBinding:
        return LocalResourceBinding(
            slot_ref=self.slot_ref.to_domain(),
            local_kind=self.local_kind,
            local_id=self.local_id,
        )

    @model_validator(mode="after")
    def validate_domain_binding(self) -> "FlowPackageImportResourceBindingRequest":
        # Keep slot/local-kind compatibility owned by LocalResourceBinding while
        # surfacing invalid import selections at the HTTP boundary.
        self.to_domain()
        return self


def _empty_import_resource_binding_requests() -> list[
    FlowPackageImportResourceBindingRequest
]:
    return []


class _FlowPackageImportTargetStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_transcription_required: bool = Field(strict=True)
    default_transcription_model_id: UUID | None

    def to_domain(self) -> FlowPackageImportTargetState:
        return FlowPackageImportTargetState(
            audio_transcription_required=self.audio_transcription_required,
            default_transcription_model_id=self.default_transcription_model_id,
        )


class FlowPackageImportRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "package_base64": "UEsDBBQAAAAIA...",
                "expected_content_checksum": "0" * 64,
                "expected_target_state": {
                    "audio_transcription_required": True,
                    "default_transcription_model_id": (
                        "22222222-2222-4222-8222-222222222222"
                    ),
                },
                "selected_bindings": [
                    {
                        "slot_ref": {
                            "kind": "model",
                            "slot": "structured",
                            "label": "Structured extraction",
                        },
                        "local_kind": "completion_model",
                        "local_id": "11111111-1111-4111-8111-111111111111",
                    }
                ],
            }
        },
    )

    package_base64: str = Field(
        description=(
            "Base64-encoded `.eneopkg` bytes. The decoded package must stay "
            "within the Flow package upload byte cap."
        )
    )
    expected_content_checksum: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "Checksum from the reviewed import plan. Import fails before mutation "
            "when the submitted package does not match that plan."
        ),
    )
    expected_target_state: FlowPackageImportTargetState = Field(
        description=(
            "Load-bearing target-space state from the reviewed plan. A changed "
            "audio transcription default requires a fresh plan."
        )
    )
    selected_bindings: list[FlowPackageImportResourceBindingRequest] = Field(
        default_factory=_empty_import_resource_binding_requests,
        description=(
            "Local target resources selected for package dependency slots. "
            "Knowledge slots may target `collection`, `website`, or "
            "`integration_knowledge` resources."
        ),
    )

    @field_validator("expected_target_state", mode="before")
    @classmethod
    def parse_expected_target_state(
        cls,
        value: object,
    ) -> FlowPackageImportTargetState:
        if isinstance(value, FlowPackageImportTargetState):
            return value
        return _FlowPackageImportTargetStateRequest.model_validate(value).to_domain()

    def import_selection(self) -> FlowPackageImportSelection:
        return FlowPackageImportSelection(
            selected_bindings=[
                selected_binding.to_domain()
                for selected_binding in self.selected_bindings
            ]
        )


class FlowPackageImportPublic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "example": {
                "import_id": "99999999-9999-4999-8999-999999999999",
                "flow_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "flow_name": "Case Report",
                "package_id": "se.demo.case-report",
                "package_version": "1.0.0",
                "content_checksum": "0" * 64,
                "steps_created": 4,
                "resource_bindings_count": 3,
            }
        },
    )

    import_id: UUID = Field(description="Identifier of the package import record.")
    flow_id: UUID = Field(description="Identifier of the imported draft Flow.")
    flow_name: str = Field(description="Name of the imported draft Flow.")
    package_id: str = Field(description="Portable package identifier.")
    package_version: str = Field(description="Publisher-assigned package version.")
    content_checksum: str = Field(
        description="SHA-256 based checksum covering the imported package content."
    )
    steps_created: int = Field(
        ge=0,
        description="Number of Flow steps created during import.",
    )
    resource_bindings_count: int = Field(
        ge=0,
        description="Number of selected local resource bindings persisted for the draft.",
    )

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from eneo.flow_packages.domain.flow_package_checksum import (
    compose_content_checksum,
    hash_json_value,
)
from eneo.flow_packages.domain.flow_package_draft import (
    FlowPackageFlowDraft,
    normalize_flow_package_spec,
)
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_manifest import (
    FLOW_PACKAGE_PAYLOAD_SCHEMA,
    FLOW_PACKAGE_TEMPLATES_PAYLOAD_SCHEMA,
    EneoPackageKind,
    FlowPackageManifest,
    FlowPackageManifestMetadata,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageKnowledgeRequirement,
    FlowPackageModelKind,
    FlowPackageModelRequirement,
    FlowPackageRequirementEntry,
    FlowPackageRequirementSet,
    FlowPackageTemplateAssetRequirement,
)
from eneo.flow_packages.domain.flow_package_templates import (
    FlowPackageTemplateDescriptor,
    validate_package_template_payloads,
)
from eneo.flows.flow_authoring_spec import AssistantSpec, FlowDraftSpecCore, OutputMode
from eneo.flows.flow_resource_bindings import ResourceSlotRef
from eneo.flows.flow_validators_template import has_template_fill_resource_reference
from eneo.resource_packages.checksum import coerce_json_object

MANIFEST_PATH = "manifest.json"
FLOW_DRAFT_PATH = "flow.draft.json"
REQUIREMENTS_PATH = "requirements.json"
PROVENANCE_PATH = "provenance.json"

PACKAGE_DOCUMENT_PATHS = (
    MANIFEST_PATH,
    FLOW_DRAFT_PATH,
    REQUIREMENTS_PATH,
    PROVENANCE_PATH,
)
REQUIRED_PACKAGE_FILES = frozenset(PACKAGE_DOCUMENT_PATHS)


@dataclass(frozen=True, slots=True)
class _FlowPackageDocumentHashes:
    spec_hash: str
    manifest_hash: str
    requirements_hash: str
    provenance_hash: str
    content_checksum: str


class FlowPackageEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    manifest: FlowPackageManifest
    draft: FlowPackageFlowDraft
    requirements: FlowPackageRequirementSet
    provenance: FlowPackageProvenance
    spec_hash: str
    manifest_hash: str
    requirements_hash: str
    provenance_hash: str
    content_checksum: str
    template_payloads: dict[str, bytes] = Field(default_factory=dict, exclude=True)

    @property
    def spec(self) -> FlowDraftSpecCore:
        return self.draft.spec

    def active_requirements(self) -> list[FlowPackageRequirementEntry]:
        """Declared requirements that the installed flow will actually read.

        A completion-model slot no step references is inert. The spec loader
        strips ``model_ref`` from steps that run no model, so a package
        exported before that rule can declare a model only such steps carried.
        Binding it changes nothing in the installed flow, so the importer is
        not asked to.
        """
        inert_slot_refs = self.validated_resource_contract().inert_slot_refs
        return [
            requirement
            for requirement in self.requirements.requirements
            if requirement.slot_ref.ref not in inert_slot_refs
        ]

    def validated_resource_contract(
        self,
    ) -> "ValidatedFlowPackageResourceContract":
        declared_requirements = {
            requirement.slot_ref.ref: requirement
            for requirement in self.requirements.requirements
        }
        declared_slot_refs = {
            ref: requirement.slot_ref
            for ref, requirement in declared_requirements.items()
        }
        referenced_slot_refs = frozenset(
            ref
            for step in self.spec.steps
            for ref in _assistant_slot_refs(step.assistant_spec)
        )
        template_refs = frozenset(
            ref
            for step in self.spec.steps
            if isinstance(ref := (step.output_config or {}).get("template_ref"), str)
        )
        referenced_slot_refs = referenced_slot_refs | template_refs
        unknown_slot_refs = referenced_slot_refs.difference(declared_slot_refs)
        if unknown_slot_refs:
            first_unknown = min(unknown_slot_refs)
            raise FlowPackageValidationError(
                code=(FlowPackageErrorCode.IMPORT_DRAFT_REFERENCES_UNDECLARED_SLOT),
                message=(
                    "Flow package draft references a resource slot that is not "
                    "declared."
                ),
                context={
                    "slot_ref": first_unknown,
                    "unknown_count": len(unknown_slot_refs),
                },
            )
        for step in self.spec.steps:
            template_ref = (step.output_config or {}).get("template_ref")
            if isinstance(template_ref, str) and not isinstance(
                declared_requirements[template_ref], FlowPackageTemplateAssetRequirement
            ):
                raise _invalid_requirement_use(
                    slot_ref=template_ref, reason="template_ref_kind_mismatch"
                )
            model_ref = step.assistant_spec.model_ref
            if model_ref is not None:
                requirement = declared_requirements[model_ref]
                if not isinstance(requirement, FlowPackageModelRequirement):
                    raise _invalid_requirement_use(
                        slot_ref=model_ref,
                        reason="assistant_model_ref_kind_mismatch",
                    )
                if requirement.model_kind is not FlowPackageModelKind.COMPLETION_MODEL:
                    raise _invalid_requirement_use(
                        slot_ref=model_ref,
                        reason="assistant_model_requires_completion_model",
                    )
                if not requirement.required:
                    raise _invalid_requirement_use(
                        slot_ref=model_ref,
                        reason="referenced_model_must_be_required",
                    )
            for knowledge_ref in step.assistant_spec.knowledge_refs:
                if not isinstance(
                    declared_requirements[knowledge_ref],
                    FlowPackageKnowledgeRequirement,
                ):
                    raise _invalid_requirement_use(
                        slot_ref=knowledge_ref,
                        reason="assistant_knowledge_ref_kind_mismatch",
                    )
        inert_slot_refs = frozenset(
            ref
            for ref, requirement in declared_requirements.items()
            if isinstance(requirement, FlowPackageModelRequirement)
            and requirement.model_kind is FlowPackageModelKind.COMPLETION_MODEL
            and ref not in referenced_slot_refs
        )
        return ValidatedFlowPackageResourceContract(
            declared_slot_refs=declared_slot_refs,
            referenced_slot_refs=referenced_slot_refs,
            inert_slot_refs=inert_slot_refs,
        )

    @classmethod
    def verify_from_subdocuments(
        cls,
        *,
        manifest: FlowPackageManifest,
        draft: FlowPackageFlowDraft,
        requirements: FlowPackageRequirementSet,
        provenance: FlowPackageProvenance,
        template_payloads: dict[str, bytes] | None = None,
    ) -> "FlowPackageEnvelope":
        require_flow_package_manifest(manifest)
        hashes = _calculate_hashes(
            manifest_metadata=manifest,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
        )
        if manifest.content_checksum != hashes.content_checksum:
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.CHECKSUM_MISMATCH,
                message="Flow package content checksum does not match.",
            )
        return cls._from_subdocuments(
            manifest=manifest,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
            hashes=hashes,
            template_payloads=template_payloads,
        )

    @classmethod
    def build_for_export(
        cls,
        *,
        manifest_metadata: FlowPackageManifestMetadata,
        draft: FlowPackageFlowDraft,
        requirements: FlowPackageRequirementSet,
        provenance: FlowPackageProvenance,
        template_payloads: dict[str, bytes] | None = None,
    ) -> "FlowPackageEnvelope":
        require_flow_package_manifest(manifest_metadata)
        hashes = _calculate_hashes(
            manifest_metadata=manifest_metadata,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
        )
        return cls._from_subdocuments(
            manifest=manifest_metadata.with_content_checksum(hashes.content_checksum),
            draft=draft,
            requirements=requirements,
            provenance=provenance,
            hashes=hashes,
            template_payloads=template_payloads,
        )

    @classmethod
    def _from_subdocuments(
        cls,
        *,
        manifest: FlowPackageManifest,
        draft: FlowPackageFlowDraft,
        requirements: FlowPackageRequirementSet,
        provenance: FlowPackageProvenance,
        hashes: _FlowPackageDocumentHashes,
        template_payloads: dict[str, bytes] | None = None,
    ) -> "FlowPackageEnvelope":
        envelope = cls(
            manifest=manifest,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
            spec_hash=hashes.spec_hash,
            manifest_hash=hashes.manifest_hash,
            requirements_hash=hashes.requirements_hash,
            provenance_hash=hashes.provenance_hash,
            content_checksum=hashes.content_checksum,
            template_payloads=template_payloads or {},
        )
        _validate_portable_step_identity(envelope.spec)
        _validate_template_contract(envelope)
        # Validate without replacing the spec covered by the package checksum.
        normalize_flow_package_spec(envelope.spec)
        envelope.validated_resource_contract()
        return envelope


def _calculate_hashes(
    *,
    manifest_metadata: FlowPackageManifestMetadata,
    draft: FlowPackageFlowDraft,
    requirements: FlowPackageRequirementSet,
    provenance: FlowPackageProvenance,
) -> _FlowPackageDocumentHashes:
    spec_hash = draft.spec.spec_hash()
    manifest_hash = hash_json_value(manifest_metadata.canonical_hash_input())
    requirements_hash = hash_json_value(requirements.canonical_hash_input())
    provenance_hash = hash_json_value(provenance.canonical_hash_input())
    content_checksum = compose_content_checksum(
        spec_hash=spec_hash,
        manifest_hash=manifest_hash,
        requirements_hash=requirements_hash,
        provenance_hash=provenance_hash,
    )
    return _FlowPackageDocumentHashes(
        spec_hash=spec_hash,
        manifest_hash=manifest_hash,
        requirements_hash=requirements_hash,
        provenance_hash=provenance_hash,
        content_checksum=content_checksum,
    )


def require_flow_package_manifest(manifest: FlowPackageManifestMetadata) -> None:
    if manifest.kind is EneoPackageKind.FLOW and manifest.payload_schema in {
        FLOW_PACKAGE_PAYLOAD_SCHEMA,
        FLOW_PACKAGE_TEMPLATES_PAYLOAD_SCHEMA,
    }:
        return
    raise FlowPackageValidationError(
        code=FlowPackageErrorCode.PACKAGE_KIND_UNSUPPORTED,
        message="This package reader only supports flow package payloads.",
        context={
            "kind": manifest.kind.value,
            "payload_schema": manifest.payload_schema,
        },
    )


@dataclass(frozen=True, slots=True)
class ValidatedFlowPackageResourceContract:
    declared_slot_refs: dict[str, ResourceSlotRef]
    referenced_slot_refs: frozenset[str]
    # Declared completion-model slots that no step in the draft reads.
    inert_slot_refs: frozenset[str] = frozenset()


def _assistant_slot_refs(assistant: AssistantSpec) -> tuple[str, ...]:
    refs: list[str] = []
    if assistant.model_ref is not None:
        refs.append(assistant.model_ref)
    refs.extend(assistant.knowledge_refs)
    return tuple(refs)


def _invalid_requirement_use(
    *,
    slot_ref: str,
    reason: str,
) -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.REQUIREMENTS_INVALID,
        message="Flow package resource requirements do not match draft usage.",
        context={"slot_ref": slot_ref, "reason": reason},
    )


def _validate_template_contract(envelope: FlowPackageEnvelope) -> None:
    descriptors: dict[str, FlowPackageTemplateDescriptor] = {
        requirement.slot_ref.ref: requirement.template
        for requirement in envelope.requirements.requirements
        if isinstance(requirement, FlowPackageTemplateAssetRequirement)
        and requirement.template is not None
    }
    for step in envelope.spec.steps:
        if (
            step.output_mode is OutputMode.TEMPLATE_FILL
            or has_template_fill_resource_reference(step.output_config)
        ):
            if (
                envelope.manifest.payload_schema
                != FLOW_PACKAGE_TEMPLATES_PAYLOAD_SCHEMA
            ):
                raise FlowPackageValidationError(
                    code=FlowPackageErrorCode.IMPORT_TEMPLATE_ASSETS_UNSUPPORTED,
                    message="Template-fill steps require the Word template package format.",
                    context={"plan_step_ref": step.plan_step_ref},
                )
        config = step.output_config or {}
        ref = config.get("template_ref")
        if step.output_mode is not OutputMode.TEMPLATE_FILL:
            if any(
                key in config for key in ("template_ref", "placeholders", "bindings")
            ) or has_template_fill_resource_reference(config):
                raise _invalid_requirement_use(
                    slot_ref=str(ref or ""), reason="inactive_template_config"
                )
            continue
        descriptor = descriptors.get(ref) if isinstance(ref, str) else None
        if descriptor is None or has_template_fill_resource_reference(config):
            raise _invalid_requirement_use(
                slot_ref=str(ref or ""), reason="missing_portable_template"
            )
        names = {field.name for field in descriptor.fields}
        bindings = config.get("bindings")
        if (
            not isinstance(bindings, dict)
            or set(coerce_json_object(config.get("bindings"))) != names
            or config.get("placeholders") != [field.name for field in descriptor.fields]
        ):
            raise _invalid_requirement_use(
                slot_ref=str(ref), reason="template_binding_contract_mismatch"
            )
    if (
        descriptors
        and envelope.manifest.payload_schema != FLOW_PACKAGE_TEMPLATES_PAYLOAD_SCHEMA
    ):
        raise _invalid_requirement_use(
            slot_ref=min(descriptors), reason="template_payload_requires_v2"
        )
    used_refs = {
        str((step.output_config or {}).get("template_ref"))
        for step in envelope.spec.steps
        if step.output_mode is OutputMode.TEMPLATE_FILL
    }
    if set(descriptors) != used_refs:
        raise _invalid_requirement_use(
            slot_ref="", reason="template_requirements_do_not_match_usage"
        )
    validate_package_template_payloads(descriptors, envelope.template_payloads)


def _validate_portable_step_identity(spec: FlowDraftSpecCore) -> None:
    seen_refs: set[str] = set()
    for step in spec.steps:
        if not step.plan_step_ref or step.plan_step_ref != step.plan_step_ref.strip():
            raise _invalid_portable_step_ref(
                plan_step_ref=step.plan_step_ref,
                reason="invalid_plan_step_ref",
            )
        if step.plan_step_ref in seen_refs:
            raise _invalid_portable_step_ref(
                plan_step_ref=step.plan_step_ref,
                reason="duplicate_plan_step_ref",
            )
        seen_refs.add(step.plan_step_ref)
        if step.existing_step_ref is not None:
            raise _invalid_portable_step_ref(
                plan_step_ref=step.plan_step_ref,
                reason="existing_step_ref_not_portable",
            )


def _invalid_portable_step_ref(
    *,
    plan_step_ref: str,
    reason: str,
) -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.FLOW_DRAFT_INVALID,
        message="Flow package step identity is not portable.",
        context={"plan_step_ref": plan_step_ref, "reason": reason},
    )

from __future__ import annotations

import base64
import hashlib
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest

from eneo.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
    build_flow_package_import_plan,
)
from eneo.flow_packages.application.flow_package_install_service import (
    resolve_flow_package_install_command,
)
from eneo.flow_packages.application.flow_package_template_uploads import (
    FlowPackageTemplateUpload,
    resolve_flow_package_template_files,
)
from eneo.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from eneo.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportSelection,
)
from eneo.flow_packages.domain.flow_package_manifest import (
    EneoPackageKind,
    FlowPackageManifestMetadata,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageRequirementSet,
    FlowPackageTemplateAssetRequirement,
)
from eneo.flow_packages.infrastructure.flow_package_zip_reader import read_flow_package
from eneo.flow_packages.infrastructure.flow_package_zip_writer import write_flow_package
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import ResourceSlotKind, ResourceSlotRef


def _template_envelope(
    *, included: bool = True, shared: bool = False
) -> FlowPackageEnvelope:
    template_bytes = (
        Path(__file__).resolve().parents[4]
        / "frontend/apps/web/static/examples/eneo-word-template.docx"
    ).read_bytes()
    checksum = hashlib.sha256(template_bytes).hexdigest()
    asset_path = f"templates/{checksum}.docx"
    slot = ResourceSlotRef(
        kind=ResourceSlotKind.TEMPLATE_ASSET, slot="report", label="Rapport.docx"
    )
    requirement = FlowPackageTemplateAssetRequirement.model_validate(
        {
            "slot_ref": slot,
            "used_by_steps": ["report", "second"] if shared else ["report"],
            "template": {
                "filename": "Rapport.docx",
                "checksum": checksum,
                "size_bytes": len(template_bytes),
                "fields": [{"name": "dokument", "kind": "rich"}],
                "asset_path": asset_path if included else None,
            },
        }
    )
    envelope = FlowPackageEnvelope.build_for_export(
        manifest_metadata=FlowPackageManifestMetadata(
            schema_version=1,
            kind=EneoPackageKind.FLOW,
            payload_schema="eneo.flow_package.v2",
            package_id="se.example.report",
            package_version="1.0.0",
            name="Rapport",
        ),
        draft=FlowPackageFlowDraft(
            schema_version=1,
            spec=FlowDraftSpecCore(
                flow_name="Rapport",
                steps=[
                    StepSpec(
                        plan_step_ref="report",
                        name="Fyll rapport",
                        input_source="flow_input",
                        input_type="text",
                        output_mode="template_fill",
                        output_type="docx",
                        assistant_spec=AssistantSpec(instructions=""),
                        output_config={
                            "template_ref": slot.ref,
                            "placeholders": ["dokument"],
                            "bindings": {"dokument": "{{flow_input.text}}"},
                        },
                    )
                ],
            ),
        ),
        requirements=FlowPackageRequirementSet(
            schema_version=1, requirements=[requirement]
        ),
        provenance=FlowPackageProvenance.for_portable_export(
            exported_at=datetime(2026, 10, 1, tzinfo=timezone.utc), omissions=[]
        ),
        template_payloads={asset_path: template_bytes} if included else {},
    )

    if shared:
        second = StepSpec.model_validate(
            {
                **envelope.spec.steps[0].model_dump(),
                **{
                    "plan_step_ref": "second",
                    "name": "Second",
                    "input_source": "all_previous_steps",
                    "input_type": "text",
                    "output_config": {
                        **envelope.spec.steps[0].output_config,
                        "bindings": {"dokument": "{{ report.output.text }}"},
                    },
                    "input_bindings": {
                        "source_refs": [{"step_ref": "report", "output": "text"}]
                    },
                },
            }
        )
        envelope = FlowPackageEnvelope.build_for_export(
            manifest_metadata=FlowPackageManifestMetadata.model_validate(
                envelope.manifest.model_dump(exclude={"spec_hash", "content_checksum"})
            ),
            draft=envelope.draft.model_copy(
                update={
                    "spec": envelope.spec.model_copy(
                        update={"steps": [envelope.spec.steps[0], second]}
                    )
                }
            ),
            requirements=envelope.requirements,
            provenance=envelope.provenance,
            template_payloads=envelope.template_payloads,
        )
    return envelope


def test_template_package_round_trip_preserves_docx_and_bindings() -> None:
    envelope = _template_envelope()
    asset_path, template_bytes = next(iter(envelope.template_payloads.items()))

    package_bytes = write_flow_package(envelope)
    imported = read_flow_package(package_bytes)

    assert imported.spec.steps[0].output_config == {
        "template_ref": "template_asset.report",
        "placeholders": ["dokument"],
        "bindings": {"dokument": "{{flow_input.text}}"},
    }
    assert imported.content_checksum == envelope.content_checksum
    with zipfile.ZipFile(BytesIO(package_bytes)) as package:
        assert package.read(asset_path) == template_bytes


def _upload(
    envelope: FlowPackageEnvelope, content: bytes | None = None
) -> FlowPackageTemplateUpload:
    return FlowPackageTemplateUpload(
        template_ref="template_asset.report",
        filename="Replacement.docx",
        content_base64=base64.b64encode(
            content
            if content is not None
            else next(iter(envelope.template_payloads.values()))
        ).decode(),
    )


def _rewrite_zip(content: bytes, transform) -> bytes:
    result = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(content)) as source,
        zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for name in source.namelist():
            target.writestr(name, transform(name, source.read(name)))
    return result.getvalue()


def test_missing_template_blocks_install_until_a_matching_docx_is_reviewed() -> None:
    omitted = read_flow_package(write_flow_package(_template_envelope(included=False)))
    candidates = FlowPackageImportPlannerCandidates()
    plan = build_flow_package_import_plan(omitted, candidates=candidates)
    assert not plan.can_install_as_draft
    assert plan.dependency_resolutions[0].install_blocks
    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_install_command(
            envelope=omitted,
            import_plan=plan,
            expected_content_checksum=omitted.content_checksum,
            expected_target_state=plan.target_state,
            selection=FlowPackageImportSelection(),
            candidates=candidates,
        )
    assert error.value.code is FlowPackageErrorCode.TEMPLATE_UPLOAD_REQUIRED
    files = resolve_flow_package_template_files(
        omitted, [_upload(_template_envelope())]
    )
    reviewed = build_flow_package_import_plan(
        omitted, candidates=candidates, template_files=files
    )
    assert reviewed.can_install_as_draft
    assert (
        reviewed.dependency_resolutions[0].upload_checksum
        == files["template_asset.report"].checksum
    )
    checksums = {ref: file.checksum for ref, file in files.items()}
    command = resolve_flow_package_install_command(
        envelope=omitted,
        import_plan=reviewed,
        expected_content_checksum=omitted.content_checksum,
        expected_target_state=reviewed.target_state,
        selection=FlowPackageImportSelection(),
        candidates=candidates,
        template_files=files,
        expected_template_upload_checksums=checksums,
    )
    assert {
        ref: identity.checksum
        for ref, identity in command.selection.template_uploads.items()
    } == checksums
    renamed = resolve_flow_package_template_files(
        omitted,
        [_upload(_template_envelope()).model_copy(update={"filename": "Renamed.docx"})],
    )
    renamed_command = resolve_flow_package_install_command(
        envelope=omitted,
        import_plan=reviewed,
        expected_content_checksum=omitted.content_checksum,
        expected_target_state=reviewed.target_state,
        selection=FlowPackageImportSelection(),
        candidates=candidates,
        template_files=renamed,
        expected_template_upload_checksums=checksums,
    )
    assert command.selection.storage_json() != renamed_command.selection.storage_json()
    with pytest.raises(FlowPackageValidationError) as changed:
        resolve_flow_package_install_command(
            envelope=omitted,
            import_plan=reviewed,
            expected_content_checksum=omitted.content_checksum,
            expected_target_state=reviewed.target_state,
            selection=FlowPackageImportSelection(),
            candidates=candidates,
            template_files=files,
            expected_template_upload_checksums={"template_asset.report": "0" * 64},
        )
    assert changed.value.code is FlowPackageErrorCode.CHECKSUM_MISMATCH


def test_replacement_with_changed_tags_is_rejected_with_actionable_context() -> None:
    original = _template_envelope()
    content = next(iter(original.template_payloads.values()))
    changed = _rewrite_zip(
        content,
        lambda name, data: data.replace(b'w:val="dokument"', b'w:val="other"')
        if name == "word/document.xml"
        else data,
    )
    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_template_files(
            _template_envelope(included=False), [_upload(original, changed)]
        )
    assert error.value.code is FlowPackageErrorCode.TEMPLATE_FIELDS_MISMATCH
    assert error.value.context["missing_fields"] == "dokument"
    assert error.value.context["added_fields"] == "other"


@pytest.mark.parametrize(
    "case",
    [
        "invalid_docx",
        "invalid_base64",
        "unknown_slot",
        "duplicate",
        "included_override",
    ],
)
def test_unreviewable_template_uploads_fail_closed(case: str) -> None:
    original = _template_envelope()
    omitted = _template_envelope(included=False)
    upload = _upload(original)
    if case == "invalid_docx":
        upload = _upload(original, b"not a DOCX")
    if case == "invalid_base64":
        upload = upload.model_copy(update={"content_base64": "!!!!"})
    if case == "unknown_slot":
        upload = upload.model_copy(update={"template_ref": "template_asset.unknown"})
    if case == "included_override":
        omitted = original
    with pytest.raises(FlowPackageValidationError) as error:
        resolve_flow_package_template_files(
            omitted, [upload, upload] if case == "duplicate" else [upload]
        )
    assert error.value.code is FlowPackageErrorCode.TEMPLATE_FILE_INVALID


def test_changed_packaged_word_bytes_fail_checksum_verification() -> None:
    package = write_flow_package(_template_envelope())
    changed = _rewrite_zip(
        package,
        lambda name, data: data + b"changed" if name.startswith("templates/") else data,
    )
    with pytest.raises(FlowPackageValidationError) as error:
        read_flow_package(changed)
    assert error.value.code is FlowPackageErrorCode.CHECKSUM_MISMATCH


def test_shared_template_is_stored_once_and_resolves_for_both_steps() -> None:
    envelope = _template_envelope(shared=True)
    package = write_flow_package(envelope)
    imported = read_flow_package(package)
    assert len(imported.spec.steps) == 2
    assert len(resolve_flow_package_template_files(imported)) == 1
    with zipfile.ZipFile(BytesIO(package)) as archive:
        assert (
            len([name for name in archive.namelist() if name.startswith("templates/")])
            == 1
        )


def test_template_package_does_not_disable_strict_validation_of_other_steps() -> None:
    from eneo.flows.flow_authoring_spec import FormFieldSpec

    envelope = _template_envelope(shared=True)
    envelope.spec.form_fields = [FormFieldSpec(name="name", type="text", label="Name")]
    envelope.spec.steps[0].output_config["bindings"] = {
        "dokument": "{{ flow_input.name }}"
    }
    step = envelope.spec.steps[1]
    step.output_mode = OutputMode.PASS_THROUGH
    step.output_type = OutputType.TEXT
    step.output_config = None
    step.assistant_spec.instructions = "Read {{ indata_text }}"
    with pytest.raises(FlowPackageValidationError) as error:
        build_flow_package_import_plan(
            envelope, candidates=FlowPackageImportPlannerCandidates()
        )
    assert error.value.code is FlowPackageErrorCode.FLOW_DRAFT_INVALID
    assert error.value.context["reason"] == "flow_input_alias_not_received"

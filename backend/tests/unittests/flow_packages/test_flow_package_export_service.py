from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

import pytest

from eneo.flow_packages.application.flow_package_export_service import (
    MAX_PACKAGE_EXPORT_BYTES,
    FlowPackageExportService,
    build_flow_package_export_envelope,
)
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageExportError,
    FlowPackageExportErrorCode,
)
from eneo.flow_packages.domain.flow_package_manifest import (
    EneoPackageKind,
    FlowPackageManifestMetadata,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageModelKind,
    FlowPackageModelRequirement,
)
from eneo.flow_packages.infrastructure.flow_package_zip_reader import (
    read_flow_package,
)
from eneo.flow_packages.infrastructure.flow_package_zip_writer import (
    write_flow_package,
)
from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
    AssistantAuthoringSnapshots,
)
from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


@pytest.mark.anyio
async def test_export_service_builds_zip_with_side_effect_free_dependencies() -> None:
    assistant_id = uuid4()
    model_id = uuid4()
    flow_id = uuid4()
    flow = _flow(
        steps=[
            _step(
                1,
                assistant_id=assistant_id,
                input_bindings={"question": "{{ flow_input.text }}"},
            )
        ]
    )
    snapshots = {
        assistant_id: _snapshot(
            model_ref=AssistantAuthoringResourceRef(
                local_ref=str(model_id),
                label="Structured model",
                local_kind=LocalResourceKind.COMPLETION_MODEL,
            )
        )
    }
    bindings = (
        _binding(
            slot_kind=ResourceSlotKind.MODEL,
            slot="structured-model",
            label="Structured model",
            local_kind=LocalResourceKind.COMPLETION_MODEL,
            local_id=model_id,
        ),
    )
    dependency_service = _FakeFlowPackageExportFlowService(
        assistant_snapshots=snapshots,
        resource_bindings=bindings,
    )
    export_service = FlowPackageExportService(
        flow_service=dependency_service,
        package_writer=write_flow_package,
        clock=lambda: datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    )

    result = await export_service.export_to_bytes(
        flow_id=flow_id,
        flow=flow,
        manifest_metadata=_manifest_metadata(),
    )

    assert dependency_service.flow == flow
    assert dependency_service.flow_id == flow_id
    assert result.filename == "se.demo.meeting-report-1.0.0.eneopkg"
    reparsed = read_flow_package(result.package_bytes)
    assert reparsed == result.envelope
    assert reparsed.provenance.source_instance_id is None
    assert reparsed.provenance.exported_by is None
    assert reparsed.provenance.exported_at == datetime(
        2026,
        5,
        18,
        12,
        0,
        tzinfo=timezone.utc,
    )


@pytest.mark.anyio
async def test_export_service_rejects_oversized_package_bytes() -> None:
    assistant_id = uuid4()
    flow = _flow(steps=[_step(1, assistant_id=assistant_id)])
    export_service = FlowPackageExportService(
        flow_service=_FakeFlowPackageExportFlowService(
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        ),
        package_writer=lambda envelope: b"x" * (MAX_PACKAGE_EXPORT_BYTES + 1),
    )

    with pytest.raises(FlowPackageExportError) as exc_info:
        await export_service.export_to_bytes(
            flow_id=uuid4(),
            flow=flow,
            manifest_metadata=_manifest_metadata(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE
    assert exc_info.value.context == {
        "package_size_bytes": MAX_PACKAGE_EXPORT_BYTES + 1,
        "max_package_export_bytes": MAX_PACKAGE_EXPORT_BYTES,
    }


@pytest.mark.anyio
async def test_export_service_records_persisted_flow_mcp_as_one_typed_omission() -> (
    None
):
    assistant_id = uuid4()
    flow = _flow(steps=[_step(1, assistant_id=assistant_id)])
    dependency_service = _FakeFlowPackageExportFlowService(
        assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
        resource_bindings=tuple(),
        omitted_mcp_assistant_count=2,
    )
    export_service = FlowPackageExportService(
        flow_service=dependency_service,
        package_writer=write_flow_package,
    )

    result = await export_service.export_to_bytes(
        flow_id=flow.id,
        flow=flow,
        manifest_metadata=_manifest_metadata(),
    )

    assert result.envelope.provenance.model_dump(mode="json")["omissions"] == [
        {"kind": "mcp_attachment", "count": 2}
    ]
    assert read_flow_package(result.package_bytes).provenance.omissions == (
        result.envelope.provenance.omissions
    )


@pytest.mark.anyio
async def test_export_service_rejects_nonportable_config_before_writing_bytes() -> None:
    assistant_id = uuid4()
    writes: list[object] = []

    def package_writer(envelope: object) -> bytes:
        writes.append(envelope)
        return b"package"

    export_service = FlowPackageExportService(
        flow_service=_FakeFlowPackageExportFlowService(
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        ),
        package_writer=package_writer,
    )

    with pytest.raises(FlowPackageExportError) as exc_info:
        await export_service.export_to_bytes(
            flow_id=uuid4(),
            flow=_flow(
                steps=[
                    _step(
                        1,
                        assistant_id=assistant_id,
                        input_config={"token": "plaintext-do-not-export"},
                    )
                ]
            ),
            manifest_metadata=_manifest_metadata(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.STEP_CONFIG_NOT_PORTABLE
    assert exc_info.value.context == {
        "step_order": 1,
        "config_field": "input_config",
    }
    assert "plaintext-do-not-export" not in str(exc_info.value)
    assert writes == []


def test_export_builds_portable_envelope_and_round_trips_zip() -> None:
    assistant_id = uuid4()
    model_id = uuid4()
    envelope = build_flow_package_export_envelope(
        flow=_flow(
            steps=[
                _step(
                    1,
                    assistant_id=assistant_id,
                    input_bindings={"question": "{{ flow_input.text }}"},
                )
            ]
        ),
        assistant_snapshots={
            assistant_id: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    label="Structured model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            )
        },
        resource_bindings=(
            _binding(
                slot_kind=ResourceSlotKind.MODEL,
                slot="structured-model",
                label="Structured model",
                local_kind=LocalResourceKind.COMPLETION_MODEL,
                local_id=model_id,
            ),
        ),
        manifest_metadata=_manifest_metadata(),
        provenance=_provenance(),
    )

    step = envelope.draft.spec.steps[0]
    assert step.plan_step_ref == "step_1"
    assert step.assistant_spec.model_ref == "model.structured-model"
    assert all(step.existing_step_ref is None for step in envelope.draft.spec.steps)
    requirement = envelope.requirements.requirements[0]
    assert isinstance(requirement, FlowPackageModelRequirement)
    assert requirement.slot_ref.ref == "model.structured-model"
    assert requirement.slot_ref.label == "Structured model"
    assert requirement.used_by_steps == ["step_1"]
    assert requirement.model_kind is FlowPackageModelKind.COMPLETION_MODEL
    assert read_flow_package(write_flow_package(envelope)) == envelope


def test_export_preserves_only_strict_mode_relevant_portable_config() -> None:
    document_assistant_id = uuid4()
    item_assistant_id = uuid4()
    envelope = _build_envelope(
        flow=_flow(
            steps=[
                _step(
                    1,
                    assistant_id=document_assistant_id,
                    input_type="document",
                    input_config={
                        "runtime_input": {
                            "enabled": True,
                            "required": True,
                            "max_files": 3,
                            "input_format": "document",
                            "execution_mode": "per_source",
                            "accepted_mimetypes_override": ["application/pdf"],
                            "label": "Documents",
                            "description": "Upload source documents.",
                        }
                    },
                    output_config={"citation_mode": "inline_inref_sidecar"},
                ),
                _step(
                    2,
                    assistant_id=item_assistant_id,
                    input_source="previous_step",
                    input_type="json",
                    output_type="json",
                    input_config={"item_map": {"enabled": True}},
                ),
            ]
        ),
        assistant_snapshots={
            document_assistant_id: _snapshot(model_ref=None),
            item_assistant_id: _snapshot(model_ref=None),
        },
        resource_bindings=tuple(),
    )

    document_step, item_step = envelope.draft.spec.steps
    assert document_step.input_config == {
        "runtime_input": {
            "enabled": True,
            "required": True,
            "max_files": 3,
            "input_format": "document",
            "execution_mode": "per_source",
            "accepted_mimetypes_override": ["application/pdf"],
            "label": "Documents",
            "description": "Upload source documents.",
        }
    }
    assert document_step.output_config == {"citation_mode": "inline_inref_sidecar"}
    assert item_step.input_config == {"item_map": {"enabled": True}}
    assert item_step.output_config is None

    reparsed = read_flow_package(write_flow_package(envelope))
    assert reparsed == envelope
    assert reparsed.content_checksum == envelope.content_checksum


def test_export_omits_recognized_portable_config_when_mode_irrelevant() -> None:
    assistant_id = uuid4()
    envelope = _build_envelope(
        flow=_flow(
            steps=[
                _step(
                    1,
                    assistant_id=assistant_id,
                    input_type="text",
                    output_mode="compose_text",
                    input_config={
                        "runtime_input": {"enabled": True},
                        "item_map": {"enabled": True},
                    },
                    output_config={"citation_mode": "inline_inref_sidecar"},
                )
            ]
        ),
        assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
        resource_bindings=tuple(),
    )

    step = envelope.draft.spec.steps[0]
    assert step.input_config is None
    assert step.output_config is None


@pytest.mark.parametrize(
    ("step_kwargs", "config_field", "sensitive_value"),
    [
        (
            {
                "input_source": "http_get",
                "input_config": {
                    "auth": {"mode": "bearer_token", "token": "plain-bearer"}
                },
            },
            "input_config",
            "plain-bearer",
        ),
        (
            {
                "input_config": {
                    "auth": {
                        "mode": "api_key",
                        "header_name": "X-API-Key",
                        "key": "encrypted-api-key",
                    }
                },
            },
            "input_config",
            "encrypted-api-key",
        ),
        (
            {
                "output_config": {
                    "auth": {
                        "mode": "basic_auth",
                        "username": "local-user",
                        "password": "plain-password",
                    }
                },
            },
            "output_config",
            "plain-password",
        ),
        (
            {
                "output_config": {
                    "auth": {
                        "mode": "bearer_token",
                        "token": {"$secret": "stored"},
                    }
                },
            },
            "output_config",
            "stored",
        ),
        (
            {"input_config": {"token": "unknown-plaintext"}},
            "input_config",
            "unknown-plaintext",
        ),
        (
            {
                "output_config": {
                    "template_filename_preview": "unsupported-preview.docx"
                }
            },
            "output_config",
            "unsupported-preview.docx",
        ),
        (
            {
                "input_type": "document",
                "input_config": {
                    "runtime_input": {
                        "enabled": True,
                        "unexpected_secret": "nested-plaintext",
                    }
                },
            },
            "input_config",
            "nested-plaintext",
        ),
    ],
    ids=[
        "active-http-bearer",
        "stale-http-encrypted-api-key",
        "stale-http-basic-password",
        "stored-secret-sentinel",
        "unknown-top-level-field",
        "unknown-output-field",
        "unknown-nested-field",
    ],
)
def test_export_rejects_secret_or_unknown_step_config_without_echoing_values(
    step_kwargs: dict[str, object],
    config_field: str,
    sensitive_value: str,
) -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id, **step_kwargs)]),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.STEP_CONFIG_NOT_PORTABLE
    assert exc_info.value.context == {
        "step_order": 1,
        "config_field": config_field,
    }
    assert sensitive_value not in str(exc_info.value)
    assert sensitive_value not in repr(exc_info.value.context)


def test_export_validates_variables_in_emitted_portable_config() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(
                steps=[
                    _step(
                        1,
                        assistant_id=assistant_id,
                        input_type="document",
                        input_config={
                            "runtime_input": {
                                "enabled": True,
                                "description": "Use {{ missing_value }}",
                            }
                        },
                    )
                ]
            ),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.VARIABLE_REFERENCE_INVALID


def test_export_preserves_form_fields_from_flow_metadata() -> None:
    assistant_id = uuid4()
    envelope = _build_envelope(
        flow=_flow(
            metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "case_id",
                            "type": "text",
                            "label": "Case ID",
                            "required": True,
                        }
                    ]
                }
            },
            steps=[
                _step(
                    1,
                    assistant_id=assistant_id,
                    input_bindings={"question": "{{ flow_input.case_id }}"},
                )
            ],
        ),
        assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
        resource_bindings=tuple(),
    )

    assert envelope.draft.spec.form_fields is not None
    assert envelope.draft.spec.form_fields[0].name == "case_id"
    assert envelope.draft.spec.form_fields[0].label == "Case ID"
    assert envelope.draft.spec.form_fields[0].required is True


@pytest.mark.parametrize(
    "step_kwargs",
    [
        {"input_bindings": {"question": "{{ missing_value }}"}},
        {"input_contract": {"description": "{{ missing_value }}"}},
        {"output_contract": {"description": "{{ missing_value }}"}},
    ],
)
def test_export_rejects_invalid_template_references_in_step_payloads(
    step_kwargs: dict[str, FlowPersistedJsonObject],
) -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id, **step_kwargs)]),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.VARIABLE_REFERENCE_INVALID
    assert exc_info.value.context["step_order"] == 1


def test_export_rejects_invalid_template_references_in_assistant_instructions() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
            assistant_snapshots={
                assistant_id: _snapshot(
                    instructions="Use {{ missing_value }}",
                    model_ref=None,
                )
            },
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.VARIABLE_REFERENCE_INVALID


@pytest.mark.parametrize(
    "template",
    [
        "{{ step_2.output.text }}",
        "{{ step_input.unknown_key }}",
        "{{ flow_input.unregistered_field }}",
    ],
)
def test_export_rejects_forward_or_invalid_runtime_references(template: str) -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(
                steps=[
                    _step(
                        1,
                        assistant_id=assistant_id,
                        input_bindings={"question": template},
                    )
                ]
            ),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.VARIABLE_REFERENCE_INVALID


def test_export_sorts_used_by_steps_by_step_order_not_lexicographic_ref() -> None:
    assistant_a = uuid4()
    assistant_b = uuid4()
    model_id = uuid4()
    envelope = _build_envelope(
        flow=_flow(
            steps=[
                _step(10, assistant_id=assistant_b),
                _step(2, assistant_id=assistant_a),
            ]
        ),
        assistant_snapshots={
            assistant_a: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            ),
            assistant_b: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            ),
        },
        resource_bindings=(
            _binding(
                slot_kind=ResourceSlotKind.MODEL,
                slot="shared-model",
                label="Shared model",
                local_kind=LocalResourceKind.COMPLETION_MODEL,
                local_id=model_id,
            ),
        ),
    )

    requirement = envelope.requirements.requirements[0]
    assert isinstance(requirement, FlowPackageModelRequirement)
    assert requirement.used_by_steps == ["step_2", "step_10"]


def test_export_rejects_missing_assistant_snapshot() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
            assistant_snapshots={},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.MISSING_ASSISTANT_SNAPSHOT


def test_export_rejects_unsupported_output_mode() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(
                steps=[_step(1, assistant_id=assistant_id, output_mode="http_post")]
            ),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.UNSUPPORTED_STEP_IO


def test_export_rejects_legacy_http_post_input() -> None:
    class LegacyInputSource(StrEnum):
        HTTP_POST = "http_post"

    assistant_id = uuid4()
    legacy_step = _step(1, assistant_id=assistant_id).model_copy(
        update={"input_source": LegacyInputSource.HTTP_POST}
    )

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[legacy_step]),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.UNSUPPORTED_STEP_IO


def test_export_rejects_template_fill_steps() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(
                steps=[_step(1, assistant_id=assistant_id, output_mode="template_fill")]
            ),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert (
        exc_info.value.code
        is FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED
    )


def test_export_rejects_template_asset_refs_in_output_config() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(
                steps=[
                    _step(
                        1,
                        assistant_id=assistant_id,
                        output_config={"template_asset_id": str(uuid4())},
                    )
                ]
            ),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert (
        exc_info.value.code
        is FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED
    )


def test_export_rejects_stale_template_file_refs_in_output_config() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(
                steps=[
                    _step(
                        1,
                        assistant_id=assistant_id,
                        output_config={"template_file_id": str(uuid4())},
                    )
                ]
            ),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert (
        exc_info.value.code
        is FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED
    )


def test_export_allocates_package_slots_for_unbound_snapshot_resources() -> None:
    assistant_id = uuid4()
    model_id = uuid4()
    knowledge_id = uuid4()

    envelope = _build_envelope(
        flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
        assistant_snapshots={
            assistant_id: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    label="Structured model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                ),
                knowledge_refs=(
                    AssistantAuthoringResourceRef(
                        local_ref=str(knowledge_id),
                        label="Policy",
                        local_kind=LocalResourceKind.COLLECTION,
                    ),
                ),
            )
        },
        resource_bindings=tuple(),
    )

    step = envelope.draft.spec.steps[0]
    assert step.assistant_spec.model_ref == "model.structured-model"
    assert step.assistant_spec.knowledge_refs == ["knowledge.policy"]
    requirement_refs = {
        requirement.slot_ref.ref for requirement in envelope.requirements.requirements
    }
    assert requirement_refs == {"knowledge.policy", "model.structured-model"}


def test_export_allocates_package_slots_for_all_knowledge_resource_kinds() -> None:
    assistant_id = uuid4()
    collection_id = uuid4()
    website_id = uuid4()
    integration_knowledge_id = uuid4()

    envelope = _build_envelope(
        flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
        assistant_snapshots={
            assistant_id: _snapshot(
                model_ref=None,
                knowledge_refs=(
                    AssistantAuthoringResourceRef(
                        local_ref=str(collection_id),
                        label="Policy",
                        local_kind=LocalResourceKind.COLLECTION,
                    ),
                    AssistantAuthoringResourceRef(
                        local_ref=str(website_id),
                        label="Public guidance",
                        local_kind=LocalResourceKind.WEBSITE,
                    ),
                    AssistantAuthoringResourceRef(
                        local_ref=str(integration_knowledge_id),
                        label="SharePoint folder",
                        local_kind=LocalResourceKind.INTEGRATION_KNOWLEDGE,
                    ),
                ),
            )
        },
        resource_bindings=tuple(),
    )

    step = envelope.draft.spec.steps[0]
    assert step.assistant_spec.knowledge_refs == [
        "knowledge.policy",
        "knowledge.public-guidance",
        "knowledge.sharepoint-folder",
    ]
    requirement_refs = {
        requirement.slot_ref.ref for requirement in envelope.requirements.requirements
    }
    assert requirement_refs == {
        "knowledge.policy",
        "knowledge.public-guidance",
        "knowledge.sharepoint-folder",
    }


def test_export_reuses_one_package_slot_for_shared_unbound_snapshot_resource() -> None:
    assistant_a = uuid4()
    assistant_b = uuid4()
    model_id = uuid4()

    envelope = _build_envelope(
        flow=_flow(
            steps=[
                _step(1, assistant_id=assistant_a),
                _step(2, assistant_id=assistant_b),
            ]
        ),
        assistant_snapshots={
            assistant_a: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    label="Shared model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            ),
            assistant_b: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    label="Shared model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            ),
        },
        resource_bindings=tuple(),
    )

    assert [step.assistant_spec.model_ref for step in envelope.draft.spec.steps] == [
        "model.shared-model",
        "model.shared-model",
    ]
    requirements = envelope.requirements.requirements
    assert len(requirements) == 1
    requirement = requirements[0]
    assert isinstance(requirement, FlowPackageModelRequirement)
    assert requirement.slot_ref.ref == "model.shared-model"
    assert requirement.used_by_steps == ["step_1", "step_2"]


def test_export_uses_short_uuid_slot_when_snapshot_resource_label_is_missing() -> None:
    assistant_id = uuid4()
    model_id = UUID("11111111-1111-4111-8111-111111111111")

    envelope = _build_envelope(
        flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
        assistant_snapshots={
            assistant_id: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            )
        },
        resource_bindings=tuple(),
    )

    step = envelope.draft.spec.steps[0]
    assert step.assistant_spec.model_ref == "model.model-11111111"
    requirement = envelope.requirements.requirements[0]
    assert isinstance(requirement, FlowPackageModelRequirement)
    assert requirement.slot_ref.ref == "model.model-11111111"
    assert requirement.slot_ref.label == "model 11111111"


def test_export_rejects_untyped_snapshot_resource_ref() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
            assistant_snapshots={
                assistant_id: _snapshot(
                    model_ref=AssistantAuthoringResourceRef(local_ref=str(uuid4()))
                )
            },
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF


def test_export_rejects_non_uuid_snapshot_resource_ref() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
            assistant_snapshots={
                assistant_id: _snapshot(
                    model_ref=AssistantAuthoringResourceRef(
                        local_ref="model.gpt",
                        local_kind=LocalResourceKind.COMPLETION_MODEL,
                    )
                )
            },
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF


def test_export_rejects_snapshot_local_kind_that_cannot_satisfy_slot_kind() -> None:
    assistant_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
            assistant_snapshots={
                assistant_id: _snapshot(
                    model_ref=AssistantAuthoringResourceRef(
                        local_ref=str(uuid4()),
                        local_kind=LocalResourceKind.COLLECTION,
                    )
                )
            },
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF


def test_export_collapses_ambiguous_prior_slots_that_share_one_local_target() -> None:
    first_assistant_id = uuid4()
    second_assistant_id = uuid4()
    model_id = uuid4()

    envelope = _build_envelope(
        flow=_flow(
            steps=[
                _step(1, assistant_id=first_assistant_id),
                _step(2, assistant_id=second_assistant_id),
            ]
        ),
        assistant_snapshots={
            first_assistant_id: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    label="Shared production model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            ),
            second_assistant_id: _snapshot(
                model_ref=AssistantAuthoringResourceRef(
                    local_ref=str(model_id),
                    label="Shared production model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                )
            ),
        },
        resource_bindings=(
            _binding(
                slot_kind=ResourceSlotKind.MODEL,
                slot="source-model-a",
                label="Source model A",
                local_kind=LocalResourceKind.COMPLETION_MODEL,
                local_id=model_id,
            ),
            _binding(
                slot_kind=ResourceSlotKind.MODEL,
                slot="source-model-b",
                label="Source model B",
                local_kind=LocalResourceKind.COMPLETION_MODEL,
                local_id=model_id,
            ),
        ),
    )

    assert [step.assistant_spec.model_ref for step in envelope.draft.spec.steps] == [
        "model.shared-production-model",
        "model.shared-production-model",
    ]
    requirements = envelope.requirements.requirements
    assert len(requirements) == 1
    requirement = requirements[0]
    assert isinstance(requirement, FlowPackageModelRequirement)
    assert requirement.slot_ref.ref == "model.shared-production-model"
    assert requirement.used_by_steps == ["step_1", "step_2"]


def test_export_rejects_duplicate_resource_bindings_for_same_slot() -> None:
    assistant_id = uuid4()
    model_id = uuid4()

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(steps=[_step(1, assistant_id=assistant_id)]),
            assistant_snapshots={
                assistant_id: _snapshot(
                    model_ref=AssistantAuthoringResourceRef(
                        local_ref=str(model_id),
                        local_kind=LocalResourceKind.COMPLETION_MODEL,
                    )
                )
            },
            resource_bindings=(
                _binding(
                    slot_kind=ResourceSlotKind.MODEL,
                    slot="shared-model",
                    label="Shared model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                    local_id=model_id,
                ),
                _binding(
                    slot_kind=ResourceSlotKind.MODEL,
                    slot="shared-model",
                    label="Shared model",
                    local_kind=LocalResourceKind.COMPLETION_MODEL,
                    local_id=uuid4(),
                ),
            ),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.DUPLICATE_RESOURCE_BINDING


def test_export_rejects_invalid_form_schema() -> None:
    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(metadata_json={"form_schema": []}, steps=[]),
            assistant_snapshots={},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.FORM_SCHEMA_INVALID


def test_export_rejects_deeply_nested_json_payloads() -> None:
    assistant_id = uuid4()
    nested_payload: object = "{{ flow_input.text }}"
    for _ in range(40):
        nested_payload = {"nested": nested_payload}

    with pytest.raises(FlowPackageExportError) as exc_info:
        _build_envelope(
            flow=_flow(
                steps=[
                    _step(
                        1,
                        assistant_id=assistant_id,
                        output_contract={"root": nested_payload},
                    )
                ]
            ),
            assistant_snapshots={assistant_id: _snapshot(model_ref=None)},
            resource_bindings=tuple(),
        )

    assert exc_info.value.code is FlowPackageExportErrorCode.JSON_PAYLOAD_TOO_DEEP


def _build_envelope(
    *,
    flow: Flow,
    assistant_snapshots: dict[UUID, AssistantAuthoringSnapshot],
    resource_bindings: tuple[LocalResourceBinding, ...],
):
    return build_flow_package_export_envelope(
        flow=flow,
        assistant_snapshots=assistant_snapshots,
        resource_bindings=resource_bindings,
        manifest_metadata=_manifest_metadata(),
        provenance=_provenance(),
    )


def _flow(
    *,
    steps: list[FlowStep],
    metadata_json: FlowPersistedJsonObject | None = None,
) -> Flow:
    user_id = uuid4()
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Reusable meeting flow",
        description="Portable package export fixture.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=metadata_json,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=steps,
    )


class _FakeFlowPackageExportFlowService:
    def __init__(
        self,
        *,
        assistant_snapshots: AssistantAuthoringSnapshots,
        resource_bindings: tuple[LocalResourceBinding, ...],
        omitted_mcp_assistant_count: int = 0,
    ) -> None:
        self._assistant_snapshots = assistant_snapshots
        self._resource_bindings = resource_bindings
        self._omitted_mcp_assistant_count = omitted_mcp_assistant_count
        self.flow: Flow | None = None
        self.flow_id: UUID | None = None

    async def count_flow_step_assistants_with_mcp_configuration(
        self,
        *,
        flow_id: UUID,
    ) -> int:
        self.flow_id = flow_id
        return self._omitted_mcp_assistant_count

    async def get_flow_assistant_snapshots(
        self,
        flow: Flow,
    ) -> AssistantAuthoringSnapshots:
        self.flow = flow
        return self._assistant_snapshots

    async def list_resource_bindings(
        self,
        *,
        flow_id: UUID,
    ) -> tuple[LocalResourceBinding, ...]:
        self.flow_id = flow_id
        return self._resource_bindings


def _step(
    step_order: int,
    *,
    assistant_id: UUID,
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    input_bindings: FlowPersistedJsonObject | None = None,
    input_contract: FlowPersistedJsonObject | None = None,
    output_contract: FlowPersistedJsonObject | None = None,
    input_config: FlowPersistedJsonObject | None = None,
    output_config: FlowPersistedJsonObject | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id,
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source=input_source,
        input_type=input_type,
        input_contract=input_contract,
        output_mode=output_mode,
        output_type=output_type,
        output_contract=output_contract,
        input_bindings=input_bindings,
        output_classification_override=None,
        input_config=input_config,
        output_config=output_config,
    )


def _snapshot(
    *,
    instructions: str = "Follow the package instructions.",
    model_ref: AssistantAuthoringResourceRef | None,
    knowledge_refs: tuple[AssistantAuthoringResourceRef, ...] = tuple(),
) -> AssistantAuthoringSnapshot:
    return AssistantAuthoringSnapshot(
        instructions=instructions,
        model=model_ref,
        knowledge_refs=knowledge_refs,
    )


def _binding(
    *,
    slot_kind: ResourceSlotKind,
    slot: str,
    label: str,
    local_kind: LocalResourceKind,
    local_id: UUID,
) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(kind=slot_kind, slot=slot, label=label),
        local_kind=local_kind,
        local_id=local_id,
    )


def _manifest_metadata() -> FlowPackageManifestMetadata:
    return FlowPackageManifestMetadata(
        schema_version=1,
        kind=EneoPackageKind.FLOW,
        package_id="se.demo.meeting-report",
        package_version="1.0.0",
        name="Meeting report",
        description="Reusable meeting report flow.",
    )


def _provenance() -> FlowPackageProvenance:
    return FlowPackageProvenance(
        schema_version=1,
        exported_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        source_instance_id="source-instance",
        omissions=[],
    )

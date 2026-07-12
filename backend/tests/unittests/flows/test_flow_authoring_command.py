from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter

from eneo.flows.application.flow_authoring_command import (
    CreateFlowAuthoringCommand,
    EditFlowAuthoringCommand,
    FlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftMaterializationResult,
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    FlowResourceBindingSource,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.main.exceptions import BadRequestException


def test_flow_authoring_command_discriminates_create_and_edit() -> None:
    spec = _spec()
    adapter = TypeAdapter(FlowAuthoringCommand)

    create = adapter.validate_python(
        {
            "kind": "create",
            "space_id": str(uuid4()),
            "spec": spec.model_dump(mode="json"),
            "origin": {
                "kind": "flow_package",
                "package_id": "se.demo.flow",
                "package_version": "1.0.0",
                "content_checksum": "sha256:abc",
            },
        }
    )
    edit = adapter.validate_python(
        {
            "kind": "edit",
            "space_id": str(uuid4()),
            "flow_id": str(uuid4()),
            "expected_revision": 7,
            "spec": spec.model_dump(mode="json"),
            "removed_existing_step_refs": [],
            "origin": {
                "kind": "ai_builder",
                "session_id": str(uuid4()),
                "plan_id": str(uuid4()),
                "spec_hash": spec.spec_hash(),
                "applied_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )

    assert isinstance(create, CreateFlowAuthoringCommand)
    assert isinstance(edit, EditFlowAuthoringCommand)
    assert edit.expected_revision == 7


@pytest.mark.anyio
async def test_apply_uses_origin_binding_source() -> None:
    flow_id = uuid4()
    materializer = _RecordingMaterializer(flow_id=flow_id)
    spec = _spec()
    service = FlowAuthoringCommandService(materializer=materializer)

    result = await service.apply(
        command=CreateFlowAuthoringCommand(
            space_id=uuid4(),
            spec=spec,
            origin=FlowPackageAuthoringOrigin(
                package_id="se.demo.flow",
                package_version="1.0.0",
                content_checksum="sha256:abc",
            ),
        ),
        flow_service=_flow_service_with_transaction(active=True),
    )

    assert result.flow_id == flow_id
    assert materializer.binding_source is FlowResourceBindingSource.PACKAGE_IMPORT


@pytest.mark.anyio
async def test_prepare_rejects_create_command_with_existing_step_ref() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        await FlowAuthoringCommandService().prepare(
            command=CreateFlowAuthoringCommand(
                space_id=uuid4(),
                spec=_spec(existing_step_ref="existing_step_1"),
                origin=FlowPackageAuthoringOrigin(
                    package_id="se.demo.flow",
                    package_version="1.0.0",
                    content_checksum="sha256:abc",
                ),
            ),
            flow_service=SimpleNamespace(),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("assistant_spec", "expected_slot_ref"),
    [
        (
            AssistantSpec(instructions="Use model.", model_ref="model.default"),
            "model.default",
        ),
        (
            AssistantSpec(
                instructions="Use knowledge.",
                knowledge_refs=["knowledge.policy"],
            ),
            "knowledge.policy",
        ),
    ],
)
async def test_prepare_rejects_unresolved_canonical_resource_refs(
    assistant_spec: AssistantSpec,
    expected_slot_ref: str,
) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        await FlowAuthoringCommandService().prepare(
            command=CreateFlowAuthoringCommand(
                space_id=uuid4(),
                spec=_spec(assistant_spec=assistant_spec),
                origin=FlowPackageAuthoringOrigin(
                    package_id="se.demo.flow",
                    package_version="1.0.0",
                    content_checksum="sha256:abc",
                ),
            ),
            flow_service=SimpleNamespace(),
        )

    assert exc_info.value.code == "unresolved_slot_binding"
    assert exc_info.value.context["slot_ref"] == expected_slot_ref


@pytest.mark.anyio
async def test_prepare_accepts_bound_canonical_resource_refs() -> None:
    prepared = await FlowAuthoringCommandService().prepare(
        command=CreateFlowAuthoringCommand(
            space_id=uuid4(),
            spec=_spec(
                assistant_spec=AssistantSpec(
                    instructions="Use model.",
                    model_ref="model.default",
                )
            ),
            origin=FlowPackageAuthoringOrigin(
                package_id="se.demo.flow",
                package_version="1.0.0",
                content_checksum="sha256:abc",
            ),
            resource_bindings=(_resource_binding(),),
        ),
        flow_service=SimpleNamespace(),
    )

    assert prepared.preview.resource_bindings_count == 1
    assert prepared.preview.assistants_to_create == 1


@pytest.mark.anyio
async def test_prepare_allows_transcribe_only_after_model_ref_normalization() -> None:
    prepared = await FlowAuthoringCommandService().prepare(
        command=CreateFlowAuthoringCommand(
            space_id=uuid4(),
            spec=_spec(
                assistant_spec=AssistantSpec(
                    instructions="Transcribe.",
                    model_ref="model.default",
                ),
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            origin=FlowPackageAuthoringOrigin(
                package_id="se.demo.flow",
                package_version="1.0.0",
                content_checksum="sha256:abc",
            ),
        ),
        flow_service=SimpleNamespace(),
    )

    assert prepared.spec.steps[0].assistant_spec.model_ref is None
    assert prepared.preview.steps_created == 1


@pytest.mark.anyio
async def test_prepare_and_materializer_use_same_unresolved_resource_error() -> None:
    command = CreateFlowAuthoringCommand(
        space_id=uuid4(),
        spec=_spec(
            assistant_spec=AssistantSpec(
                instructions="Use model.",
                model_ref="model.default",
            )
        ),
        origin=FlowPackageAuthoringOrigin(
            package_id="se.demo.flow",
            package_version="1.0.0",
            content_checksum="sha256:abc",
        ),
    )

    with pytest.raises(BadRequestException) as prepare_error:
        await FlowAuthoringCommandService().prepare(
            command=command,
            flow_service=SimpleNamespace(),
        )

    with pytest.raises(BadRequestException) as materializer_error:
        await FlowDraftMaterializer().execute(
            changeset=compile_flow_draft_changeset(command.spec, None),
            flow_service=SimpleNamespace(),
            space_id=command.space_id,
            flow_id=None,
            binding_source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )

    assert prepare_error.value.code == materializer_error.value.code
    assert prepare_error.value.context == materializer_error.value.context


@pytest.mark.anyio
async def test_apply_requires_active_transaction() -> None:
    with pytest.raises(RuntimeError, match="active transaction"):
        await FlowAuthoringCommandService(materializer=_RecordingMaterializer()).apply(
            command=CreateFlowAuthoringCommand(
                space_id=uuid4(),
                spec=_spec(),
                origin=FlowPackageAuthoringOrigin(
                    package_id="se.demo.flow",
                    package_version="1.0.0",
                    content_checksum="sha256:abc",
                ),
            ),
            flow_service=_flow_service_with_transaction(active=False),
        )


@pytest.mark.anyio
async def test_apply_requires_inspectable_transaction_owner() -> None:
    with pytest.raises(RuntimeError, match="inspectable transaction owner"):
        await FlowAuthoringCommandService(materializer=_RecordingMaterializer()).apply(
            command=CreateFlowAuthoringCommand(
                space_id=uuid4(),
                spec=_spec(),
                origin=FlowPackageAuthoringOrigin(
                    package_id="se.demo.flow",
                    package_version="1.0.0",
                    content_checksum="sha256:abc",
                ),
            ),
            flow_service=SimpleNamespace(),
        )


def _spec(
    *,
    flow_description: str = "",
    assistant_spec: AssistantSpec | None = None,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    existing_step_ref: str | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flow",
        flow_description=flow_description,
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=existing_step_ref,
                name="Step A",
                assistant_spec=assistant_spec
                or AssistantSpec(instructions="Do something."),
                input_source=InputSource.FLOW_INPUT,
                input_type=input_type,
                output_mode=output_mode,
                output_type=output_type,
            )
        ],
    )


def _resource_binding(
    *,
    slot: str = "default",
    slot_kind: ResourceSlotKind = ResourceSlotKind.MODEL,
    local_kind: LocalResourceKind = LocalResourceKind.COMPLETION_MODEL,
    local_id: UUID | None = None,
) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(kind=slot_kind, slot=slot, label=slot),
        local_kind=local_kind,
        local_id=local_id or uuid4(),
    )


def _flow_service_with_transaction(*, active: bool) -> SimpleNamespace:
    return SimpleNamespace(
        flow_repo=SimpleNamespace(
            session=SimpleNamespace(in_transaction=lambda: active),
        )
    )


class _RecordingMaterializer:
    def __init__(self, *, flow_id: UUID | None = None) -> None:
        self.flow_id = flow_id or uuid4()
        self.binding_source: FlowResourceBindingSource | None = None

    async def execute(self, **kwargs: object) -> FlowDraftMaterializationResult:
        self.binding_source = kwargs["binding_source"]
        return FlowDraftMaterializationResult(
            flow_id=self.flow_id,
            flow_name="Flow",
            draft_revision=1,
            steps_created=1,
            steps_updated=0,
            steps_removed=0,
        )

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.flows.application.flow_authoring_command import (
    CreateFlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    FlowDraftMaterializationResult,
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
)
from eneo.flows.flow_authoring_spec import (
    MAX_FLOW_AUTHORING_STEPS,
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
async def test_a_create_naming_an_existing_step_is_refused_before_any_write() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        await FlowAuthoringCommandService(materializer=_RecordingMaterializer()).apply(
            command=_command(_spec(existing_step_ref="existing_step_1")),
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
async def test_unresolved_canonical_resource_refs_are_refused_before_any_write(
    assistant_spec: AssistantSpec,
    expected_slot_ref: str,
) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        await FlowAuthoringCommandService(materializer=_RecordingMaterializer()).apply(
            command=_command(_spec(assistant_spec=assistant_spec)),
            flow_service=SimpleNamespace(),
        )

    assert exc_info.value.code == "unresolved_slot_binding"
    assert exc_info.value.context["slot_ref"] == expected_slot_ref


@pytest.mark.anyio
async def test_bound_canonical_resource_refs_are_handed_to_the_materializer() -> None:
    materializer = _RecordingMaterializer()
    binding = _resource_binding()

    await FlowAuthoringCommandService(materializer=materializer).apply(
        command=_command(
            _spec(
                assistant_spec=AssistantSpec(
                    instructions="Use model.",
                    model_ref="model.default",
                )
            ),
            resource_bindings=(binding,),
        ),
        flow_service=_flow_service_with_transaction(active=True),
    )

    assert materializer.kwargs["resource_bindings"] == (binding,)
    assert len(materializer.changeset.assistants_to_create) == 1


def _spec_with_steps(count: int) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            StepSpec(
                plan_step_ref=f"step_{index}",
                name=f"Step {index}",
                assistant_spec=AssistantSpec(instructions="Do something."),
                input_source=(
                    InputSource.FLOW_INPUT if index == 1 else InputSource.PREVIOUS_STEP
                ),
            )
            for index in range(1, count + 1)
        ],
    )


@pytest.mark.anyio
async def test_a_spec_over_the_step_limit_is_refused_before_any_write() -> None:
    materializer = _RecordingMaterializer()
    await FlowAuthoringCommandService(materializer=materializer).apply(
        command=_command(_spec_with_steps(MAX_FLOW_AUTHORING_STEPS)),
        flow_service=_flow_service_with_transaction(active=True),
    )
    assert len(materializer.changeset.compiled_steps) == MAX_FLOW_AUTHORING_STEPS

    with pytest.raises(BadRequestException) as exc_info:
        await FlowAuthoringCommandService(materializer=_RecordingMaterializer()).apply(
            command=_command(_spec_with_steps(MAX_FLOW_AUTHORING_STEPS + 1)),
            flow_service=SimpleNamespace(),
        )

    assert exc_info.value.code == "flow_step_limit_exceeded"


@pytest.mark.anyio
async def test_a_transcription_step_is_created_without_its_model_ref() -> None:
    materializer = _RecordingMaterializer()

    await FlowAuthoringCommandService(materializer=materializer).apply(
        command=_command(
            _spec(
                assistant_spec=AssistantSpec(
                    instructions="Transcribe.",
                    model_ref="model.default",
                ),
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            )
        ),
        flow_service=_flow_service_with_transaction(active=True),
    )

    (created,) = materializer.changeset.assistants_to_create
    assert created.assistant_spec.model_ref is None


@pytest.mark.anyio
async def test_apply_and_materializer_use_same_unresolved_resource_error() -> None:
    command = _command(
        _spec(
            assistant_spec=AssistantSpec(
                instructions="Use model.",
                model_ref="model.default",
            )
        )
    )

    with pytest.raises(BadRequestException) as apply_error:
        await FlowAuthoringCommandService(materializer=_RecordingMaterializer()).apply(
            command=command,
            flow_service=SimpleNamespace(),
        )

    with pytest.raises(BadRequestException) as materializer_error:
        await FlowDraftMaterializer().execute(
            changeset=compile_flow_draft_changeset(command.spec),
            flow_service=SimpleNamespace(),
            space_id=command.space_id,
            binding_source=FlowResourceBindingSource.PACKAGE_IMPORT,
        )

    assert apply_error.value.code == materializer_error.value.code
    assert apply_error.value.context == materializer_error.value.context


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
        self.kwargs: dict[str, object] = {}

    @property
    def changeset(self) -> FlowDraftChangeSet:
        changeset = self.kwargs["changeset"]
        assert isinstance(changeset, FlowDraftChangeSet)
        return changeset

    async def execute(self, **kwargs: object) -> FlowDraftMaterializationResult:
        self.kwargs = kwargs
        binding_source = kwargs["binding_source"]
        assert isinstance(binding_source, FlowResourceBindingSource)
        self.binding_source = binding_source
        return FlowDraftMaterializationResult(
            flow_id=self.flow_id,
            flow_name="Flow",
            draft_revision=1,
            steps_created=1,
        )


def _command(
    spec: FlowDraftSpecCore,
    *,
    resource_bindings: tuple[LocalResourceBinding, ...] = (),
) -> CreateFlowAuthoringCommand:
    return CreateFlowAuthoringCommand(
        space_id=uuid4(),
        spec=spec,
        origin=FlowPackageAuthoringOrigin(
            package_id="se.demo.flow",
            package_version="1.0.0",
            content_checksum="sha256:abc",
        ),
        resource_bindings=resource_bindings,
    )

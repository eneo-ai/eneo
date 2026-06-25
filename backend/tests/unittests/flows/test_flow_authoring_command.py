from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter

from intric.flows.application.flow_authoring_command import (
    CreateFlowAuthoringCommand,
    EditFlowAuthoringCommand,
    FlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
)
from intric.flows.application.flow_draft_materialization import (
    FlowDraftMaterializationResult,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)
from intric.flows.flow_resource_bindings import FlowResourceBindingSource
from intric.main.exceptions import BadRequestException


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
                assistant_spec=AssistantSpec(instructions="Do something."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=output_type,
            )
        ],
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

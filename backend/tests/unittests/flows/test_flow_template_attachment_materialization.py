from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.application.flow_authoring_command import TemplateAttachmentIntent
from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_template_attachment_materialization import (
    materialize_template_attachment,
)
from eneo.flows.domain.flow import FlowTemplateAsset
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceKind,
    ResourceSlotKind,
)
from eneo.main.exceptions import BadRequestException


def _step(
    *,
    plan_step_ref: str,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_step_ref,
        name=plan_step_ref,
        assistant_spec=AssistantSpec(instructions=f"Run {plan_step_ref}."),
        input_source=(
            InputSource.FLOW_INPUT
            if plan_step_ref == "step_a"
            else InputSource.PREVIOUS_STEP
        ),
        input_type=InputType.TEXT,
        output_mode=output_mode,
        output_type=output_type,
    )


def _changeset(
    *,
    bindings: dict[str, str] | None = None,
):
    approved_bindings = bindings or {"case_id": "{{ flow_input.case_id }}"}
    spec = FlowDraftSpecCore(
        flow_name="Template flow",
        form_fields=[
            FormFieldSpec(
                name="case_id",
                type="text",
                label="Case ID",
                required=False,
            )
        ],
        steps=[
            _step(plan_step_ref="step_a"),
            _step(
                plan_step_ref="step_b",
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
            ).model_copy(update={"output_config": {"bindings": approved_bindings}}),
        ],
    )
    return compile_flow_draft_changeset(spec, current_flow=None)


def _asset(
    *,
    flow_id: UUID,
    file_id: UUID,
    placeholders: list[str],
) -> FlowTemplateAsset:
    now = datetime.now(timezone.utc)
    return FlowTemplateAsset(
        id=uuid4(),
        flow_id=flow_id,
        space_id=uuid4(),
        tenant_id=uuid4(),
        file_id=file_id,
        name="expected-template.docx",
        checksum="checksum",
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        placeholders=placeholders,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_materialize_template_attachment_injects_only_local_asset_identity() -> (
    None
):
    flow_id = uuid4()
    file_id = uuid4()
    asset = _asset(
        flow_id=flow_id,
        file_id=file_id,
        placeholders=[
            "kundnamn",
            "flow_input.case_id",
            "datum",
            "step_a.output.text",
        ],
    )
    template_asset_service = AsyncMock()
    template_asset_service.create_from_existing_attached_file.return_value = asset

    result = await materialize_template_attachment(
        intent=TemplateAttachmentIntent(
            file_id=file_id,
            terminal_plan_step_ref="step_b",
        ),
        changeset=_changeset(
            bindings={
                "kundnamn": "{{ flow_input.kundnamn }}",
                "flow_input.case_id": "{{ flow_input.case_id }}",
                "datum": "{{ datum }}",
                "step_a.output.text": "{{ step_1.output.text }}",
            }
        ),
        flow_id=flow_id,
        template_asset_service=template_asset_service,
    )

    template_asset_service.create_from_existing_attached_file.assert_awaited_once_with(
        flow_id=flow_id,
        file_id=file_id,
    )
    terminal = result.changeset.compiled_steps[-1]
    assert terminal.output_config == {
        "template_asset_id": str(asset.id),
        "bindings": {
            "kundnamn": "{{ flow_input.kundnamn }}",
            "flow_input.case_id": "{{ flow_input.case_id }}",
            "datum": "{{ datum }}",
            "step_a.output.text": "{{ step_1.output.text }}",
        },
    }
    assert result.changeset.metadata_json == _changeset().metadata_json
    assert result.binding.slot_ref.kind is ResourceSlotKind.TEMPLATE_ASSET
    assert result.binding.slot_ref.slot == "document-template"
    assert result.binding.slot_ref.label == asset.name
    assert result.binding.local_kind is LocalResourceKind.TEMPLATE_ASSET
    assert result.binding.local_id == asset.id


@pytest.mark.asyncio
async def test_materialize_template_attachment_refuses_changed_placeholder_contract() -> (
    None
):
    flow_id = uuid4()
    file_id = uuid4()
    asset = _asset(
        flow_id=flow_id,
        file_id=file_id,
        placeholders=["customer.name"],
    )
    template_asset_service = AsyncMock()
    template_asset_service.create_from_existing_attached_file.return_value = asset

    with pytest.raises(BadRequestException) as exc_info:
        await materialize_template_attachment(
            intent=TemplateAttachmentIntent(
                file_id=file_id,
                terminal_plan_step_ref="step_b",
            ),
            changeset=_changeset(),
            flow_id=flow_id,
            template_asset_service=template_asset_service,
        )

    assert exc_info.value.code == "architecture_materialization_failed"
    assert exc_info.value.context == {
        "reason": "template_placeholder_contract_changed",
        "approved_count": 1,
        "actual_count": 1,
        "missing_placeholders": ["case_id"],
        "added_placeholders": ["customer.name"],
    }


@pytest.mark.asyncio
async def test_materialize_template_attachment_refuses_missing_approved_bindings_before_promotion() -> (
    None
):
    flow_id = uuid4()
    file_id = uuid4()
    asset = _asset(
        flow_id=flow_id,
        file_id=file_id,
        placeholders=[],
    )
    template_asset_service = AsyncMock()
    template_asset_service.create_from_existing_attached_file.return_value = asset

    with pytest.raises(BadRequestException) as exc_info:
        await materialize_template_attachment(
            intent=TemplateAttachmentIntent(
                file_id=file_id,
                terminal_plan_step_ref="step_b",
            ),
            changeset=compile_flow_draft_changeset(
                FlowDraftSpecCore(
                    flow_name="Template flow",
                    steps=[
                        _step(
                            plan_step_ref="step_b",
                            output_mode=OutputMode.TEMPLATE_FILL,
                            output_type=OutputType.DOCX,
                        )
                    ],
                ),
                current_flow=None,
            ),
            flow_id=flow_id,
            template_asset_service=template_asset_service,
        )

    assert exc_info.value.code == "architecture_materialization_failed"
    assert exc_info.value.context["reason"] == "template_binding_contract_missing"
    template_asset_service.create_from_existing_attached_file.assert_not_awaited()

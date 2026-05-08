from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from intric.flows.api.flow_models import FlowOutputDelivery
from intric.flows.flow import Flow, FlowStep
from intric.flows.flow_input_limits import FlowInputLimits
from intric.flows.flow_run_contract_service import FlowRunContractService
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.main.exceptions import NotFoundException


def _flow(*, step: FlowStep) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        created_at=now,
        updated_at=now,
    )


def _step(*, step_order: int, input_type: str) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        input_source="flow_input",
        input_type=input_type,
        output_mode="pass_through",
        output_type="text",
        mcp_policy="inherit",
    )


def _limits() -> FlowInputLimits:
    return FlowInputLimits(
        file_max_size_bytes=12_000_000,
        audio_max_size_bytes=25_000_000,
        max_files_per_run=5,
    )


def _service(
    *,
    flow_service: AsyncMock,
    settings_service: AsyncMock,
    flow_version_repo: AsyncMock,
    template_asset_repo: AsyncMock | None = None,
) -> FlowRunContractService:
    return FlowRunContractService(
        flow_service=flow_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
        template_asset_repo=template_asset_repo or AsyncMock(),
    )


@pytest.mark.asyncio
async def test_get_run_contract_returns_published_inputs_final_output_and_templates() -> (
    None
):
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    template_asset_repo = AsyncMock()

    runtime_step = _step(step_order=1, input_type="text").model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": True,
                    "max_files": 2,
                    "input_format": "document",
                    "label": "Upload",
                    "description": "Attach source files",
                }
            }
        }
    )
    template_step = _step(step_order=2, input_type="text").model_copy(
        update={
            "output_mode": "template_fill",
            "output_type": "docx",
            "output_config": {
                "template_asset_id": str(uuid4()),
                "template_file_id": str(uuid4()),
                "template_checksum": "published-checksum",
                "template_name": "Published template",
                "bindings": {"Body": "{{step_1.output.text}}"},
            },
        }
    )
    flow = _flow(step=runtime_step).model_copy(
        update={
            "published_version": 4,
            "steps": [runtime_step, template_step],
            "metadata_json": {
                "form_schema": {
                    "fields": [
                        {
                            "name": "live_draft_field",
                            "type": "text",
                            "order": 1,
                        }
                    ]
                }
            },
        }
    )
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = _limits()
    asset_id = UUID(str(template_step.output_config["template_asset_id"]))
    template_asset_repo.get.return_value = SimpleNamespace(
        id=asset_id,
        file_id=UUID(str(template_step.output_config["template_file_id"])),
        name="Shared template",
        checksum="published-checksum",
    )
    flow_version_repo.get.return_value = SimpleNamespace(
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow.id),
            "metadata_json": {
                "form_schema": {
                    "fields": [
                        {
                            "name": "published_field",
                            "type": "text",
                            "label": "Published field",
                            "required": True,
                            "order": 1,
                        }
                    ]
                }
            },
            "steps": [
                {
                    "step_id": str(runtime_step.id),
                    "step_order": 1,
                    "assistant_id": str(runtime_step.assistant_id),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "input_config": runtime_step.input_config,
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                },
                {
                    "step_id": str(template_step.id),
                    "step_order": 2,
                    "assistant_id": str(template_step.assistant_id),
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_mode": "template_fill",
                    "output_type": "docx",
                    "output_config": template_step.output_config,
                    "mcp_policy": "inherit",
                },
            ],
        }
    )

    contract = await _service(
        flow_service=flow_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
        template_asset_repo=template_asset_repo,
    ).get_run_contract(flow_id=flow.id)

    assert contract.published_flow_version == 4
    assert contract.final_output is not None
    assert contract.final_output.step_id == template_step.id
    assert contract.final_output.output_type == "docx"
    assert contract.final_output.output_mode == "template_fill"
    assert contract.final_output.delivery == FlowOutputDelivery.ARTIFACT
    assert contract.aggregate_max_files == 2
    assert contract.form_fields[0].name == "published_field"
    assert contract.form_fields[0].label == "Published field"
    assert contract.steps_requiring_input[0].step_id == runtime_step.id
    assert contract.steps_requiring_input[0].label == "Upload"
    assert contract.steps_requiring_input[0].required is True
    assert contract.steps_requiring_input[0].max_files == 2
    assert contract.steps_requiring_input[0].max_file_size_bytes == 12_000_000
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in contract.steps_requiring_input[0].accepted_mimetypes
    )
    assert contract.template_readiness[0].status == "ready"
    assert contract.template_readiness[0].template_asset_id == asset_id


@pytest.mark.asyncio
async def test_get_run_contract_caps_step_file_count_by_tenant_limit() -> None:
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()

    runtime_step = _step(step_order=1, input_type="text").model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "max_files": 10,
                    "input_format": "document",
                    "label": "Upload",
                }
            }
        }
    )
    flow = _flow(step=runtime_step).model_copy(
        update={"published_version": 1, "steps": [runtime_step]}
    )
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = _limits()
    flow_version_repo.get.return_value = SimpleNamespace(
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow.id),
            "steps": [
                {
                    "step_id": str(runtime_step.id),
                    "step_order": 1,
                    "assistant_id": str(runtime_step.assistant_id),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "input_config": runtime_step.input_config,
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ],
        }
    )

    contract = await _service(
        flow_service=flow_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    ).get_run_contract(flow_id=flow.id)

    assert contract.aggregate_max_files == 5
    assert contract.steps_requiring_input[0].max_files == 5


@pytest.mark.asyncio
async def test_get_run_contract_returns_review_steps() -> None:
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()

    review_step = _step(step_order=1, input_type="text").model_copy(
        update={
            "user_description": "Review extracted transcription",
            "output_type": "json",
            "output_contract": {
                "type": "object",
                "required": ["transcription"],
                "properties": {"transcription": {"type": "string"}},
                "additionalProperties": False,
            },
            "review_policy": {"mode": "edit"},
        }
    )
    flow = _flow(step=review_step).model_copy(
        update={"published_version": 2, "steps": [review_step]}
    )
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = _limits()
    flow_version_repo.get.return_value = SimpleNamespace(
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow.id),
            "steps": [
                {
                    "step_id": str(review_step.id),
                    "step_order": 1,
                    "assistant_id": str(review_step.assistant_id),
                    "user_description": review_step.user_description,
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "output_contract": review_step.output_contract,
                    "review_policy": review_step.review_policy,
                    "mcp_policy": "inherit",
                }
            ],
        }
    )

    contract = await _service(
        flow_service=flow_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    ).get_run_contract(flow_id=flow.id)

    assert len(contract.steps_requiring_review) == 1
    review_contract = contract.steps_requiring_review[0]
    assert review_contract.step_id == review_step.id
    assert review_contract.label == "Review extracted transcription"
    assert review_contract.review_mode == "edit"
    assert review_contract.output_type == "json"
    assert review_contract.output_contract == review_step.output_contract


@pytest.mark.asyncio
async def test_get_run_contract_uses_terminal_step_after_review_step() -> None:
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()

    review_step = _step(step_order=1, input_type="text").model_copy(
        update={
            "user_description": "Review transcription",
            "output_type": "json",
            "output_contract": {
                "type": "object",
                "properties": {"transcription": {"type": "string"}},
            },
            "review_policy": {"mode": "edit"},
        }
    )
    final_step = _step(step_order=2, input_type="json").model_copy(
        update={
            "input_source": "previous_step",
            "user_description": "Create Word report",
            "output_type": "docx",
        }
    )
    flow = _flow(step=review_step).model_copy(
        update={"published_version": 3, "steps": [review_step, final_step]}
    )
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = _limits()
    flow_version_repo.get.return_value = SimpleNamespace(
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow.id),
            "steps": [
                {
                    "step_id": str(review_step.id),
                    "step_order": 1,
                    "assistant_id": str(review_step.assistant_id),
                    "user_description": review_step.user_description,
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "output_contract": review_step.output_contract,
                    "review_policy": review_step.review_policy,
                    "mcp_policy": "inherit",
                },
                {
                    "step_id": str(final_step.id),
                    "step_order": 2,
                    "assistant_id": str(final_step.assistant_id),
                    "user_description": final_step.user_description,
                    "input_source": "previous_step",
                    "input_type": "json",
                    "output_mode": "pass_through",
                    "output_type": "docx",
                    "mcp_policy": "inherit",
                },
            ],
        }
    )

    contract = await _service(
        flow_service=flow_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    ).get_run_contract(flow_id=flow.id)

    assert contract.final_output is not None
    assert contract.final_output.step_id == final_step.id
    assert contract.final_output.label == "Create Word report"
    assert contract.final_output.output_type == "docx"
    assert contract.final_output.delivery == FlowOutputDelivery.ARTIFACT
    assert [step.step_id for step in contract.steps_requiring_review] == [
        review_step.id
    ]


@pytest.mark.asyncio
async def test_get_run_contract_marks_missing_template_assets_unavailable() -> None:
    flow_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    template_asset_repo = AsyncMock()

    template_step = _step(step_order=1, input_type="text").model_copy(
        update={
            "output_mode": "template_fill",
            "output_type": "docx",
            "output_config": {
                "template_asset_id": str(uuid4()),
                "template_file_id": str(uuid4()),
                "template_checksum": "published-checksum",
                "template_name": "Published template",
                "bindings": {"Body": "{{step_1.output.text}}"},
            },
        }
    )
    flow = _flow(step=template_step).model_copy(
        update={"published_version": 4, "steps": [template_step]}
    )
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = _limits()
    template_asset_repo.get.side_effect = NotFoundException("missing")
    flow_version_repo.get.return_value = SimpleNamespace(
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow.id),
            "steps": [
                {
                    "step_id": str(template_step.id),
                    "step_order": 1,
                    "assistant_id": str(template_step.assistant_id),
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "template_fill",
                    "output_type": "docx",
                    "output_config": template_step.output_config,
                    "mcp_policy": "inherit",
                }
            ],
        }
    )

    contract = await _service(
        flow_service=flow_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
        template_asset_repo=template_asset_repo,
    ).get_run_contract(flow_id=flow.id)

    assert contract.template_readiness[0].status == "unavailable"
    assert contract.template_readiness[0].message_code == "flow_template_not_accessible"

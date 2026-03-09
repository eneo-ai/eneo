from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile

from intric.flows.flow import Flow, FlowStep
from intric.flows.flow_file_upload_service import FlowFileInputPolicy, FlowFileUploadService
from intric.flows.flow_input_limits import FlowInputLimits
from intric.main.exceptions import BadRequestException, FileNotSupportedException, FileTooLargeException


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


@pytest.mark.asyncio
async def test_policy_uses_first_flow_input_step_by_order() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    audio_step = _step(step_order=2, input_type="audio")
    text_step = _step(step_order=1, input_type="text")
    flow = _flow(step=audio_step).model_copy(update={"steps": [audio_step, text_step]})
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )

    policy = await service.get_input_policy(flow_id=flow.id)

    # First flow_input step is text => no file upload accepted.
    assert policy.input_type == "text"
    assert policy.accepts_file_upload is False
    assert policy.max_file_size_bytes is None
    assert policy.max_files_per_run is None
    assert policy.recommended_run_payload == {"input_payload_json": {"text": "<text-input>"}}


@pytest.mark.asyncio
async def test_policy_for_audio_includes_max_files_and_recommended_payload() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    audio_step = _step(step_order=1, input_type="audio")
    flow = _flow(step=audio_step).model_copy(update={"steps": [audio_step]})
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )

    policy = await service.get_input_policy(flow_id=flow.id)

    assert policy.input_type == "audio"
    assert policy.accepts_file_upload is True
    assert policy.max_file_size_bytes == 25_000_000
    assert policy.max_files_per_run == 10
    assert policy.recommended_run_payload == {
        "file_ids": ["<file-id-uuid>"],
        "input_payload_json": {"text": "optional context for later prompt steps"},
    }


@pytest.mark.asyncio
async def test_upload_rejects_mimetype_not_allowed_for_step_type(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )

    upload = UploadFile(
        filename="not-audio.pdf",
        file=BytesIO(b"fake"),
        headers={"content-type": "application/pdf"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    message = str(exc_info.value)
    assert exc_info.value.code == "unsupported_media_type"
    assert exc_info.value.context == {
        "flow_id": str(flow.id),
        "input_type": "audio",
        "received_type": "application/pdf",
    }
    assert "Unsupported file type 'application/pdf'" in message
    assert "flow input type 'audio'" in message
    assert "Allowed types:" in message

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_without_content_type_is_rejected_with_allowed_types_hint(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )

    upload = UploadFile(
        filename="audio.bin",
        file=BytesIO(b"fake"),
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    message = str(exc_info.value)
    assert exc_info.value.code == "unsupported_media_type"
    assert exc_info.value.context == {
        "flow_id": str(flow.id),
        "input_type": "audio",
        "received_type": "missing",
    }
    assert "Unsupported file type 'missing'" in message
    assert "flow input type 'audio'" in message
    assert "Allowed types:" in message

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_wraps_file_too_large_with_effective_limit_message(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )
    file_service.save_file.side_effect = FileTooLargeException("File too large.")

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mpeg"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(FileTooLargeException, match="25000000") as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert exc_info.value.code == "file_too_large"
    assert exc_info.value.context == {
        "flow_id": str(flow.id),
        "max_file_size_bytes": 25_000_000,
    }

    file_service.save_file.assert_awaited_once()
    assert file_service.save_file.await_args.kwargs["max_size"] == 25_000_000


@pytest.mark.asyncio
async def test_upload_document_input_uses_file_limit_not_audio_limit(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="document"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )
    file_service.save_file.return_value = AsyncMock()

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="doc.pdf",
        file=BytesIO(b"%PDF-1.4 fake"),
        headers={"content-type": "application/pdf"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_awaited_once()
    assert file_service.save_file.await_args.kwargs["max_size"] == 11_000_000


@pytest.mark.asyncio
async def test_upload_accepts_content_type_with_parameters(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )
    file_service.save_file.return_value = AsyncMock()

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mpeg; charset=binary"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_rejects_when_sniffed_content_type_is_not_allowed(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="spoofed.mp3",
        file=BytesIO(b"%PDF-1.4 fake"),
        headers={"content-type": "audio/mpeg"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    with pytest.raises(
        FileNotSupportedException,
        match="Detected file type 'application/pdf'",
    ) as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert exc_info.value.code == "unsupported_media_type"
    assert exc_info.value.context == {
        "flow_id": str(flow.id),
        "input_type": "audio",
        "received_type": "audio/mpeg",
        "detected_type": "application/pdf",
    }


@pytest.mark.asyncio
async def test_upload_rejects_zero_byte_file_with_clear_error(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="empty.wav",
        file=BytesIO(b""),
        headers={"content-type": "audio/wav"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(BadRequestException, match="Uploaded file is empty") as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert exc_info.value.code == "flow_input_file_empty"
    assert exc_info.value.context == {"flow_id": str(flow.id)}

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_declared_type_even_if_sniffed_type_is_allowed(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="declared-pdf-but-audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "application/pdf"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert "Unsupported file type 'application/pdf'" in str(exc_info.value)
    assert "flow input type 'audio'" in str(exc_info.value)

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_uses_declared_type_when_sniffer_returns_unknown(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )
    file_service.save_file.return_value = AsyncMock()

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mpeg"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "application/octet-stream",
    )

    await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_accepts_declared_audio_mp3_alias(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )
    file_service.save_file.return_value = AsyncMock()

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mp3"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_rejects_flows_without_file_upload_input() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="text"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mpeg"},
    )

    with pytest.raises(BadRequestException, match="does not accept file uploads") as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert exc_info.value.code == "flow_input_upload_not_supported"

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_when_policy_limit_is_missing(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )
    service.get_input_policy = AsyncMock(
        return_value=FlowFileInputPolicy(
            flow_id=flow.id,
            input_type="audio",
            input_source="flow_input",
            accepts_file_upload=True,
            accepted_mimetypes=["audio/mpeg"],
            max_file_size_bytes=None,
            max_files_per_run=10,
            recommended_run_payload={"file_ids": ["<file-id-uuid>"]},
        )
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mpeg"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert exc_info.value.code == "flow_input_policy_missing_limit"
    assert exc_info.value.context == {"flow_id": str(flow.id)}
    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_for_audio_uses_tenant_audio_max_files() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    audio_step = _step(step_order=1, input_type="audio")
    flow = _flow(step=audio_step).model_copy(update={"steps": [audio_step]})
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
        audio_max_files_per_run=20,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )

    policy = await service.get_input_policy(flow_id=flow.id)

    assert policy.max_files_per_run == 20


@pytest.mark.asyncio
async def test_policy_for_document_with_file_count_limit() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    doc_step = _step(step_order=1, input_type="document")
    flow = _flow(step=doc_step).model_copy(update={"steps": [doc_step]})
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
        max_files_per_run=5,
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
    )

    policy = await service.get_input_policy(flow_id=flow.id)

    assert policy.max_files_per_run == 5


@pytest.mark.asyncio
async def test_get_run_contract_returns_runtime_steps_and_template_readiness() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
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
        update={"published_version": 4, "steps": [runtime_step, template_step]}
    )
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=12_000_000,
        audio_max_size_bytes=25_000_000,
        max_files_per_run=5,
    )
    asset_id = UUID(str(template_step.output_config["template_asset_id"]))
    template_asset_repo.get.return_value = SimpleNamespace(
        id=asset_id,
        file_id=UUID(str(template_step.output_config["template_file_id"])),
        name="Shared template",
        checksum="published-checksum",
    )
    flow_version_repo.get.return_value = SimpleNamespace(
        definition_json={
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
            ]
        }
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
        template_asset_repo=template_asset_repo,
    )

    contract = await service.get_run_contract(flow_id=flow.id)

    assert contract["published_flow_version"] == 4
    assert contract["aggregate_max_files"] == 2
    assert contract["steps_requiring_input"][0]["step_id"] == runtime_step.id
    assert contract["steps_requiring_input"][0]["label"] == "Upload"
    assert contract["steps_requiring_input"][0]["required"] is True
    assert contract["steps_requiring_input"][0]["max_files"] == 2
    assert contract["steps_requiring_input"][0]["max_file_size_bytes"] == 12_000_000
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in contract["steps_requiring_input"][0]["accepted_mimetypes"]
    )
    assert contract["template_readiness"][0]["status"] == "ready"
    assert contract["template_readiness"][0]["template_asset_id"] == asset_id


@pytest.mark.asyncio
async def test_upload_runtime_file_for_step_rejects_unknown_step_id() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    template_asset_repo = AsyncMock()

    runtime_step = _step(step_order=1, input_type="text").model_copy(
        update={"input_config": {"runtime_input": {"enabled": True}}}
    )
    flow = _flow(step=runtime_step).model_copy(update={"published_version": 1, "steps": [runtime_step]})
    flow_service.get_flow.return_value = flow
    flow_version_repo.get.return_value = SimpleNamespace(
        definition_json={
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
            ]
        }
    )

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
        template_asset_repo=template_asset_repo,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=uuid4(),
            upload_file=UploadFile(filename="x.txt", file=BytesIO(b"content")),
        )

    assert exc_info.value.code == "flow_run_unknown_step_input"

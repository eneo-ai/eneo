from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from intric.flows.flow import Flow, FlowStep
from intric.flows.flow_file_upload_service import FlowFileUploadService
from intric.main.exceptions import BadRequestException, FileNotSupportedException, FileTooLargeException
from intric.settings.settings import FlowInputLimitsPublic


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
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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
async def test_upload_rejects_mimetype_not_allowed_for_step_type() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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

    with pytest.raises(FileNotSupportedException, match="Allowed types:"):
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_without_content_type_is_rejected_with_allowed_types_hint() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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

    with pytest.raises(FileNotSupportedException, match="Allowed types:"):
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_wraps_file_too_large_with_effective_limit_message(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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

    with pytest.raises(FileTooLargeException, match="25000000"):
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_awaited_once()
    assert file_service.save_file.await_args.kwargs["max_size"] == 25_000_000


@pytest.mark.asyncio
async def test_upload_document_input_uses_file_limit_not_audio_limit(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="document"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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

    with pytest.raises(FileNotSupportedException, match="Detected file type 'application/pdf'"):
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_uses_declared_type_when_sniffer_returns_unknown(monkeypatch) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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
async def test_upload_rejects_flows_without_file_upload_input() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="text"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits.return_value = FlowInputLimitsPublic(
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

    with pytest.raises(BadRequestException, match="does not accept file uploads"):
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    file_service.save_file.assert_not_awaited()

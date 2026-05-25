from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from intric.flows.flow import Flow, FlowStep
from intric.flows.flow_file_upload_service import FlowFileUploadService
from intric.flows.flow_input_limits import FlowInputLimits
from intric.flows.flow_run_contract_service import FlowRunContractService
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.main.exceptions import (
    BadRequestException,
    FileNotSupportedException,
    FileTooLargeException,
)


def _flow(*, step: FlowStep) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        published_version=1,
        created_at=now,
        updated_at=now,
    )


def _step(*, step_order: int, input_type: str) -> FlowStep:
    input_config = None
    if input_type in {"audio", "document", "file"}:
        input_config = {
            "runtime_input": {
                "enabled": True,
                "input_format": input_type,
            }
        }
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        input_source="flow_input",
        input_type=input_type,
        input_config=input_config,
        output_mode="pass_through",
        output_type="text",
        mcp_policy="inherit",
    )


def _definition_json(flow: Flow, step: FlowStep) -> dict[str, object]:
    return {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(flow.id),
        "steps": [
            {
                "step_id": str(step.id),
                "step_order": step.step_order,
                "assistant_id": str(step.assistant_id),
                "input_source": step.input_source,
                "input_type": step.input_type,
                "input_config": step.input_config,
                "output_mode": step.output_mode,
                "output_type": step.output_type,
                "mcp_policy": step.mcp_policy,
            }
        ],
    }


def _version_repo(flow: Flow, published_step: FlowStep | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get.return_value = SimpleNamespace(
        definition_json=_definition_json(flow, published_step or flow.steps[0])
    )
    return repo


def _service(
    *,
    flow_service: AsyncMock,
    file_service: AsyncMock,
    settings_service: AsyncMock,
    flow_version_repo: AsyncMock,
) -> FlowFileUploadService:
    return FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )


@pytest.mark.asyncio
async def test_flow_upload_and_run_contract_share_runtime_input_spec() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    runtime_step = _step(step_order=1, input_type="audio").model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": True,
                    "input_format": "audio",
                    "max_files": 4,
                    "label": "Recording",
                }
            }
        }
    )
    flow = _flow(step=runtime_step)
    flow_service.get_flow.return_value = flow
    limits = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
        audio_max_files_per_run=20,
    )
    settings_service.get_flow_input_limits_resolved.return_value = limits
    flow_version_repo = _version_repo(flow, published_step=runtime_step)

    contract = await FlowRunContractService(
        flow_service=flow_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
        template_asset_repo=AsyncMock(),
    ).get_run_contract(flow_id=flow.id)
    upload_policy = await _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )._get_published_flow_upload_policy(flow_id=flow.id)

    [runtime_input] = contract.steps_requiring_input
    assert runtime_input.max_files == upload_policy.max_files_per_run == 4
    assert (
        runtime_input.max_file_size_bytes
        == upload_policy.max_file_size_bytes
        == 25_000_000
    )
    assert sorted(runtime_input.accepted_mimetypes) == sorted(
        upload_policy.accepted_mimetypes
    )


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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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
async def test_upload_wraps_file_too_large_with_effective_limit_message(
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
    file_service.save_file.side_effect = FileTooLargeException("File too large.")

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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
async def test_upload_document_input_uses_file_limit_not_audio_limit(
    monkeypatch,
) -> None:
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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
async def test_upload_offloads_file_inspection_to_thread(monkeypatch) -> None:
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mpeg"},
    )

    calls: list[str] = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service.asyncio.to_thread",
        fake_to_thread,
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service.magic.from_buffer",
        lambda _chunk, mime=True: "audio/mpeg",
    )

    await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)

    assert calls == ["_is_empty_upload_file", "_sniff_mimetype"]
    file_service.save_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_rejects_when_sniffed_content_type_is_not_allowed(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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
async def test_upload_rejects_declared_type_even_if_sniffed_type_is_allowed(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    flow = _flow(step=_step(step_order=1, input_type="audio"))
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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
async def test_upload_uses_declared_type_when_sniffer_returns_unknown(
    monkeypatch,
) -> None:
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
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

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
    )
    upload = UploadFile(
        filename="audio.mp3",
        file=BytesIO(b"fake"),
        headers={"content-type": "audio/mpeg"},
    )

    with pytest.raises(
        BadRequestException, match="does not accept file uploads"
    ) as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert exc_info.value.code == "flow_input_upload_not_supported"

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_upload_uses_published_input_not_draft_input(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    draft_step = _step(step_order=1, input_type="audio")
    published_step = _step(step_order=1, input_type="document")
    flow = _flow(step=draft_step).model_copy(update={"steps": [draft_step]})
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )
    file_service.save_file.return_value = AsyncMock()

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow, published_step=published_step),
    )
    upload = UploadFile(
        filename="published.pdf",
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
async def test_flow_upload_rejects_when_published_input_rejects_draft_allowed_file(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    draft_step = _step(step_order=1, input_type="document")
    published_step = _step(step_order=1, input_type="audio")
    flow = _flow(step=draft_step).model_copy(update={"steps": [draft_step]})
    flow_service.get_flow.return_value = flow
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=11_000_000,
        audio_max_size_bytes=25_000_000,
    )

    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow, published_step=published_step),
    )
    upload = UploadFile(
        filename="draft-allowed.pdf",
        file=BytesIO(b"%PDF-1.4 fake"),
        headers={"content-type": "application/pdf"},
    )
    monkeypatch.setattr(
        "intric.flows.flow_file_upload_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_file_for_flow(flow_id=flow.id, upload_file=upload)
    assert exc_info.value.context == {
        "flow_id": str(flow.id),
        "input_type": "audio",
        "received_type": "application/pdf",
        "detected_type": "application/pdf",
    }
    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_runtime_file_for_step_rejects_unknown_step_id() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()

    runtime_step = _step(step_order=1, input_type="text").model_copy(
        update={"input_config": {"runtime_input": {"enabled": True}}}
    )
    flow = _flow(step=runtime_step).model_copy(
        update={"published_version": 1, "steps": [runtime_step]}
    )
    flow_service.get_flow.return_value = flow
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

    service = FlowFileUploadService(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=uuid4(),
            upload_file=UploadFile(filename="x.txt", file=BytesIO(b"content")),
        )

    assert exc_info.value.code == "flow_run_unknown_step_input"

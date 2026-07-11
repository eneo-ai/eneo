from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError

from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_input_limits import FlowInputLimits
from eneo.flows.flow_run_contract_service import FlowRunContractService
from eneo.flows.flow_runtime_file_service import FlowRuntimeFileService
from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    published_definition_checksum,
)
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    FileNotSupportedException,
    FileTooLargeException,
    NotFoundException,
)

RUNTIME_ATTACHMENT_CONSTRAINTS = (
    "fk_flow_run_step_input_files_file_id_files",
    "fk_flow_run_step_input_files_runtime_upload",
    "fk_flow_run_step_result_files_file_id_files",
)


class _Transaction:
    def __init__(self, session: "_Session"):
        self.session = session

    async def __aenter__(self):
        self.session.events.append("begin")
        self.session._active_transaction = True
        return None

    async def __aexit__(self, exc_type, exc, traceback):
        self.session.events.append("exit")
        self.session.exit_exc_type = exc_type
        self.session._active_transaction = False
        return None


class _Session:
    def __init__(self, *, in_transaction: bool = False):
        self._in_transaction = in_transaction
        self._active_transaction = False
        self.begin_calls = 0
        self.exit_exc_type: type[BaseException] | None = None
        self.events: list[str] = []

    def in_transaction(self) -> bool:
        return self._in_transaction or self._active_transaction

    def begin(self) -> _Transaction:
        self.begin_calls += 1
        return _Transaction(self)


class _ConstraintOrigin(Exception):
    def __init__(self, constraint_name: str):
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


def _user(*, tenant_id=None):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        active_api_key=None,
    )


def _runtime_upload_repo(*, session: _Session | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.session = session or _Session()
    repo.exists_for_owner.return_value = True
    return repo


def _integrity_error_for_constraint(constraint_name: str) -> IntegrityError:
    return IntegrityError(
        statement="DELETE FROM files",
        params={},
        orig=_ConstraintOrigin(constraint_name),
    )


def _integrity_error_with_origin_message(message: str) -> IntegrityError:
    return IntegrityError(
        statement="DELETE FROM files",
        params={},
        orig=Exception(message),
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
    definition_json = _definition_json(flow, published_step or flow.steps[0])
    repo.get.return_value = SimpleNamespace(
        version=flow.published_version,
        definition_checksum=published_definition_checksum(definition_json),
        definition_json=definition_json,
    )
    return repo


def _service(
    *,
    flow_service: AsyncMock,
    file_service: AsyncMock,
    settings_service: AsyncMock,
    flow_version_repo: AsyncMock,
    user=None,
    session: _Session | None = None,
    runtime_upload_repo: AsyncMock | None = None,
) -> FlowRuntimeFileService:
    session = session or _Session()
    file_service.repo = SimpleNamespace(session=session)
    runtime_upload_repo = runtime_upload_repo or _runtime_upload_repo(session=session)
    runtime_upload_repo.session = session
    return FlowRuntimeFileService(
        user=user or _user(),
        session=session,
        flow_service=flow_service,
        file_service=file_service,
        runtime_upload_repo=runtime_upload_repo,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )


@pytest.mark.asyncio
async def test_upload_runtime_file_requires_persisted_flow_id() -> None:
    runtime_step = _step(step_order=1, input_type="document")
    assert runtime_step.id is not None
    flow = _flow(step=runtime_step).model_copy(update={"id": None})
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(FlowPersistedIdMissingError):
        await service.upload_runtime_file_for_step(
            flow_id=uuid4(),
            step_id=runtime_step.id,
            upload_file=UploadFile(filename="input.txt", file=BytesIO(b"content")),
        )

    flow_version_repo.get.assert_not_awaited()
    file_service.document_from_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_step_upload_and_run_contract_share_runtime_input_spec(
    monkeypatch,
) -> None:
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
    file_service.save_file.return_value = SimpleNamespace(
        id=uuid4(),
        name="recording.mp3",
        size=1024,
        mimetype="audio/mpeg",
    )
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
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )
    upload = UploadFile(
        filename="recording.mp3",
        file=BytesIO(b"fake audio"),
        headers={"content-type": "audio/mpeg"},
    )
    monkeypatch.setattr(
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id,
        step_id=runtime_step.id,
        upload_file=upload,
    )

    [runtime_input] = contract.steps_requiring_input
    assert runtime_input.max_files == 4
    assert runtime_input.max_file_size_bytes == 25_000_000
    assert "audio/mpeg" in runtime_input.accepted_mimetypes
    file_service.save_file.assert_awaited_once()
    assert file_service.save_file.await_args.kwargs["max_size"] == (
        runtime_input.max_file_size_bytes
    )


@pytest.mark.asyncio
async def test_upload_runtime_file_for_step_records_flow_upload_binding(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    session = _Session()
    runtime_upload_repo = _runtime_upload_repo()

    runtime_step = _step(step_order=1, input_type="document")
    flow = _flow(step=runtime_step)
    user = _user(tenant_id=flow.tenant_id)
    file_id = uuid4()
    flow_service.get_flow.return_value = flow

    async def save_file(*args, **kwargs):
        session.events.append("save_file")
        assert session.in_transaction()
        return SimpleNamespace(
            id=file_id,
            name="source.pdf",
            size=1024,
            mimetype="application/pdf",
        )

    async def create_runtime_upload(**kwargs):
        session.events.append("create_runtime_upload")
        assert session.in_transaction()

    file_service.save_file.side_effect = save_file
    runtime_upload_repo.create.side_effect = create_runtime_upload
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )
    service = _service(
        user=user,
        session=session,
        flow_service=flow_service,
        file_service=file_service,
        runtime_upload_repo=runtime_upload_repo,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
    )
    upload = UploadFile(
        filename="source.pdf",
        file=BytesIO(b"%PDF-1.4 fake"),
        headers={"content-type": "application/pdf"},
    )
    monkeypatch.setattr(
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id,
        step_id=runtime_step.id,
        upload_file=upload,
    )

    runtime_upload_repo.create.assert_awaited_once()
    assert session.begin_calls == 1
    assert session.events == ["begin", "save_file", "create_runtime_upload", "exit"]
    create_kwargs = runtime_upload_repo.create.await_args.kwargs
    assert create_kwargs["file_id"] == file_id
    assert create_kwargs["flow_id"] == flow.id
    assert create_kwargs["tenant_id"] == flow.tenant_id
    assert create_kwargs["uploaded_for_step_id"] == runtime_step.id
    assert create_kwargs["principal"].principal_user_id == user.id


@pytest.mark.asyncio
async def test_upload_runtime_file_rolls_back_when_binding_insert_fails(
    monkeypatch,
) -> None:
    class BindingInsertFailure(RuntimeError):
        pass

    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    session = _Session()
    runtime_upload_repo = _runtime_upload_repo()

    runtime_step = _step(step_order=1, input_type="document")
    flow = _flow(step=runtime_step)
    user = _user(tenant_id=flow.tenant_id)
    file_id = uuid4()
    flow_service.get_flow.return_value = flow

    async def save_file(*args, **kwargs):
        session.events.append("save_file")
        assert session.in_transaction()
        return SimpleNamespace(
            id=file_id,
            name="source.pdf",
            size=1024,
            mimetype="application/pdf",
        )

    async def create_runtime_upload(**kwargs):
        session.events.append("create_runtime_upload")
        assert session.in_transaction()
        raise BindingInsertFailure("binding insert failed")

    file_service.save_file.side_effect = save_file
    runtime_upload_repo.create.side_effect = create_runtime_upload
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=10_000_000,
        audio_max_size_bytes=25_000_000,
    )
    service = _service(
        user=user,
        session=session,
        flow_service=flow_service,
        file_service=file_service,
        runtime_upload_repo=runtime_upload_repo,
        settings_service=settings_service,
        flow_version_repo=_version_repo(flow),
    )
    upload = UploadFile(
        filename="source.pdf",
        file=BytesIO(b"%PDF-1.4 fake"),
        headers={"content-type": "application/pdf"},
    )
    monkeypatch.setattr(
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    with pytest.raises(BindingInsertFailure):
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=runtime_step.id,
            upload_file=upload,
        )

    assert session.begin_calls == 1
    assert session.events == ["begin", "save_file", "create_runtime_upload", "exit"]
    assert session.exit_exc_type is BindingInsertFailure


def test_service_rejects_split_upload_write_sessions() -> None:
    file_service = AsyncMock()
    file_service.repo = SimpleNamespace(session=_Session())
    runtime_upload_repo = _runtime_upload_repo(session=_Session())

    with pytest.raises(RuntimeError, match="share the injected AsyncSession"):
        FlowRuntimeFileService(
            user=_user(),
            session=_Session(),
            flow_service=AsyncMock(),
            file_service=file_service,
            runtime_upload_repo=runtime_upload_repo,
            settings_service=AsyncMock(),
            flow_version_repo=AsyncMock(),
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
        )
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
        )
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(FileTooLargeException, match="25000000") as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
        )
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
    )

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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
    )

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
        "eneo.flows.flow_runtime_file_service.asyncio.to_thread",
        fake_to_thread,
    )
    monkeypatch.setattr(
        "eneo.flows.flow_runtime_file_service.magic.from_buffer",
        lambda _chunk, mime=True: "audio/mpeg",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
    )

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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    with pytest.raises(
        FileNotSupportedException,
        match="Detected file type 'application/pdf'",
    ) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
        )
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: None,
    )

    with pytest.raises(
        FlowBadRequestException, match="Uploaded file is empty"
    ) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
        )
    assert exc_info.value.code == FlowApiErrorCode.RUNTIME_FILE_EMPTY.value
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
        )
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "application/octet-stream",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
    )

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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "audio/mpeg",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id, step_id=flow.steps[0].id, upload_file=upload
    )

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
        BadRequestException, match="Runtime input is not enabled"
    ) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=flow.steps[0].id,
            upload_file=upload,
        )
    assert exc_info.value.code == "flow_run_runtime_input_disabled"

    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_file_upload_uses_published_input_not_draft_input(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    draft_step = _step(step_order=1, input_type="audio")
    published_step = draft_step.model_copy(
        update={
            "input_type": "document",
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "input_format": "document",
                }
            },
        }
    )
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    await service.upload_runtime_file_for_step(
        flow_id=flow.id,
        step_id=flow.steps[0].id,
        upload_file=upload,
    )

    file_service.save_file.assert_awaited_once()
    assert file_service.save_file.await_args.kwargs["max_size"] == 11_000_000


@pytest.mark.asyncio
async def test_runtime_file_upload_rejects_when_published_input_rejects_draft_allowed_file(
    monkeypatch,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()

    draft_step = _step(step_order=1, input_type="document")
    published_step = draft_step.model_copy(
        update={
            "input_type": "audio",
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "input_format": "audio",
                }
            },
        }
    )
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
        "eneo.flows.flow_runtime_file_service._sniff_mimetype",
        lambda _upload_file: "application/pdf",
    )

    with pytest.raises(FileNotSupportedException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=flow.steps[0].id,
            upload_file=upload,
        )
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
    definition_json = {
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
    flow_version_repo.get.return_value = SimpleNamespace(
        version=flow.published_version,
        definition_checksum=published_definition_checksum(definition_json),
        definition_json=definition_json,
    )

    session = _Session()
    file_service.repo = SimpleNamespace(session=session)
    runtime_upload_repo = _runtime_upload_repo(session=session)
    service = FlowRuntimeFileService(
        user=_user(),
        session=session,
        flow_service=flow_service,
        file_service=file_service,
        runtime_upload_repo=runtime_upload_repo,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    unknown_step_id = uuid4()

    with pytest.raises(BadRequestException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=unknown_step_id,
            upload_file=UploadFile(filename="x.txt", file=BytesIO(b"content")),
        )

    assert exc_info.value.code == "flow_run_unknown_step_input"
    assert exc_info.value.context == {"step_id": str(unknown_step_id)}


@pytest.mark.asyncio
async def test_upload_runtime_file_for_step_requires_published_flow() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()

    runtime_step = _step(step_order=1, input_type="document")
    flow = _flow(step=runtime_step).model_copy(
        update={"published_version": None, "steps": [runtime_step]}
    )
    flow_service.get_flow.return_value = flow
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(FlowBadRequestException) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=runtime_step.id,
            upload_file=UploadFile(filename="x.txt", file=BytesIO(b"content")),
        )

    assert exc_info.value.code is FlowApiErrorCode.FLOW_NOT_PUBLISHED
    assert str(exc_info.value) == (
        "Flow must be published before runtime files can be uploaded."
    )
    flow_version_repo.get.assert_not_awaited()
    settings_service.get_flow_input_limits_resolved.assert_not_awaited()
    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_runtime_file_rejects_published_snapshot_without_executable_steps() -> (
    None
):
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()

    runtime_step = _step(step_order=1, input_type="text").model_copy(
        update={"input_config": {"runtime_input": {"enabled": True}}}
    )
    flow = _flow(step=runtime_step).model_copy(
        update={"published_version": 3, "steps": [runtime_step]}
    )
    flow_service.get_flow.return_value = flow
    definition_json = {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(flow.id),
        "steps": [],
    }
    flow_version_repo.get.return_value = SimpleNamespace(
        version=flow.published_version,
        definition_checksum=published_definition_checksum(definition_json),
        definition_json=definition_json,
    )
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(FlowPublishedDefinitionWithoutExecutableStepsError) as exc_info:
        await service.upload_runtime_file_for_step(
            flow_id=flow.id,
            step_id=runtime_step.id,
            upload_file=UploadFile(filename="x.txt", file=BytesIO(b"content")),
        )

    assert exc_info.value.flow_id == flow.id
    assert exc_info.value.flow_version == 3
    settings_service.get_flow_input_limits_resolved.assert_not_awaited()
    file_service.save_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_runtime_file_deletes_owned_orphan_file() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(step=_step(step_order=1, input_type="audio"))
    file_id = uuid4()
    deleted_file = SimpleNamespace(id=file_id, name="orphan.pdf")
    flow_service.get_flow.return_value = flow
    file_service.delete_file.return_value = deleted_file
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    result = await service.delete_runtime_file(flow_id=flow.id, file_id=file_id)

    assert result is deleted_file
    file_service.delete_file.assert_awaited_once_with(file_id)
    flow_version_repo.get.assert_not_called()
    settings_service.get_flow_input_limits_resolved.assert_not_called()


@pytest.mark.asyncio
async def test_delete_runtime_file_hides_file_without_flow_upload_binding() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    runtime_upload_repo = _runtime_upload_repo()
    runtime_upload_repo.exists_for_owner.return_value = False
    flow = _flow(step=_step(step_order=1, input_type="audio"))
    file_id = uuid4()
    flow_service.get_flow.return_value = flow
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        runtime_upload_repo=runtime_upload_repo,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.delete_runtime_file(flow_id=flow.id, file_id=file_id)

    assert exc_info.value.code == "not_found"
    runtime_upload_repo.exists_for_owner.assert_awaited_once()
    file_service.delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_runtime_file_requires_published_flow() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(step=_step(step_order=1, input_type="audio")).model_copy(
        update={"published_version": None}
    )
    flow_service.get_flow.return_value = flow
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.delete_runtime_file(flow_id=flow.id, file_id=uuid4())

    assert isinstance(exc_info.value, FlowBadRequestException)
    assert exc_info.value.code is FlowApiErrorCode.FLOW_NOT_PUBLISHED
    assert exc_info.value.code == "flow_not_published"
    assert str(exc_info.value) == (
        "Flow must be published before runtime files can be deleted."
    )
    file_service.delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_runtime_file_maps_missing_or_unowned_to_not_found() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(step=_step(step_order=1, input_type="audio"))
    file_id = uuid4()
    flow_service.get_flow.return_value = flow
    file_service.delete_file.side_effect = NotFoundException()
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.delete_runtime_file(flow_id=flow.id, file_id=file_id)

    assert exc_info.value.code == "not_found"


@pytest.mark.parametrize("constraint_name", RUNTIME_ATTACHMENT_CONSTRAINTS)
@pytest.mark.asyncio
async def test_delete_runtime_file_maps_runtime_attachment_constraints(
    constraint_name: str,
) -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(step=_step(step_order=1, input_type="audio"))
    file_id = uuid4()
    flow_service.get_flow.return_value = flow
    file_service.delete_file.side_effect = _integrity_error_for_constraint(
        constraint_name
    )
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(ConflictException) as exc_info:
        await service.delete_runtime_file(flow_id=flow.id, file_id=file_id)

    assert str(exc_info.value) == "Runtime file is already attached to a flow run."
    assert exc_info.value.code == "flow_runtime_file_attached"
    assert exc_info.value.context == {
        "flow_id": str(flow.id),
        "file_id": str(file_id),
    }


@pytest.mark.asyncio
async def test_delete_runtime_file_maps_asyncpg_attachment_message() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(step=_step(step_order=1, input_type="audio"))
    file_id = uuid4()
    flow_service.get_flow.return_value = flow
    file_service.delete_file.side_effect = _integrity_error_with_origin_message(
        'violates foreign key constraint "fk_flow_run_step_input_files_file_id_files"'
    )
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(ConflictException) as exc_info:
        await service.delete_runtime_file(flow_id=flow.id, file_id=file_id)

    assert exc_info.value.code == "flow_runtime_file_attached"
    assert exc_info.value.context == {
        "flow_id": str(flow.id),
        "file_id": str(file_id),
    }


@pytest.mark.asyncio
async def test_delete_runtime_file_reraises_unrelated_integrity_error() -> None:
    flow_service = AsyncMock()
    file_service = AsyncMock()
    settings_service = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(step=_step(step_order=1, input_type="audio"))
    error = _integrity_error_for_constraint("fk_flow_template_assets_file_id_files")
    flow_service.get_flow.return_value = flow
    file_service.delete_file.side_effect = error
    service = _service(
        flow_service=flow_service,
        file_service=file_service,
        settings_service=settings_service,
        flow_version_repo=flow_version_repo,
    )

    with pytest.raises(IntegrityError) as exc_info:
        await service.delete_runtime_file(flow_id=flow.id, file_id=uuid4())

    assert exc_info.value is error

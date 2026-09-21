from unittest.mock import AsyncMock

import httpx
import pytest

from eneo.files import audio
from eneo.files.transcriber import Transcriber
from eneo.flows.flow_api_error_code import FLOW_TYPED_IO_ERROR_CODES, FlowApiErrorCode
from eneo.flows.flow_error_taxonomy import (
    FLOW_ERROR_TAXONOMY,
    validate_flow_error_taxonomy,
)
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.runtime.diarizing_transcription import DiarizingFlowTranscriber
from eneo.flows.runtime.remote_transcription import RemoteFlowTranscriber
from eneo.flows.runtime.transcription import transcribe_audio_input
from eneo.main.config import get_settings
from eneo.main.exceptions import TypedIOValidationException
from tests.unit.files import test_audio
from tests.unit.flows.runtime.test_remote_transcription import (
    RESULT_BODY,
    RecordingObserver,
    ScriptedService,
    accepted,
    make_client,
    status,
)
from tests.unit.transcription_models.infrastructure.adapters.test_litellm_transcription import (
    TRANSPORT,
    _adapter,
)
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_transcription import _audio_file

spool_contract = audio_spool_test_support.spool_contract

recording = test_audio.recording
ffmpeg = test_audio.ffmpeg


@pytest.mark.parametrize("engine", ["registry", "remote"])
@pytest.mark.parametrize(
    "limit, ceiling",
    [("duration_seconds", 1), ("decoded_bytes", 6000)],
)
async def test_oversized_audio_is_a_final_typed_refusal_before_provider_work(
    recording, ffmpeg, monkeypatch, engine, limit, ceiling, spool_contract
):
    spool_contract.duration_seconds = None
    source, _, temp_dir = recording
    settings = get_settings().model_copy(update={f"flow_audio_max_{limit}": ceiling})
    monkeypatch.setattr(audio, "get_settings", lambda: settings)
    decode = AsyncMock(wraps=audio._decode_audio)
    monkeypatch.setattr(audio, "_decode_audio", decode)
    provider = AsyncMock()
    monkeypatch.setattr(TRANSPORT, provider)
    observer = RecordingObserver()
    service = ScriptedService()
    remote = RemoteFlowTranscriber(make_client(service))
    registry = Transcriber(file_service=AsyncMock())
    adapter = _adapter()
    monkeypatch.setattr(
        registry, "prepare_transcription", AsyncMock(return_value=adapter)
    )
    label_speakers = AsyncMock()
    monkeypatch.setattr(remote, "label_speakers", label_speakers)
    retry_sleep = AsyncMock()
    monkeypatch.setattr(adapter._transcribe_chunk.retry, "sleep", retry_sleep)
    transcriber = (
        DiarizingFlowTranscriber(registry, remote) if engine == "registry" else remote
    )
    file = _audio_file(name="recording.wav")
    file.blob = source.read_bytes()
    download = spool_contract.downloads([file])

    with pytest.raises(TypedIOValidationException) as error:
        await transcribe_audio_input(
            files=[file],
            transcriber=transcriber,
            transcription_model=adapter.model,
            language="auto",
            step_order=1,
            max_files=1,
            max_inline_text_bytes=1024,
            open_audio_download=download,
            transcription_call_observer=observer,
        )

    assert error.value.code == "typed_io_audio_exceeds_limit"
    assert error.value.context is not None
    assert error.value.context.keys() == {"limit", "measured", "ceiling"}
    assert error.value.context["limit"] == limit
    assert error.value.context["ceiling"] == ceiling
    assert type(error.value.context["measured"]) is int
    assert error.value.context["measured"] > ceiling
    assert isinstance(error.value.__cause__, audio.AudioDecodeLimitExceeded)
    assert decode.call_count == 1
    provider.assert_not_awaited()
    retry_sleep.assert_not_awaited()
    label_speakers.assert_not_awaited()
    assert service.requests == []
    assert observer.started_facts == []
    assert observer.completed_calls == []
    assert observer.rejected_calls == []
    assert observer.unknown_calls == []
    assert file.blob == source.read_bytes()
    assert list(temp_dir.iterdir()) == []


async def test_remote_counts_duration_without_materialising_decoded_audio(
    recording, ffmpeg, monkeypatch, spool_contract
):
    spool_contract.duration_seconds = None
    source, _, temp_dir = recording
    temporary_files = []
    named_temp_file = audio.tempfile.NamedTemporaryFile

    def record_temp_file(*args, **kwargs):
        handle = named_temp_file(*args, **kwargs)
        temporary_files.append(handle.name)
        return handle

    monkeypatch.setattr(audio.tempfile, "NamedTemporaryFile", record_temp_file)
    service = ScriptedService(
        submit_responses=[accepted()],
        status_responses=[status("completed")],
        result_responses=[httpx.Response(200, json=RESULT_BODY)],
    )
    observer = RecordingObserver()
    file = _audio_file(name="recording.wav")
    file.blob = source.read_bytes()
    spool = await spool_contract.spool(file)
    try:
        await RemoteFlowTranscriber(make_client(service)).transcribe(
            spool, _adapter().model, file_id=file.id, observer=observer
        )
    finally:
        await spool.aclose()

    assert len(temporary_files) == 1
    assert observer.started_facts[0].audio_seconds == 10
    assert file.blob in service.requests[0].read()
    assert list(temp_dir.iterdir()) == []


def test_audio_refusal_has_non_retryable_typed_taxonomy():
    code = FlowApiErrorCode("typed_io_audio_exceeds_limit")
    assert code in FLOW_TYPED_IO_ERROR_CODES
    assert FlowRunError(code=code, message="audio ceiling exceeded").retryable is False
    validate_flow_error_taxonomy()
    entry = FLOW_ERROR_TAXONOMY[code]
    assert entry.category == "Typed input/output"
    assert entry.handling_phase == "Run execution"
    assert "split" in entry.consumer_action.lower()
    assert "administrator" in entry.consumer_action.lower()


async def test_local_preparation_decodes_once(recording, ffmpeg, monkeypatch):
    from types import SimpleNamespace

    from eneo.flows.runtime.diarizing_transcription import RegistryFlowTranscriber
    from tests.unittests.flows.audio_spool_test_support import AudioDownloads

    source, _, temp_dir = recording
    decode = AsyncMock(wraps=audio._decode_audio)
    monkeypatch.setattr(audio, "_decode_audio", decode)
    provider = AsyncMock(return_value=SimpleNamespace(text="hello"))
    monkeypatch.setattr(TRANSPORT, provider)
    registry = Transcriber(file_service=AsyncMock())
    adapter = _adapter()
    monkeypatch.setattr(registry, "_get_adapter", AsyncMock(return_value=adapter))
    file = _audio_file(name="recording.wav")
    download = AudioDownloads([file], payload=source.read_bytes())

    result = await transcribe_audio_input(
        files=[file],
        transcriber=RegistryFlowTranscriber(registry),
        transcription_model=adapter.model,
        language="auto",
        step_order=1,
        max_files=1,
        max_inline_text_bytes=1024,
        open_audio_download=download,
    )

    assert "hello" in result.text
    assert decode.await_count == 1
    provider.assert_awaited_once()
    download.assert_finished()
    assert list(temp_dir.iterdir()) == []

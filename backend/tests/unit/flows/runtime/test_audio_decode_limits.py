from unittest.mock import AsyncMock, Mock

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
    RecordingObserver,
    ScriptedService,
    make_client,
)
from tests.unit.transcription_models.infrastructure.adapters.test_litellm_transcription import (
    TRANSPORT,
    _adapter,
)
from tests.unittests.flows.test_flow_transcription import _audio_file

recording = test_audio.recording


@pytest.mark.parametrize("engine", ["registry", "remote"])
@pytest.mark.parametrize(
    "limit, ceiling",
    [("duration_seconds", 1), ("decoded_bytes", 6000)],
)
async def test_oversized_audio_is_a_final_typed_refusal_before_provider_work(
    recording, monkeypatch, engine, limit, ceiling
):
    source, _, temp_dir = recording
    settings = get_settings().model_copy(update={f"flow_audio_max_{limit}": ceiling})
    monkeypatch.setattr(audio, "get_settings", lambda: settings)
    decode = Mock(wraps=audio._to_wav)
    monkeypatch.setattr(audio, "_to_wav", decode)
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
    monkeypatch.setattr(remote._submit_job.retry, "sleep", retry_sleep)
    monkeypatch.setattr(adapter._transcribe_chunk.retry, "sleep", retry_sleep)
    transcriber = (
        DiarizingFlowTranscriber(registry, remote) if engine == "registry" else remote
    )
    file = _audio_file(name="recording.wav")
    file.blob = source.read_bytes()
    load = AsyncMock(return_value=file)

    with pytest.raises(TypedIOValidationException) as error:
        await transcribe_audio_input(
            files=[file],
            transcriber=transcriber,
            transcription_model=adapter.model,
            language="auto",
            step_order=1,
            max_files=1,
            max_inline_text_bytes=1024,
            load_audio_payload=load,
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

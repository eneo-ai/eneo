import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from eneo.files import audio
from eneo.files.file_service import FileDownload
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.diarizing_transcription import DiarizingFlowTranscriber
from eneo.flows.runtime.remote_transcription import RemoteFlowTranscriber
from eneo.main.exceptions import TypedIOValidationException
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    TranscriptSegment,
)
from tests.unit.files import test_audio
from tests.unit.flows.runtime.test_remote_transcription import (
    RESULT_BODY,
    RecordingObserver,
    ScriptedService,
    accepted,
    make_client,
    status,
)
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_transcription import (
    _audio_file,
    _build_executor,
    _patch_run_input_payload,
    _run,
    _runtime_step,
    _SpaceStub,
    _state,
)

spool_contract = audio_spool_test_support.spool_contract
recording = test_audio.recording
ffmpeg = test_audio.ffmpeg


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "diarize"])
async def test_audio_step_uses_download_and_removes_spool(
    user, recording, ffmpeg, monkeypatch, outcome, spool_contract
):
    spool_contract.duration_seconds = None
    source, _, temp_dir = recording
    payload = source.read_bytes()
    file = _audio_file(name="recording.wav", size=len(payload))
    executor, flow_run_repo, space_repo, file_service, transcriber = _build_executor(
        user, spool_contract=spool_contract
    )
    file_service.get_files_by_ids.return_value = [file]
    file_service.get_file_content.side_effect = AssertionError("whole-file hydration")
    model = SimpleNamespace(
        id=uuid4(), name="whisper", model_name="whisper", can_access=True
    )
    space_repo.get_space_by_assistant.return_value = _SpaceStub([model], model)
    paths = []
    duration = AsyncMock(wraps=audio.measure_duration)
    monkeypatch.setattr(audio, "measure_duration", duration)
    from unittest.mock import Mock

    from eneo.flows.runtime import audio_spool

    digest = Mock(wraps=audio_spool._digest_file)
    monkeypatch.setattr(audio_spool, "_digest_file", digest)

    download = spool_contract.downloads([file], payload=payload)
    file_service.get_audio_download = download

    async def transcribe(spool, model, **kwargs):
        download.assert_finished()
        assert spool.path.read_bytes() == payload
        assert spool.duration_seconds == 10
        assert spool.digest == hashlib.sha256(payload).hexdigest()
        assert spool.byte_size == len(payload)
        paths.append(spool.path)
        if outcome == "failure":
            raise TypedIOValidationException(
                "typed failure", code="typed_io_transcription_failed"
            )
        if outcome == "cancel":
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        return TranscribedAudio("hello", spool.duration_seconds)

    transcriber.transcribe = transcribe
    observer = RecordingObserver()
    if outcome == "diarize":

        async def local(*, filepath, **kwargs):
            download.assert_finished()
            assert filepath.read_bytes() == payload
            paths.append(filepath)
            return TranscribedAudio(
                "hello", 10, segments=(TranscriptSegment("hello", 0, 10),)
            )

        service = ScriptedService(
            submit_responses=[accepted()],
            status_responses=[status("completed")],
            result_responses=[
                httpx.Response(200, json={**RESULT_BODY, "model": model.model_name})
            ],
        )
        executor.transcriber = DiarizingFlowTranscriber(
            SimpleNamespace(transcribe_from_filepath=local),
            RemoteFlowTranscriber(make_client(service)),
        )
    run = _run(user=user, payload={})
    _patch_run_input_payload(flow_run_repo, run)

    async def execute():
        return await executor._resolve_step_input(
            step=_runtime_step(),
            context=executor.variable_resolver.build_context(
                run.input_payload_json, []
            ),
            run=run,
            prior_results=[],
            state=_state(),
            version_metadata={
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": str(model.id)},
                }
            },
            requested_file_ids=[file.id],
            transcription_call_observer=observer,
        )

    if outcome in {"success", "diarize"}:
        assert (await execute()).text == (
            RESULT_BODY["text"] if outcome == "diarize" else "hello"
        )
    else:
        error = (
            asyncio.CancelledError
            if outcome == "cancel"
            else TypedIOValidationException
        )
        with pytest.raises(error):
            await execute()
    assert len(paths) == 1
    assert not paths[0].exists()
    assert list(temp_dir.iterdir()) == []
    assert len(download.streams) == 1
    assert duration.await_count == 1
    assert digest.call_count == 1
    if outcome == "diarize":
        assert observer.started_facts[0].audio_seconds == 10
        assert len(observer.started_facts) == 1
        assert payload in service.requests[0].read()
    file_service.get_file_content.assert_not_awaited()


@pytest.mark.parametrize("interruption", ["failure", "cancel"])
async def test_interrupted_download_closes_source_and_removes_partial_spool(
    tmp_path, monkeypatch, interruption
):
    from eneo.flows.runtime.audio_spool import spool_audio

    monkeypatch.setattr(audio.tempfile, "tempdir", str(tmp_path))
    closed = []
    started = asyncio.Event()

    async def download(file_id):
        async def chunks():
            yield b"first chunk"
            started.set()
            if interruption == "failure":
                raise OSError("download interrupted")
            await asyncio.Future()

        async def close():
            closed.append(True)

        return FileDownload(
            file_id=file_id,
            tenant_id=uuid4(),
            chunks=chunks(),
            content_length=1024,
            media_type="audio/wav",
            filename="a.wav",
            sha256=b"",
            content_range=None,
            range_supported=True,
            _close=close,
        )

    task = asyncio.create_task(spool_audio(uuid4(), open_audio_download=download))
    await started.wait()
    if interruption == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if interruption == "cancel" else OSError):
        await task
    assert closed == [True]
    assert list(tmp_path.iterdir()) == []


async def test_inline_payload_is_released_before_measurement(tmp_path, monkeypatch):
    import weakref

    from eneo.flows.runtime.audio_spool import spool_audio

    class Payload:
        data = b"inline audio"

    retained = []
    monkeypatch.setattr(audio.tempfile, "tempdir", str(tmp_path))

    async def download(file_id):
        payload = Payload()
        retained.append(weakref.ref(payload))

        async def chunks():
            yield payload.data

        async def close():
            assert payload.data

        return FileDownload(
            file_id=file_id,
            tenant_id=uuid4(),
            chunks=chunks(),
            content_length=len(payload.data),
            media_type="audio/wav",
            filename="a.wav",
            sha256=b"",
            content_range=None,
            range_supported=True,
            _close=close,
        )

    async def measure(filepath):
        assert retained[0]() is None
        return 1.0

    monkeypatch.setattr(audio, "measure_duration", measure)
    spool = await spool_audio(uuid4(), open_audio_download=download)
    try:
        assert spool.path.read_bytes() == Payload.data
    finally:
        await spool.aclose()
    assert list(tmp_path.iterdir()) == []


async def test_cancellation_waits_for_digest_reader_before_removing_spool(
    tmp_path, monkeypatch
):
    import threading

    from eneo.flows.runtime import audio_spool
    from tests.unittests.flows.audio_spool_test_support import AudioDownloads

    monkeypatch.setattr(audio.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(audio, "measure_duration", AsyncMock(return_value=1.0))
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    digest = audio_spool._digest_file
    paths = []

    def slow_digest(path):
        paths.append(path)
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        assert path.exists()
        return digest(path)

    monkeypatch.setattr(audio_spool, "_digest_file", slow_digest)
    file = _audio_file(name="recording.wav")
    downloads = AudioDownloads([file])
    task = asyncio.create_task(
        audio_spool.spool_audio(file.id, open_audio_download=downloads)
    )
    try:
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert paths[0].exists()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    downloads.assert_finished()
    assert list(tmp_path.iterdir()) == []

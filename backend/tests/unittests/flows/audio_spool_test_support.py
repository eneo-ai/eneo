from collections import Counter
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from eneo.files.file_service import FileDownload
from eneo.flows.runtime import audio_spool


class AudioDownloads:
    def __init__(self, files, *, payload=None):
        self.files = files
        self.payload = payload
        self.calls = []
        self.streams = []
        self.error = None

    async def __call__(self, file_id):
        self.calls.append(file_id)
        if self.error is not None:
            raise self.error
        files = self.files() if callable(self.files) else self.files
        file = next(file for file in files if file.id == file_id)
        payload = (
            self.payload
            if self.payload is not None
            else getattr(file, "blob", b"audio")
        )
        state = {"streamed": False, "closed": 0}
        self.streams.append(state)

        async def chunks():
            assert not state["streamed"]
            for offset in range(0, len(payload), 4096):
                yield payload[offset : offset + 4096]
            state["streamed"] = True

        async def close():
            state["closed"] += 1
            assert state["closed"] == 1

        return FileDownload(
            file_id=file_id,
            tenant_id=getattr(file, "tenant_id", uuid4()),
            chunks=chunks(),
            content_length=len(payload),
            media_type=file.mimetype,
            filename=file.name,
            sha256=sha256(payload).digest(),
            content_range=None,
            range_supported=True,
            _close=close,
        )

    def assert_finished(self):
        for state in self.streams:
            assert state == {"streamed": True, "closed": 1}


class SpoolContract:
    def __init__(self):
        self.duration_seconds = 42.0
        self.duration_calls = Counter()
        self.paths = []
        self.sources = []
        self.owned_spools = []

    def downloads(self, files, *, payload=None):
        source = AudioDownloads(files, payload=payload)
        self.sources.append(source)
        return source

    async def spool(self, file, *, payload=None):
        spool = await audio_spool.spool_audio(
            file.id, open_audio_download=self.downloads([file], payload=payload)
        )
        self.owned_spools.append(spool)
        return spool

    def assert_finished(self):
        assert sum(len(source.streams) for source in self.sources) == len(self.paths)
        for source in self.sources:
            source.assert_finished()
        for path in self.paths:
            assert self.duration_calls[path] <= 1
            assert not path.exists(), f"Spool was not closed: {path}"
        assert set(self.duration_calls) <= set(self.paths)


@pytest.fixture
async def spool_contract(monkeypatch):
    contract = SpoolContract()
    measure = audio_spool.audio.measure_duration
    acquire = audio_spool.spool_audio

    async def measure_once(filepath, **kwargs):
        path = Path(filepath)
        contract.duration_calls[path] += 1
        assert contract.duration_calls[path] == 1
        value = (
            await measure(filepath, **kwargs)
            if contract.duration_seconds is None
            else contract.duration_seconds
        )
        return value

    async def acquire_spool(*args, **kwargs):
        spool = await acquire(*args, **kwargs)
        contract.paths.append(spool.path)
        return spool

    from eneo.flows.runtime import transcription

    monkeypatch.setattr(audio_spool.audio, "measure_duration", measure_once)
    monkeypatch.setattr(audio_spool, "spool_audio", acquire_spool)
    monkeypatch.setattr(transcription, "spool_audio", acquire_spool)
    yield contract
    for spool in contract.owned_spools:
        await spool.aclose()
    contract.assert_finished()

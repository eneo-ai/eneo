from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
)


class _CredentialResolverStub:
    provider_id = "provider-id"

    def get_api_key(self) -> str:
        return "test-key"

    def get_credential_field(self, *, field: str) -> str | None:
        return None


@pytest.mark.parametrize(
    ("language", "expected_language"),
    [
        (None, "sv"),
        ("sv", "sv"),
        ("en", "en"),
    ],
)
@pytest.mark.asyncio
async def test_kb_whisper_language_fallback_only_when_language_is_auto(
    monkeypatch, tmp_path, language, expected_language
):
    captured_kwargs: dict[str, object] = {}

    async def fake_atranscription(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(text="transcript")

    monkeypatch.setattr(
        "eneo.transcription_models.infrastructure.adapters.litellm_transcription.litellm.atranscription",
        AsyncMock(side_effect=fake_atranscription),
    )
    audio_path = tmp_path / "chunk.wav"
    audio_path.write_bytes(b"audio")
    adapter = LiteLLMTranscriptionAdapter(
        model=SimpleNamespace(name="KB Whisper", model_name="kb-whisper-large"),
        credential_resolver=_CredentialResolverStub(),
        provider_type="openai",
    )

    result = await adapter._transcribe_chunk(audio_path, language=language)

    assert result == "transcript"
    assert captured_kwargs["language"] == expected_language

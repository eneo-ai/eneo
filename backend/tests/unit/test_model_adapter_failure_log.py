"""A provider's error can echo what it was sent: the text to embed, what was
said in a recording. The adapters log a failed request by its provider,
operation, kind and status code, never by its message."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from litellm.exceptions import BadRequestError
from tenacity import wait_fixed

from eneo.embedding_models.infrastructure.adapters import (
    litellm_embeddings as embeddings_module,
)
from eneo.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.model_providers.infrastructure import litellm_transport
from eneo.transcription_models.infrastructure.adapters import (
    litellm_transcription as transcription_module,
)
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    LiteLLMTranscriptionAdapter,
)

_PRIVATE = "Utredning om Anna Svensson"


def _rejected(**_kwargs: object) -> None:
    raise BadRequestError(
        message=f"could not process input: {_PRIVATE}",
        model="m",
        llm_provider="openai",
    )


async def _rejecting(**kwargs: object) -> None:
    _rejected(**kwargs)


def _capture(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, module: Any
) -> None:
    name = f"eneo.test.{module.__name__}"
    monkeypatch.setattr(module, "logger", logging.getLogger(name))
    caplog.set_level(logging.DEBUG, logger=name)


def _failure(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    logged = caplog.text + "".join(repr(r.__dict__) for r in caplog.records)
    assert _PRIVATE not in logged
    (record,) = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert record.exc_info is None
    assert record.__dict__["error_status"] == 400
    assert "BadRequestError" in record.getMessage()
    return record


@pytest.mark.asyncio
async def test_a_failed_embedding_request_is_logged_without_the_providers_message(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _capture(monkeypatch, caplog, embeddings_module)
    monkeypatch.setattr(litellm_transport, "aembedding", _rejecting)
    resolver = Mock(provider_type="openai")
    resolver.get_api_key.return_value = "test-key"
    resolver.get_credential_field.return_value = None
    adapter = LiteLLMEmbeddingAdapter(
        model=cast(
            Any,
            SimpleNamespace(
                name="m",
                family=None,
                litellm_model_name="openai/m",
                dimensions=None,
                max_batch_size=None,
                max_input=None,
            ),
        ),
        credential_resolver=resolver,
    )
    get_embeddings = LiteLLMEmbeddingAdapter._get_embeddings.retry_with(
        wait=wait_fixed(0)
    )

    with pytest.raises(ProviderRejectedRequestException):
        await get_embeddings(adapter, [_PRIVATE])

    record = _failure(caplog)
    assert record.__dict__["provider"] == "openai"
    assert record.__dict__["operation"] == "embedding"
    assert "openai/m" in record.getMessage()


@pytest.mark.asyncio
async def test_a_failed_transcription_request_is_logged_without_the_providers_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    _capture(monkeypatch, caplog, transcription_module)
    monkeypatch.setattr(litellm_transport, "atranscription", _rejecting)
    resolver = Mock(provider_type="openai")
    resolver.get_api_key.return_value = "test-key"
    resolver.get_credential_field.return_value = None
    adapter = LiteLLMTranscriptionAdapter(
        model=cast(Any, SimpleNamespace(name="w", model_name="whisper-1")),
        credential_resolver=resolver,
        provider_type="openai",
    )
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    transcribe_chunk = LiteLLMTranscriptionAdapter._transcribe_chunk.retry_with(
        wait=wait_fixed(0)
    )

    with pytest.raises(ProviderRejectedRequestException):
        await transcribe_chunk(adapter, chunk, audio_seconds=1.0)

    record = _failure(caplog)
    assert record.__dict__["provider"] == "openai"
    assert record.__dict__["operation"] == "transcription"
    assert "openai/whisper-1" in record.getMessage()

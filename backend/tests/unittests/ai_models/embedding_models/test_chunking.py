from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from eneo.embedding_models.domain import chunking
from eneo.embedding_models.domain.chunking import (
    ChunkConfig,
    ChunkSettings,
    build_text_splitter,
    effective_chunk_config,
)
from eneo.tokens.token_utils import count_tokens


@pytest.fixture(autouse=True)
def platform_defaults(monkeypatch: pytest.MonkeyPatch):
    # The environment of the machine running the tests must not leak in.
    monkeypatch.setattr(chunking.settings, "chunk_size", 200)
    monkeypatch.setattr(chunking.settings, "chunk_overlap", 40)
    monkeypatch.setattr(chunking, "_announced", set())


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    recorder = MagicMock()
    monkeypatch.setattr(chunking, "logger", recorder)
    return recorder


def model(max_input: int | None, name: str = "model") -> SimpleNamespace:
    return SimpleNamespace(name=name, max_input=max_input)


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CHUNK_SIZE", "300")
    monkeypatch.setenv("CHUNK_OVERLAP", "60")

    assert ChunkSettings().model_dump() == {"chunk_size": 300, "chunk_overlap": 60}


def test_a_model_with_room_gets_the_configured_values():
    assert effective_chunk_config(model(8191)) == ChunkConfig(200, 40)


def test_a_model_with_a_lower_limit_clamps_the_size_and_scales_the_overlap(
    log: MagicMock,
):
    assert effective_chunk_config(model(120, "e5")) == ChunkConfig(120, 24)
    effective_chunk_config(model(120, "e5"))

    # Announced once per model, not per document.
    assert log.info.call_count == 1
    assert "exceeds max_input 120" in log.info.call_args.args[0]
    log.warning.assert_not_called()


def test_a_model_without_a_limit_is_not_clamped_but_warns_once(log: MagicMock):
    assert effective_chunk_config(model(None, "unknown")) == ChunkConfig(200, 40)
    effective_chunk_config(model(None, "unknown"))

    assert log.warning.call_count == 1
    assert "no max_input" in log.warning.call_args.args[0]
    log.info.assert_not_called()


def test_the_splitter_never_exceeds_the_models_limit():
    splitter = build_text_splitter(model(30))
    text = " ".join(f"word{i}" for i in range(400))

    chunks = splitter.split_text(text)

    assert len(chunks) > 1
    assert max(count_tokens(chunk) for chunk in chunks) <= 30

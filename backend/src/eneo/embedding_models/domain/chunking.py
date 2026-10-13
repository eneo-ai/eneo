"""One chunking configuration for every ingest path.

``ChunkSettings`` is the installation-wide setting: ``CHUNK_SIZE`` and
``CHUNK_OVERLAP`` from the environment, 200/40 when unset. ``effective_chunk_config``
applies the one adjustment that depends on the receiving model: a chunk never exceeds
the embedding model's registered ``max_input``. Upload, integration sync and crawl all
build their splitter through ``build_text_splitter``, and retrieval sizes its candidate
set from the same answer, so the number is known in one place.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic_settings import BaseSettings

from eneo.main.logging import get_logger
from eneo.tokens.token_utils import count_tokens

logger = get_logger(__name__)


class ChunkSettings(BaseSettings):
    chunk_size: int = 200
    chunk_overlap: int = 40


settings = ChunkSettings()

# E5 models expect every passage to carry this prefix; the embedding adapter adds it
# after chunking, so the chunk budget has to leave room for it.
E5_PASSAGE_PREFIX = "passage: "


class ChunkTarget(Protocol):
    """What chunking needs to know about the model that will embed the chunks.

    Satisfied by the ORM ``EmbeddingModel``, the domain entity and the crawler's
    frozen ``EmbeddingModelSpec`` alike.
    """

    @property
    def name(self) -> str: ...

    @property
    def family(self) -> str | None: ...

    @property
    def max_input(self) -> int | None: ...


@dataclass(frozen=True)
class ChunkConfig:
    chunk_size: int
    chunk_overlap: int


# Each (event, model name, limit) is logged once per process: chunking runs per
# document, and the message is about the model, not the document. Chunking also runs
# from worker threads, hence the lock.
_announced: set[tuple[str, str, int | None]] = set()
_announced_lock = threading.Lock()


def _announce_once(
    event: str, model_name: str, max_input: int | None, message: str, *, warning: bool
) -> None:
    key = (event, model_name, max_input)
    with _announced_lock:
        if key in _announced:
            return
        _announced.add(key)
    if warning:
        logger.warning(message, extra={"embedding_model": model_name})
    else:
        logger.info(message, extra={"embedding_model": model_name})


def _prefix_tokens(embedding_model: ChunkTarget) -> int:
    """Tokens the embedding adapter adds to every chunk before sending it."""
    if embedding_model.family == "e5":
        return count_tokens(E5_PASSAGE_PREFIX)
    return 0


def effective_chunk_config(embedding_model: ChunkTarget) -> ChunkConfig:
    """The chunk size and overlap actually used for ``embedding_model``.

    The configured size is clamped so that a chunk, plus any prefix the adapter adds
    for the model family, fits the model's ``max_input``; the overlap keeps the
    configured ratio so it stays below the size. A model without ``max_input`` is not
    clamped, and that is logged once so operators know the limit is unguarded.
    """
    size, overlap = settings.chunk_size, settings.chunk_overlap
    max_input = embedding_model.max_input
    model_name = embedding_model.name

    if max_input is None or max_input <= 0:
        _announce_once(
            "missing_max_input",
            model_name,
            max_input,
            f"Embedding model {model_name} has no max_input; chunks are not clamped "
            "to its limit",
            warning=True,
        )
        return ChunkConfig(size, overlap)

    budget = max_input - _prefix_tokens(embedding_model)
    if budget <= 0:
        _announce_once(
            "unusable_max_input",
            model_name,
            max_input,
            f"max_input {max_input} of embedding model {model_name} leaves no room "
            "for a chunk; chunks are not clamped to its limit",
            warning=True,
        )
        return ChunkConfig(size, overlap)
    if budget < size:
        clamped_overlap = overlap * budget // size
        _announce_once(
            "clamped",
            model_name,
            max_input,
            f"CHUNK_SIZE {size} exceeds what max_input {max_input} of embedding model "
            f"{model_name} allows; chunking at {budget} tokens with {clamped_overlap} "
            "overlap",
            warning=False,
        )
        return ChunkConfig(budget, clamped_overlap)

    return ChunkConfig(size, overlap)


def build_text_splitter(
    embedding_model: ChunkTarget, *, reserved_tokens: int = 0
) -> RecursiveCharacterTextSplitter:
    """The shared splitter, leaving room for text prepended before embedding."""
    config = effective_chunk_config(embedding_model)
    if not 0 <= reserved_tokens < config.chunk_size:
        raise ValueError("Reserved tokens must leave room for the chunk's text")
    chunk_size = config.chunk_size - reserved_tokens
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=config.chunk_overlap * chunk_size // config.chunk_size,
        length_function=count_tokens,
    )

"""One chunking configuration for every ingest path.

``ChunkSettings`` is the installation-wide setting: ``CHUNK_SIZE`` and
``CHUNK_OVERLAP`` from the environment, 200/40 when unset. ``effective_chunk_config``
applies the one adjustment that depends on the receiving model: a chunk never exceeds
the embedding model's registered ``max_input``. Upload, integration sync and crawl all
build their splitter through ``build_text_splitter``, and retrieval sizes its candidate
set from the same answer, so the number is known in one place.
"""

from __future__ import annotations

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


class ChunkTarget(Protocol):
    """What chunking needs to know about the model that will embed the chunks.

    Satisfied by the ORM ``EmbeddingModel``, the domain entity and the crawler's
    frozen ``EmbeddingModelSpec`` alike.
    """

    @property
    def name(self) -> str: ...

    @property
    def max_input(self) -> int | None: ...


@dataclass(frozen=True)
class ChunkConfig:
    chunk_size: int
    chunk_overlap: int


# Each (event, model) pair is logged once per process: chunking runs per document,
# and the message is about the model, not the document.
_announced: set[tuple[str, str]] = set()


def _announce_once(event: str, model_name: str, message: str, *, warning: bool) -> None:
    key = (event, model_name)
    if key in _announced:
        return
    _announced.add(key)
    if warning:
        logger.warning(message, extra={"embedding_model": model_name})
    else:
        logger.info(message, extra={"embedding_model": model_name})


def effective_chunk_config(embedding_model: ChunkTarget) -> ChunkConfig:
    """The chunk size and overlap actually used for ``embedding_model``.

    The configured size is clamped to the model's ``max_input``; the overlap keeps the
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
            f"Embedding model {model_name} has no max_input; chunks are not clamped "
            "to its limit",
            warning=True,
        )
        return ChunkConfig(size, overlap)

    if max_input < size:
        clamped_overlap = overlap * max_input // size
        _announce_once(
            "clamped",
            model_name,
            f"CHUNK_SIZE {size} exceeds max_input {max_input} of embedding model "
            f"{model_name}; chunking at {max_input} tokens with {clamped_overlap} "
            "overlap",
            warning=False,
        )
        return ChunkConfig(max_input, clamped_overlap)

    return ChunkConfig(size, overlap)


def build_text_splitter(embedding_model: ChunkTarget) -> RecursiveCharacterTextSplitter:
    """The splitter every ingest path uses, sized for ``embedding_model``."""
    config = effective_chunk_config(embedding_model)
    return RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        length_function=count_tokens,
    )

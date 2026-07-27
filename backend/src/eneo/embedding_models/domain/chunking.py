"""Single source of truth for how document text is split into chunks.

Both ingestion paths — ``Datastore._chunk_text`` and the crawl worker's
``persistence`` — build their splitter here so chunking cannot diverge.

``chunk_size``/``chunk_overlap`` fall back to ``ChunkSettings`` (env-overridable,
preserving the previous behaviour); a knowledge source may pass its own values.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic_settings import BaseSettings

from eneo.completion_models.infrastructure.context_builder import count_tokens


class ChunkSettings(BaseSettings):
    chunk_size: int = 200
    chunk_overlap: int = 40


settings = ChunkSettings()

# Safety valve: keep chunks well under the model's token limit, where embedding
# quality degrades and oversized chunks get silently truncated at embed time.
MAX_CHUNK_FRACTION = 0.6


def clamp_chunk_size(chunk_size: int, max_input: int | None) -> int:
    """Cap chunk_size at MAX_CHUNK_FRACTION of the model's max_input.

    ``max_input`` of None/0 (unknown limit) leaves the value untouched.
    """
    if not max_input:
        return chunk_size
    ceiling = int(max_input * MAX_CHUNK_FRACTION)
    return min(chunk_size, ceiling) if ceiling > 0 else chunk_size


def build_text_splitter(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> RecursiveCharacterTextSplitter:
    size = chunk_size if chunk_size is not None else settings.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
    # RecursiveCharacterTextSplitter requires overlap < size; cap it so a small
    # chunk_size (e.g. below the default overlap) can never break ingestion.
    overlap = min(overlap, size // 2)
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        length_function=count_tokens,
    )

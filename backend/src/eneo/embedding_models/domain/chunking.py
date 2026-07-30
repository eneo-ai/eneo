"""Single source of truth for how document text is split into chunks.

Both ingestion paths — ``Datastore._chunk_text`` and the crawl worker's
``persistence`` — build their splitter here so chunking cannot diverge.

``chunk_size``/``chunk_overlap`` fall back to ``ChunkSettings`` (env-overridable,
preserving the previous behaviour); a knowledge source may pass its own values.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic_settings import BaseSettings


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


def resolve_chunk_config(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> tuple[int, int]:
    """Resolve the values a splitter will actually use.

    ``None`` means "use the platform default", so the resolved pair is what the
    text was really split with — not what the caller asked for. Ingestion stamps
    the result on the info blob, which lets a later crawl tell whether stored
    material was chunked with the configuration that is in force now. Comparing
    raw config instead would report a difference between ``None`` and an explicit
    200 even though both split the text identically.
    """
    size = chunk_size if chunk_size is not None else settings.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
    # RecursiveCharacterTextSplitter requires overlap < size; cap it so a small
    # chunk_size (e.g. below the default overlap) can never break ingestion.
    return size, min(overlap, size // 2)


def chunking_is_unchanged(
    *,
    stored_chunk_size: int | None,
    stored_chunk_overlap: int | None,
    effective_chunk_size: int,
    effective_chunk_overlap: int,
) -> bool:
    """Whether already-stored chunks match the chunking in force now.

    ``None`` means the material was ingested before the effective values were
    recorded. What it was really split with is unknowable, so it counts as
    unchanged — treating it as a mismatch would make the first crawl after this
    change re-chunk and re-embed every page of every website.
    """
    if stored_chunk_size is not None and stored_chunk_size != effective_chunk_size:
        return False
    if (
        stored_chunk_overlap is not None
        and stored_chunk_overlap != effective_chunk_overlap
    ):
        return False
    return True


def build_text_splitter(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> RecursiveCharacterTextSplitter:
    # Imported lazily to avoid a circular import at module load: this module is
    # pulled in early via ``website.py`` -> ``clamp_chunk_size``, while
    # ``context_builder`` depends (transitively) back on ``info_blob``.
    from eneo.completion_models.infrastructure.context_builder import count_tokens

    size, overlap = resolve_chunk_config(chunk_size, chunk_overlap)
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        length_function=count_tokens,
    )

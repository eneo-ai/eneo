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

# Practical RAG systems land at 10-20% overlap for small chunks and 5-10% for large
# ones, and cost grows sharply as overlap approaches the chunk size — every extra
# token of overlap is re-embedded and re-stored in the neighbouring chunk. 20% is the
# top of the useful range, so it is a ceiling rather than a recommendation. The
# platform default (200/40) sits exactly on it.
MAX_OVERLAP_FRACTION = 0.2


def max_overlap_for(chunk_size: int) -> int:
    """The largest overlap a caller may request for ``chunk_size``."""
    return int(chunk_size * MAX_OVERLAP_FRACTION)


def validate_overlap_within_policy(chunk_size: int, chunk_overlap: int) -> None:
    """Raise when an explicitly requested pair exceeds the overlap ceiling.

    Refusing is deliberate: capping instead would store and display one overlap
    while indexing another, which is the whole reason this ceiling is explicit.
    """
    ceiling = max_overlap_for(chunk_size)
    if chunk_overlap > ceiling:
        raise ValueError(
            f"chunk_overlap must not exceed {int(MAX_OVERLAP_FRACTION * 100)}% of "
            f"chunk_size (at most {ceiling} for a chunk_size of {chunk_size})"
        )


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
    # RecursiveCharacterTextSplitter raises only when overlap > size, so cap at the
    # size itself. Capping lower would silently index a different overlap than the
    # one the source stores and shows. The cap still covers a small chunk_size
    # combined with a larger platform-default overlap, which is what would crash.
    return size, min(overlap, size)


def chunking_is_unchanged(
    *,
    stored_chunk_size: int | None,
    stored_chunk_overlap: int | None,
    requested_chunk_size: int | None,
    requested_chunk_overlap: int | None,
) -> bool:
    """Whether already-stored chunks match the chunking the source asks for now.

    ``requested_*`` is the source's own configuration, where ``None`` means
    "platform default". Unrecorded chunking on the stored side is handled by
    intent rather than by guessing:

    - While the source is still on platform defaults, unrecorded material counts
      as unchanged. Anything else would re-chunk and re-embed every existing page
      of every website the first time this ships.
    - Once the source carries an explicit size or overlap, unrecorded material is
      stale. That configuration is a deliberate choice, and material that predates
      it cannot be shown to satisfy it — leaving it alone would let a source report
      a setting its own knowledge does not follow, indefinitely.
    """
    source_is_explicit = (
        requested_chunk_size is not None or requested_chunk_overlap is not None
    )
    if stored_chunk_size is None or stored_chunk_overlap is None:
        return not source_is_explicit

    effective_size, effective_overlap = resolve_chunk_config(
        requested_chunk_size, requested_chunk_overlap
    )
    return (
        stored_chunk_size == effective_size
        and stored_chunk_overlap == effective_overlap
    )


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

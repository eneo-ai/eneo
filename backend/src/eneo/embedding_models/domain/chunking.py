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
# ones. Every token of overlap is re-embedded and re-stored in the neighbouring chunk,
# so the chunk count grows as size / (size - overlap): 1.11x at 10%, 1.25x at 20%,
# 1.33x at 25%, 2x at 50%.
#
# This ceiling exists to stop the pathological end of that curve, not to enforce the
# median — the UI's discrete steps guide towards the usual range. 25% leaves room for
# the case that justifies it, a very small chunk where a single sentence spans the
# boundary, and keeps the ceiling above every offered step so no valid choice can be
# nudged over it by rounding.
MAX_OVERLAP_FRACTION = 0.25


def max_overlap_for(chunk_size: int) -> int:
    """The largest overlap a caller may request for ``chunk_size``."""
    return int(chunk_size * MAX_OVERLAP_FRACTION)


def default_overlap_ratio() -> float:
    """The platform default overlap expressed as a share of the default size.

    This is what a defaulted overlap means for a source that chose its own size.
    """
    if settings.chunk_size <= 0:
        return 0.0
    return settings.chunk_overlap / settings.chunk_size


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

    A defaulted overlap follows the platform's default *ratio* rather than its
    absolute token count. The ceiling is a share of the size, so an absolute default
    cannot honour it: a source that sets only ``chunk_size=50`` would otherwise take
    the platform's 40 tokens and land on 80% overlap, well past a limit the API
    refuses for an explicit pair. Taking the ratio keeps every combination inside the
    policy and scales with the size the caller actually chose. A source on full
    defaults is unaffected — the ratio of the default pair reproduces it exactly.
    """
    size = chunk_size if chunk_size is not None else settings.chunk_size
    if chunk_overlap is not None:
        overlap = chunk_overlap
    elif size == settings.chunk_size:
        overlap = settings.chunk_overlap
    else:
        overlap = round(size * default_overlap_ratio())
    # Last guard for values that never passed the API — an env-configured pair, or a
    # row written before the ceiling existed. RecursiveCharacterTextSplitter raises
    # only when overlap > size, so that is where this caps.
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

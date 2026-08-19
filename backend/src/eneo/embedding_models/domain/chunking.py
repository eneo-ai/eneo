"""Single source of truth for how document text is split into chunks.

Both ingestion paths — ``Datastore._chunk_text`` and the crawl worker's
``persistence`` — build their splitter here so chunking cannot diverge.

``chunk_size``/``chunk_overlap`` fall back to ``ChunkSettings`` (env-overridable,
preserving the previous behaviour); a knowledge source may pass its own values.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic_settings import BaseSettings

from eneo.main.exceptions import BadRequestException


class ChunkSettings(BaseSettings):
    chunk_size: int = 200
    chunk_overlap: int = 40


settings = ChunkSettings()

# Keep chunks well under the model's token limit, where embedding quality
# degrades and oversized chunks get silently truncated at embed time.
MAX_CHUNK_FRACTION = 0.6

# Caps the pathological end of the overlap curve (each overlapping token is
# re-embedded and re-stored) while staying above every step the UI offers.
MAX_OVERLAP_FRACTION = 0.25


def max_overlap_for(chunk_size: int) -> int:
    """The largest overlap a caller may request for ``chunk_size``."""
    return int(chunk_size * MAX_OVERLAP_FRACTION)


# A small chunk size multiplies embedding calls, stored rows and index entries
# per document; this keeps the fan-out within ~5x of the 200-token default.
MIN_CHUNK_SIZE = 50

# Generous against any current model's context, but far below the INTEGER
# column's range so an oversized request fails as a 400 instead of a DB error.
MAX_CHUNK_SIZE = 100_000


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


def resolve_source_chunk_config(
    *,
    chunk_size: int | None,
    chunk_overlap: int | None,
    max_input: int | None,
) -> tuple[int | None, int | None]:
    """Validate the pair a knowledge source is about to store.

    Callers pass the pair *after* merging a partial update with what the source
    already had — the two fields are only valid together. The model's size
    ceiling is applied before the overlap is judged, so anything that cannot be
    honoured raises instead of being adjusted later.

    ``(None, None)`` is the only delegating state; any explicit side stores the
    whole resolved pair, so a stored configuration keeps meaning the same thing
    when the platform defaults change. A fully defaulted source is exempt from
    the overlap ceiling — the env-configured defaults were never subject to it.
    """
    if chunk_size is None and chunk_overlap is None:
        return None, None

    if chunk_size is not None:
        if chunk_size < MIN_CHUNK_SIZE:
            raise BadRequestException(
                f"chunk_size must be at least {MIN_CHUNK_SIZE} tokens; smaller chunks "
                "multiply embedding calls, stored rows and index work per document"
            )
        if chunk_size > MAX_CHUNK_SIZE:
            raise BadRequestException(
                f"chunk_size must not exceed {MAX_CHUNK_SIZE} tokens"
            )
    # Resolve and clamp both sides before validating; both are about to be stored.
    effective_size, effective_overlap = resolve_chunk_config(chunk_size, chunk_overlap)
    effective_size = clamp_chunk_size(effective_size, max_input)
    if effective_size < MIN_CHUNK_SIZE:
        # The model's input limit forces the size below the public floor;
        # persisting the clamped value would be refused on the next save.
        raise BadRequestException(
            f"this embedding model caps chunks at {effective_size} tokens, below the "
            f"minimum of {MIN_CHUNK_SIZE}; leave the chunk settings on the "
            "platform defaults for this model"
        )

    try:
        validate_overlap_within_policy(effective_size, effective_overlap)
    except ValueError as error:
        # The shared rule raises ValueError so pydantic can turn it into a 422;
        # from here it must become a BadRequestException or the caller gets a 500.
        if chunk_overlap is None:
            raise BadRequestException(
                f"a chunk_size of {effective_size} needs an explicit chunk_overlap of "
                f"at most {max_overlap_for(effective_size)}; the platform default of "
                f"{settings.chunk_overlap} would exceed "
                f"{int(MAX_OVERLAP_FRACTION * 100)}% of it"
            ) from error
        raise BadRequestException(str(error)) from error

    return effective_size, effective_overlap


def clamp_chunk_size(chunk_size: int, max_input: int | None) -> int:
    """Cap chunk_size at MAX_CHUNK_FRACTION of the model's max_input.

    ``max_input`` of None/0 (unknown limit) leaves the value untouched.
    """
    if max_input is None or max_input == 0:
        return chunk_size
    # A known limit always produces a ceiling, even a zero one, so the caller's
    # floor check can refuse a model whose input is too small to chunk for.
    return min(chunk_size, int(max_input * MAX_CHUNK_FRACTION))


def resolve_chunk_config(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> tuple[int, int]:
    """Resolve the values a splitter will actually use.

    ``None`` means "use the platform default". Ingestion stamps the resolved
    pair on the info blob, which lets a later crawl tell whether stored material
    was chunked with the configuration in force now. A defaulted overlap is the
    platform's absolute token default — the same number ``ChunkingPolicyPublic``
    publishes — not a share of the chosen size.
    """
    size = chunk_size if chunk_size is not None else settings.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
    # Last guard for values that never passed the API (env-configured pairs);
    # RecursiveCharacterTextSplitter raises when overlap > size.
    return size, min(overlap, size)


def chunking_is_unchanged(
    *,
    stored_chunk_size: int | None,
    stored_chunk_overlap: int | None,
    requested_chunk_size: int | None,
    requested_chunk_overlap: int | None,
) -> bool:
    """Whether already-stored chunks match the chunking the source asks for now.

    Material with unrecorded chunking counts as unchanged while the source
    delegates to platform defaults (anything else would re-embed every existing
    page when this ships), but as stale once the source carries an explicit
    setting it cannot be shown to satisfy.
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
    # Imported lazily to avoid a circular import: this module loads early via
    # website.py, while context_builder depends transitively back on info_blob.
    from eneo.completion_models.infrastructure.context_builder import count_tokens

    size, overlap = resolve_chunk_config(chunk_size, chunk_overlap)
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        length_function=count_tokens,
    )

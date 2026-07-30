import pytest

from eneo.embedding_models.domain import chunking
from eneo.embedding_models.domain.chunking import (
    ChunkSettings,
    build_text_splitter,
    chunking_is_unchanged,
    clamp_chunk_size,
    resolve_chunk_config,
)


@pytest.fixture
def platform_defaults(monkeypatch: pytest.MonkeyPatch) -> ChunkSettings:
    """Pin the env-overridable defaults so assertions don't depend on the environment."""
    settings = ChunkSettings(chunk_size=200, chunk_overlap=40)
    monkeypatch.setattr(chunking, "settings", settings)
    return settings


def test_resolve_falls_back_to_platform_defaults(platform_defaults: ChunkSettings):
    assert resolve_chunk_config(None, None) == (200, 40)


def test_resolve_uses_explicit_values(platform_defaults: ChunkSettings):
    assert resolve_chunk_config(500, 100) == (500, 100)


def test_resolve_fills_only_the_missing_value(platform_defaults: ChunkSettings):
    assert resolve_chunk_config(500, None) == (500, 40)
    assert resolve_chunk_config(None, 10) == (200, 10)


@pytest.mark.parametrize(
    ["chunk_size", "chunk_overlap", "expected_overlap"],
    [
        (50, 40, 25),  # overlap above the cap is halved down to size // 2
        (80, 40, 40),  # exactly at the cap is left alone
        (200, 40, 40),  # comfortably below the cap is left alone
        (1, 40, 0),  # a size of 1 leaves no room for overlap at all
    ],
)
def test_resolve_caps_overlap_below_chunk_size(
    platform_defaults: ChunkSettings,
    chunk_size: int,
    chunk_overlap: int,
    expected_overlap: int,
):
    # RecursiveCharacterTextSplitter raises if overlap >= size, which would break
    # ingestion for any small chunk_size a user is allowed to set.
    size, overlap = resolve_chunk_config(chunk_size, chunk_overlap)

    assert (size, overlap) == (chunk_size, expected_overlap)
    assert overlap < size or size == 1


def test_resolve_defaults_are_capped_too(monkeypatch: pytest.MonkeyPatch):
    # A deployment could set CHUNK_OVERLAP higher than CHUNK_SIZE via env.
    monkeypatch.setattr(
        chunking, "settings", ChunkSettings(chunk_size=30, chunk_overlap=90)
    )

    assert resolve_chunk_config(None, None) == (30, 15)


def test_splitter_is_built_from_the_resolved_values(platform_defaults: ChunkSettings):
    splitter = build_text_splitter(50, 40)

    assert splitter._chunk_size == 50
    assert splitter._chunk_overlap == 25


@pytest.mark.parametrize(
    ["chunk_size", "max_input", "expected"],
    [
        (5000, 1000, 600),  # capped at MAX_CHUNK_FRACTION of the model limit
        (500, 1000, 500),  # below the ceiling, untouched
        (600, 1000, 600),  # exactly at the ceiling, untouched
        (5000, None, 5000),  # unknown limit, untouched
        (5000, 0, 5000),  # a zero limit is treated as unknown, not as a ceiling
    ],
)
def test_clamp_chunk_size(chunk_size: int, max_input: int | None, expected: int):
    assert clamp_chunk_size(chunk_size, max_input) == expected


class TestChunkingIsUnchanged:
    """The stale check that decides whether stored material must be re-chunked."""

    def test_identical_values_are_unchanged(self):
        assert chunking_is_unchanged(
            stored_chunk_size=200,
            stored_chunk_overlap=40,
            effective_chunk_size=200,
            effective_chunk_overlap=40,
        )

    def test_different_size_is_a_change(self):
        assert not chunking_is_unchanged(
            stored_chunk_size=200,
            stored_chunk_overlap=40,
            effective_chunk_size=1000,
            effective_chunk_overlap=40,
        )

    def test_different_overlap_is_a_change(self):
        assert not chunking_is_unchanged(
            stored_chunk_size=200,
            stored_chunk_overlap=40,
            effective_chunk_size=200,
            effective_chunk_overlap=10,
        )

    def test_unrecorded_chunking_never_counts_as_a_change(self):
        # Blobs ingested before these columns existed have unknowable chunking.
        # Treating them as stale would re-chunk and re-embed every existing page
        # on the first crawl after deploying this.
        assert chunking_is_unchanged(
            stored_chunk_size=None,
            stored_chunk_overlap=None,
            effective_chunk_size=1000,
            effective_chunk_overlap=100,
        )

    @pytest.mark.parametrize(
        ["stored_chunk_size", "stored_chunk_overlap"],
        [(200, None), (None, 40)],
    )
    def test_a_recorded_field_that_differs_is_a_change_on_its_own(
        self, stored_chunk_size: int | None, stored_chunk_overlap: int | None
    ):
        # Each field is judged independently: "unknown" excuses only itself, so a
        # recorded value that differs still forces a re-index. Ingestion writes both
        # fields together, so a half-recorded row should not occur in practice —
        # this pins the behaviour in case one ever does.
        assert not chunking_is_unchanged(
            stored_chunk_size=stored_chunk_size,
            stored_chunk_overlap=stored_chunk_overlap,
            effective_chunk_size=1000,
            effective_chunk_overlap=100,
        )

    def test_default_config_matches_material_stamped_with_the_defaults(self):
        # A source left on "use platform defaults" resolves to 200/40, which is what
        # the blob was stamped with — comparing raw config would see None != 200
        # and re-index the whole source for no reason.
        stored_size, stored_overlap = resolve_chunk_config(None, None)
        effective_size, effective_overlap = resolve_chunk_config(None, None)

        assert chunking_is_unchanged(
            stored_chunk_size=stored_size,
            stored_chunk_overlap=stored_overlap,
            effective_chunk_size=effective_size,
            effective_chunk_overlap=effective_overlap,
        )

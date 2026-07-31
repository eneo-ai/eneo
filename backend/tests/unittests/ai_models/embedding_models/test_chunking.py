import pytest

from eneo.embedding_models.domain import chunking
from eneo.embedding_models.domain.chunking import (
    MIN_CHUNK_SIZE,
    ChunkSettings,
    build_text_splitter,
    chunking_is_unchanged,
    clamp_chunk_size,
    max_overlap_for,
    resolve_chunk_config,
    resolve_source_chunk_config,
    validate_overlap_within_policy,
)
from eneo.main.exceptions import BadRequestException


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
    # A defaulted overlap follows the default ratio (20%), not its token count.
    assert resolve_chunk_config(500, None) == (500, 100)
    assert resolve_chunk_config(None, 10) == (200, 10)


@pytest.mark.parametrize("chunk_size", [1, 50, 100, 128, 200, 1000, 5000])
def test_a_defaulted_overlap_always_stays_inside_the_ceiling(
    platform_defaults: ChunkSettings, chunk_size: int
):
    # The ceiling is a share of the size, so an absolute default cannot honour it:
    # a source setting only chunk_size=50 would take the platform's 40 tokens and
    # land on 80% overlap, which the API refuses for an explicit pair.
    _, overlap = resolve_chunk_config(chunk_size, None)

    assert overlap <= max_overlap_for(chunk_size)


def test_a_source_on_full_defaults_is_unaffected_by_the_ratio(
    platform_defaults: ChunkSettings,
):
    assert resolve_chunk_config(None, None) == (
        platform_defaults.chunk_size,
        platform_defaults.chunk_overlap,
    )


@pytest.mark.parametrize(
    ["chunk_size", "chunk_overlap", "expected_overlap"],
    [
        (50, 40, 40),  # a valid overlap is honoured, never quietly reduced
        (50, 60, 50),  # above the splitter's limit it is capped, not crashed
        (200, 40, 40),  # the platform default pair passes through
        (1, 40, 1),  # an explicit overlap larger than the size caps to the size
    ],
)
def test_resolve_caps_overlap_below_chunk_size(
    platform_defaults: ChunkSettings,
    chunk_size: int,
    chunk_overlap: int,
    expected_overlap: int,
):
    # RecursiveCharacterTextSplitter raises only when overlap > size. The resolver is
    # the last guard for values that never went through the API, such as a platform
    # default overlap larger than a small per-source size.
    size, overlap = resolve_chunk_config(chunk_size, chunk_overlap)

    assert (size, overlap) == (chunk_size, expected_overlap)
    assert overlap <= size


def test_resolve_defaults_are_capped_too(monkeypatch: pytest.MonkeyPatch):
    # A deployment could set CHUNK_OVERLAP higher than CHUNK_SIZE via env.
    monkeypatch.setattr(
        chunking, "settings", ChunkSettings(chunk_size=30, chunk_overlap=90)
    )

    assert resolve_chunk_config(None, None) == (30, 30)


def test_splitter_is_built_from_the_resolved_values(platform_defaults: ChunkSettings):
    splitter = build_text_splitter(50, 40)

    assert splitter._chunk_size == 50
    assert splitter._chunk_overlap == 40


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

    def test_stamp_matching_the_request_is_unchanged(self):
        assert chunking_is_unchanged(
            stored_chunk_size=1000,
            stored_chunk_overlap=100,
            requested_chunk_size=1000,
            requested_chunk_overlap=100,
        )

    def test_source_on_defaults_matches_material_stamped_with_the_defaults(self):
        # A source left on "use platform defaults" resolves to the same pair its blobs
        # were stamped with. Comparing raw config would see None != 200 and re-index
        # the whole source for nothing.
        stored_size, stored_overlap = resolve_chunk_config(None, None)

        assert chunking_is_unchanged(
            stored_chunk_size=stored_size,
            stored_chunk_overlap=stored_overlap,
            requested_chunk_size=None,
            requested_chunk_overlap=None,
        )

    @pytest.mark.parametrize(
        ["requested_chunk_size", "requested_chunk_overlap"],
        [(1000, 100), (1000, None), (None, 10)],
    )
    def test_a_different_request_is_a_change(
        self, requested_chunk_size: int | None, requested_chunk_overlap: int | None
    ):
        assert not chunking_is_unchanged(
            stored_chunk_size=200,
            stored_chunk_overlap=40,
            requested_chunk_size=requested_chunk_size,
            requested_chunk_overlap=requested_chunk_overlap,
        )

    def test_unrecorded_chunking_is_left_alone_while_the_source_uses_defaults(self):
        # Blobs ingested before these columns existed have unknowable chunking.
        # Treating them as stale would re-chunk and re-embed every existing page of
        # every website the first time this ships.
        assert chunking_is_unchanged(
            stored_chunk_size=None,
            stored_chunk_overlap=None,
            requested_chunk_size=None,
            requested_chunk_overlap=None,
        )

    @pytest.mark.parametrize(
        ["requested_chunk_size", "requested_chunk_overlap"],
        [(1000, 100), (1000, None), (None, 10)],
    )
    def test_unrecorded_chunking_is_stale_once_the_source_is_explicit(
        self, requested_chunk_size: int | None, requested_chunk_overlap: int | None
    ):
        # An explicit configuration is a deliberate choice. Material that predates it
        # cannot be shown to satisfy it, so it must be re-chunked — otherwise a source
        # reports a setting its own knowledge never follows.
        assert not chunking_is_unchanged(
            stored_chunk_size=None,
            stored_chunk_overlap=None,
            requested_chunk_size=requested_chunk_size,
            requested_chunk_overlap=requested_chunk_overlap,
        )

    @pytest.mark.parametrize(
        ["stored_chunk_size", "stored_chunk_overlap"],
        [(200, None), (None, 40)],
    )
    def test_half_recorded_chunking_follows_the_same_rule(
        self, stored_chunk_size: int | None, stored_chunk_overlap: int | None
    ):
        # Ingestion writes both fields together, so this should not occur. Pinned so a
        # partially stamped row is treated as unknown rather than as a lucky match.
        assert chunking_is_unchanged(
            stored_chunk_size=stored_chunk_size,
            stored_chunk_overlap=stored_chunk_overlap,
            requested_chunk_size=None,
            requested_chunk_overlap=None,
        )
        assert not chunking_is_unchanged(
            stored_chunk_size=stored_chunk_size,
            stored_chunk_overlap=stored_chunk_overlap,
            requested_chunk_size=1000,
            requested_chunk_overlap=100,
        )


class TestOverlapPolicy:
    """The ceiling that keeps requested overlap inside the useful range."""

    @pytest.mark.parametrize(
        ["chunk_size", "expected"],
        [(200, 50), (50, 12), (1000, 250), (128, 32), (1, 0)],
    )
    def test_max_overlap_is_a_share_of_the_size(self, chunk_size: int, expected: int):
        assert max_overlap_for(chunk_size) == expected

    def test_the_platform_default_stays_below_the_ceiling(
        self, platform_defaults: ChunkSettings
    ):
        # The default should be a usable value, not the boundary — sitting on the
        # ceiling means a later size change can push it over by rounding alone.
        assert platform_defaults.chunk_overlap < max_overlap_for(
            platform_defaults.chunk_size
        )

    @pytest.mark.parametrize(
        ["chunk_size", "chunk_overlap"], [(200, 40), (200, 50), (50, 12), (50, 0)]
    )
    def test_overlap_on_or_below_the_ceiling_is_accepted(
        self, chunk_size: int, chunk_overlap: int
    ):
        validate_overlap_within_policy(chunk_size, chunk_overlap)

    @pytest.mark.parametrize(["chunk_size", "chunk_overlap"], [(200, 51), (50, 40)])
    def test_overlap_above_the_ceiling_is_refused_not_adjusted(
        self, chunk_size: int, chunk_overlap: int
    ):
        # Refusing rather than capping is the point: capping would store and display
        # one overlap while indexing another.
        with pytest.raises(ValueError, match="must not exceed"):
            validate_overlap_within_policy(chunk_size, chunk_overlap)


class TestSourceChunkConfig:
    """The one owner of the pair a knowledge source stores."""

    def test_a_merged_pair_that_cannot_be_honoured_is_refused(self):
        # The bug this exists for: a size-only update landing next to a retained
        # overlap of 40 was stored as 100/40 while the splitter used 100/25, so the
        # source reported a setting its own chunks did not follow.
        with pytest.raises(BadRequestException, match="chunk_overlap must not exceed"):
            resolve_source_chunk_config(
                chunk_size=100, chunk_overlap=40, max_input=None
            )

    def test_a_pair_that_can_be_honoured_passes_through(self):
        assert resolve_source_chunk_config(
            chunk_size=200, chunk_overlap=40, max_input=None
        ) == (200, 40)

    def test_none_is_preserved_as_use_the_platform_default(self):
        assert resolve_source_chunk_config(
            chunk_size=None, chunk_overlap=None, max_input=8191
        ) == (None, None)

    def test_an_explicit_overlap_is_judged_against_the_default_size(
        self, platform_defaults: ChunkSettings
    ):
        # With no size of its own the source will split at the platform size, so the
        # overlap has to fit that, not some size the caller never mentioned.
        assert resolve_source_chunk_config(
            chunk_size=None, chunk_overlap=50, max_input=None
        ) == (None, 50)
        with pytest.raises(BadRequestException, match="chunk_overlap must not exceed"):
            resolve_source_chunk_config(
                chunk_size=None, chunk_overlap=60, max_input=None
            )

    def test_the_model_ceiling_is_applied_before_the_overlap_is_judged(self):
        # max_input 1000 caps the size at 600, so the overlap ceiling is 150, not 250.
        assert resolve_source_chunk_config(
            chunk_size=1000, chunk_overlap=150, max_input=1000
        ) == (600, 150)
        with pytest.raises(BadRequestException, match="chunk_overlap must not exceed"):
            resolve_source_chunk_config(
                chunk_size=1000, chunk_overlap=200, max_input=1000
            )

    @pytest.mark.parametrize("chunk_size", [1, 10, MIN_CHUNK_SIZE - 1])
    def test_a_size_below_the_floor_is_refused(self, chunk_size: int):
        # One chunk per token turns a single upload into thousands of embedding calls,
        # rows and index entries.
        with pytest.raises(BadRequestException, match="chunk_size must be at least"):
            resolve_source_chunk_config(
                chunk_size=chunk_size, chunk_overlap=None, max_input=None
            )

    def test_the_floor_itself_is_allowed(self):
        assert resolve_source_chunk_config(
            chunk_size=MIN_CHUNK_SIZE, chunk_overlap=None, max_input=None
        ) == (MIN_CHUNK_SIZE, None)

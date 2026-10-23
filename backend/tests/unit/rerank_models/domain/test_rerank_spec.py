"""How many candidates the vector search fetches for the reranker."""

from unittest.mock import MagicMock

from eneo.rerank_models.domain.rerank_spec import (
    DEFAULT_CANDIDATE_FACTOR,
    DEFAULT_MAX_CANDIDATES,
    RerankSpec,
)


def _spec(**overrides) -> RerankSpec:
    values = dict(reranker=MagicMock(), query="q", model_name="m")
    values.update(overrides)
    return RerankSpec(**values)


class TestCandidateCount:
    def test_defaults_are_the_prd_starting_point(self):
        assert DEFAULT_CANDIDATE_FACTOR == 5
        assert DEFAULT_MAX_CANDIDATES == 100

    def test_factor_times_n_below_the_cap(self):
        assert _spec().candidate_count(10) == 50

    def test_capped_for_large_n(self):
        # The newer retrieval version asks for about 320 chunks; the reranker
        # decides the content, so the cap wins.
        assert _spec().candidate_count(320) == 100

    def test_never_fewer_than_n_when_n_is_below_the_cap(self):
        assert _spec(candidate_factor=1).candidate_count(7) == 7

    def test_explicit_factor_and_cap(self):
        assert _spec(candidate_factor=2, max_candidates=9).candidate_count(6) == 9

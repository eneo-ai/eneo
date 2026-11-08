from dataclasses import dataclass

from eneo.rerank_models.domain.reranker import Reranker

# Defaults for a new rerank model; the ranges match the database checks.
DEFAULT_CANDIDATE_FACTOR = 5
DEFAULT_MAX_CANDIDATES = 100
CANDIDATE_FACTOR_RANGE = (1, 20)
MAX_CANDIDATES_RANGE = (1, 1000)


@dataclass(frozen=True)
class RerankSpec:
    """What a caller hands to semantic search to have the candidates reranked.
    ``query`` is the current question, not the search string."""

    reranker: Reranker
    query: str
    model_name: str
    candidate_factor: int = DEFAULT_CANDIDATE_FACTOR
    max_candidates: int = DEFAULT_MAX_CANDIDATES

    def candidate_count(self, requested: int) -> int:
        """How many candidates the reranker scores for ``requested`` chunks."""
        return min(requested * self.candidate_factor, self.max_candidates)

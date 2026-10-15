from dataclasses import dataclass

from eneo.rerank_models.domain.reranker import Reranker

# Starting points from the PRD (#1035, B5). The verification on mixed chunk
# sizes sets the final values; they become per-model columns only if it shows
# that models need different ones.
DEFAULT_CANDIDATE_FACTOR = 5
DEFAULT_MAX_CANDIDATES = 100


@dataclass(frozen=True)
class RerankSpec:
    """What a caller hands to semantic search to have the candidates reranked.

    ``query`` is what the reranker scores against: the current question, not
    the search string, which in inject mode is the whole conversation.
    """

    reranker: Reranker
    query: str
    model_name: str
    candidate_factor: int = DEFAULT_CANDIDATE_FACTOR
    max_candidates: int = DEFAULT_MAX_CANDIDATES

    def candidate_count(self, requested: int) -> int:
        """How many candidates the vector search fetches for ``requested`` chunks.

        Capped so that the newer retrieval version, which asks for hundreds,
        hands the reranker a bounded set: the reranker decides the content.
        """
        return min(requested * self.candidate_factor, self.max_candidates)

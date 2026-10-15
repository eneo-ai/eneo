from typing import Protocol, Sequence


class Reranker(Protocol):
    """Scores a query against each text; the only thing the search step needs.

    Returns one relevance score per text, in input order. Higher is more
    relevant. Any exception means the step falls back to vector order.
    """

    async def rerank(self, query: str, texts: Sequence[str]) -> list[float]: ...

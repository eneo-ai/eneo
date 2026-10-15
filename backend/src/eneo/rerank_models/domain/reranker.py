from typing import Protocol, Sequence


class Reranker(Protocol):
    """One relevance score per text, in input order; higher is more relevant."""

    async def rerank(self, query: str, texts: Sequence[str]) -> list[float]: ...

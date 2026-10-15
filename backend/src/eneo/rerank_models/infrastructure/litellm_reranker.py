from typing import Any, Sequence, cast

from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.outbound_headers_runtime import (
    ProviderOutboundHeaders,
    apply_outbound_headers,
)


class LiteLLMReranker:
    """``Reranker`` over LiteLLM's rerank API; a text the provider leaves out
    of its results scores 0."""

    def __init__(
        self,
        *,
        route: str,
        provider_kwargs: dict[str, Any],
        outbound_headers: ProviderOutboundHeaders | None,
        timeout_seconds: float,
    ) -> None:
        self.route = route
        self.provider_kwargs = provider_kwargs
        self.outbound_headers = outbound_headers
        self.timeout_seconds = timeout_seconds

    async def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        params: dict[str, Any] = {
            "model": self.route,
            "query": query,
            "documents": list(texts),
            "top_n": len(texts),
            "timeout": self.timeout_seconds,
            **self.provider_kwargs,
        }
        apply_outbound_headers(params, self.outbound_headers)

        response: Any = await litellm_transport.arerank(**params)

        scores = [0.0] * len(texts)
        results = cast(
            "list[Any]", getattr(response, "results", None) or response["results"]
        )
        for item in results:
            if isinstance(item, dict):
                entry = cast("dict[str, Any]", item)
                index, score = int(entry["index"]), entry.get("relevance_score")
            else:
                index, score = int(item.index), getattr(item, "relevance_score", None)
            if 0 <= index < len(scores) and score is not None:
                scores[index] = float(cast(float, score))
        return scores

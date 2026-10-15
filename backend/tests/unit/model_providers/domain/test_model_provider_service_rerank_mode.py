"""Reranking as a discoverable model mode with a connection test.

Rerank models are surfaced through the same provider discovery path as the
other model types: LiteLLM's ``rerank`` mode maps to ``rerank``, provider
hints and well-known name fragments classify unknown names, and the
validation probe sends one short query with two documents through the
transport so a wrong model name or endpoint shows up at registration time.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from eneo.model_providers.domain import model_provider_service
from eneo.model_providers.domain.model_provider_service import (
    LITELLM_MODE_TO_OUR_MODE,
    ModelProviderService,
)


class TestModeMapping:
    def test_rerank_maps_to_rerank(self):
        assert LITELLM_MODE_TO_OUR_MODE["rerank"] == "rerank"

    def test_provider_hint_recognises_rerank_models(self):
        assert model_provider_service._extract_mode_hint({"model_type": "rerank"}) == (
            "rerank"
        )

    @pytest.mark.parametrize(
        "name",
        ["rerank-v3.5", "jina-reranker-v2-base-multilingual", "bge-reranker-v2-m3"],
    )
    def test_known_rerank_name_fragments_classify_as_rerank(self, name):
        assert model_provider_service._infer_mode_from_name(name) == "rerank"

    def test_catalog_entry_keeps_only_name_and_mode(self):
        with patch(
            "litellm.model_cost",
            {"rerank-v3.5": {"mode": "rerank", "litellm_provider": "cohere"}},
        ):
            entry = model_provider_service._enrich_with_litellm_metadata(
                "rerank-v3.5", "cohere"
            )

        assert entry == {"name": "rerank-v3.5", "mode": "rerank"}


def _service(provider_type: str, endpoint: str = "") -> ModelProviderService:
    provider = MagicMock()
    provider.id = uuid4()
    provider.provider_type = provider_type
    provider.credentials = {"api_key": "ciphertext"}
    provider.config = {"endpoint": endpoint}
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=provider)
    service = ModelProviderService(repository=repository, encryption=MagicMock())
    service._decrypt_credentials = lambda creds: {"api_key": "test-key"}  # type: ignore[method-assign]
    return service


class TestValidateRerankModel:
    async def test_probe_sends_one_query_with_two_documents(self):
        service = _service("cohere")
        arerank = AsyncMock(return_value=MagicMock())

        with patch.object(model_provider_service.litellm_transport, "arerank", arerank):
            result = await service.validate_model(uuid4(), "rerank-v3.5", "rerank")

        assert result == {"success": True, "message": "Model validated successfully"}
        kwargs = arerank.await_args.kwargs
        assert kwargs["model"] == "cohere/rerank-v3.5"
        assert kwargs["api_key"] == "test-key"
        assert isinstance(kwargs["query"], str) and kwargs["query"]
        assert len(kwargs["documents"]) == 2
        assert kwargs["top_n"] == 1
        assert "api_base" not in kwargs

    async def test_self_hosted_probe_routes_to_the_endpoint(self):
        service = _service("vllm", endpoint="http://reranker:8000")
        arerank = AsyncMock(return_value=MagicMock())

        with patch.object(model_provider_service.litellm_transport, "arerank", arerank):
            await service.validate_model(uuid4(), "bge-reranker-v2-m3", "rerank")

        kwargs = arerank.await_args.kwargs
        assert kwargs["model"] == "hosted_vllm/bge-reranker-v2-m3"
        assert kwargs["api_base"] == "http://reranker:8000"

    async def test_probe_honours_the_rerank_timeout_setting(self):
        service = _service("cohere")
        arerank = AsyncMock(return_value=MagicMock())
        settings = MagicMock(rerank_request_timeout_seconds=7)

        with (
            patch.object(model_provider_service.litellm_transport, "arerank", arerank),
            patch.object(model_provider_service, "get_settings", return_value=settings),
        ):
            await service.validate_model(uuid4(), "rerank-v3.5", "rerank")

        assert arerank.await_args.kwargs["timeout"] == 7

    @pytest.mark.parametrize(
        ("error_name", "expected"),
        [
            ("AuthenticationError", "Invalid API key"),
            ("NotFoundError", "Model not found: rerank-v3.5"),
            ("APIConnectionError", "Could not connect to API"),
        ],
    )
    async def test_provider_errors_map_like_the_other_types(self, error_name, expected):
        service = _service("cohere")
        error = type(error_name, (Exception,), {})("boom")

        with patch.object(
            model_provider_service.litellm_transport,
            "arerank",
            AsyncMock(side_effect=error),
        ):
            result = await service.validate_model(uuid4(), "rerank-v3.5", "rerank")

        assert result == {"success": False, "error": expected}


class TestListAvailableModelsRerankFilter:
    async def test_mode_filter_keeps_only_rerank_entries(self):
        """A provider's live list mixes modes; ``mode="rerank"`` narrows it."""
        service = _service("openai", endpoint="http://models.example")
        payload = {
            "data": [
                {"id": "bge-reranker-v2-m3"},
                {"id": "gpt-4o"},
                {"id": "text-embedding-3-small"},
            ]
        }

        async def fake_get(self, url, headers=None, **kwargs):  # noqa: ARG001
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

        with (
            patch("httpx.AsyncClient.get", new=fake_get),
            patch("litellm.model_cost", {}),
        ):
            result = await service.list_available_models(uuid4(), mode="rerank")

        assert result == [{"name": "bge-reranker-v2-m3", "mode": "rerank"}]

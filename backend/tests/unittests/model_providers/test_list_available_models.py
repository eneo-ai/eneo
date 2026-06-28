"""End-to-end tests for ``list_available_models``: fetch → normalize →
enrich → sort newest-first. Covers the composition risk that's not exercised
by the per-helper unit tests."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from eneo.main.exceptions import BadRequestException
from eneo.model_providers.domain.model_provider_service import ModelProviderService


def _build_service_with_provider(
    provider_type: str, endpoint: str = ""
) -> tuple[ModelProviderService, Any]:
    """Build a service whose repository returns a stub provider matching the
    given type. Credentials decryption is bypassed so we don't need real keys."""
    provider = MagicMock()
    provider.id = uuid4()
    provider.provider_type = provider_type
    provider.credentials = {"api_key": "ciphertext"}
    provider.config = {"endpoint": endpoint}

    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=provider)

    encryption = MagicMock()
    service = ModelProviderService(repository=repository, encryption=encryption)
    # Bypass real decryption — return the api_key field as-is.
    service._decrypt_credentials = lambda creds: {"api_key": "test-key"}  # type: ignore[method-assign]
    return service, provider


def _mock_httpx_get(payload: dict[str, Any]):
    """Patch httpx.AsyncClient.get to return a 200 response with the given JSON."""

    async def fake_get(self, url, headers=None, **kwargs):  # noqa: ARG001
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    return patch("httpx.AsyncClient.get", new=fake_get)


@pytest.mark.asyncio
async def test_results_sorted_newest_first_with_display_names() -> None:
    """A response with ISO-formatted ``created_at`` and ``display_name``
    should be sorted newest-first and propagate the friendly name through."""
    payload = {
        "data": [
            {
                "id": "model-old",
                "display_name": "Model (Old)",
                "created_at": "2025-05-14T00:00:00Z",
            },
            {
                "id": "model-newest",
                "display_name": "Model (Newest)",
                "created_at": "2025-11-01T00:00:00Z",
            },
            {
                "id": "model-mid",
                "display_name": "Model (Mid)",
                "created_at": "2025-10-01T00:00:00Z",
            },
        ]
    }
    service, _ = _build_service_with_provider("openai")
    with _mock_httpx_get(payload), patch("litellm.model_cost", {}):
        result = await service.list_available_models(uuid4())

    names = [r["name"] for r in result]
    assert names == ["model-newest", "model-mid", "model-old"]
    assert result[0]["display_name"] == "Model (Newest)"
    # All entries get a mode (default "completion" for unknown live-listed names).
    assert all(r["mode"] == "completion" for r in result)


@pytest.mark.asyncio
async def test_openai_compatible_endpoint_with_rich_response_shape() -> None:
    """Validates the maintainability promise: any OpenAI-compatible provider
    that follows the /v1/models shape works without code changes. Some
    providers return additional fields (``name``, ``release_date``); the
    normalizer pulls them in via fallback chains."""
    payload = {
        "data": [
            {
                "id": "model-a",
                "name": "Model A",
                "object": "model",
                "created": 1730000000,
                "release_date": "2025-09-15",
            }
        ]
    }
    service, _ = _build_service_with_provider(
        "hosted_vllm", endpoint="https://api.example.com"
    )
    with _mock_httpx_get(payload), patch("litellm.model_cost", {}):
        result = await service.list_available_models(uuid4())

    assert len(result) == 1
    assert result[0]["name"] == "model-a"
    assert result[0]["display_name"] == "Model A"  # falls back from `name`
    assert result[0]["mode"] == "completion"  # default for unknown live-listed names


@pytest.mark.asyncio
async def test_openai_filters_realtime_and_audio_variants() -> None:
    """Live list calls into the same filter as the static endpoint, so noise
    like realtime-preview and gpt-audio doesn't reach the picker."""
    payload = {
        "data": [
            {"id": "gpt-4o", "created": 1715000000},
            {"id": "gpt-4o-realtime-preview", "created": 1716000000},
            {"id": "gpt-audio-mini", "created": 1717000000},
        ]
    }
    fake_cost = {
        "gpt-4o": {"litellm_provider": "openai", "mode": "chat"},
        "gpt-4o-realtime-preview": {"litellm_provider": "openai", "mode": "chat"},
        "gpt-audio-mini": {"litellm_provider": "openai", "mode": "chat"},
    }
    service, _ = _build_service_with_provider("openai")
    with _mock_httpx_get(payload), patch("litellm.model_cost", fake_cost):
        result = await service.list_available_models(uuid4())

    assert [r["name"] for r in result] == ["gpt-4o"]


@pytest.mark.asyncio
async def test_azure_returns_empty_without_calling_out() -> None:
    """Azure's /openai/models returns the wrong thing. We skip it entirely."""

    async def fail(*_args, **_kwargs):
        raise AssertionError("Azure should not perform an HTTP call")

    service, _ = _build_service_with_provider("azure")
    with patch("httpx.AsyncClient.get", new=fail):
        result = await service.list_available_models(uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_unknown_provider_without_endpoint_returns_empty() -> None:
    """A provider type without a default URL and without a configured
    endpoint short-circuits to empty — frontend then falls back to static."""

    async def fail(*_args, **_kwargs):
        raise AssertionError("Should not perform an HTTP call")

    service, _ = _build_service_with_provider("gemini")
    with patch("httpx.AsyncClient.get", new=fail):
        result = await service.list_available_models(uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_http_error_returns_error_entry_for_frontend() -> None:
    async def fake_get(self, url, headers=None, **kwargs):  # noqa: ARG001
        return httpx.Response(
            401, json={"error": "Unauthorized"}, request=httpx.Request("GET", url)
        )

    service, _ = _build_service_with_provider("anthropic")
    with patch("httpx.AsyncClient.get", new=fake_get):
        result = await service.list_available_models(uuid4())

    assert len(result) == 1 and "error" in result[0]


@pytest.mark.asyncio
async def test_anthropic_uses_x_api_key_header() -> None:
    """Verify the auth-header dispatch reaches the wire."""
    captured: dict[str, Any] = {}

    async def fake_get(self, url, headers=None, **kwargs):  # noqa: ARG001
        captured["url"] = url
        captured["headers"] = headers
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    service, _ = _build_service_with_provider("anthropic")
    with patch("httpx.AsyncClient.get", new=fake_get):
        await service.list_available_models(uuid4())

    assert captured["url"] == "https://api.anthropic.com/v1/models"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in captured["headers"]


@pytest.mark.asyncio
async def test_openai_compatible_endpoint_uses_bearer() -> None:
    captured: dict[str, Any] = {}

    async def fake_get(self, url, headers=None, **kwargs):  # noqa: ARG001
        captured["url"] = url
        captured["headers"] = headers
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    service, _ = _build_service_with_provider(
        "hosted_vllm", endpoint="https://api.example.com/"
    )
    with patch("httpx.AsyncClient.get", new=fake_get):
        await service.list_available_models(uuid4())

    # Trailing slash on endpoint should be stripped, no double slash in path.
    assert captured["url"] == "https://api.example.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_endpoint_with_v1_suffix_does_not_double() -> None:
    """Regression: users who paste the URL with ``/v1`` should not get
    ``…/v1/v1/models``."""
    captured: dict[str, Any] = {}

    async def fake_get(self, url, headers=None, **kwargs):  # noqa: ARG001
        captured["url"] = url
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    service, _ = _build_service_with_provider(
        "hosted_vllm", endpoint="https://api.example.com/v1"
    )
    with patch("httpx.AsyncClient.get", new=fake_get):
        await service.list_available_models(uuid4())

    assert captured["url"] == "https://api.example.com/v1/models"


@pytest.mark.asyncio
async def test_provider_metadata_classifies_embedding_with_obscure_name() -> None:
    """Regression: embedding models whose names don't contain the word
    "embedding" (e.g. ``intfloat/multilingual-e5-large-instruct``) used to
    get bucketed as completion. When the provider's response includes
    ``model_type``/``capabilities`` we use that instead of name inference."""
    payload = {
        "data": [
            {
                "id": "intfloat/multilingual-e5-large-instruct",
                "name": "multilingual-e5-large-instruct",
                "model_type": "embedding",
                "capabilities": {"embeddings": True},
            },
            {
                "id": "meta-llama/Llama-3.1-8B-Instruct",
                "name": "Llama-3.1-8B-Instruct",
                "model_type": "text",
                "capabilities": {"embeddings": False},
            },
        ]
    }
    service, _ = _build_service_with_provider(
        "hosted_vllm", endpoint="https://api.example.com"
    )
    with _mock_httpx_get(payload), patch("litellm.model_cost", {}):
        result = await service.list_available_models(uuid4())

    by_name = {r["name"]: r for r in result}
    assert by_name["intfloat/multilingual-e5-large-instruct"]["mode"] == "embedding"
    assert by_name["meta-llama/Llama-3.1-8B-Instruct"]["mode"] == "completion"


@pytest.mark.asyncio
async def test_mode_filter_returns_only_matching_entries() -> None:
    """Service-level mode filter: callers asking for ``mode="embedding"``
    must get only embedding entries; completion/transcription are dropped."""
    payload = {
        "data": [
            {"id": "chat-model", "created": 1715000000},
            {"id": "future-embedding-1", "created": 1716000000},
            {"id": "whisper-1", "created": 1717000000},
        ]
    }
    service, _ = _build_service_with_provider("openai")
    with _mock_httpx_get(payload), patch("litellm.model_cost", {}):
        result = await service.list_available_models(uuid4(), mode="embedding")

    assert len(result) == 1
    assert result[0]["name"] == "future-embedding-1"
    assert result[0]["mode"] == "embedding"


@pytest.mark.asyncio
async def test_mode_none_returns_all_modes() -> None:
    """Backwards compat: omitting ``mode`` returns everything (so existing
    consumers and ad-hoc /v1/models inspection both still work)."""
    payload = {
        "data": [
            {"id": "chat-model", "created": 1715000000},
            {"id": "future-embedding-1", "created": 1716000000},
            {"id": "whisper-1", "created": 1717000000},
        ]
    }
    service, _ = _build_service_with_provider("openai")
    with _mock_httpx_get(payload), patch("litellm.model_cost", {}):
        result = await service.list_available_models(uuid4())

    assert {r["mode"] for r in result} == {"completion", "embedding", "transcription"}


@pytest.mark.asyncio
async def test_delete_rejects_provider_with_attached_models_as_bad_request() -> None:
    repository = MagicMock()
    repository.count_models_for_provider = AsyncMock(return_value=2)
    repository.delete = AsyncMock()
    service = ModelProviderService(repository=repository, encryption=MagicMock())

    with pytest.raises(BadRequestException, match="2 model\\(s\\)"):
        await service.delete(uuid4())

    repository.delete.assert_not_awaited()

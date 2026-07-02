from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.model_providers.domain.model_provider_service import ModelProviderService


def _build_service_with_provider(
    provider_type: str,
) -> tuple[ModelProviderService, Any]:
    provider = MagicMock()
    provider.id = uuid4()
    provider.provider_type = provider_type
    provider.credentials = {"api_key": "ciphertext"}
    provider.config = {
        "endpoint": "https://models.example",
        "api_version": "2026-01-01",
        "deployment_name": "gpt-5-prod",
    }

    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=provider)

    service = ModelProviderService(repository=repository, encryption=MagicMock())
    service._decrypt_credentials = lambda creds: {"api_key": "test-key"}  # type: ignore[method-assign]
    return service, provider


@pytest.mark.asyncio
async def test_connection_uses_max_completion_tokens_for_azure(monkeypatch):
    captured_kwargs: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> None:
        captured_kwargs.update(kwargs)

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    service, provider = _build_service_with_provider("azure")

    result = await service.test_connection(provider.id)

    assert result == {"success": True, "message": "Connection successful"}
    assert captured_kwargs["model"] == "azure/gpt-5-prod"
    assert captured_kwargs["max_completion_tokens"] == 1
    assert captured_kwargs["drop_params"] is True
    assert "max_tokens" not in captured_kwargs

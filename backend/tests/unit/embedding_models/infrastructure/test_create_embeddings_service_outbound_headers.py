"""Which header configuration and attributes an embedding request uses.

A crawl embeds with the configuration snapshotted at bootstrap (documented);
everything else loads the provider row, and so its headers, per request.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.embedding_models.infrastructure.adapters.litellm_embeddings import (
    LiteLLMEmbeddingAdapter,
)
from eneo.embedding_models.infrastructure.create_embeddings_service import (
    CreateEmbeddingsService,
)
from eneo.model_providers.infrastructure import litellm_provider
from eneo.model_providers.infrastructure.litellm_provider import (
    ResolvedLiteLLMProvider,
)
from eneo.scim.constants import SCIM_ENTERPRISE_USER_URN
from eneo.settings.encryption_service import EncryptionService
from eneo.worker.crawl_context import EmbeddingModelSpec

ENDPOINT = "https://gateway.internal/v1"


def _stored(value: str) -> list[dict[str, Any]]:
    return [{"id": "h1", "name": "X-Org-Unit", "value": value, "secret": False}]


def _user(**enterprise: str) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        external_id=None,
        scim_extensions={SCIM_ENTERPRISE_USER_URN: enterprise} if enterprise else None,
    )


def _service(user: Any, *, session: Any = None) -> CreateEmbeddingsService:
    return CreateEmbeddingsService(
        tenant=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        encryption_service=EncryptionService(None),
        session=session,
        user=user,
    )


def _spec(provider_id: Any, stored: list[dict[str, Any]] | None) -> EmbeddingModelSpec:
    return EmbeddingModelSpec(
        id=uuid4(),
        name="embed",
        litellm_model_name="hosted_vllm/embed",
        family=None,
        max_input=512,
        max_batch_size=None,
        dimensions=None,
        provider_id=provider_id,
        provider_type="hosted_vllm",
        provider_credentials={},
        provider_config={"endpoint": ENDPOINT},
        provider_outbound_headers=stored,
    )


def _provider(provider_id: Any, stored: list[dict[str, Any]] | None) -> Any:
    return ResolvedLiteLLMProvider(
        id=provider_id,
        tenant_id=uuid4(),
        name="gateway",
        provider_type="hosted_vllm",
        credentials={},
        config={"endpoint": ENDPOINT},
        outbound_headers=stored,
    )


def _sent(adapter: Any) -> dict[str, str]:
    assert isinstance(adapter, LiteLLMEmbeddingAdapter)
    if adapter.outbound_headers is None:
        return {}
    return adapter.outbound_headers.resolve(ENDPOINT)


class TestCrawlSnapshot:
    async def test_the_bootstrap_snapshot_is_used_not_the_current_row(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        provider_id = uuid4()
        # The row as edited after the crawl started; must never be consulted.
        load = AsyncMock(return_value=_provider(provider_id, _stored("edited")))
        monkeypatch.setattr(litellm_provider, "load_active_litellm_provider", load)
        service = _service(_user())

        adapter = await service._get_adapter(_spec(provider_id, _stored("snapshot")))

        assert _sent(adapter) == {"X-Org-Unit": "snapshot"}
        load.assert_not_awaited()

    async def test_a_snapshot_without_headers_sends_none(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        provider_id = uuid4()
        load = AsyncMock(return_value=_provider(provider_id, _stored("added later")))
        monkeypatch.setattr(litellm_provider, "load_active_litellm_provider", load)

        adapter = await _service(_user())._get_adapter(_spec(provider_id, None))

        assert adapter.outbound_headers is None  # type: ignore[attr-defined]
        load.assert_not_awaited()


class TestFreshness:
    """Outside a crawl, each request reads the provider row and the user anew."""

    async def test_a_header_deleted_between_two_requests_is_not_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        provider_id = uuid4()
        load = AsyncMock(
            side_effect=[
                _provider(provider_id, _stored("eu-north")),
                _provider(provider_id, None),
            ]
        )
        monkeypatch.setattr(litellm_provider, "load_active_litellm_provider", load)
        model = SimpleNamespace(id=uuid4(), name="embed", provider_id=provider_id)
        service = _service(_user(), session=object())

        first = await service._get_adapter(model)  # type: ignore[arg-type]
        second = await service._get_adapter(model)  # type: ignore[arg-type]

        assert _sent(first) == {"X-Org-Unit": "eu-north"}
        assert _sent(second) == {}
        assert load.await_count == 2

    async def test_an_attribute_removed_between_two_requests_is_not_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        provider_id = uuid4()
        load = AsyncMock(
            return_value=_provider(provider_id, _stored("{{user.department}}"))
        )
        monkeypatch.setattr(litellm_provider, "load_active_litellm_provider", load)
        model = SimpleNamespace(id=uuid4(), name="embed", provider_id=provider_id)

        # Each request's container carries that request's user.
        before = await _service(
            _user(department="Miljö"), session=object()
        )._get_adapter(
            model  # type: ignore[arg-type]
        )
        after = await _service(_user(), session=object())._get_adapter(
            model  # type: ignore[arg-type]
        )

        assert _sent(before) == {"X-Org-Unit": "Milj%C3%B6"}
        assert _sent(after) == {}  # omitted by the default policy

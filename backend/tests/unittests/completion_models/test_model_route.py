from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.model_providers.domain.model_route import (
    MAX_MODEL_ROUTE_LENGTH,
    resolve_model_route,
)
from tests.fixtures import TEST_MODEL_CHATGPT


def test_completion_model_route_uses_provider_qualified_name():
    model = TEST_MODEL_CHATGPT.model_copy(
        update={
            "name": "claude-sonnet-4",
            "provider_type": "anthropic",
        }
    )

    assert model.get_model_route() == "anthropic/claude-sonnet-4"


def test_completion_model_route_preserves_explicit_legacy_route():
    model = TEST_MODEL_CHATGPT.model_copy(
        update={
            "provider_type": None,
            "litellm_model_name": "azure/legacy-deployment",
        }
    )

    assert model.get_model_route() == "azure/legacy-deployment"


def test_tenant_adapter_uses_the_completion_models_canonical_route():
    model = TEST_MODEL_CHATGPT.model_copy(
        update={
            "name": "gpt-4.1",
            "provider_id": uuid4(),
            "provider_type": "azure",
        }
    )

    adapter = TenantModelAdapter(
        model=model,
        credential_resolver=MagicMock(),
        provider_type="azure",
    )

    assert adapter.get_model_route() == model.get_model_route()


def test_model_route_accepts_the_maximum_length():
    route = "m" * MAX_MODEL_ROUTE_LENGTH

    assert resolve_model_route(model_name=route) == route


def test_model_route_rejects_an_oversized_route():
    with pytest.raises(ValueError, match="Model route cannot exceed"):
        resolve_model_route(model_name="m" * (MAX_MODEL_ROUTE_LENGTH + 1))

from unittest.mock import Mock

import pytest
from litellm.exceptions import BadRequestError

from intric.main.exceptions import APIKeyNotConfiguredException, OpenAIException
from intric.model_providers.infrastructure.litellm_provider import (
    build_litellm_model_name,
    build_litellm_provider_kwargs,
)
from intric.model_providers.infrastructure.litellm_transport import (
    INVALID_REQUEST_MESSAGE,
    is_provider_unavailable_error,
    raise_provider_unavailable,
    raise_public_litellm_error,
)
from intric.tenants.provider_field_config import get_required_fields


def test_build_litellm_model_name_is_canonical():
    assert (
        build_litellm_model_name("anthropic", "claude-sonnet-4")
        == "anthropic/claude-sonnet-4"
    )


def test_hosted_vllm_does_not_require_api_key():
    resolver = Mock(provider_type="hosted_vllm")
    resolver.get_api_key.return_value = None
    resolver.get_credential_field.side_effect = lambda *, field, required=False: (
        "https://models.example/v1" if field == "endpoint" else None
    )

    kwargs = build_litellm_provider_kwargs(resolver)

    resolver.get_api_key.assert_called_once_with(required=False)
    assert kwargs == {"api_base": "https://models.example/v1"}
    assert get_required_fields("hosted_vllm") == {"endpoint"}


def test_azure_provider_fields_are_resolved_once_from_canonical_definition():
    values = {
        "endpoint": "https://azure.example",
        "api_version": "2026-01-01",
        "deployment_name": "gpt-4o-prod",
    }
    resolver = Mock(provider_type="azure")
    resolver.get_api_key.return_value = "secret"
    resolver.get_credential_field.side_effect = (
        lambda *, field, required=False: values.get(field)
    )

    kwargs = build_litellm_provider_kwargs(resolver)

    assert kwargs == {
        "api_key": "secret",
        "api_base": "https://azure.example",
        "api_version": "2026-01-01",
    }


def test_bad_request_error_does_not_leak_provider_details():
    provider_error = BadRequestError(
        message="secret upstream deployment details",
        model="gpt-4o",
        llm_provider="openai",
    )

    with pytest.raises(OpenAIException) as exc_info:
        raise_public_litellm_error(
            provider_error,
            provider_type="openai",
            is_unavailable=is_provider_unavailable_error,
            raise_unavailable=raise_provider_unavailable,
        )

    assert str(exc_info.value) == INVALID_REQUEST_MESSAGE
    assert "secret upstream" not in str(exc_info.value)
    assert exc_info.value.code == "provider_rejected_request"


def test_credential_resolution_error_does_not_leak_internal_details():
    resolver = Mock(provider_type="openai")
    resolver.get_api_key.side_effect = ValueError(
        "Failed to decrypt provider 123 with key material xyz"
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        build_litellm_provider_kwargs(resolver)

    assert "decrypt" not in str(exc_info.value).lower()
    assert "123" not in str(exc_info.value)

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eneo.flows.domain.provider_call import (
    ProviderCallRequest,
    ProviderCallResponseFormat,
)


@pytest.mark.parametrize(
    "requested_capabilities",
    [
        ("reasoning", "reasoning"),
        ("tool_calling", "reasoning"),
    ],
)
def test_provider_call_request_rejects_non_canonical_capability_tuples(
    requested_capabilities: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError, match="sorted and unique"):
        ProviderCallRequest.model_validate(
            {
                "provider_request_hash": "a" * 64,
                "requested_capabilities": requested_capabilities,
            }
        )


@pytest.mark.parametrize(
    ("response_format", "requested_capabilities"),
    [
        (ProviderCallResponseFormat.JSON_OBJECT, ()),
        (ProviderCallResponseFormat.NONE, ("structured_output",)),
    ],
)
def test_provider_call_request_rejects_inconsistent_structured_output_facts(
    response_format: ProviderCallResponseFormat,
    requested_capabilities: tuple[str, ...],
) -> None:
    with pytest.raises(
        ValidationError,
        match="Structured-output capability and response format must agree",
    ):
        ProviderCallRequest(
            provider_request_hash="a" * 64,
            requested_model="openai/test-model",
            provider="openai",
            response_format=response_format,
            requested_capabilities=requested_capabilities,
        )

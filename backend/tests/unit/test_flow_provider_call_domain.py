from __future__ import annotations

import pytest
from pydantic import ValidationError

from eneo.flows.domain.provider_call import ProviderCallRequest


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

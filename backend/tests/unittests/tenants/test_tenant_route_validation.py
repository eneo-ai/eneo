import pytest
from pydantic import ValidationError

from eneo.tenants.presentation.tenant_federation_router import (
    PatchFederationRequest,
)


@pytest.mark.parametrize(
    "field",
    ["provider", "discovery_endpoint", "client_id", "client_secret"],
)
def test_patch_federation_rejects_explicit_null_for_required_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="PATCH does not allow null"):
        PatchFederationRequest.model_validate({field: None})


def test_patch_federation_allows_required_fields_to_be_omitted() -> None:
    request = PatchFederationRequest.model_validate(
        {"allowed_domains": ["example.com"]}
    )

    assert request.model_fields_set == {"allowed_domains"}

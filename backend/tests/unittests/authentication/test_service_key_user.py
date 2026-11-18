from uuid import uuid4

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    CredentialFacts,
)
from eneo.authentication.service_key_user import build_service_key_user
from tests.fixtures import TEST_TENANT
from tests.unit.api_key_test_utils import make_api_key


def test_a_service_key_user_names_its_credential() -> None:
    """A request admitted with a service key carries the credential the
    request rules read, like any other API key request."""
    key = make_api_key(
        default_permission=ApiKeyPermission.WRITE,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        tenant_id=TEST_TENANT.id,
        service_principal_id=uuid4(),
    )

    user = build_service_key_user(key=key, tenant=TEST_TENANT)

    assert user.credential == CredentialFacts(kind="api_key")

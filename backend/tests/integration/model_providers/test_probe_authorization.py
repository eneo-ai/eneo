"""Only tenant admins may call a model provider with its stored credentials.

Connection-check and its legacy /test adapter are covered through the real
service in test_provider_connection_check.py.
"""

from uuid import uuid4

import pytest

from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def tenant_tokens(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        users = container.user_repo()
        admin = await users.get_user_by_email("test@example.com")
        member = await users.add(
            UserAdd(
                email=f"provider-member-{uuid4().hex[:8]}@example.com",
                username=f"provider_member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
            )
        )
        auth = container.auth_service()
        return (
            auth.create_access_token_for_user(admin),
            auth.create_access_token_for_user(member),
        )


@pytest.mark.parametrize(
    ("method", "path", "body", "service_method", "result"),
    [
        ("GET", "models", None, "list_available_models", []),
        (
            "POST",
            "validate-model",
            {"model_name": "gpt-4o", "model_type": "completion"},
            "validate_model",
            {"success": True},
        ),
    ],
)
async def test_provider_probes_require_admin(
    client, tenant_tokens, monkeypatch, method, path, body, service_method, result
):
    calls = 0

    async def probe(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return result

    monkeypatch.setattr(ModelProviderService, service_method, probe)
    admin_token, member_token = tenant_tokens
    url = f"/api/v1/admin/model-providers/{uuid4()}/{path}/"

    member_response = await client.request(
        method, url, headers={"Authorization": f"Bearer {member_token}"}, json=body
    )
    assert member_response.status_code == 403, member_response.text
    assert calls == 0

    admin_response = await client.request(
        method, url, headers={"Authorization": f"Bearer {admin_token}"}, json=body
    )
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json() == result
    assert calls == 1

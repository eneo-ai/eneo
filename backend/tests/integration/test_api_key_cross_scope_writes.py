"""Adversarial integration tests for API key v2 — \"allow least possible\".

Each test encodes a scenario where an API key is intended to be rejected.
A pass means the boundary held: body-driven cross-scope writes, feature-flag
variations, dual credentials, lifecycle edges (suspend), and denial-message
side channels.

Run with:
    uv run pytest tests/integration/test_api_key_cross_scope_writes.py -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/integration/test_api_key_scope_integration.py)
# ---------------------------------------------------------------------------


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(default_user)
    return token


@pytest.fixture
async def api_client(app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
        follow_redirects=True,
    ) as c:
        yield c


@pytest.fixture
def resource_permissions_enforcement_off(test_settings):
    """Temporarily set ``api_key_enforce_resource_permissions=False``.

    Mirrors the ``legacy_credentials_mode`` fixture: mutates the global settings
    singleton (not via env vars), rebuilds the DI-managed encryption service to
    keep the Container consistent, and restores on teardown.
    """
    from dependency_injector import providers

    from intric.main.config import get_settings, set_settings
    from intric.main.container.container import Container
    from intric.settings.encryption_service import EncryptionService

    original_settings = get_settings()
    override = test_settings.model_copy(
        update={"api_key_enforce_resource_permissions": False}
    )
    set_settings(override)

    Container.encryption_service.reset_last_overriding()
    service = EncryptionService(override.encryption_key)
    Container.encryption_service.override(providers.Object(service))

    yield

    set_settings(original_settings)
    Container.encryption_service.reset_last_overriding()
    original_service = EncryptionService(original_settings.encryption_key)
    Container.encryption_service.override(providers.Object(original_service))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_space(client, *, token: str, name: str | None = None) -> str:
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": name or f"space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_assistant(client, *, token: str, space_id: str) -> str:
    resp = await client.post(
        "/api/v1/assistants/",
        json={"name": f"asst-{uuid4().hex[:8]}", "space_id": space_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_api_key(
    client,
    *,
    token: str,
    scope_type: str = "tenant",
    scope_id: str | None = None,
    permission: str = "read",
    resource_permissions: dict | None = None,
) -> tuple[str, str]:
    """Create an sk_ key and return (secret, key_id)."""
    body: dict = {
        "name": f"key-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
    }
    if scope_id is not None:
        body["scope_id"] = scope_id
    if resource_permissions is not None:
        body["resource_permissions"] = resource_permissions
    resp = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    return payload["secret"], payload["api_key"]["id"]


def _error_code(resp) -> str | None:
    try:
        current = resp.json()
    except Exception:
        return None
    for _ in range(4):
        if not isinstance(current, dict):
            return None
        code = current.get("code")
        if isinstance(code, str):
            return code
        current = current.get("detail")
    return None


# ---------------------------------------------------------------------------
# Lifecycle edge: suspended key
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_suspended_key_is_rejected_on_every_request(client, bearer_token):
    """A suspended key must fail authentication on any endpoint."""
    secret, key_id = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="read"
    )

    # Sanity: key works before suspension
    pre = await client.get("/api/v1/spaces/", headers={"X-API-Key": secret})
    assert pre.status_code == 200, pre.text

    # Suspend it
    suspend_resp = await client.post(
        f"/api/v1/api-keys/{key_id}/suspend",
        json={"reason_code": "security_concern", "reason_text": "test"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert suspend_resp.status_code == 200, suspend_resp.text
    assert suspend_resp.json()["state"] == "suspended"

    # Same key, every verb — must be rejected
    for method, path in [
        ("GET", "/api/v1/spaces/"),
        ("GET", "/api/v1/assistants/"),
        ("POST", "/api/v1/spaces/"),
    ]:
        resp = await client.request(
            method,
            path,
            headers={"X-API-Key": secret},
            json={"name": "after-suspend"} if method == "POST" else None,
        )
        assert resp.status_code in (401, 403), (
            f"{method} {path} after suspend returned {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Feature-flag-off contract: basic permission is still a ceiling
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_feature_flag_off_basic_permission_is_still_enforced(
    client, bearer_token, resource_permissions_enforcement_off
):
    """With ``api_key_enforce_resource_permissions=False`` the fine-grained
    ResourcePermissions granularity is skipped, but the basic method→permission
    ceiling must still fail-close: a read-only key must not be able to POST."""
    # Read-only key, no resource_permissions payload.
    read_secret, _ = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="read"
    )

    # GET passes the basic method check.
    get_resp = await client.get("/api/v1/spaces/", headers={"X-API-Key": read_secret})
    assert get_resp.status_code == 200, get_resp.text

    # POST must still 403 — basic method check is method→write for POST,
    # and the key is only read-level.
    post_resp = await client.post(
        "/api/v1/spaces/",
        json={"name": "should-be-denied"},
        headers={"X-API-Key": read_secret},
    )
    assert post_resp.status_code == 403, post_resp.text
    assert _error_code(post_resp) in {
        "insufficient_permission",
        "insufficient_resource_permission",
    }, post_resp.text


# ---------------------------------------------------------------------------
# Dual credentials: invalid bearer + valid api-key
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dual_credentials_invalid_bearer_does_not_silently_escalate(
    client, bearer_token
):
    """Sending an invalid Bearer JWT alongside a valid API key must not grant
    bearer-path privileges. Either the request is authorized by the API key
    alone (at the key's scope/permission) or it is rejected — never more."""
    read_secret, _ = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="read"
    )

    # Garbage bearer + valid X-API-Key header on the SAME request.
    # Expectations:
    #   - If bearer takes precedence and raises: 401 (do not escalate).
    #   - If the API key is honored: outcome matches the KEY's permissions,
    #     not the bearer user's (so POST still 403 for a read key).
    get_resp = await client.get(
        "/api/v1/spaces/",
        headers={
            "Authorization": "Bearer this.is.not.a.valid.jwt",
            "X-API-Key": read_secret,
        },
    )
    # Read key + GET is permitted; invalid bearer must not DE-authorize.
    # A 401 would mean the bearer path clobbered the key. That is a regression
    # direction we accept (no escalation) but note it:
    assert get_resp.status_code in (200, 401), (
        f"Unexpected status {get_resp.status_code}: {get_resp.text}"
    )

    # The dangerous direction: read key + POST must NEVER succeed, regardless
    # of what the bearer user would have been allowed to do.
    post_resp = await client.post(
        "/api/v1/spaces/",
        json={"name": "dual-cred-should-fail"},
        headers={
            "Authorization": "Bearer this.is.not.a.valid.jwt",
            "X-API-Key": read_secret,
        },
    )
    assert post_resp.status_code in (401, 403), (
        f"Read key POST with invalid bearer returned {post_resp.status_code}: "
        f"{post_resp.text}"
    )


# ---------------------------------------------------------------------------
# Body-driven cross-scope: transfer assistant to a space the key does not own
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transfer_assistant_to_other_space_denied_for_space_scoped_key(
    client, bearer_token
):
    """A space-scoped key transferring an assistant into a different space
    must be denied. API-key v2 scopes are single-space, so any operation
    that affects a space outside the key's scope requires a tenant key.

    Denial happens at the service layer: resource_mover_service calls
    actor.can_create_assistants() on the target space, and the actor returns
    no role because the key's scope does not cover that space."""
    space_a = await _create_space(client, token=bearer_token, name="xfer-A")
    space_b = await _create_space(client, token=bearer_token, name="xfer-B")
    asst = await _create_assistant(client, token=bearer_token, space_id=space_a)

    key_a, _ = await _create_api_key(
        client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_a,
        permission="admin",
    )

    resp = await client.post(
        f"/api/v1/assistants/{asst}/transfer/",
        json={"target_space_id": space_b, "move_resources": False},
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code in (403, 422), (
        f"Space-A-scoped key transferred assistant into space B "
        f"(status={resp.status_code}): {resp.text}."
    )

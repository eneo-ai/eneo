"""Integration tests for API v2 scope hardening (Plan 2A-2D).

Covers:
- 2A: Admin route guards (integration, storage, user-groups)
- 2B: List filtering regressions (assistants, spaces)
- 2B: Prompt scope checks
- 2C: Create-body scope mismatch (POST /assistants/)
- 2D: Files behavior contract (GET/POST allowed, DELETE blocked)

These tests hit real endpoints through httpx ASGI transport with a real database.
Scope enforcement defaults to True (env flag + feature flag fail-closed).
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from intric.main.config import get_settings, set_settings


# ---------------------------------------------------------------------------
# Fixtures
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
    """HTTP client with follow_redirects=True to handle FastAPI trailing-slash redirects."""
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
        follow_redirects=True,
    ) as c:
        yield c


async def _create_space(client, *, token: str, name: str | None = None) -> str:
    """Create a space and return its ID."""
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": name or f"space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_assistant(client, *, token: str, space_id: str) -> str:
    """Create an assistant in a space and return its ID."""
    resp = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"asst-{uuid4().hex[:8]}",
            "space_id": space_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_app(client, *, token: str, space_id: str) -> str:
    """Create an app in a space and return its ID."""
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"app-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_assistant_with_prompt(
    client,
    *,
    token: str,
    space_id: str,
    prompt_text: str,
    db_container,
    user_id: UUID,
    tenant_id: UUID,
) -> tuple[str, str]:
    """Create assistant and seed a selected prompt mapping; return (assistant_id, prompt_id)."""
    import sqlalchemy as sa
    from intric.database.tables.prompts_table import Prompts, PromptsAssistants

    resp = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"asst-{uuid4().hex[:8]}",
            "space_id": space_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assistant_id = resp.json()["id"]

    async with db_container() as container:
        session = container.session()
        prompt_id = await session.scalar(
            sa.insert(Prompts)
            .values(
                text=prompt_text,
                description="scope-test",
                user_id=user_id,
                tenant_id=tenant_id,
            )
            .returning(Prompts.id)
        )
        await session.execute(
            sa.insert(PromptsAssistants).values(
                prompt_id=prompt_id,
                assistant_id=UUID(assistant_id),
                is_selected=True,
            )
        )
        await session.commit()

    return assistant_id, str(prompt_id)


async def _create_group(client, *, token: str, space_id: str, name: str | None = None) -> str:
    """Create a legacy knowledge group/collection in a space and return its ID."""
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge/groups/",
        json={"name": name or f"group-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_info_blob(
    db_container,
    *,
    user_id: UUID,
    tenant_id: UUID,
    group_id: str,
    text: str,
) -> str:
    """Create one info blob directly in DB (avoids external embedding dependency)."""
    from intric.info_blobs.info_blob import InfoBlobAdd

    async with db_container() as container:
        repo = container.info_blob_repo()
        blob = await repo.add(
            InfoBlobAdd(
                text=text,
                size=len(text.encode("utf-8")),
                user_id=user_id,
                tenant_id=tenant_id,
                group_id=UUID(group_id),
            )
        )
    return str(blob.id)


async def _create_api_key(
    client,
    *,
    token: str,
    scope_type: str = "tenant",
    scope_id: str | None = None,
    permission: str = "read",
) -> str:
    """Create an sk_ API key and return the secret."""
    body: dict = {
        "name": f"key-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
    }
    if scope_id is not None:
        body["scope_id"] = scope_id
    resp = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["secret"]


async def _create_file_scoped_key(
    client,
    *,
    token: str,
    scope_type: str,
    permission: str = "write",
) -> str:
    """Create scope resource(s) as needed and return an API key for file-route tests."""
    if scope_type == "app":
        existing_apps_resp = await client.get(
            "/api/v1/apps/",
            headers={"Authorization": f"Bearer {token}"},
        )
        if existing_apps_resp.status_code == 404:
            existing_apps_resp = await client.get(
                "/api/v1/apps",
                headers={"Authorization": f"Bearer {token}"},
            )
        if existing_apps_resp.status_code != 200:
            pytest.skip(
                f"Cannot query apps endpoint for app-scoped key fixture (status={existing_apps_resp.status_code})"
            )
        existing_apps = existing_apps_resp.json().get("items", [])
        if existing_apps:
            scope_id = existing_apps[0]["id"]
        else:
            # App creation requires transcription model setup in the target space.
            # Fall back to creating one; skip if fixture tenant lacks prerequisites.
            space_id = await _create_space(
                client, token=token, name=f"file-scope-{scope_type}-{uuid4().hex[:6]}"
            )
            try:
                scope_id = await _create_app(client, token=token, space_id=space_id)
            except AssertionError as exc:
                pytest.skip(f"Cannot provision app-scoped key fixture in this environment: {exc}")
    else:
        space_id = await _create_space(
            client, token=token, name=f"file-scope-{scope_type}-{uuid4().hex[:6]}"
        )
        scope_id = space_id

    if scope_type == "assistant":
        scope_id = await _create_assistant(client, token=token, space_id=space_id)

    return await _create_api_key(
        client,
        token=token,
        scope_type=scope_type,
        scope_id=scope_id,
        permission=permission,
    )


def _error_code_from_response(response) -> str | None:
    """Best-effort extraction of API error code across payload shapes."""
    try:
        current = response.json()
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


@contextmanager
def _scope_enforcement_kill_switch(mode: str):
    """Temporarily disable scope enforcement using env-off or tenant-flag-off mode."""
    if mode not in {"env_off", "tenant_flag_off"}:
        raise ValueError(f"Unsupported mode: {mode}")

    settings = get_settings()
    patched = settings.model_copy(update={"api_key_enforce_scope": mode != "env_off"})
    set_settings(patched)
    tenant_patch = (
        patch(
            "intric.users.user_service.UserService._is_scope_enforcement_enabled",
            new=AsyncMock(return_value=False),
        )
        if mode == "tenant_flag_off"
        else nullcontext()
    )
    try:
        with tenant_patch:
            yield
    finally:
        set_settings(settings)


# ---------------------------------------------------------------------------
# 2B: List Filtering — Assistants
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_get_assistants_returns_only_scope_space(
    client, bearer_token
):
    """Space-scoped key listing assistants sees only assistants in its space."""
    space_a = await _create_space(client, token=bearer_token, name="space-A")
    space_b = await _create_space(client, token=bearer_token, name="space-B")
    asst_a = await _create_assistant(client, token=bearer_token, space_id=space_a)
    asst_b = await _create_assistant(client, token=bearer_token, space_id=space_b)

    # Key scoped to space A
    key_a = await _create_api_key(
        client, token=bearer_token, scope_type="space", scope_id=space_a
    )

    resp = await client.get(
        "/api/v1/assistants/",
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    ids = {item["id"] for item in items}
    assert asst_a in ids, f"Expected assistant {asst_a} in space A, got {ids}"
    assert asst_b not in ids, f"Assistant {asst_b} from space B should NOT appear"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assistant_scoped_key_get_assistants_returns_only_that_assistant(
    client, bearer_token
):
    """Assistant-scoped key listing assistants sees only its own assistant."""
    space = await _create_space(client, token=bearer_token)
    asst_1 = await _create_assistant(client, token=bearer_token, space_id=space)
    asst_2 = await _create_assistant(client, token=bearer_token, space_id=space)

    key = await _create_api_key(
        client, token=bearer_token, scope_type="assistant", scope_id=asst_1
    )

    resp = await client.get(
        "/api/v1/assistants/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    ids = {item["id"] for item in items}
    assert asst_1 in ids
    assert asst_2 not in ids


# ---------------------------------------------------------------------------
# 2B: List Filtering — Spaces
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_get_spaces_returns_only_scope_space(
    client, bearer_token
):
    """Space-scoped key listing spaces sees only its scoped space."""
    space_a = await _create_space(client, token=bearer_token, name="space-scope-A")
    space_b = await _create_space(client, token=bearer_token, name="space-scope-B")

    key_a = await _create_api_key(
        client, token=bearer_token, scope_type="space", scope_id=space_a
    )

    resp = await client.get(
        "/api/v1/spaces/",
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    ids = {item["id"] for item in items}
    assert space_a in ids, f"Expected space {space_a}, got {ids}"
    assert space_b not in ids, f"Space {space_b} should NOT appear"


# ---------------------------------------------------------------------------
# 2B: List Filtering — Info Blobs + Legacy Groups
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_get_info_blobs_returns_only_scope_space_blobs(
    api_client, bearer_token, db_container, default_user
):
    """Space-scoped key listing /info-blobs/ only sees blobs from the scoped space."""
    space_a = await _create_space(api_client, token=bearer_token, name="blob-space-A")
    space_b = await _create_space(api_client, token=bearer_token, name="blob-space-B")
    group_a = await _create_group(api_client, token=bearer_token, space_id=space_a)
    group_b = await _create_group(api_client, token=bearer_token, space_id=space_b)

    blob_a = await _seed_info_blob(
        db_container,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        group_id=group_a,
        text="space-a-blob",
    )
    blob_b = await _seed_info_blob(
        db_container,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        group_id=group_b,
        text="space-b-blob",
    )

    key_a = await _create_api_key(
        api_client, token=bearer_token, scope_type="space", scope_id=space_a
    )

    resp = await api_client.get(
        "/api/v1/info-blobs/",
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert blob_a in ids, f"Expected blob {blob_a} from scoped space, got {ids}"
    assert blob_b not in ids, f"Blob {blob_b} from other space should not appear"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_get_legacy_groups_returns_only_scope_space_groups(
    api_client, bearer_token
):
    """Space-scoped key listing legacy /groups/ only sees groups from scoped space."""
    space_a = await _create_space(api_client, token=bearer_token, name="groups-space-A")
    space_b = await _create_space(api_client, token=bearer_token, name="groups-space-B")

    group_a = await _create_group(
        api_client, token=bearer_token, space_id=space_a, name="group-A"
    )
    group_b = await _create_group(
        api_client, token=bearer_token, space_id=space_b, name="group-B"
    )

    key_a = await _create_api_key(
        api_client, token=bearer_token, scope_type="space", scope_id=space_a
    )

    resp = await api_client.get(
        "/api/v1/groups/",
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert group_a in ids, f"Expected group {group_a} from scoped space, got {ids}"
    assert group_b not in ids, f"Group {group_b} from other space should not appear"


# ---------------------------------------------------------------------------
# 2B: Dashboard Filtering
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_dashboard_returns_only_scope_space(
    api_client, bearer_token
):
    """Space-scoped key should only see its scoped space in dashboard payload."""
    space_a = await _create_space(api_client, token=bearer_token, name="dash-space-A")
    space_b = await _create_space(api_client, token=bearer_token, name="dash-space-B")

    key_a = await _create_api_key(
        api_client, token=bearer_token, scope_type="space", scope_id=space_a
    )

    resp = await api_client.get(
        "/api/v1/dashboard/",
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["spaces"]["items"]}
    assert space_a in ids, f"Expected scoped space {space_a}, got {ids}"
    assert space_b not in ids, f"Non-scoped space {space_b} should not appear"


# ---------------------------------------------------------------------------
# 2B: Prompt Scope
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_can_access_prompt_in_same_space(
    api_client, bearer_token, db_container, default_user
):
    """Space-scoped key can access prompt linked to assistant in same space."""
    space = await _create_space(api_client, token=bearer_token, name="prompt-space")
    _, prompt_id = await _create_assistant_with_prompt(
        api_client,
        token=bearer_token,
        space_id=space,
        prompt_text="same-space-prompt",
        db_container=db_container,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
    )

    key = await _create_api_key(
        api_client, token=bearer_token, scope_type="space", scope_id=space
    )

    resp = await api_client.get(
        f"/api/v1/prompts/{prompt_id}/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == prompt_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_denied_prompt_from_other_space(
    api_client, bearer_token, db_container, default_user
):
    """Space-scoped key cannot access prompt linked to assistant in other space."""
    space_a = await _create_space(api_client, token=bearer_token, name="prompt-space-A")
    space_b = await _create_space(api_client, token=bearer_token, name="prompt-space-B")
    _, _ = await _create_assistant_with_prompt(
        api_client,
        token=bearer_token,
        space_id=space_a,
        prompt_text="space-a-prompt",
        db_container=db_container,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
    )
    _, prompt_b = await _create_assistant_with_prompt(
        api_client,
        token=bearer_token,
        space_id=space_b,
        prompt_text="space-b-prompt",
        db_container=db_container,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
    )

    key_a = await _create_api_key(
        api_client, token=bearer_token, scope_type="space", scope_id=space_a
    )

    resp = await api_client.get(
        f"/api/v1/prompts/{prompt_b}/",
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    detail = body.get("detail", body)
    assert detail["code"] == "insufficient_scope"


# ---------------------------------------------------------------------------
# 2C: Create-Body Scope Mismatch
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_post_assistants_wrong_space_returns_403(
    api_client, bearer_token
):
    """Space-scoped key creating assistant in another space → 403 insufficient_scope."""
    space_a = await _create_space(api_client, token=bearer_token)
    space_b = await _create_space(api_client, token=bearer_token)

    key_a = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_a,
        permission="write",
    )

    resp = await api_client.post(
        "/api/v1/assistants/",
        json={"name": "cross-space-bot", "space_id": space_b},
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    body = resp.json()
    detail = body.get("detail", body)
    assert detail["code"] == "insufficient_scope"
    assert space_a in detail["message"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_post_assistants_matching_space_succeeds(
    client, bearer_token
):
    """Space-scoped key creating assistant in its own space → success."""
    space = await _create_space(client, token=bearer_token)

    key = await _create_api_key(
        client,
        token=bearer_token,
        scope_type="space",
        scope_id=space,
        permission="write",
    )

    resp = await client.post(
        "/api/v1/assistants/",
        json={"name": "in-scope-bot", "space_id": space},
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["space_id"] == space


# ---------------------------------------------------------------------------
# 2C: Path Scope Mismatch on Space-Scoped Create Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_cannot_create_app_in_other_space_path(
    api_client, bearer_token
):
    """Space-scoped key cannot create app under another space path."""
    space_a = await _create_space(api_client, token=bearer_token)
    space_b = await _create_space(api_client, token=bearer_token)

    key_a = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_a,
        permission="write",
    )

    resp = await api_client.post(
        f"/api/v1/spaces/{space_b}/applications/apps/",
        json={"name": "cross-space-app"},
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 403, resp.text
    assert _error_code_from_response(resp) == "insufficient_scope", resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_cannot_create_collection_in_other_space_path(
    api_client, bearer_token
):
    """Space-scoped key cannot create collection under another space path."""
    space_a = await _create_space(api_client, token=bearer_token)
    space_b = await _create_space(api_client, token=bearer_token)

    key_a = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_a,
        permission="write",
    )

    resp = await api_client.post(
        f"/api/v1/spaces/{space_b}/knowledge/groups/",
        json={"name": "cross-space-collection"},
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 403, resp.text
    assert _error_code_from_response(resp) == "insufficient_scope", resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_cannot_create_website_in_other_space_path(
    api_client, bearer_token
):
    """Space-scoped key cannot create website under another space path."""
    space_a = await _create_space(api_client, token=bearer_token)
    space_b = await _create_space(api_client, token=bearer_token)

    key_a = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_a,
        permission="write",
    )

    resp = await api_client.post(
        f"/api/v1/spaces/{space_b}/knowledge/websites/",
        json={"url": "https://example.com", "name": "cross-space-site"},
        headers={"X-API-Key": key_a},
    )
    assert resp.status_code == 403, resp.text
    assert _error_code_from_response(resp) == "insufficient_scope", resp.text


# ---------------------------------------------------------------------------
# 2B: List Filtering — for_tenant blocked for scoped keys
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_for_tenant_true_blocked(api_client, bearer_token):
    """Space-scoped key cannot use for_tenant=true (requires tenant scope)."""
    space = await _create_space(api_client, token=bearer_token)
    key = await _create_api_key(
        api_client, token=bearer_token, scope_type="space", scope_id=space
    )

    resp = await api_client.get(
        "/api/v1/assistants/?for_tenant=true",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    body = resp.json()
    detail = body.get("detail", body)
    assert detail["code"] == "insufficient_scope"


# ---------------------------------------------------------------------------
# 2D: Files Behavior Contract
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_get_files_allowed(client, bearer_token):
    """Space-scoped key can GET /files/ (files are user-scoped, read is safe)."""
    space = await _create_space(client, token=bearer_token)
    key = await _create_api_key(
        client, token=bearer_token, scope_type="space", scope_id=space
    )

    resp = await client.get(
        "/api/v1/files/",
        headers={"X-API-Key": key},
    )
    # Should succeed (200) even if empty — not blocked by scope
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_delete_files_denied_403(api_client, bearer_token):
    """Space-scoped key DELETE /files/{id} → 403 insufficient_scope.

    Files are user-scoped; DELETE is blocked for non-tenant keys because
    files may be attached to conversations across multiple spaces.
    """
    space = await _create_space(api_client, token=bearer_token)
    key = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space,
        permission="admin",
    )

    # Use a random UUID — the scope check fires BEFORE the file lookup
    resp = await api_client.delete(
        f"/api/v1/files/{uuid4()}/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    body = resp.json()
    detail = body.get("detail", body)
    assert detail["code"] == "insufficient_scope"
    assert "tenant-scoped" in detail["message"]


# ---------------------------------------------------------------------------
# 2A: Admin Route Guards
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_cannot_access_storage_admin(client, bearer_token):
    """Space-scoped key accessing /storage/ (admin route) → 403."""
    space = await _create_space(client, token=bearer_token)
    key = await _create_api_key(
        client, token=bearer_token, scope_type="space", scope_id=space
    )

    resp = await client.get(
        "/api/v1/storage/",
        headers={"X-API-Key": key},
    )
    # Should be blocked by TENANT_ADMIN_API_KEY_GUARDS
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_read_key_cannot_access_storage_admin(client, bearer_token):
    """Tenant-scoped READ key accessing /storage/ (requires ADMIN) → 403."""
    key = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="read"
    )

    resp = await client.get(
        "/api/v1/storage/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_admin_key_can_access_storage(client, bearer_token):
    """Tenant-scoped ADMIN key accessing /storage/ → success."""
    key = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="admin"
    )

    resp = await client.get(
        "/api/v1/storage/",
        headers={"X-API-Key": key},
    )
    # Should succeed (may return empty data, but not 403)
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_cannot_access_integrations_admin(client, bearer_token):
    """Space-scoped key accessing /integrations/ (admin route) → 403."""
    space = await _create_space(client, token=bearer_token)
    key = await _create_api_key(
        client, token=bearer_token, scope_type="space", scope_id=space
    )

    resp = await client.get(
        "/api/v1/integrations/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_read_key_cannot_access_integrations_admin(client, bearer_token):
    """Tenant-scoped READ key cannot access integration admin routes (ADMIN required)."""
    key = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="read"
    )

    resp = await client.get(
        "/api/v1/integrations/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_admin_key_can_access_integrations_admin(client, bearer_token):
    """Tenant-scoped ADMIN key can access integration admin routes."""
    key = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="admin"
    )

    resp = await client.get(
        "/api/v1/integrations/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_cannot_access_user_groups_admin(client, bearer_token):
    """Space-scoped key accessing /user-groups/ (admin route) → 403."""
    space = await _create_space(client, token=bearer_token)
    key = await _create_api_key(
        client, token=bearer_token, scope_type="space", scope_id=space
    )

    resp = await client.get(
        "/api/v1/user-groups/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_read_key_cannot_access_user_groups_admin(client, bearer_token):
    """Tenant-scoped READ key cannot access user-groups admin routes."""
    key = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="read"
    )

    resp = await client.get(
        "/api/v1/user-groups/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_admin_key_can_access_user_groups_admin(client, bearer_token):
    """Tenant-scoped ADMIN key can access user-groups admin routes."""
    key = await _create_api_key(
        client, token=bearer_token, scope_type="tenant", permission="admin"
    )

    resp = await client.get(
        "/api/v1/user-groups/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 2D: Files — additional coverage (POST allowed, tenant DELETE not blocked)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_post_files_allowed(api_client, bearer_token):
    """Space-scoped key can POST /files/ (upload for conversation workflow)."""
    space = await _create_space(api_client, token=bearer_token)
    key = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space,
        permission="write",
    )

    # Upload a tiny text file
    resp = await api_client.post(
        "/api/v1/files/",
        files={"upload_file": ("test.txt", b"hello world", "text/plain")},
        headers={"X-API-Key": key},
    )
    # Should succeed (200 or 201) — not blocked by scope
    assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_space_scoped_key_get_file_by_id_allowed(api_client, bearer_token):
    """Space-scoped key can GET /files/{id}/ for files it owns."""
    space = await _create_space(api_client, token=bearer_token)
    key = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space,
        permission="write",
    )

    upload_resp = await api_client.post(
        "/api/v1/files/",
        files={"upload_file": ("lookup.txt", b"file-content", "text/plain")},
        headers={"X-API-Key": key},
    )
    assert upload_resp.status_code in (200, 201), upload_resp.text
    file_id = upload_resp.json()["id"]

    get_resp = await api_client.get(
        f"/api/v1/files/{file_id}/",
        headers={"X-API-Key": key},
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == file_id


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["assistant", "app"])
async def test_non_space_scoped_keys_get_files_allowed(api_client, bearer_token, scope_type):
    """Assistant/app scoped keys can GET /files/."""
    key = await _create_file_scoped_key(
        api_client,
        token=bearer_token,
        scope_type=scope_type,
        permission="read",
    )

    resp = await api_client.get(
        "/api/v1/files/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["assistant", "app"])
async def test_non_space_scoped_keys_post_files_allowed(api_client, bearer_token, scope_type):
    """Assistant/app scoped keys can POST /files/ (upload)."""
    key = await _create_file_scoped_key(
        api_client,
        token=bearer_token,
        scope_type=scope_type,
        permission="write",
    )

    resp = await api_client.post(
        "/api/v1/files/",
        files={"upload_file": (f"{scope_type}-upload.txt", b"hello", "text/plain")},
        headers={"X-API-Key": key},
    )
    assert resp.status_code in (200, 201), resp.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["assistant", "app"])
async def test_non_space_scoped_keys_get_file_by_id_allowed(api_client, bearer_token, scope_type):
    """Assistant/app scoped keys can GET /files/{id}/ for owned files."""
    key = await _create_file_scoped_key(
        api_client,
        token=bearer_token,
        scope_type=scope_type,
        permission="write",
    )

    upload_resp = await api_client.post(
        "/api/v1/files/",
        files={"upload_file": (f"{scope_type}-lookup.txt", b"file-content", "text/plain")},
        headers={"X-API-Key": key},
    )
    assert upload_resp.status_code in (200, 201), upload_resp.text
    file_id = upload_resp.json()["id"]

    get_resp = await api_client.get(
        f"/api/v1/files/{file_id}/",
        headers={"X-API-Key": key},
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == file_id


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["assistant", "app"])
async def test_non_space_scoped_keys_delete_files_denied_403(api_client, bearer_token, scope_type):
    """Assistant/app scoped keys remain blocked on DELETE /files/{id}/."""
    key = await _create_file_scoped_key(
        api_client,
        token=bearer_token,
        scope_type=scope_type,
        permission="admin",
    )

    resp = await api_client.delete(
        f"/api/v1/files/{uuid4()}/",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403, resp.text
    assert _error_code_from_response(resp) == "insufficient_scope", resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_admin_key_delete_files_not_blocked_by_scope(api_client, bearer_token):
    """Tenant-scoped ADMIN key DELETE /files/{id} → not blocked by scope check.

    Should get 404 (file doesn't exist) rather than 403 (scope denied).
    Verifies the deferred enforcement allows tenant keys through.
    """
    key = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="tenant",
        permission="admin",
    )

    resp = await api_client.delete(
        f"/api/v1/files/{uuid4()}/",
        headers={"X-API-Key": key},
    )
    # Should NOT be 403 — tenant keys pass the scope check.
    # Non-existent file should return 404 from FileService.delete_file.
    assert resp.status_code != 403, f"Tenant admin key should not be scope-blocked: {resp.text}"
    assert resp.status_code == 404, f"Expected 404 for non-existent file, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Kill-switch OFF behavior (env OFF or tenant flag OFF)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("kill_switch_mode", ["env_off", "tenant_flag_off"])
async def test_kill_switch_off_disables_scope_list_filtering(
    api_client, bearer_token, db_container, default_user, kill_switch_mode
):
    """When scope enforcement is off, scoped keys should see cross-space list results."""
    space_a = await _create_space(api_client, token=bearer_token, name=f"ks-{kill_switch_mode}-A")
    space_b = await _create_space(api_client, token=bearer_token, name=f"ks-{kill_switch_mode}-B")

    asst_a = await _create_assistant(api_client, token=bearer_token, space_id=space_a)
    asst_b = await _create_assistant(api_client, token=bearer_token, space_id=space_b)
    group_a = await _create_group(api_client, token=bearer_token, space_id=space_a)
    group_b = await _create_group(api_client, token=bearer_token, space_id=space_b)
    blob_a = await _seed_info_blob(
        db_container,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        group_id=group_a,
        text=f"kill-switch-{kill_switch_mode}-blob-a",
    )
    blob_b = await _seed_info_blob(
        db_container,
        user_id=default_user.id,
        tenant_id=default_user.tenant_id,
        group_id=group_b,
        text=f"kill-switch-{kill_switch_mode}-blob-b",
    )

    key_a = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_a,
        permission="read",
    )

    with _scope_enforcement_kill_switch(kill_switch_mode):
        resp_assistants = await api_client.get(
            "/api/v1/assistants/",
            headers={"X-API-Key": key_a},
        )
        assert resp_assistants.status_code == 200, resp_assistants.text
        assistant_ids = {item["id"] for item in resp_assistants.json()["items"]}
        assert asst_a in assistant_ids
        assert asst_b in assistant_ids

        resp_spaces = await api_client.get(
            "/api/v1/spaces/",
            headers={"X-API-Key": key_a},
        )
        assert resp_spaces.status_code == 200, resp_spaces.text
        space_ids = {item["id"] for item in resp_spaces.json()["items"]}
        assert space_a in space_ids
        assert space_b in space_ids

        resp_dashboard = await api_client.get(
            "/api/v1/dashboard/",
            headers={"X-API-Key": key_a},
        )
        assert resp_dashboard.status_code == 200, resp_dashboard.text
        dashboard_space_ids = {item["id"] for item in resp_dashboard.json()["spaces"]["items"]}
        assert space_a in dashboard_space_ids
        assert space_b in dashboard_space_ids

        resp_blobs = await api_client.get(
            "/api/v1/info-blobs/",
            headers={"X-API-Key": key_a},
        )
        assert resp_blobs.status_code == 200, resp_blobs.text
        blob_ids = {item["id"] for item in resp_blobs.json()["items"]}
        assert blob_a in blob_ids
        assert blob_b in blob_ids

        resp_groups = await api_client.get(
            "/api/v1/groups/",
            headers={"X-API-Key": key_a},
        )
        assert resp_groups.status_code == 200, resp_groups.text
        group_ids = {item["id"] for item in resp_groups.json()["items"]}
        assert group_a in group_ids
        assert group_b in group_ids


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("kill_switch_mode", ["env_off", "tenant_flag_off"])
async def test_kill_switch_off_allows_cross_space_assistant_create(
    api_client, bearer_token, kill_switch_mode
):
    """When scope enforcement is off, foreign-space create should not be scope-blocked."""
    space_a = await _create_space(api_client, token=bearer_token)
    space_b = await _create_space(api_client, token=bearer_token)

    key_a = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space_a,
        permission="write",
    )

    with _scope_enforcement_kill_switch(kill_switch_mode):
        resp = await api_client.post(
            "/api/v1/assistants/",
            json={"name": f"ks-{kill_switch_mode}-cross-space", "space_id": space_b},
            headers={"X-API-Key": key_a},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["space_id"] == space_b


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("kill_switch_mode", ["env_off", "tenant_flag_off"])
async def test_kill_switch_off_delete_file_not_scope_blocked(
    api_client, bearer_token, kill_switch_mode
):
    """When scope enforcement is off, DELETE /files/{id} should pass scope guard."""
    space = await _create_space(api_client, token=bearer_token)
    key = await _create_api_key(
        api_client,
        token=bearer_token,
        scope_type="space",
        scope_id=space,
        permission="admin",
    )

    with _scope_enforcement_kill_switch(kill_switch_mode):
        resp = await api_client.delete(
            f"/api/v1/files/{uuid4()}/",
            headers={"X-API-Key": key},
        )
        assert resp.status_code != 403, resp.text
        assert _error_code_from_response(resp) != "insufficient_scope"

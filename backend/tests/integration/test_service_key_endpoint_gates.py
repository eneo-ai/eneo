"""Integration tests for service-key endpoint gating.

Covers the three guarantees of the service-key hardening:

1. Synthesized permissions: a TENANT+ADMIN service key can call admin
   listings (e.g. `?for_tenant=true`) — the route-level role gate now
   passes via the synthetic role attached in `_build_service_user`.
2. Lifecycle gate: api-key lifecycle mutations (PATCH/DELETE/revoke/
   rotate/extend/purge/suspend/reactivate + notification PUTs) are
   session-only — no API key, user or service, can call them.
3. User-identity gate: endpoints that semantically require a real human
   user reject service keys with `code=user_identity_required`.

User-owned bearer/keys are unaffected — covered by the assertions on
the bearer-token control case in each block.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_service_key(
    client,
    *,
    token: str,
    scope_type: str,
    scope_id: str | None = None,
    permission: str,
    expires_at: str | None = None,
) -> dict:
    body: dict = {
        "name": f"svc-key-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
        "ownership": "service",
    }
    if scope_id is not None:
        body["scope_id"] = scope_id
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def tenant_admin_service_secret(client, admin_token) -> str:
    """A TENANT+ADMIN service key — needs an expiry to satisfy the
    write/admin guardrail policy."""
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    payload = await _create_service_key(
        client,
        token=admin_token,
        scope_type="tenant",
        permission="admin",
        expires_at=expires,
    )
    return payload["secret"]


@pytest.fixture
async def tenant_read_service_secret(client, admin_token) -> str:
    """A TENANT+READ service key — no guardrails required."""
    payload = await _create_service_key(
        client,
        token=admin_token,
        scope_type="tenant",
        permission="read",
    )
    return payload["secret"]


@pytest.fixture
async def test_space_id(client, admin_token) -> str:
    """Real space the test can address. Needed because `forbid_org_space`
    on the `/spaces/{id}/applications/*` routes resolves the space before
    our `require_user_for_creation` gate runs — a placeholder UUID would
    404 there before the gate ever fires."""
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"gate-test-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# 1. Synthesized permissions — admin listings now work for service keys
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_admin_service_key_can_list_assistants_for_tenant(
    client, tenant_admin_service_secret
):
    """`?for_tenant=true` is gated by validate_permissions(ADMIN). With the
    synthetic role, a TENANT+ADMIN service key now passes the gate."""
    resp = await client.get(
        "/api/v1/assistants/?for_tenant=true",
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_read_service_key_cannot_list_assistants_for_tenant(
    client, tenant_read_service_secret
):
    """READ-permission service keys still fail the ADMIN role gate — the
    synthesized role only adds ADMIN for TENANT+ADMIN keys."""
    resp = await client.get(
        "/api/v1/assistants/?for_tenant=true",
        headers={"X-API-Key": tenant_read_service_secret},
    )
    assert resp.status_code in (401, 403), resp.text


# ---------------------------------------------------------------------------
# 2. Lifecycle gate — api-key mutations are session-only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("PATCH", "/api/v1/api-keys/{id}"),
        ("DELETE", "/api/v1/api-keys/{id}"),
        ("POST", "/api/v1/api-keys/{id}/revoke"),
        ("POST", "/api/v1/api-keys/{id}/rotate"),
        ("POST", "/api/v1/api-keys/{id}/extend"),
        ("POST", "/api/v1/api-keys/{id}/purge"),
        ("POST", "/api/v1/api-keys/{id}/suspend"),
        ("POST", "/api/v1/api-keys/{id}/reactivate"),
        ("PUT", "/api/v1/api-keys/notification-preferences"),
    ],
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_lifecycle_mutations_reject_service_keys(
    client, tenant_admin_service_secret, admin_token, method, path
):
    """No API key — including a TENANT+ADMIN service key — can call api-key
    lifecycle mutations. The SESSION policy rejects them all with 403."""
    # Mint a target key so the path resolves to something real for endpoints
    # that take {id}.
    payload = await _create_service_key(
        client,
        token=admin_token,
        scope_type="tenant",
        permission="read",
    )
    target_id = payload["api_key"]["id"]
    full_path = path.format(id=target_id)

    body: dict = {}
    if "extend" in path:
        body = {
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        }
    elif "notification-preferences" in path:
        body = {"enabled": True, "days_before_expiry": [7]}
    elif method == "PATCH":
        body = {"name": "renamed"}

    resp = await client.request(
        method,
        full_path,
        json=body,
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 403, resp.text
    assert "session token" in resp.text.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logging_details_rejects_service_key(
    client,
    tenant_read_service_secret,
):
    response = await client.get(
        f"/api/v1/logging/{uuid4()}/",
        headers={"X-API-Key": tenant_read_service_secret},
    )

    assert response.status_code == 403, response.text
    assert response.json().get("code") == "session_auth_required"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_turn_diagnostics_reject_service_keys(
    client, tenant_admin_service_secret
):
    resp = await client.get(
        f"/api/v1/conversations/{uuid4()}/messages/{uuid4()}/diagnostics/",
        headers={"X-API-Key": tenant_admin_service_secret},
    )

    assert resp.status_code == 403, resp.text
    assert "session token" in resp.text.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_turn_diagnostics_reject_user_owned_api_keys(client, admin_token):
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"debug-gate-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "ownership": "user",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201, response.text

    resp = await client.get(
        f"/api/v1/conversations/{uuid4()}/messages/{uuid4()}/diagnostics/",
        headers={"X-API-Key": response.json()["secret"]},
    )

    assert resp.status_code == 403, resp.text
    assert "session token" in resp.text.lower()


# ---------------------------------------------------------------------------
# 3. User-identity gate — (b)-class endpoints reject service keys
# ---------------------------------------------------------------------------


def _has_user_identity_required_code(payload: dict) -> bool:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("code") == "user_identity_required"
    if isinstance(detail, str):
        return "user_identity_required" in detail
    # Top-level shape used by some error wrappers
    return payload.get("code") == "user_identity_required"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_users_me_rejects_service_key(client, tenant_admin_service_secret):
    resp = await client.get(
        "/api/v1/users/me/",
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 403, resp.text
    assert _has_user_identity_required_code(resp.json()), resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_users_me_works_for_bearer_user(client, admin_token):
    """Sanity check — the user-identity gate must NOT regress bearer auth."""
    resp = await client.get(
        "/api/v1/users/me/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# 4. Creation gate — service keys cannot create new user-owned resources
# ---------------------------------------------------------------------------


def _has_creation_gate_code(payload: dict) -> bool:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("code") == "service_key_cannot_create_resources"
    if isinstance(detail, str):
        return "service_key_cannot_create_resources" in detail
    return payload.get("code") == "service_key_cannot_create_resources"


# (method, path_template, json_body) — `{space_id}` in path_template is
# replaced with a real space id from the fixture. The `/spaces/{id}/applications/*`
# routes carry `Depends(forbid_org_space)` which resolves the space before
# our creation gate runs, so a placeholder id would 404 there. Top-level
# routes without a path resolver use a stub UUID directly.
_STUB_ID = "00000000-0000-0000-0000-000000000001"
_CREATION_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("POST", "/api/v1/spaces/", {"name": "x"}),
    # A service outside a space has only its creator to tie it to an
    # organisation, and a service key has no person to be that creator.
    ("POST", "/api/v1/services/", {"name": "x"}),
    # An icon records its uploader, which a service key does not have.
    ("POST", "/api/v1/icons/", None),
    ("POST", "/api/v1/roles/", {"name": "x", "permissions": []}),
    ("POST", "/api/v1/mcp-servers/", {"name": "x", "url": "https://example.com"}),
    ("POST", "/api/v1/mcp-servers/bundled/compute/", {}),
    ("POST", "/api/v1/document-templates/", {"name": "x"}),
    (
        "POST",
        "/api/v1/help-assistants/runs/",
        {
            "kind": "prompt_guide",
            "target_type": "assistant",
            "target_id": _STUB_ID,
            "question": "x",
        },
    ),
    (
        "POST",
        f"/api/v1/help-assistants/runs/{_STUB_ID}/turns/",
        {"question": "x"},
    ),
    (
        "POST",
        f"/api/v1/conversations/{_STUB_ID}/documents/{_STUB_ID}/versions/",
        {"content": "# x\n"},
    ),
]


@pytest.mark.parametrize("method,path_template,body", _CREATION_ENDPOINTS)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_creation_endpoints_return_403_with_gate_code(
    client, tenant_admin_service_secret, test_space_id, method, path_template, body
):
    """Every gated create endpoint returns 403 with the creation-gate code
    when called by a service key, regardless of body validity."""
    path = path_template.format(space_id=test_space_id)
    resp = await client.request(
        method,
        path,
        json=body,
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 403, f"{method} {path}: {resp.status_code} {resp.text}"
    assert _has_creation_gate_code(resp.json()), f"{method} {path}: {resp.text}"


async def test_a_file_a_service_key_uploads_is_owned_by_its_principal(
    client,
    db_container,
    tenant_admin_service_secret,
) -> None:
    response = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("source.txt", b"payload", "text/plain")},
        headers={"X-API-Key": tenant_admin_service_secret},
    )

    assert response.status_code in (200, 201), response.text
    async with db_container() as container:
        result = await container.session().execute(
            sa.text(
                "SELECT f.owner_type, f.owner_user_id, f.owner_service_id,"
                " p.display_name, p.state"
                " FROM files f"
                " LEFT JOIN service_principals p ON p.id = f.owner_service_id"
                " WHERE f.id = :id"
            ),
            {"id": response.json()["id"]},
        )
        file = result.mappings().one()
    assert file["owner_type"] == "service_key"
    assert file["owner_user_id"] is None
    assert file["owner_service_id"] is not None
    assert file["state"] == "active"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bearer_user_can_create_space(client, admin_token):
    """Sanity check — the creation gate must NOT regress bearer auth."""
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"control-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# What a service key may create: assistants, apps and services in a space
# ---------------------------------------------------------------------------


async def _creator(db_container, table: str, row_id: str):
    """Who made the row, and whether the service principal is the key's own."""
    async with db_container() as container:
        result = await container.session().execute(
            sa.text(
                f"SELECT r.user_id, r.created_by_service_id, p.state"
                f" FROM {table} r"
                f" LEFT JOIN service_principals p ON p.id = r.created_by_service_id"
                f" WHERE r.id = :id"
            ),
            {"id": row_id},
        )
        return result.mappings().one()


def _made_by_a_service(creator) -> bool:
    return (
        creator["user_id"] is None
        and creator["created_by_service_id"] is not None
        and creator["state"] == "active"
    )


async def test_service_key_creates_an_assistant_in_a_space(
    client, db_container, admin_token, tenant_admin_service_secret, test_space_id
):
    key = {"X-API-Key": tenant_admin_service_secret}

    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/applications/assistants/",
        json={"name": "Invoice assistant"},
        headers=key,
    )
    assert created.status_code in (200, 201), created.text
    assistant_id = created.json()["id"]

    assert _made_by_a_service(await _creator(db_container, "assistants", assistant_id))
    # The key reads what it made, and so does a person in the space.
    by_key = await client.get(f"/api/v1/assistants/{assistant_id}/", headers=key)
    assert by_key.status_code == 200, by_key.text
    by_person = await client.get(
        f"/api/v1/spaces/{test_space_id}/applications/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert by_person.status_code == 200, by_person.text
    listed = {item["id"]: item for item in by_person.json()["assistants"]["items"]}
    assert listed[assistant_id]["user_id"] is None


async def test_service_key_creates_an_assistant_through_the_assistants_route(
    client, db_container, tenant_admin_service_secret, test_space_id
):
    created = await client.post(
        "/api/v1/assistants/",
        json={"name": "Invoice assistant", "space_id": test_space_id},
        headers={"X-API-Key": tenant_admin_service_secret},
    )

    assert created.status_code in (200, 201), created.text
    assert _made_by_a_service(
        await _creator(db_container, "assistants", created.json()["id"])
    )


async def test_service_key_writes_the_prompt_of_an_assistant(
    client, db_container, tenant_admin_service_secret, test_space_id
):
    key = {"X-API-Key": tenant_admin_service_secret}
    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/applications/assistants/",
        json={"name": "Invoice assistant"},
        headers=key,
    )
    assert created.status_code in (200, 201), created.text
    assistant_id = created.json()["id"]

    updated = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"prompt": {"text": "Read the invoice and list the amounts."}},
        headers=key,
    )

    assert updated.status_code == 200, updated.text
    prompt = updated.json()["prompt"]
    assert prompt["text"] == "Read the invoice and list the amounts."
    assert _made_by_a_service(await _creator(db_container, "prompts", prompt["id"]))


async def test_service_key_writes_the_prompt_of_an_assistant_a_person_made(
    client, db_container, admin_token, tenant_admin_service_secret, test_space_id
):
    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/applications/assistants/",
        json={"name": "A person's assistant"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code in (200, 201), created.text
    assistant_id = created.json()["id"]
    person = await _creator(db_container, "assistants", assistant_id)
    assert person["user_id"] is not None
    assert person["created_by_service_id"] is None

    updated = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"prompt": {"text": "Answer in one sentence."}},
        headers={"X-API-Key": tenant_admin_service_secret},
    )

    assert updated.status_code == 200, updated.text
    assert _made_by_a_service(
        await _creator(db_container, "prompts", updated.json()["prompt"]["id"])
    )


async def test_service_key_creates_an_app_in_a_space(
    client, db_container, tenant_admin_service_secret, test_space_id
):
    key = {"X-API-Key": tenant_admin_service_secret}

    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/applications/apps/",
        json={"name": "Invoice app"},
        headers=key,
    )
    if created.status_code == 400 and "transcription model" in created.text:
        pytest.skip("This environment has no transcription model for apps")
    assert created.status_code in (200, 201), created.text
    app_id = created.json()["id"]

    assert _made_by_a_service(await _creator(db_container, "apps", app_id))
    read = await client.get(f"/api/v1/apps/{app_id}/", headers=key)
    assert read.status_code == 200, read.text


async def test_service_key_creates_a_service_in_a_space(
    client, db_container, admin_token, tenant_admin_service_secret, test_space_id
):
    key = {"X-API-Key": tenant_admin_service_secret}

    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/applications/services/",
        json={"name": "Invoice service"},
        headers=key,
    )
    assert created.status_code in (200, 201), created.text
    service_id = created.json()["id"]

    assert _made_by_a_service(await _creator(db_container, "services", service_id))
    # A service without a person as creator still shows up in its space.
    by_person = await client.get(
        f"/api/v1/spaces/{test_space_id}/applications/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert by_person.status_code == 200, by_person.text
    assert service_id in {item["id"] for item in by_person.json()["services"]["items"]}


async def test_service_key_creates_a_collection_in_a_space(
    client, db_container, admin_token, tenant_admin_service_secret, test_space_id
):
    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/knowledge/groups/",
        json={"name": "Handbook"},
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert created.status_code in (200, 201), created.text
    collection_id = created.json()["id"]

    assert _made_by_a_service(await _creator(db_container, "groups", collection_id))
    # A collection without a person as creator still shows up in its space.
    by_person = await client.get(
        f"/api/v1/spaces/{test_space_id}/knowledge/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert by_person.status_code == 200, by_person.text
    assert collection_id in {item["id"] for item in by_person.json()["groups"]["items"]}


async def test_service_key_creates_a_website_in_a_space_and_its_crawl_is_its_own(
    client,
    db_container,
    tenant_admin_service_secret,
    test_space_id,
    monkeypatch,
):
    from eneo.websites.domain import crawl_service

    monkeypatch.setattr(crawl_service, "reconcile_crawl_work", AsyncMock())

    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/knowledge/websites/",
        json={"name": "Intranet", "url": "https://example.com"},
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert created.status_code in (200, 201), created.text
    website_id = created.json()["id"]

    assert _made_by_a_service(await _creator(db_container, "websites", website_id))
    async with db_container() as container:
        job = (
            await container.session().execute(
                sa.text(
                    "SELECT j.user_id, j.service_principal_id FROM jobs j"
                    " JOIN crawl_attempts a ON a.dispatch_id = j.id"
                    " JOIN crawl_runs r ON r.id = a.crawl_run_id"
                    " WHERE r.website_id = :website_id"
                ),
                {"website_id": website_id},
            )
        ).one()
    assert job.user_id is None
    assert job.service_principal_id is not None


async def test_an_assistant_key_reaches_an_assistant_a_service_key_made(
    client, admin_token, tenant_admin_service_secret, test_space_id
):
    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/applications/assistants/",
        json={"name": "Invoice assistant"},
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert created.status_code in (200, 201), created.text
    assistant_id = created.json()["id"]
    scoped = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"assistant-key-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "assistant",
            "scope_id": assistant_id,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert scoped.status_code == 201, scoped.text

    read = await client.get(
        f"/api/v1/assistants/{assistant_id}/",
        headers={"X-API-Key": scoped.json()["secret"]},
    )

    assert read.status_code == 200, read.text


async def test_an_assistant_a_service_key_made_counts_for_its_organisation(
    client, admin_token, tenant_admin_service_secret, test_space_id
):
    created = await client.post(
        f"/api/v1/spaces/{test_space_id}/applications/assistants/",
        json={"name": "Invoice assistant"},
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert created.status_code in (200, 201), created.text

    listed = await client.get(
        "/api/v1/assistants/?for_tenant=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert listed.status_code == 200, listed.text
    assert created.json()["id"] in {item["id"] for item in listed.json()["items"]}

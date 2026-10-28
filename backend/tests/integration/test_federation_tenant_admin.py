"""Tenant admins edit their organisation's IdP settings at /api/v1/admin/federation.

The operator registers the IdP (super API key); an org admin in an interactive
session edits the label, client ID, secret and allowed domains of their own
tenant only. Every change is audited and atomic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.authentication.auth_service import AuthService
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.tenant_table import Tenants
from eneo.main.config import get_settings, set_settings
from eneo.tenants import tenant_federation_service

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

URL = "/api/v1/admin/federation"
SECRET = "operator-entered-Zq7x"
NEW_SECRET = "tenant-admin-new-K9w2"


def _idp(slug: str) -> dict[str, str]:
    base = f"https://idp.{slug}.local"
    return {
        "discovery_endpoint": f"{base}/.well-known/openid-configuration",
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "jwks_uri": f"{base}/jwks",
    }


def _discovery(*idps: dict[str, str]) -> dict[str, dict[str, str]]:
    keys = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
    return {idp["discovery_endpoint"]: {k: idp[k] for k in keys} for idp in idps}


async def _register(
    client: AsyncClient, key: str, tenant_id: UUID | str, idp: dict[str, str], **extra
) -> None:
    body = {
        "provider": "entra",
        "client_id": "operator-client",
        "client_secret": SECRET,
        "discovery_endpoint": idp["discovery_endpoint"],
        "canonical_public_origin": "https://org.eneo.test",
        "allowed_domains": ["example.com"],
        **extra,
    }
    response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant_id}/federation",
        json=body,
        headers={"X-API-Key": key},
    )
    assert response.status_code == 200, response.text


async def _stored(tenant_id: UUID | str) -> dict[str, Any]:
    async with sessionmanager.session() as session, session.begin():
        config = await session.scalar(
            sa.select(Tenants.federation_config).where(Tenants.id == tenant_id)
        )
        return dict(config or {})


async def _store(tenant_id: UUID | str, config: dict[str, Any]) -> None:
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(federation_config=config)
        )


async def _audit_rows(tenant_id: UUID | str) -> list[dict[str, Any]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.scalars(
            sa.select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.action == "federation_updated")
            .order_by(AuditLog.timestamp)
        )
        return [
            {
                "actor_id": row.actor_id,
                "actor_type": row.actor_type,
                "entity_type": row.entity_type,
                "metadata": row.log_metadata,
            }
            for row in rows
        ]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def configured(
    client: AsyncClient, super_admin_token: str, oidc_mock, test_tenant
) -> dict[str, str]:
    idp = _idp("org")
    oidc_mock(discovery=_discovery(idp))
    await _register(client, super_admin_token, test_tenant.id, idp)
    return idp


async def _view(client: AsyncClient, token: str) -> dict[str, Any]:
    response = await client.get(URL, headers=_bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_admin_view_shows_the_settings_and_never_the_secret(
    client: AsyncClient, admin_token: str, configured: dict[str, str], test_tenant
):
    view = await _view(client, admin_token)

    stored = await _stored(test_tenant.id)
    assert view["configured"] is True
    assert view["provider"] == "entra"
    assert view["discovery_endpoint"] == configured["discovery_endpoint"]
    assert view["issuer"] == configured["issuer"]
    assert view["client_id"] == "operator-client"
    assert view["client_secret_set"] is True
    assert view["client_secret_updated_at"] is not None
    assert view["encryption_status"] == "encrypted"
    assert view["allowed_domains"] == ["example.com"]
    assert view["redirect_uris"] == ["https://org.eneo.test/login/callback"]
    assert view["scopes"] == ["openid", "email", "profile"]
    assert view["revision"]
    text = json.dumps(view)
    for leaked in (SECRET, SECRET[-4:], stored["client_secret"]):
        assert leaked not in text


async def test_not_configured_reads_as_such_and_cannot_be_patched(
    client: AsyncClient, admin_token: str
):
    view = await _view(client, admin_token)
    assert view["configured"] is False
    assert view["revision"] is None

    response = await client.patch(
        URL, json={"revision": "x", "client_id": "y"}, headers=_bearer(admin_token)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "federation_not_configured"


async def test_access_matrix(
    client: AsyncClient,
    admin_token: str,
    tenant_user_token: str,
    admin_user_api_key,
    super_admin_token: str,
    configured: dict[str, str],
    test_tenant,
):
    before = await _stored(test_tenant.id)
    revision = (await _view(client, admin_token))["revision"]
    body = {"revision": revision, "client_id": "hijacked"}
    refused = {
        "anonymous": ({}, 401),
        "member": (_bearer(tenant_user_token), 403),
        "admin API key": ({"X-API-Key": admin_user_api_key.key}, 403),
        "super key": ({"X-API-Key": super_admin_token}, 401),
    }

    for name, (headers, status) in refused.items():
        get = await client.get(URL, headers=headers)
        patch = await client.patch(URL, json=body, headers=headers)
        assert (get.status_code, patch.status_code) == (status, status), name

    key = await client.patch(
        URL, json=body, headers={"X-API-Key": admin_user_api_key.key}
    )
    assert key.json()["code"] == "session_auth_required"
    assert await _stored(test_tenant.id) == before
    assert len(await _audit_rows(test_tenant.id)) == 1  # the operator's PUT


async def test_two_tenants_stay_isolated(
    client: AsyncClient,
    admin_token: str,
    super_admin_token: str,
    oidc_mock,
    test_tenant,
    mock_transcription_models,
):
    org, other = _idp("org"), _idp("other")
    oidc_mock(discovery=_discovery(org, other))
    response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={"name": "other-org", "display_name": "other-org", "state": "active"},
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text
    other_id = response.json()["id"]
    await _register(client, super_admin_token, test_tenant.id, org)
    await _register(
        client,
        super_admin_token,
        other_id,
        other,
        client_id="other-tenant-client",
        allowed_domains=["other.se"],
    )
    other_before = await _stored(other_id)

    view = await _view(client, admin_token)
    assert "other-tenant-client" not in json.dumps(view)
    assert view["issuer"] == org["issuer"]

    smuggled = await client.patch(
        URL,
        json={"revision": view["revision"], "tenant_id": other_id, "client_id": "x"},
        headers=_bearer(admin_token),
    )
    assert smuggled.status_code == 422
    ok = await client.patch(
        URL,
        json={"revision": view["revision"], "client_id": "org-client"},
        headers=_bearer(admin_token),
    )
    assert ok.status_code == 200, ok.text

    assert await _stored(other_id) == other_before
    assert len(await _audit_rows(other_id)) == 1  # only the operator's PUT
    assert (await _stored(test_tenant.id))["client_id"] == "org-client"


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "discovery_endpoint",
            "https://attacker.example/.well-known/openid-configuration",
        ),
        ("token_endpoint", "https://attacker.example/token"),
        ("issuer", "https://attacker.example"),
        ("canonical_public_origin", "https://attacker.example"),
        ("redirect_path", "/elsewhere"),
        ("additional_redirect_uris", ["https://attacker.example/cb"]),
        ("email_claim", "preferred_username"),
        ("claims_mapping", {"email": "preferred_username"}),
        ("scopes", ["openid"]),
        ("token_endpoint_auth_method", "none"),
    ],
)
async def test_operator_owned_fields_are_refused_with_nothing_changed(
    client: AsyncClient,
    admin_token: str,
    configured: dict[str, str],
    test_tenant,
    field: str,
    value: object,
):
    before = await _stored(test_tenant.id)
    revision = (await _view(client, admin_token))["revision"]

    response = await client.patch(
        URL,
        json={"revision": revision, "client_id": "changed", field: value},
        headers=_bearer(admin_token),
    )

    assert response.status_code == 422
    assert await _stored(test_tenant.id) == before


async def test_an_edit_keeps_every_other_stored_setting(
    client: AsyncClient, admin_token: str, configured: dict[str, str], test_tenant
):
    nondefault = {
        **await _stored(test_tenant.id),
        "scopes": ["openid", "email", "groups"],
        "claims_mapping": {"email": "upn", "username": "oid", "name": "name"},
        "token_endpoint_auth_method": "client_secret_basic",
        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        "redirect_path": "/auth/callback",
        "additional_redirect_uris": ["https://alt.eneo.test/auth/callback"],
        "userinfo_endpoint": "https://idp.org.local/userinfo",
    }
    await _store(test_tenant.id, nondefault)
    view = await _view(client, admin_token)
    assert view["scopes"] == ["openid", "email", "groups"]
    assert view["token_endpoint_auth_method"] == "client_secret_basic"
    assert view["redirect_uris"] == [
        "https://org.eneo.test/auth/callback",
        "https://alt.eneo.test/auth/callback",
    ]

    response = await client.patch(
        URL,
        json={"revision": view["revision"], "provider": "Org Entra"},
        headers=_bearer(admin_token),
    )

    assert response.status_code == 200, response.text
    assert await _stored(test_tenant.id) == {**nondefault, "provider": "Org Entra"}
    assert response.json()["provider"] == "Org Entra"
    assert response.json()["revision"] != view["revision"]


async def test_a_save_on_a_stale_revision_conflicts(
    client: AsyncClient, admin_token: str, configured: dict[str, str], test_tenant
):
    revision = (await _view(client, admin_token))["revision"]
    first = await client.patch(
        URL,
        json={"revision": revision, "client_id": "first"},
        headers=_bearer(admin_token),
    )
    assert first.status_code == 200, first.text

    stale = await client.patch(
        URL,
        json={"revision": revision, "client_id": "second"},
        headers=_bearer(admin_token),
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "federation_config_revision_conflict"
    assert (await _stored(test_tenant.id))["client_id"] == "first"


async def test_two_concurrent_saves_the_second_gets_409(
    client: AsyncClient, admin_token: str, configured: dict[str, str], test_tenant
):
    revision = (await _view(client, admin_token))["revision"]

    responses = await asyncio.gather(
        *(
            client.patch(
                URL,
                json={"revision": revision, "client_id": f"concurrent-{i}"},
                headers=_bearer(admin_token),
            )
            for i in range(2)
        )
    )

    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()
    assert (await _stored(test_tenant.id))["client_id"] == winner["client_id"]
    assert len(await _audit_rows(test_tenant.id)) == 2  # operator PUT + winner


async def test_a_masked_looking_secret_is_refused(
    client: AsyncClient, admin_token: str, configured: dict[str, str], test_tenant
):
    before = await _stored(test_tenant.id)
    revision = (await _view(client, admin_token))["revision"]

    response = await client.patch(
        URL,
        json={"revision": revision, "client_secret": "********"},
        headers=_bearer(admin_token),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "federation_secret_looks_masked"
    assert await _stored(test_tenant.id) == before


async def test_changes_are_audited_even_with_auditing_switched_off(
    client: AsyncClient,
    admin_token: str,
    admin_user,
    configured: dict[str, str],
    test_tenant,
):
    headers = _bearer(admin_token)
    for path, body in (
        (
            "/api/v1/audit/config",
            {"updates": [{"category": "admin_actions", "enabled": False}]},
        ),
        (
            "/api/v1/audit/config/actions",
            {"updates": [{"action": "federation_updated", "enabled": False}]},
        ),
        ("/api/v1/settings/audit-logging", {"enabled": False}),
    ):
        switched_off = await client.patch(path, json=body, headers=headers)
        assert switched_off.status_code == 200, (path, switched_off.text)
    actions = await client.get("/api/v1/audit/config/actions", headers=headers)
    federation = next(
        a for a in actions.json()["actions"] if a["action"] == "federation_updated"
    )
    assert federation["enabled"] is True

    revision = (await _view(client, admin_token))["revision"]
    response = await client.patch(
        URL,
        json={
            "revision": revision,
            "client_id": "next-client",
            "allowed_domains": ["example.com", "example.se"],
            "client_secret": NEW_SECRET,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    rows = await _audit_rows(test_tenant.id)
    assert len(rows) == 2
    row = rows[-1]
    assert row["actor_id"] == admin_user.id
    assert row["actor_type"] == "user"
    assert row["entity_type"] == "federation_config"
    metadata = row["metadata"]
    assert metadata["via"] == "admin"
    assert metadata["changes"] == {
        "client_id": {"old": "operator-client", "new": "next-client"},
        "allowed_domains": {
            "old": ["example.com"],
            "new": ["example.com", "example.se"],
        },
        "client_secret": {"replaced": True},
    }
    stored = await _stored(test_tenant.id)
    text = json.dumps(metadata) + json.dumps(response.json())
    for leaked in (SECRET, NEW_SECRET, NEW_SECRET[-4:], stored["client_secret"]):
        assert leaked not in text

    operator_row = rows[0]["metadata"]
    assert rows[0]["actor_id"] is None
    assert operator_row["via"] == "super_api_key"
    assert operator_row["changes"]["client_secret"] == {"replaced": True}


async def test_the_secret_never_reaches_the_logs(
    client: AsyncClient, admin_token: str, configured: dict[str, str]
):
    import logging

    class _Records(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.lines: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.lines.append(f"{record.getMessage()} {record.__dict__}")

    handler = _Records()
    tenant_federation_service.logger.addHandler(handler)
    try:
        revision = (await _view(client, admin_token))["revision"]
        response = await client.patch(
            URL,
            json={"revision": revision, "client_secret": NEW_SECRET},
            headers=_bearer(admin_token),
        )
    finally:
        tenant_federation_service.logger.removeHandler(handler)

    assert response.status_code == 200, response.text
    assert handler.lines
    assert not any(NEW_SECRET in line for line in handler.lines)


@pytest.fixture
async def raw_client(app) -> AsyncIterator[AsyncClient]:
    """A client that receives the 500 instead of the server's exception."""
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
    ) as client:
        yield client


async def test_a_failed_audit_write_keeps_the_old_settings(
    raw_client: AsyncClient,
    admin_token: str,
    configured: dict[str, str],
    test_tenant,
    monkeypatch,
):
    before = await _stored(test_tenant.id)
    revision = (await _view(raw_client, admin_token))["revision"]

    async def _fail(self, audit_log):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", _fail)
    response = await raw_client.patch(
        URL,
        json={"revision": revision, "client_id": "unaudited"},
        headers=_bearer(admin_token),
    )

    assert response.status_code == 500
    assert await _stored(test_tenant.id) == before


async def test_a_failed_commit_keeps_the_old_settings_and_no_audit_row(
    raw_client: AsyncClient,
    admin_token: str,
    configured: dict[str, str],
    test_tenant,
    monkeypatch,
):
    before = await _stored(test_tenant.id)
    revision = (await _view(raw_client, admin_token))["revision"]
    original = AuditLogRepositoryImpl.create

    async def _mark(self, audit_log):
        created = await original(self, audit_log)
        self.session.sync_session.info["fail_commit"] = True
        return created

    def _before_commit(session: Session) -> None:
        if session.info.pop("fail_commit", False):
            raise RuntimeError("commit failed")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", _mark)
    event.listen(Session, "before_commit", _before_commit)
    try:
        response = await raw_client.patch(
            URL,
            json={"revision": revision, "client_id": "uncommitted"},
            headers=_bearer(admin_token),
        )
    finally:
        event.remove(Session, "before_commit", _before_commit)

    assert response.status_code == 500
    assert await _stored(test_tenant.id) == before
    assert len(await _audit_rows(test_tenant.id)) == 1


async def test_federation_disabled_hides_the_route(
    client: AsyncClient, admin_token: str
):
    original = get_settings()
    set_settings(original.model_copy(update={"federation_enabled": False}))
    try:
        get = await client.get(URL, headers=_bearer(admin_token))
        patch = await client.patch(
            URL, json={"revision": "r", "client_id": "x"}, headers=_bearer(admin_token)
        )
        runtime = await client.get("/api/v1/runtime-config")
    finally:
        set_settings(original)

    assert (get.status_code, patch.status_code) == (404, 404)
    assert get.json()["code"] == patch.json()["code"] == "federation_disabled"
    assert runtime.json()["federation_enabled"] is False
    assert (await client.get("/api/v1/runtime-config")).json()["federation_enabled"]


async def test_after_a_bad_admin_save_one_operator_patch_restores_sign_in(
    client: AsyncClient,
    admin_token: str,
    super_admin_token: str,
    oidc_mock,
    jwks_mock,
    db_container,
    test_tenant,
    monkeypatch,
):
    """Fake IdP: knows two clients; sign-in uses whatever the tenant stores."""
    idp = _idp("org")
    codes = [f"code-{i}" for i in range(5)]
    fake_idp = oidc_mock(
        discovery=_discovery(idp),
        tokens={
            (idp["token_endpoint"], code): {"id_token": "id", "access_token": "at"}
            for code in codes
        },
        clients={"operator-client": SECRET, "second-client": "second-secret"},
    )
    jwks_mock()
    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda self, **kwargs: {"email": "test@example.com", "email_verified": True},
    )
    await _register(client, super_admin_token, test_tenant.id, idp)
    async with db_container() as container:
        slug = await container.tenant_repo().generate_slug_for_tenant(test_tenant.id)

    async def sign_in(code: str) -> int:
        initiated = await client.get(f"/api/v1/auth/initiate?tenant={slug}")
        assert initiated.status_code == 200, initiated.text
        callback = await client.post(
            "/api/v1/auth/callback",
            json={"code": code, "state": initiated.json()["state"]},
        )
        return callback.status_code

    assert await sign_in(codes[0]) == 200

    # The admin points sign-in at another registered client and adds a domain:
    # the next sign-in uses both.
    view = await _view(client, admin_token)
    switched = await client.patch(
        URL,
        json={
            "revision": view["revision"],
            "client_id": "second-client",
            "client_secret": "second-secret",
            "allowed_domains": ["example.com", "example.se"],
        },
        headers=_bearer(admin_token),
    )
    assert switched.status_code == 200, switched.text
    assert await sign_in(codes[1]) == 200
    assert fake_idp()["token_clients"][-1] == "second-client"

    # A wrong client ID locks every SSO user out ...
    broken = await client.patch(
        URL,
        json={"revision": switched.json()["revision"], "client_id": "typo-client"},
        headers=_bearer(admin_token),
    )
    assert broken.status_code == 200, broken.text
    assert await sign_in(codes[2]) == 401

    # ... until one operator PATCH puts the registered client back.
    restored = await client.patch(
        f"/api/v1/sysadmin/tenants/{test_tenant.id}/federation",
        json={"client_id": "operator-client", "client_secret": SECRET},
        headers={"X-API-Key": super_admin_token},
    )
    assert restored.status_code == 200, restored.text
    assert await sign_in(codes[3]) == 200
    assert fake_idp()["token_clients"][-1] == "operator-client"

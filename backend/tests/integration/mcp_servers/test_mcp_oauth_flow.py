"""The OAuth connect flow end to end through the API, against an in-memory
vendor authorization server, with tokens landing encrypted in PostgreSQL."""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.mcp_oauth_table import MCPOAuthConnections
from eneo.database.tables.mcp_server_table import MCPServers
from tests.unit.mcp_servers.infrastructure.oauth.fake_authorization_server import (
    FakeAuthorizationServer,
)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
def vendor(monkeypatch) -> FakeAuthorizationServer:
    server = FakeAuthorizationServer(challenge_scope="mcp:read")
    server.install(monkeypatch)
    return server


@pytest.fixture
def public_origin(monkeypatch):
    from eneo.main import config as config_module

    settings = config_module.get_settings()
    monkeypatch.setattr(settings, "public_origin", "https://eneo.example")
    return "https://eneo.example"


async def _oauth_server(session, tenant_id, vendor, *, auth_scope="per_user") -> UUID:
    row = MCPServers(
        tenant_id=tenant_id,
        name=f"vendor-{uuid4().hex[:6]}",
        http_url=vendor.server_url,
        http_auth_type="oauth",
        auth_scope=auth_scope,
        is_enabled=True,
    )
    session.add(row)
    await session.flush()
    return row.id


async def test_connect_disconnect_round_trip(
    client, admin_token, admin_user, db_container, vendor, public_origin
):
    async with db_container() as container:
        server_id = await _oauth_server(
            container.session(), admin_user.tenant_id, vendor
        )
    headers = {"Authorization": f"Bearer {admin_token}"}

    before = await client.get("/api/v1/mcp-oauth/connections/", headers=headers)
    assert before.status_code == 200, before.text
    assert {c["mcp_server_id"]: c["status"] for c in before.json()["items"]}[
        str(server_id)
    ] == "not_connected"

    started = await client.post(
        f"/api/v1/mcp-oauth/servers/{server_id}/authorize-url/", headers=headers
    )
    assert started.status_code == 200, started.text
    code, state = vendor.authorize(started.json()["url"])

    done = await client.post(
        f"/api/v1/mcp-oauth/servers/{server_id}/callback/",
        json={"code": code, "state": state},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "connected"
    assert done.json()["scopes"] == ["mcp:read"]

    async with db_container() as container:
        session = container.session()
        row = (
            await session.scalars(
                sa.select(MCPOAuthConnections).where(
                    MCPOAuthConnections.mcp_server_id == server_id
                )
            )
        ).one()
        assert row.user_id == admin_user.id
        assert row.access_token_ciphertext is not None
        assert "access-1" not in row.access_token_ciphertext
        assert row.refresh_token_ciphertext is not None

    after = await client.get("/api/v1/mcp-oauth/connections/", headers=headers)
    assert {c["mcp_server_id"]: c["status"] for c in after.json()["items"]}[
        str(server_id)
    ] == "connected"

    gone = await client.delete(
        f"/api/v1/mcp-oauth/servers/{server_id}/connection/", headers=headers
    )
    assert gone.status_code == 204, gone.text
    assert vendor.revoked == ["refresh-1"]


async def test_replayed_state_is_refused(
    client, admin_token, admin_user, db_container, vendor, public_origin
):
    async with db_container() as container:
        server_id = await _oauth_server(
            container.session(), admin_user.tenant_id, vendor
        )
    headers = {"Authorization": f"Bearer {admin_token}"}
    started = await client.post(
        f"/api/v1/mcp-oauth/servers/{server_id}/authorize-url/", headers=headers
    )
    code, state = vendor.authorize(started.json()["url"])
    first = await client.post(
        f"/api/v1/mcp-oauth/servers/{server_id}/callback/",
        json={"code": code, "state": state},
        headers=headers,
    )
    assert first.status_code == 200

    replay = await client.post(
        f"/api/v1/mcp-oauth/servers/{server_id}/callback/",
        json={"code": code, "state": state},
        headers=headers,
    )
    assert replay.status_code == 400
    assert "expired" in replay.text


async def test_client_metadata_document_is_public(client, public_origin):
    response = await client.get("/api/v1/mcp-oauth/client.json")

    assert response.status_code == 200, response.text
    document = response.json()
    assert document["client_id"] == "https://eneo.example/api/v1/mcp-oauth/client.json"
    assert document["redirect_uris"] == ["https://eneo.example/mcp-oauth/callback"]
    assert document["token_endpoint_auth_method"] == "none"


async def test_shared_connection_is_one_row_for_the_server(
    client, admin_token, admin_user, db_container, vendor, public_origin
):
    async with db_container() as container:
        server_id = await _oauth_server(
            container.session(), admin_user.tenant_id, vendor, auth_scope="shared"
        )
    headers = {"Authorization": f"Bearer {admin_token}"}
    for _ in range(2):
        started = await client.post(
            f"/api/v1/mcp-oauth/servers/{server_id}/authorize-url/", headers=headers
        )
        code, state = vendor.authorize(started.json()["url"])
        done = await client.post(
            f"/api/v1/mcp-oauth/servers/{server_id}/callback/",
            json={"code": code, "state": state},
            headers=headers,
        )
        assert done.status_code == 200, done.text
        assert done.json()["auth_scope"] == "shared"

    async with db_container() as container:
        session = container.session()
        rows = (
            await session.scalars(
                sa.select(MCPOAuthConnections).where(
                    MCPOAuthConnections.mcp_server_id == server_id
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].user_id is None
        assert rows[0].connected_by_user_id == admin_user.id

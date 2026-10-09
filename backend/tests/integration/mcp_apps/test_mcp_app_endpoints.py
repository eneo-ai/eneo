"""The two-step sandbox delivery: an authenticated mint returns a signed URL on
the content origin (auditing the mint), and the content endpoint serves the
trusted proxy with the host-built CSP, authorized solely by the token. Only a
view approved for a tool gets a link, and it is served on the content host and
nowhere else."""

import hashlib
import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.authentication.signed_urls import generate_mcp_app_view_token
from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.main.config import get_settings
from eneo.mcp_apps.domain.csp import build_app_csp
from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
    McpAppViewRepo,
)
from eneo.mcp_apps.presentation import mcp_apps_router as router_module

VIEW_URI = "ui://weather/dashboard"
VIEW_HTML = "<html><body>weather</body></html>"
UI_META = {"csp": {"connectDomains": ["https://api.example.com"]}}


def _apps_settings(monkeypatch, **overrides):
    base = get_settings().model_copy(
        update={
            "mcp_apps_enabled": True,
            "mcp_app_content_base_url": "http://content.test",
            **overrides,
        }
    )
    monkeypatch.setattr(router_module, "get_settings", lambda: base)
    return base


CONTENT_HOST = {"host": "content.test"}


async def _seed_view(tenant_id, *, approved: bool = True) -> object:
    """A stored view; ``approved`` gives it a tool whose approved view it is."""
    content_hash = hashlib.sha256(VIEW_HTML.encode()).hexdigest()
    async with sessionmanager.session() as session:
        async with session.begin():
            server = MCPServers(
                tenant_id=tenant_id,
                name=f"apps-endpoint-{uuid4()}",
                http_url="http://localhost:9000/mcp",
                http_auth_type="none",
                is_enabled=True,
            )
            session.add(server)
            await session.flush()
            server_id = server.id
            session.add(
                MCPServerTools(
                    mcp_server_id=server_id,
                    name="get_weather",
                    description="Current weather",
                    meta={"ui": {"resourceUri": VIEW_URI}},
                    ui_resource_sha256=content_hash if approved else None,
                    pending_ui_resource_sha256=None if approved else content_hash,
                )
            )
        repo = McpAppViewRepo(session)
        return await repo.upsert(
            tenant_id=tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=content_hash,
            html=VIEW_HTML,
            ui_meta=UI_META,
        )


async def test_mint_and_content_round_trip(
    client, admin_user, admin_user_api_key, monkeypatch
):
    settings = _apps_settings(monkeypatch)
    view_id = await _seed_view(admin_user.tenant_id)

    with patch(
        "eneo.audit.application.audit_service.AuditService.log_async",
        new_callable=AsyncMock,
    ) as log_async:
        mint = await client.post(
            f"/api/v1/mcp-apps/views/{view_id}/token/",
            headers={"X-API-Key": admin_user_api_key.key},
        )

    assert mint.status_code == 200
    body = mint.json()
    assert body["url"].startswith(
        f"http://content.test/api/v1/mcp-apps/views/{view_id}/content?token="
    )
    assert body["expires_at"] > int(time.time())
    mint_audits = [
        call.kwargs
        for call in log_async.await_args_list
        if call.kwargs.get("action") is not None
        and call.kwargs["action"].value == "mcp_app_view_link_created"
    ]
    assert len(mint_audits) == 1
    assert mint_audits[0]["tenant_id"] == admin_user.tenant_id

    token = body["url"].split("token=")[1]
    content = await client.get(
        f"/api/v1/mcp-apps/views/{view_id}/content",
        params={"token": token},
        headers=CONTENT_HOST,
    )

    assert content.status_code == 200
    assert body["html"] == VIEW_HTML
    assert VIEW_HTML not in content.text
    assert "sandbox-proxy-ready" in content.text

    # The same route answers on Eneo's own address too; a view is never
    # handed out from there.
    on_app_host = await client.get(
        f"/api/v1/mcp-apps/views/{view_id}/content", params={"token": token}
    )
    assert on_app_host.status_code == 404
    assert content.headers["content-security-policy"] == build_app_csp(
        UI_META["csp"], frame_ancestors=settings.public_origin or None
    )
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["referrer-policy"] == "no-referrer"
    assert content.headers["cache-control"] == "no-store"


async def test_expired_token_is_refused(client, admin_user, monkeypatch):
    _apps_settings(monkeypatch)
    view_id = await _seed_view(admin_user.tenant_id)
    now = int(time.time())
    token = generate_mcp_app_view_token(
        view_id=view_id,
        tenant_id=admin_user.tenant_id,
        expires_at=now - 1,
        issued_at=now - 120,
    )

    response = await client.get(
        f"/api/v1/mcp-apps/views/{view_id}/content",
        params={"token": token},
        headers=CONTENT_HOST,
    )

    assert response.status_code == 404


async def test_token_for_other_view_is_refused(client, admin_user, monkeypatch):
    _apps_settings(monkeypatch)
    view_id = await _seed_view(admin_user.tenant_id)
    token = generate_mcp_app_view_token(
        view_id=uuid4(),
        tenant_id=admin_user.tenant_id,
        expires_at=int(time.time()) + 60,
    )

    response = await client.get(
        f"/api/v1/mcp-apps/views/{view_id}/content",
        params={"token": token},
        headers=CONTENT_HOST,
    )

    assert response.status_code == 404


async def test_mint_unknown_view_is_404(client, admin_user_api_key, monkeypatch):
    _apps_settings(monkeypatch)

    response = await client.post(
        f"/api/v1/mcp-apps/views/{uuid4()}/token/",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404


async def test_mint_with_flag_off_is_404(
    client, admin_user, admin_user_api_key, monkeypatch
):
    _apps_settings(monkeypatch, mcp_apps_enabled=False)
    view_id = await _seed_view(admin_user.tenant_id)

    response = await client.post(
        f"/api/v1/mcp-apps/views/{view_id}/token/",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404


async def test_mint_without_content_origin_is_424(
    client, admin_user, admin_user_api_key, monkeypatch
):
    _apps_settings(monkeypatch, mcp_app_content_base_url=None)
    view_id = await _seed_view(admin_user.tenant_id)

    response = await client.post(
        f"/api/v1/mcp-apps/views/{view_id}/token/",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 424
    assert "MCP_APP_CONTENT_BASE_URL" in response.json()["detail"]


async def test_view_awaiting_approval_gets_no_link(
    client, admin_user, admin_user_api_key, monkeypatch
):
    _apps_settings(monkeypatch)
    view_id = await _seed_view(admin_user.tenant_id, approved=False)

    response = await client.post(
        f"/api/v1/mcp-apps/views/{view_id}/token/",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"is_enabled_by_default": False},
        {"removed_from_remote": True},
        {"ui_resource_sha256": "b" * 64},
        {"meta": None},
        {"meta": {"ui": {"resourceUri": "ui://changed/view"}}},
    ],
)
async def test_revoked_originating_tool_revokes_links_and_content(
    client, admin_user, admin_user_api_key, monkeypatch, change
):
    import sqlalchemy as sa

    _apps_settings(monkeypatch)
    view_id = await _seed_view(admin_user.tenant_id)
    mint = await client.post(
        f"/api/v1/mcp-apps/views/{view_id}/token/",
        headers={"X-API-Key": admin_user_api_key.key},
    )
    token = mint.json()["url"].split("token=")[1]
    async with sessionmanager.session() as session, session.begin():
        view = await McpAppViewRepo(session).get_for_tenant(
            view_id, admin_user.tenant_id
        )
        await session.execute(
            sa.update(MCPServerTools)
            .where(MCPServerTools.mcp_server_id == view.mcp_server_id)
            .values(**change)
        )
    mint = await client.post(
        f"/api/v1/mcp-apps/views/{view_id}/token/",
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert mint.status_code == 404
    content = await client.get(
        f"/api/v1/mcp-apps/views/{view_id}/content",
        params={"token": token},
        headers=CONTENT_HOST,
    )
    assert content.status_code == 404

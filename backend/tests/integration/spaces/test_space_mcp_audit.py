"""A space's audit entry records which MCP servers and tools were switched."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    MCPServerToolSettings,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ADDRESS = "https://audit-secret-host.example.test/mcp"


async def _headers(db_container, admin_user) -> dict[str, str]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"space-mcp-audit-{uuid4().hex[:8]}",
                permissions=[Permission.SHARED_SPACES],
                tenant_id=admin_user.tenant_id,
            )
        )
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("case", "second_patch", "expected"),
    [
        ("server on", None, "server_on"),
        ("server off", {"mcp_servers": []}, "server_off"),
        ("tool off", "tool_off", "tool_off"),
        ("tool off for all", "tool_off_for_all", "tool_off"),
        ("class removes server", "raise_class", "server_off"),
        ("unrelated", {"name": "renamed"}, "nothing"),
    ],
)
async def test_the_space_update_audits_switched_mcp_servers_and_tools(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    second_patch: object,
    expected: str,
):
    """Kills the mutants that leave the server diff or the tool diff out of
    the SPACE_UPDATED changes, record an unchanged server or tool or a tool
    of a server switched on with the space's switch for it, diff only
    the servers a request names (a raised space classification removes a
    server too), diff the tools the space shows instead of its stored
    settings (a tool switched off for all is not shown, yet its space setting
    is stored), or write the server's address into the audit."""
    headers = await _headers(db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(security_enabled=True)
        )
        low, high = (
            SecurityClassifications(
                tenant_id=admin_user.tenant_id,
                name=f"{name}-{uuid4().hex[:6]}",
                security_level=level,
            )
            for name, level in (("low", 1), ("high", 20))
        )
        session.add_all([low, high])
        await session.flush()
        high_id = str(high.id)
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"Register {uuid4().hex[:6]}",
            http_url=_ADDRESS,
            http_auth_type="none",
            is_enabled=True,
            security_classification_id=low.id,
        )
        session.add(server)
        await session.flush()
        tool = MCPServerTools(mcp_server_id=server.id, name="lookup_case")
        session.add(tool)
        await session.flush()
        if second_patch == "tool_off_for_all":
            session.add(
                MCPServerToolSettings(
                    tenant_id=admin_user.tenant_id,
                    mcp_server_tool_id=tool.id,
                    is_enabled=False,
                )
            )
            await session.flush()
        server_entry = {"id": str(server.id), "name": server.name}
        tool_id: UUID = tool.id

    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"mcp-audit-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    space_url = f"/api/v1/spaces/{response.json()['id']}/"

    recorded: list[dict[str, object]] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        recorded.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    switch_on = {
        "mcp_servers": [{"id": server_entry["id"]}],
        "mcp_tools": [{"tool_id": str(tool_id), "is_enabled": True}],
    }
    response = await client.patch(space_url, json=switch_on, headers=headers)
    assert response.status_code == 200, response.text
    if second_patch is not None:
        recorded.clear()
        tool_off = {
            **switch_on,
            "mcp_tools": [{"tool_id": str(tool_id), "is_enabled": False}],
        }
        body = {
            "tool_off": tool_off,
            "tool_off_for_all": tool_off,
            "raise_class": {"security_classification": {"id": high_id}},
        }.get(str(second_patch), second_patch)
        response = await client.patch(space_url, json=body, headers=headers)
        assert response.status_code == 200, response.text

    (update,) = [r for r in recorded if r["action"].value == "space_updated"]
    metadata = update["metadata"]
    changes = metadata.get("changes", {})
    mcp_changes = {
        k: v for k, v in changes.items() if k in ("mcp_servers", "mcp_tools")
    }
    tool_entry = {"id": str(tool_id), "name": "lookup_case"}
    assert (
        mcp_changes
        == {
            "server_on": {"mcp_servers": {"old": [], "new": [server_entry]}},
            "server_off": {"mcp_servers": {"old": [server_entry], "new": []}},
            "tool_off": {
                "mcp_tools": {
                    "old": [{**tool_entry, "is_enabled": True}],
                    "new": [{**tool_entry, "is_enabled": False}],
                }
            },
            "nothing": {},
        }[expected]
    ), case
    assert _ADDRESS not in json.dumps(metadata, default=str)

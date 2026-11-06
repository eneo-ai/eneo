"""A server's own security classification survives an edit that does not touch it.

Every path that reads one server and writes it back (an update, the
activation switch, a settings change) keeps the classification it was given.
"""

import pytest

from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)


@pytest.mark.parametrize("edit", ["rename", "deactivate", "settings"])
async def test_an_unrelated_edit_keeps_the_servers_own_classification(
    db_container, admin_user, edit
):
    async with db_container() as container:
        session = container.session()
        classification = SecurityClassification(
            tenant_id=admin_user.tenant_id, name="Confidential", security_level=2
        )
        session.add(classification)
        await session.flush()
        classification_id = classification.id
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Search",
            purpose="web_search" if edit == "deactivate" else "general",
            http_url="https://search.example/mcp",
            http_auth_type="none",
            is_enabled=True,
            security_classification_id=classification_id,
        )
        session.add(server)
        await session.flush()
        server_id = server.id

    async with db_container() as container:
        if edit == "rename":
            await container.mcp_server_service().update_mcp_server(
                server_id, name="Web search"
            )
        elif edit == "deactivate":
            await container.mcp_server_service().deactivate_capability_server(server_id)
        else:
            await container.mcp_server_settings_service().update_mcp_settings(
                server_id, is_org_enabled=False
            )

    async with db_container() as container:
        row = await container.session().get(MCPServers, server_id)
        assert row is not None
        assert row.security_classification_id == classification_id

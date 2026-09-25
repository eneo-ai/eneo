"""Run the data backfill against real legacy associations, inside a rollback."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.tables.capabilities_table import (
    AssistantCapabilities,
    GovernancePolicyCapabilities,
    SpaceCapabilities,
)
from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools


async def test_backfill_inactive_duplicates_defaults_and_general_tools(
    db_container, admin_user, space_factory, assistant_factory, monkeypatch
):
    async with db_container() as container:
        session = container.session()
        space = await space_factory(session, "Migration")
        assistant = await assistant_factory(
            session, "Migration", None, space_id=space.id
        )
        policy = GovernancePolicies(
            tenant_id=admin_user.tenant_id,
            scope="migration",
            mcp_restriction_enabled=True,
        )
        session.add(policy)
        await session.flush()
        providers = []
        tools = []
        for name, purpose, enabled in [
            ("old", "image_generation", False),
            ("new", "image_generation", True),
            ("search", "web_search", False),
            ("ordinary", "general", True),
        ]:
            row = MCPServers(
                tenant_id=admin_user.tenant_id,
                name=name,
                purpose=purpose,
                http_url="https://example.test/mcp",
                http_auth_type="none",
                is_enabled=enabled,
            )
            session.add(row)
            await session.flush()
            tool = MCPServerTools(
                mcp_server_id=row.id,
                name=name,
                description=name,
                input_schema={"type": "object"},
                is_enabled_by_default=True,
            )
            session.add(tool)
            await session.flush()
            providers.append(row.id)
            tools.append(tool.id)

        connection = await session.connection()

        def backfill(sync_connection):
            metadata = sa.MetaData()
            owners = [
                ("spaces_mcp_servers", "space_id", space.id),
                ("assistant_mcp_servers", "assistant_id", assistant.id),
                ("governance_policy_mcp_servers", "policy_id", policy.id),
            ]
            for name, key, identifier in owners:
                table = sa.Table(name, metadata, autoload_with=sync_connection)
                for index, provider_id in enumerate(providers):
                    values = {key: identifier, "mcp_server_id": provider_id}
                    if key == "policy_id":
                        values["is_default_enabled"] = index == 1
                    sync_connection.execute(sa.insert(table).values(**values))
            overrides = [
                ("spaces_mcp_server_tools", "space_id", space.id, "mcp_server_tool_id"),
                (
                    "assistant_mcp_server_tools",
                    "assistant_id",
                    assistant.id,
                    "mcp_server_tool_id",
                ),
                (
                    "governance_policy_disabled_mcp_tools",
                    "policy_id",
                    policy.id,
                    "mcp_tool_id",
                ),
            ]
            for name, key, identifier, tool_key in overrides:
                table = sa.Table(name, metadata, autoload_with=sync_connection)
                for tool_id in tools:
                    sync_connection.execute(
                        sa.insert(table).values(**{key: identifier, tool_key: tool_id})
                    )
            for table in [
                SpaceCapabilities.__table__,
                AssistantCapabilities.__table__,
                GovernancePolicyCapabilities.__table__,
            ]:
                table.drop(sync_connection)
            path = (
                Path(__file__).parents[3]
                / "alembic/versions/202609041000_independent_capabilities.py"
            )
            spec = importlib.util.spec_from_file_location("capability_backfill", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            monkeypatch.setattr(
                module, "op", Operations(MigrationContext.configure(sync_connection))
            )
            module.upgrade()
            for name, key, identifier in owners:
                table = metadata.tables[name]
                assert sync_connection.execute(
                    sa.select(table.c.mcp_server_id).where(table.c[key] == identifier)
                ).scalars().all() == [providers[-1]]
            for name, key, identifier, tool_key in overrides:
                table = metadata.tables[name]
                assert sync_connection.execute(
                    sa.select(table.c[tool_key]).where(table.c[key] == identifier)
                ).scalars().all() == [tools[-1]]
            for table, key, identifier in [
                (SpaceCapabilities.__table__, "space_id", space.id),
                (AssistantCapabilities.__table__, "assistant_id", assistant.id),
                (GovernancePolicyCapabilities.__table__, "policy_id", policy.id),
            ]:
                rows = (
                    sync_connection.execute(
                        sa.select(table).where(table.c[key] == identifier)
                    )
                    .mappings()
                    .all()
                )
                assert {r["purpose"] for r in rows} == {
                    "image_generation",
                    "web_search",
                }
                if key == "policy_id":
                    assert {r["purpose"]: r["is_default_enabled"] for r in rows} == {
                        "image_generation": True,
                        "web_search": False,
                    }

        # Roll back DDL too, retaining the test database's current schema.
        savepoint = await session.begin_nested()
        try:
            await connection.run_sync(backfill)
        finally:
            await savepoint.rollback()

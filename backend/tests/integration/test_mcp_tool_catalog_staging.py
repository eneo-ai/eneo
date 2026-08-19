import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
    MCPServerTool,
    MCPToolCatalogStagingTimeout,
)
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import (
    MCPServerToolMapper,
)
from eneo.mcp_servers.infrastructure.repo_impl.mcp_server_tool_repo_impl import (
    MCPServerToolRepoImpl,
)


async def test_concurrent_runtime_discovery_stages_one_pending_tool(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-staging-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    async def stage(description: str) -> list[MCPServerTool]:
        async with sessionmanager.session() as session, session.begin():
            repo = MCPServerToolRepoImpl(session, MCPServerToolMapper())
            return await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="ordinary_only",
                        title="Ordinary only",
                        description=description,
                        input_schema={"type": "object", "properties": {}},
                    )
                ]
            )

    try:
        staged = await asyncio.gather(stage("first"), stage("second"))
        assert sum(bool(batch) for batch in staged) == 1

        async with sessionmanager.session() as verify_session, verify_session.begin():
            repo = MCPServerToolRepoImpl(verify_session, MCPServerToolMapper())
            tools = await repo.by_server(server_id)
        assert len(tools) == 1
        assert tools[0].description is None
        assert tools[0].pending_description in {"first", "second"}
        assert tools[0].requires_approval is True
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


async def test_runtime_staging_completes_inside_read_only_request_transaction(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-request-lifecycle-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    outer_session = sessionmanager.create_session()
    try:
        await outer_session.begin()
        await outer_session.scalar(
            sa.select(MCPServers.id).where(MCPServers.id == server_id)
        )
        repo = MCPServerToolRepoImpl(outer_session, MCPServerToolMapper())
        staged = await asyncio.wait_for(
            repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="observed-in-request",
                        title=None,
                        description="Observed while the request transaction is open",
                        input_schema={"type": "object"},
                    )
                ]
            ),
            timeout=0.5,
        )
        assert [tool.name for tool in staged] == ["observed-in-request"]
        await outer_session.rollback()
    finally:
        await outer_session.close()

    try:
        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert [tool.name for tool in tools] == ["observed-in-request"]
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


async def test_runtime_staging_times_out_behind_conflicting_request_lock(
    setup_database: None,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eneo.mcp_servers.infrastructure.repo_impl import (
        mcp_server_tool_repo_impl as repo_module,
    )

    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-request-lock-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    monkeypatch.setattr(repo_module, "MCP_TOOL_CATALOG_STAGE_TIMEOUT_SECONDS", 0.1)
    outer_session = sessionmanager.create_session()
    try:
        await outer_session.begin()
        await outer_session.scalar(
            sa.select(MCPServers.id).where(MCPServers.id == server_id).with_for_update()
        )
        repo = MCPServerToolRepoImpl(outer_session, MCPServerToolMapper())
        with pytest.raises(MCPToolCatalogStagingTimeout):
            await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="blocked-observation",
                        title=None,
                        description="Must not be partially written",
                        input_schema={"type": "object"},
                    )
                ]
            )
        await outer_session.rollback()
    finally:
        await outer_session.close()

    try:
        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert tools == []
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


async def test_runtime_discovery_rejects_disjoint_catalog_beyond_persisted_limit(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-union-count-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=2,
            tool_catalog_max_bytes=1024 * 1024,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    def observation(name: str) -> MCPServerTool:
        return MCPServerTool.pending_discovery(
            mcp_server_id=server_id,
            name=name,
            title=None,
            description=f"Contract for {name}",
            input_schema={"type": "object", "properties": {}},
        )

    try:
        async with sessionmanager.session() as first_session, first_session.begin():
            repo = MCPServerToolRepoImpl(first_session, MCPServerToolMapper())
            await repo.stage_observed([observation("first"), observation("second")])

        async with sessionmanager.session() as rejected_session:
            async with rejected_session.begin():
                repo = MCPServerToolRepoImpl(rejected_session, MCPServerToolMapper())
                with pytest.raises(ValueError, match="persisted tool catalog"):
                    await repo.stage_observed([observation("third")])

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert [tool.name for tool in tools] == ["first", "second"]
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


async def test_identity_admin_refresh_cannot_grow_persisted_union_past_limit(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server_row = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"admin-union-count-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=2,
            tool_catalog_max_bytes=1024 * 1024,
        )
        seed_session.add(server_row)
        await seed_session.flush()
        server_id = server_row.id

    server = MCPServer(
        id=server_id,
        tenant_id=admin_user.tenant_id,
        name="admin-union-count",
        http_url="http://localhost:9000/mcp",
        forward_identity=True,
        tool_catalog_max_count=2,
        tool_catalog_max_bytes=1024 * 1024,
    )
    live_catalog = [
        {"name": "first", "description": "first", "input_schema": {}},
        {"name": "second", "description": "second", "input_schema": {}},
    ]

    class CatalogClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self):
            return list(live_catalog)

    try:
        async with sessionmanager.session() as service_session, service_session.begin():
            service = MCPServerService(
                mcp_server_repo=AsyncMock(),
                mcp_server_tool_repo=MCPServerToolRepoImpl(
                    service_session, MCPServerToolMapper()
                ),
                user=admin_user,
            )
            with patch(
                "eneo.mcp_servers.application.mcp_server_service.MCPClient",
                CatalogClient,
            ):
                first = await service.discover_and_sync_tools(server)
                assert first.connection.success is True
                live_catalog[:] = [
                    {"name": "third", "description": "third", "input_schema": {}}
                ]
                rejected = await service.discover_and_sync_tools(server)
                assert rejected.connection.success is False

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert [tool.name for tool in tools] == ["first", "second"]
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


async def test_runtime_and_admin_refresh_share_one_bounded_catalog_union(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server_row = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"mixed-union-count-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=1,
            tool_catalog_max_bytes=1024 * 1024,
        )
        seed_session.add(server_row)
        await seed_session.flush()
        server_id = server_row.id

    server = MCPServer(
        id=server_id,
        tenant_id=admin_user.tenant_id,
        name="mixed-union-count",
        http_url="http://localhost:9000/mcp",
        forward_identity=True,
        tool_catalog_max_count=1,
        tool_catalog_max_bytes=1024 * 1024,
    )

    class CatalogClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self):
            return [
                {
                    "name": "admin-observed",
                    "description": "admin",
                    "input_schema": {},
                }
            ]

    async def admin_refresh():
        async with sessionmanager.session() as service_session, service_session.begin():
            service = MCPServerService(
                mcp_server_repo=AsyncMock(),
                mcp_server_tool_repo=MCPServerToolRepoImpl(
                    service_session, MCPServerToolMapper()
                ),
                user=admin_user,
            )
            return await service.discover_and_sync_tools(server)

    async def runtime_observation():
        async with sessionmanager.session() as runtime_session, runtime_session.begin():
            return await MCPServerToolRepoImpl(
                runtime_session, MCPServerToolMapper()
            ).stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="runtime-observed",
                        title=None,
                        description="runtime",
                        input_schema={},
                    )
                ]
            )

    try:
        with patch(
            "eneo.mcp_servers.application.mcp_server_service.MCPClient", CatalogClient
        ):
            refresh_result, runtime_result = await asyncio.gather(
                admin_refresh(), runtime_observation(), return_exceptions=True
            )

        successful_refresh = (
            not isinstance(refresh_result, BaseException)
            and refresh_result.connection.success
        )
        successful_runtime = isinstance(runtime_result, list)
        assert int(successful_refresh) + int(successful_runtime) == 1

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert len(tools) == 1
        assert tools[0].name in {"admin-observed", "runtime-observed"}
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


async def test_concurrent_disjoint_catalogs_cannot_exceed_persisted_byte_limit(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-union-bytes-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=10,
            tool_catalog_max_bytes=4096,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    async def stage(name: str) -> list[MCPServerTool]:
        async with sessionmanager.session() as session, session.begin():
            return await MCPServerToolRepoImpl(
                session, MCPServerToolMapper()
            ).stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name=name,
                        title=None,
                        description="x" * 3000,
                        input_schema={"type": "object", "properties": {}},
                    )
                ]
            )

    try:
        results = await asyncio.gather(
            stage("catalog-a"), stage("catalog-b"), return_exceptions=True
        )
        assert sum(isinstance(result, list) for result in results) == 1
        assert (
            sum(
                isinstance(result, ValueError)
                and "persisted tool catalog" in str(result)
                for result in results
            )
            == 1
        )

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert len(tools) == 1
        assert tools[0].name in {"catalog-a", "catalog-b"}
        assert len(tools[0].pending_description or "") == 3000
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


async def test_runtime_staging_queues_approved_drift_once(
    setup_database: None,
    admin_user,
) -> None:
    original_schema = {"type": "object", "properties": {}}
    changed_schema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
    }
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-drift-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id
        repo = MCPServerToolRepoImpl(seed_session, MCPServerToolMapper())
        await repo.upsert_by_server_and_name(
            MCPServerTool(
                mcp_server_id=server_id,
                name="ordinary_only",
                description="Approved contract",
                input_schema=original_schema,
            )
        )

    try:
        async with sessionmanager.session() as stage_session, stage_session.begin():
            repo = MCPServerToolRepoImpl(stage_session, MCPServerToolMapper())
            staged = await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="ordinary_only",
                        title=None,
                        description="Changed contract",
                        input_schema=changed_schema,
                    )
                ]
            )
            assert len(staged) == 1

        async with sessionmanager.session() as later_session, later_session.begin():
            repo = MCPServerToolRepoImpl(later_session, MCPServerToolMapper())
            await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="ordinary_only",
                        title=None,
                        description="Later unreviewed contract",
                        input_schema={"type": "object", "required": ["other"]},
                    )
                ]
            )

        async with sessionmanager.session() as verify_session, verify_session.begin():
            [tool] = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert tool.description == "Approved contract"
        assert tool.input_schema == original_schema
        assert tool.pending_description == "Changed contract"
        assert tool.pending_input_schema == changed_schema
        assert tool.requires_approval is True
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )

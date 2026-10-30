"""A help assistant calls only the MCP servers its space has switched on.

Kills the mutant that hands the helper's stored servers to the completion
unfiltered, in ``run`` and in ``continue_turn``: a server a space admin
switched off stops at once, as it does for chat turns.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import AssistantMCPServers, Assistants
from eneo.database.tables.mcp_server_table import MCPServers, SpacesMCPServers
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.helper_kind import HelperKind

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _insert_assistant(session: Any, *, admin_user: Any, space_id: UUID) -> UUID:
    model_id = await session.scalar(
        sa.select(CompletionModels.id).where(
            CompletionModels.tenant_id == admin_user.tenant_id,
            CompletionModels.is_enabled.is_(True),
        )
    )
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=f"assistant-{assistant_id}",
            user_id=admin_user.id,
            space_id=space_id,
            completion_model_id=model_id,
            logging_enabled=False,
            is_default=False,
            published=False,
        )
    )
    return assistant_id


@pytest.mark.parametrize("switched_on_in_space", [True, False])
async def test_helper_turns_call_only_servers_the_space_has_switched_on(
    db_container, admin_user, monkeypatch, switched_on_in_space: bool
):
    called_server_ids: list[list[UUID]] = []

    async def fake_get_response(self: CompletionService, **kwargs: Any):
        called_server_ids.append([server.id for server in kwargs["mcp_servers"]])
        return CompletionModelResponse(
            completion=Completion(text="ok"),
            model=kwargs["model"],
            extended_logging=None,
            total_token_count=1,
            usage=None,
        )

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)

    async with db_container() as container:
        session = container.session()
        await container.space_service().get_or_create_tenant_space()
        org_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        target_id = await _insert_assistant(
            session, admin_user=admin_user, space_id=org_space_id
        )
        helper_id = await _insert_assistant(
            session, admin_user=admin_user, space_id=org_space_id
        )
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"helper-server-{uuid4()}",
            http_url="https://mcp.example.test/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        session.add(server)
        await session.flush()
        server_id = server.id
        session.add(
            AssistantMCPServers(assistant_id=helper_id, mcp_server_id=server_id)
        )
        if switched_on_in_space:
            session.add(
                SpacesMCPServers(space_id=org_space_id, mcp_server_id=server_id)
            )
        await container.org_space_assistant_role_repo().add(
            container.helper_assistants_factory().create_role_assignment(
                org_space_id=org_space_id,
                kind=HelperKind.PROMPT_GUIDE,
                assistant_id=helper_id,
                created_by_user_id=admin_user.id,
            )
        )
        await session.flush()

        service = container.helper_run_service()
        first = await service.run(
            kind=HelperKind.PROMPT_GUIDE,
            target_type="assistant",
            target_id=target_id,
            question="Help me with the prompt.",
        )
        await service.continue_turn(run_id=first.run.id, question="And then?")

    expected = [server_id] if switched_on_in_space else []
    assert called_server_ids == [expected, expected]

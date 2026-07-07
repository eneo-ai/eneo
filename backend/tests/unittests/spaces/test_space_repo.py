from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.spaces.space_repo import SpaceRepository


def _repo(session: MagicMock) -> SpaceRepository:
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    return SpaceRepository(
        session=session,
        user=user,
        factory=MagicMock(),
        app_repo=MagicMock(),
        assistant_repo=MagicMock(),
        completion_model_repo=MagicMock(),
        transcription_model_repo=MagicMock(),
        embedding_model_repo=MagicMock(),
        http_auth_encryption=MagicMock(),
    )


async def test_get_assistants_eager_loads_mcp_tool_settings():
    """Assistant factory reads assistant_mcp_server_tools synchronously.

    Keep the relationship eager-loaded in the space repository so loading a
    personal space cannot trigger async SQLAlchemy lazy IO during domain mapping.
    """
    session = MagicMock()
    assistants_result = MagicMock()
    assistants_result.scalars.return_value.all.return_value = []
    prompts_result = MagicMock()
    prompts_result.all.return_value = []
    session.execute = AsyncMock(side_effect=[assistants_result, prompts_result])

    repo = _repo(session)
    await repo._get_assistants(uuid4())

    assistants_stmt = session.execute.await_args_list[0].args[0]
    loader_paths = [str(option.path) for option in assistants_stmt._with_options]

    assert any("assistant_mcp_server_tools" in path for path in loader_paths)

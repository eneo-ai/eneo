from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.spaces.space_init_service import SpaceInitService


def _service(space):
    space_service = MagicMock()
    space_service.get_space = AsyncMock(return_value=space)
    assistant_service = MagicMock()
    assistant_service.create_default_assistant = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    space_repo = MagicMock()
    space_repo.update = AsyncMock(side_effect=lambda s: s)
    init_service = SpaceInitService(
        user=MagicMock(),
        space_service=space_service,
        assistant_service=assistant_service,
        space_repo=space_repo,
    )
    return init_service, assistant_service


async def test_get_space_does_not_recreate_default_when_load_failed():
    """A default row that exists but failed to load must NOT trigger creation
    of a replacement — that would orphan a duplicate default (no DB-level
    uniqueness before the partial index)."""
    space = SimpleNamespace(
        default_assistant=None,
        default_assistant_load_failed=True,
        add_assistant=MagicMock(),
    )
    init_service, assistant_service = _service(space)

    result = await init_service.get_space(uuid4())

    assistant_service.create_default_assistant.assert_not_awaited()
    assert result is space


async def test_get_space_creates_default_when_genuinely_missing():
    """No default row at all → create one, as before."""
    space = SimpleNamespace(
        default_assistant=None,
        default_assistant_load_failed=False,
        add_assistant=MagicMock(),
    )
    init_service, assistant_service = _service(space)

    await init_service.get_space(uuid4())

    assistant_service.create_default_assistant.assert_awaited_once()

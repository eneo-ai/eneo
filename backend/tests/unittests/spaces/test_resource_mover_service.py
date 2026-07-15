from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.spaces.domain.resource_mover_service import ResourceMoverService


async def test_bound_assistant_cannot_move_between_spaces() -> None:
    assistant_id = uuid4()
    target_space_id = uuid4()
    assistant = MagicMock(id=assistant_id)
    source_space = MagicMock()
    source_space.get_assistant.return_value = assistant
    target_space = MagicMock()

    source_actor = MagicMock()
    source_actor.can_delete_assistants.return_value = True
    target_actor = MagicMock()
    target_actor.can_create_assistants.return_value = True
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.side_effect = [
        source_actor,
        target_actor,
    ]

    space_service = AsyncMock()
    space_service.get_space_by_assistant.return_value = source_space
    space_service.get_space.return_value = target_space
    skill_repo = AsyncMock()
    skill_repo.has_assistant_bindings.return_value = True
    space_repo = AsyncMock()

    service = ResourceMoverService(
        space_service=space_service,
        space_repo=space_repo,
        actor_manager=actor_manager,
        group_service=AsyncMock(),
        skill_repo=skill_repo,
    )

    with pytest.raises(BadRequestException, match="Remove.*Skill bindings"):
        await service.move_assistant_to_space(
            assistant_id=assistant_id,
            space_id=target_space_id,
        )

    target_space.add_assistant.assert_not_called()
    source_space.remove_assistant.assert_not_called()
    space_repo.update.assert_not_awaited()

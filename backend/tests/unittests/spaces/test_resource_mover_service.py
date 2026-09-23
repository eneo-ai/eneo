from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.spaces.domain.resource_mover_service import ResourceMoverService
from eneo.widgets.application import widget_target_lifecycle
from eneo.widgets.domain.exceptions import AssistantPublishedAsWidgetError
from eneo.widgets.domain.widget import WidgetStatus


async def test_bound_assistant_cannot_move_between_spaces() -> None:
    assistant_id = uuid4()
    target_space_id = uuid4()
    assistant = MagicMock(id=assistant_id)
    source_space = MagicMock()
    source_space.id = uuid4()
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
        source_actor,
    ]

    space_service = AsyncMock()
    space_service.get_space_by_assistant.return_value = source_space
    space_service.get_space.side_effect = lambda space_id: (
        source_space if space_id == source_space.id else target_space
    )
    skill_repo = AsyncMock()
    skill_repo.lock_assistant_space_for_update.return_value = source_space.id
    skill_repo.has_assistant_bindings.return_value = True
    space_repo = AsyncMock()

    service = ResourceMoverService(
        space_service=space_service,
        space_repo=space_repo,
        actor_manager=actor_manager,
        group_service=AsyncMock(),
        skill_repo=skill_repo,
        widget_repo=AsyncMock(),
    )

    with pytest.raises(BadRequestException, match="Remove.*Skill bindings"):
        await service.move_assistant_to_space(
            assistant_id=assistant_id,
            space_id=target_space_id,
        )

    target_space.add_assistant.assert_not_called()
    source_space.remove_assistant.assert_not_called()
    space_repo.update.assert_not_awaited()


def _mover(widgets: list) -> tuple[ResourceMoverService, MagicMock, MagicMock]:
    assistant = MagicMock()
    source_space = MagicMock()
    source_space.id = uuid4()
    source_space.get_assistant.return_value = assistant
    target_space = MagicMock()

    actor = MagicMock()
    actor.can_delete_assistants.return_value = True
    actor.can_create_assistants.return_value = True
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor

    space_service = AsyncMock()
    space_service.get_space_by_assistant.return_value = source_space
    space_service.get_space.side_effect = lambda space_id: (
        source_space if space_id == source_space.id else target_space
    )
    skill_repo = AsyncMock()
    skill_repo.lock_assistant_space_for_update.return_value = source_space.id
    skill_repo.has_assistant_bindings.return_value = False
    widget_repo = AsyncMock()
    widget_repo.list_by_target.return_value = widgets

    service = ResourceMoverService(
        space_service=space_service,
        space_repo=AsyncMock(),
        actor_manager=actor_manager,
        group_service=AsyncMock(),
        skill_repo=skill_repo,
        widget_repo=widget_repo,
    )
    return service, target_space, assistant


@pytest.mark.parametrize("status", [WidgetStatus.ACTIVE, WidgetStatus.PAUSED])
async def test_assistant_with_a_live_widget_cannot_move_between_spaces(
    status, monkeypatch
) -> None:
    archive = AsyncMock()
    monkeypatch.setattr(
        widget_target_lifecycle, "archive_drafts_of_moved_assistant", archive
    )
    draft = MagicMock(status=WidgetStatus.DRAFT)
    service, target_space, _ = _mover([draft, MagicMock(status=status)])

    with pytest.raises(AssistantPublishedAsWidgetError):
        await service.move_assistant_to_space(assistant_id=uuid4(), space_id=uuid4())

    target_space.add_assistant.assert_not_called()
    service.space_repo.update.assert_not_awaited()
    archive.assert_not_awaited()


async def test_moving_an_assistant_archives_its_draft_widgets(monkeypatch) -> None:
    archive = AsyncMock()
    monkeypatch.setattr(
        widget_target_lifecycle, "archive_drafts_of_moved_assistant", archive
    )
    drafts = [
        MagicMock(status=WidgetStatus.DRAFT),
        MagicMock(status=WidgetStatus.DRAFT),
    ]
    service, target_space, assistant = _mover(drafts)

    await service.move_assistant_to_space(assistant_id=uuid4(), space_id=uuid4())

    target_space.add_assistant.assert_called_once_with(assistant)
    archive.assert_awaited_once_with(
        service.space_repo.session,
        drafts=drafts,
        user=service.actor_manager.user,
    )


async def test_moving_an_assistant_without_widgets_archives_nothing(
    monkeypatch,
) -> None:
    archive = AsyncMock()
    monkeypatch.setattr(
        widget_target_lifecycle, "archive_drafts_of_moved_assistant", archive
    )
    service, target_space, assistant = _mover([])

    await service.move_assistant_to_space(assistant_id=uuid4(), space_id=uuid4())

    target_space.add_assistant.assert_called_once_with(assistant)
    archive.assert_not_awaited()

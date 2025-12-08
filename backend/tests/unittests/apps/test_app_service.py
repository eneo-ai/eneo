from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.apps.apps.app_service import AppService
from intric.main.exceptions import UnauthorizedException


@pytest.fixture
def service():
    return AppService(
        user=MagicMock(),
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        factory=MagicMock(),
        completion_model_crud_service=AsyncMock(),
        transcription_model_crud_service=AsyncMock(),
        file_service=AsyncMock(),
        prompt_service=AsyncMock(),
        transcriber=AsyncMock(),
        app_template_service=AsyncMock(),
        actor_manager=MagicMock(),
        completion_service=AsyncMock(),
        icon_repo=AsyncMock(),
    )


async def test_get_raise_unauthorized_if_can_not_access(
    service: AppService,
):
    actor = MagicMock()
    actor.can_read_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.get_app(MagicMock())


async def test_update_raise_unauthorized_if_can_not_edit(
    service: AppService,
):
    actor = MagicMock()
    actor.can_edit_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.update_app(MagicMock())


async def test_delete_raise_unauthorized_if_can_not_delete(
    service: AppService,
):
    actor = MagicMock()
    actor.can_delete_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.delete_app(MagicMock())

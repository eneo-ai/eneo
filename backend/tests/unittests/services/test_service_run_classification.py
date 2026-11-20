"""A service is only run when its space still accepts the service's model."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import UnauthorizedException
from eneo.services.service_service import ServiceService


def _service(space) -> ServiceService:
    service = ServiceService(
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        question_repo=AsyncMock(),
        group_service=AsyncMock(),
        user=MagicMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        actor_manager=MagicMock(),
    )
    service.space_repo.get_space_by_service.return_value = space
    return service


async def test_a_service_the_space_accepts_is_returned():
    space = MagicMock()
    space.can_use_service.return_value = True

    found = await _service(space).get_runnable_service(uuid4())

    assert found is space.get_service.return_value


async def test_a_service_below_the_spaces_level_is_refused():
    space = MagicMock()
    space.can_use_service.return_value = False

    with pytest.raises(UnauthorizedException):
        await _service(space).get_runnable_service(uuid4())


async def test_the_space_is_loaded_once_per_run():
    space = MagicMock()
    space.can_use_service.return_value = False
    service = _service(space)

    with pytest.raises(UnauthorizedException):
        await service.get_runnable_service(uuid4())

    service.space_repo.get_space_by_service.assert_awaited_once()

from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.prompts.prompt_service import PromptService


@pytest.fixture
def service():
    return PromptService(user=MagicMock(), repo=AsyncMock(), factory=MagicMock())


async def test_prompt_not_found(service: PromptService):
    service.repo.get.return_value = None
    with pytest.raises(NotFoundException):
        await service.get_prompt(MagicMock())


async def test_only_owner_can_update_description(service: PromptService):
    with pytest.raises(UnauthorizedException):
        await service.update_prompt_description(id=MagicMock(), description=MagicMock())


async def test_only_owner_can_delete(service: PromptService):
    with pytest.raises(UnauthorizedException):
        await service.delete_prompt(MagicMock())


async def test_cant_delete_selected_prompt(service: PromptService):
    service.repo.is_selected.return_value = True
    service.repo.get.return_value = MagicMock(
        user=service.user, tenant_id=service.user.tenant_id
    )

    with pytest.raises(BadRequestException):
        await service.delete_prompt(MagicMock())

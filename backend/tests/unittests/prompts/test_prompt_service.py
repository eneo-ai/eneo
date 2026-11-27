from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.prompts.prompt_service import PromptService, wrote_prompt


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
        user_id=service.user.id, tenant_id=service.user.tenant_id
    )

    with pytest.raises(BadRequestException):
        await service.delete_prompt(MagicMock())


def _person(user_id=None):
    return SimpleNamespace(
        id=user_id or uuid4(), tenant_id=uuid4(), active_api_key=None
    )


def _service_key_user(service_principal_id):
    """The made-up user a service key signs in as: its id is the key's id."""
    key = SimpleNamespace(
        id=uuid4(), ownership="service", service_principal_id=service_principal_id
    )
    return SimpleNamespace(id=key.id, tenant_id=uuid4(), active_api_key=key)


def _prompt(*, user_id=None, created_by_service_id=None):
    return SimpleNamespace(user_id=user_id, created_by_service_id=created_by_service_id)


def test_the_person_who_wrote_a_prompt_may_change_it():
    person = _person()

    assert wrote_prompt(person, _prompt(user_id=person.id))
    assert not wrote_prompt(person, _prompt(user_id=uuid4()))


def test_a_service_key_may_change_the_prompts_its_principal_wrote():
    principal_id = uuid4()
    key_user = _service_key_user(principal_id)
    rotated_key_user = _service_key_user(principal_id)

    own = _prompt(created_by_service_id=principal_id)

    assert wrote_prompt(key_user, own)
    assert wrote_prompt(rotated_key_user, own)
    assert not wrote_prompt(key_user, _prompt(created_by_service_id=uuid4()))


def test_a_person_and_a_service_key_do_not_share_prompts():
    principal_id = uuid4()
    person = _person()
    key_user = _service_key_user(principal_id)

    assert not wrote_prompt(person, _prompt(created_by_service_id=principal_id))
    assert not wrote_prompt(key_user, _prompt(user_id=person.id))
    # The key's own id is never a person, even if a prompt happens to carry it.
    assert not wrote_prompt(key_user, _prompt(user_id=key_user.id))


def test_a_prompt_whose_writer_is_gone_belongs_to_nobody():
    orphan = _prompt()

    assert not wrote_prompt(_person(), orphan)
    assert not wrote_prompt(_service_key_user(uuid4()), orphan)


async def test_a_service_key_records_its_principal_as_the_writer():
    principal_id = uuid4()
    user = _service_key_user(principal_id)
    factory = MagicMock()
    service = PromptService(user=user, repo=AsyncMock(), factory=factory)

    await service.create_prompt("Answer briefly.")

    factory.create_prompt.assert_called_once_with(
        text="Answer briefly.",
        description=None,
        user_id=None,
        created_by_service_id=principal_id,
        tenant_id=user.tenant_id,
    )


async def test_a_person_is_recorded_as_the_writer():
    user = _person()
    factory = MagicMock()
    service = PromptService(user=user, repo=AsyncMock(), factory=factory)

    await service.create_prompt("Answer briefly.", "Short answers")

    factory.create_prompt.assert_called_once_with(
        text="Answer briefly.",
        description="Short answers",
        user_id=user.id,
        created_by_service_id=None,
        tenant_id=user.tenant_id,
    )


async def test_a_prompt_written_for_someone_elses_resource_goes_to_that_person():
    owner_id = uuid4()
    factory = MagicMock()
    service = PromptService(
        user=_service_key_user(uuid4()), repo=AsyncMock(), factory=factory
    )

    await service.create_prompt("Answer briefly.", owner_user_id=owner_id)

    assert factory.create_prompt.call_args.kwargs["user_id"] == owner_id
    assert factory.create_prompt.call_args.kwargs["created_by_service_id"] is None

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.spaces.domain.resource_mover_service import ResourceMoverService

TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()


def _user(tenant_id: UUID = TENANT_ID) -> MagicMock:
    return MagicMock(id=uuid4(), tenant_id=tenant_id)


def _space(tenant_id: UUID = TENANT_ID) -> MagicMock:
    space = MagicMock()
    space.id = uuid4()
    space.tenant_id = tenant_id
    space.websites = []
    return space


def _permissive_actor() -> MagicMock:
    actor = MagicMock()
    for name in (
        "can_read_websites",
        "can_create_websites",
        "can_delete_websites",
        "can_read_collections",
        "can_create_collections",
        "can_delete_collections",
        "can_create_assistants",
        "can_delete_assistants",
    ):
        getattr(actor, name).return_value = True
    return actor


def _service(
    *,
    source_space: MagicMock,
    target_space: MagicMock,
    user: MagicMock | None = None,
    skill_repo: AsyncMock | None = None,
    group_service: AsyncMock | None = None,
) -> tuple[ResourceMoverService, AsyncMock]:
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = _permissive_actor()

    space_service = AsyncMock()
    space_service.get_space_by_assistant.return_value = source_space
    space_service.get_space_by_website.return_value = source_space
    space_service.get_space_by_collection.return_value = source_space
    space_service.get_space.side_effect = lambda space_id: (
        source_space if space_id == source_space.id else target_space
    )
    if skill_repo is None:
        skill_repo = AsyncMock()
        skill_repo.lock_assistant_space_for_update.return_value = source_space.id
        skill_repo.has_assistant_bindings.return_value = False
    space_repo = AsyncMock()

    service = ResourceMoverService(
        user=user or _user(),
        space_service=space_service,
        space_repo=space_repo,
        actor_manager=actor_manager,
        group_service=group_service or AsyncMock(),
        skill_repo=skill_repo,
        assistant_repo=AsyncMock(),
        website_repo=AsyncMock(),
    )
    return service, space_repo


async def test_bound_assistant_cannot_move_between_spaces() -> None:
    assistant_id = uuid4()
    target_space_id = uuid4()
    assistant = MagicMock(id=assistant_id)
    source_space = MagicMock()
    source_space.id = uuid4()
    source_space.id = uuid4()
    source_space.tenant_id = TENANT_ID
    source_space.get_assistant.return_value = assistant
    target_space = MagicMock()
    target_space.id = target_space_id
    target_space.tenant_id = TENANT_ID

    source_actor = MagicMock()
    source_actor.can_delete_assistants.return_value = True
    target_actor = MagicMock()
    target_actor.can_create_assistants.return_value = True
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.side_effect = [
        source_actor,
        target_actor,
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
        user=_user(),
        space_service=space_service,
        space_repo=space_repo,
        actor_manager=actor_manager,
        group_service=AsyncMock(),
        skill_repo=skill_repo,
        assistant_repo=AsyncMock(),
        website_repo=AsyncMock(),
    )

    with pytest.raises(BadRequestException, match="Remove.*Skill bindings"):
        await service.move_assistant_to_space(
            assistant_id=assistant_id,
            space_id=target_space_id,
        )

    target_space.add_assistant.assert_not_called()
    source_space.remove_assistant.assert_not_called()
    service.assistant_repo.move.assert_not_awaited()


# ---------------------------------------------------------------------------
# Moves and links never cross a tenant boundary, whatever the space roles say
# ---------------------------------------------------------------------------


async def test_assistant_move_into_foreign_tenant_space_is_denied() -> None:
    source_space = _space()
    target_space = _space(tenant_id=OTHER_TENANT_ID)
    assistant = MagicMock(
        id=uuid4(), is_default=False, completion_model=None, collections=[], websites=[]
    )
    source_space.get_assistant.return_value = assistant
    service, space_repo = _service(source_space=source_space, target_space=target_space)

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id
        )

    service.skill_repo.lock_assistant_space_for_update.assert_not_awaited()
    target_space.add_assistant.assert_not_called()
    source_space.remove_assistant.assert_not_called()
    service.assistant_repo.move.assert_not_awaited()


async def test_assistant_move_out_of_foreign_tenant_space_is_denied() -> None:
    source_space = _space(tenant_id=OTHER_TENANT_ID)
    target_space = _space()
    assistant = MagicMock(
        id=uuid4(), is_default=False, completion_model=None, collections=[], websites=[]
    )
    source_space.get_assistant.return_value = assistant
    service, space_repo = _service(source_space=source_space, target_space=target_space)

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id
        )

    service.assistant_repo.move.assert_not_awaited()


async def test_assistant_move_revalidates_tenant_after_lock() -> None:
    """The locked re-read of the source is the authoritative one; if it now
    resolves to a foreign-tenant space the move stops before any mutation."""
    source_space = _space()
    target_space = _space()
    locked_source = _space(tenant_id=OTHER_TENANT_ID)
    locked_source.id = source_space.id
    assistant = MagicMock(
        id=uuid4(), is_default=False, completion_model=None, collections=[], websites=[]
    )
    locked_source.get_assistant.return_value = assistant
    skill_repo = AsyncMock()
    skill_repo.lock_assistant_space_for_update.return_value = locked_source.id
    skill_repo.has_assistant_bindings.return_value = False
    service, space_repo = _service(
        source_space=source_space, target_space=target_space, skill_repo=skill_repo
    )
    service.space_service.get_space.side_effect = lambda space_id: {
        source_space.id: source_space,
        target_space.id: target_space,
        locked_source.id: locked_source,
    }[space_id]

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id
        )

    target_space.add_assistant.assert_not_called()
    locked_source.remove_assistant.assert_not_called()
    service.assistant_repo.move.assert_not_awaited()


async def test_assistant_move_with_foreign_tenant_attachment_is_denied() -> None:
    source_space = _space()
    target_space = _space()
    foreign_collection = MagicMock(id=uuid4(), tenant_id=OTHER_TENANT_ID)
    assistant = MagicMock(
        id=uuid4(),
        is_default=False,
        completion_model=None,
        collections=[foreign_collection],
        websites=[],
    )
    source_space.get_assistant.return_value = assistant
    group_service = AsyncMock()
    service, space_repo = _service(
        source_space=source_space,
        target_space=target_space,
        group_service=group_service,
    )

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id, move_resources=True
        )

    group_service.import_group_to_space.assert_not_awaited()
    target_space.add_assistant.assert_not_called()
    service.assistant_repo.move.assert_not_awaited()


async def test_assistant_move_within_tenant_succeeds() -> None:
    source_space = _space()
    target_space = _space()
    collection = MagicMock(id=uuid4(), tenant_id=TENANT_ID)
    assistant = MagicMock(
        id=uuid4(),
        is_default=False,
        completion_model=None,
        collections=[collection],
        websites=[],
    )
    source_space.get_assistant.return_value = assistant
    group_service = AsyncMock()
    service, space_repo = _service(
        source_space=source_space,
        target_space=target_space,
        group_service=group_service,
    )

    await service.move_assistant_to_space(
        assistant_id=assistant.id, space_id=target_space.id, move_resources=True
    )

    target_space.add_assistant.assert_called_once_with(assistant)
    group_service.import_group_to_space.assert_awaited_once()
    service.assistant_repo.move.assert_awaited_once_with(
        assistant.id, source_space.id, target_space.id
    )


async def test_caller_from_another_tenant_cannot_move_between_two_foreign_spaces() -> (
    None
):
    source_space = _space(tenant_id=OTHER_TENANT_ID)
    target_space = _space(tenant_id=OTHER_TENANT_ID)
    assistant = MagicMock(
        id=uuid4(), is_default=False, completion_model=None, collections=[], websites=[]
    )
    source_space.get_assistant.return_value = assistant
    service, space_repo = _service(
        source_space=source_space, target_space=target_space, user=_user(TENANT_ID)
    )

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id
        )

    service.assistant_repo.move.assert_not_awaited()


async def test_collection_move_into_foreign_tenant_space_is_denied() -> None:
    source_space = _space()
    target_space = _space(tenant_id=OTHER_TENANT_ID)
    collection = MagicMock(id=uuid4(), tenant_id=TENANT_ID)
    source_space.get_collection.return_value = collection
    group_service = AsyncMock()
    service, _ = _service(
        source_space=source_space,
        target_space=target_space,
        group_service=group_service,
    )

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_collection_to_space(
            collection_id=collection.id, space_id=target_space.id
        )

    group_service.import_group_to_space.assert_not_awaited()


async def test_collection_move_within_tenant_succeeds() -> None:
    source_space = _space()
    target_space = _space()
    collection = MagicMock(id=uuid4(), tenant_id=TENANT_ID)
    source_space.get_collection.return_value = collection
    group_service = AsyncMock()
    service, _ = _service(
        source_space=source_space,
        target_space=target_space,
        group_service=group_service,
    )

    await service.move_collection_to_space(
        collection_id=collection.id, space_id=target_space.id
    )

    group_service.import_group_to_space.assert_awaited_once_with(
        group_id=collection.id, space_id=target_space.id
    )


@pytest.mark.parametrize("method", ["link_website_to_space"])
async def test_website_link_and_move_into_foreign_tenant_space_are_denied(
    method: str,
) -> None:
    source_space = _space()
    target_space = _space(tenant_id=OTHER_TENANT_ID)
    website = MagicMock(id=uuid4(), tenant_id=TENANT_ID)
    source_space.get_website.return_value = website
    source_space.websites = [website]
    service, space_repo = _service(source_space=source_space, target_space=target_space)

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await getattr(service, method)(website_id=website.id, space_id=target_space.id)

    target_space.add_website.assert_not_called()
    source_space.remove_website.assert_not_called()
    service.assistant_repo.move.assert_not_awaited()


async def test_website_link_within_tenant_succeeds() -> None:
    source_space = _space()
    target_space = _space()
    website = MagicMock(id=uuid4(), tenant_id=TENANT_ID)
    source_space.get_website.return_value = website
    service, space_repo = _service(source_space=source_space, target_space=target_space)

    await service.link_website_to_space(website_id=website.id, space_id=target_space.id)

    target_space.add_website.assert_called_once_with(website)
    service.website_repo.link.assert_awaited_once_with(website.id, target_space.id)


async def test_assistant_move_to_its_current_space_is_rejected() -> None:
    space = _space()
    assistant = MagicMock(
        id=uuid4(), is_default=False, completion_model=None, collections=[], websites=[]
    )
    space.get_assistant.return_value = assistant
    service, space_repo = _service(source_space=space, target_space=space)

    with pytest.raises(BadRequestException):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=space.id
        )

    space_repo.lock.assert_not_awaited()
    service.assistant_repo.move.assert_not_awaited()

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.spaces.domain.resource_mover_service import ResourceMoverService
from eneo.widgets.application import widget_target_lifecycle
from eneo.widgets.domain.exceptions import AssistantPublishedAsWidgetError
from eneo.widgets.domain.widget import WidgetStatus

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
    widget_repo = AsyncMock()
    widget_repo.list_by_target.return_value = []

    service = ResourceMoverService(
        user=user or _user(),
        space_service=space_service,
        space_repo=space_repo,
        actor_manager=actor_manager,
        group_service=group_service or AsyncMock(),
        skill_repo=skill_repo,
        widget_repo=widget_repo,
    )
    return service, space_repo


async def test_bound_assistant_cannot_move_between_spaces() -> None:
    assistant_id = uuid4()
    target_space_id = uuid4()
    assistant = MagicMock(id=assistant_id)
    source_space = MagicMock()
    source_space.id = uuid4()
    source_space.tenant_id = TENANT_ID
    source_space.get_assistant.return_value = assistant
    target_space = MagicMock()
    target_space.tenant_id = TENANT_ID

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
        user=_user(),
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
    source_space.tenant_id = TENANT_ID
    source_space.get_assistant.return_value = assistant
    target_space = MagicMock()
    target_space.tenant_id = TENANT_ID

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
        user=_user(),
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


# ---------------------------------------------------------------------------
# Moves and links never cross a tenant boundary, whatever the space roles say
# ---------------------------------------------------------------------------


async def test_assistant_move_into_foreign_tenant_space_is_denied() -> None:
    source_space = _space()
    target_space = _space(tenant_id=OTHER_TENANT_ID)
    assistant = MagicMock(id=uuid4(), collections=[], websites=[])
    source_space.get_assistant.return_value = assistant
    service, space_repo = _service(source_space=source_space, target_space=target_space)

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id
        )

    service.skill_repo.lock_assistant_space_for_update.assert_not_awaited()
    target_space.add_assistant.assert_not_called()
    source_space.remove_assistant.assert_not_called()
    space_repo.update.assert_not_awaited()


async def test_assistant_move_out_of_foreign_tenant_space_is_denied() -> None:
    source_space = _space(tenant_id=OTHER_TENANT_ID)
    target_space = _space()
    assistant = MagicMock(id=uuid4(), collections=[], websites=[])
    source_space.get_assistant.return_value = assistant
    service, space_repo = _service(source_space=source_space, target_space=target_space)

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id
        )

    space_repo.update.assert_not_awaited()


async def test_assistant_move_revalidates_tenant_after_lock() -> None:
    """The locked re-read of the source is the authoritative one; if it now
    resolves to a foreign-tenant space the move stops before any mutation."""
    source_space = _space()
    target_space = _space()
    locked_source = _space(tenant_id=OTHER_TENANT_ID)
    assistant = MagicMock(id=uuid4(), collections=[], websites=[])
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
    space_repo.update.assert_not_awaited()


async def test_assistant_move_with_foreign_tenant_attachment_is_denied() -> None:
    source_space = _space()
    target_space = _space()
    foreign_collection = MagicMock(id=uuid4(), tenant_id=OTHER_TENANT_ID)
    assistant = MagicMock(id=uuid4(), collections=[foreign_collection], websites=[])
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
    space_repo.update.assert_not_awaited()


async def test_assistant_move_within_tenant_succeeds() -> None:
    source_space = _space()
    target_space = _space()
    collection = MagicMock(id=uuid4(), tenant_id=TENANT_ID)
    assistant = MagicMock(id=uuid4(), collections=[collection], websites=[])
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
    source_space.remove_assistant.assert_called_once_with(assistant)
    group_service.import_group_to_space.assert_awaited_once()
    assert space_repo.update.await_count == 2


async def test_caller_from_another_tenant_cannot_move_between_two_foreign_spaces() -> (
    None
):
    source_space = _space(tenant_id=OTHER_TENANT_ID)
    target_space = _space(tenant_id=OTHER_TENANT_ID)
    assistant = MagicMock(id=uuid4(), collections=[], websites=[])
    source_space.get_assistant.return_value = assistant
    service, space_repo = _service(
        source_space=source_space, target_space=target_space, user=_user(TENANT_ID)
    )

    with pytest.raises(UnauthorizedException, match="between tenants"):
        await service.move_assistant_to_space(
            assistant_id=assistant.id, space_id=target_space.id
        )

    space_repo.update.assert_not_awaited()


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


@pytest.mark.parametrize("method", ["link_website_to_space", "move_website_to_space"])
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
    space_repo.update.assert_not_awaited()


async def test_website_link_within_tenant_succeeds() -> None:
    source_space = _space()
    target_space = _space()
    website = MagicMock(id=uuid4(), tenant_id=TENANT_ID)
    source_space.get_website.return_value = website
    service, space_repo = _service(source_space=source_space, target_space=target_space)

    await service.link_website_to_space(website_id=website.id, space_id=target_space.id)

    target_space.add_website.assert_called_once_with(website)
    space_repo.update.assert_awaited_once_with(space=target_space)

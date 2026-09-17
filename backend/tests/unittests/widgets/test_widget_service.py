from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.widgets.application.widget_service import WidgetService
from eneo.widgets.domain.widget import Widget, WidgetStatus


class _InMemoryRepo:
    def __init__(self) -> None:
        self.rows: dict = {}

    async def add(self, widget: Widget) -> Widget:
        widget = widget.model_copy(update={"id": uuid4()})
        self.rows[widget.id] = widget
        return widget

    async def get(self, widget_id):
        return self.rows.get(widget_id)

    async def get_by_public_id(self, public_id):
        return next((w for w in self.rows.values() if w.public_id == public_id), None)

    async def list_by_space(self, space_id):
        return [w for w in self.rows.values() if w.space_id == space_id]

    async def update(self, widget: Widget) -> Widget:
        self.rows[widget.id] = widget
        return widget


def _user(*permissions: Permission, widget_policy=None):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=set(permissions),
        tenant=SimpleNamespace(widget_policy=widget_policy or {}),
    )


def _space(space_id, assistant, *, can_edit=True):
    space = MagicMock()
    space.id = space_id
    space.get_assistant = MagicMock(
        side_effect=lambda aid: assistant
        if aid == assistant.id
        else (_ for _ in ()).throw(NotFoundException())
    )
    return space, can_edit


def _service(user, space, can_edit=True, repo=None):
    space_service = MagicMock()
    space_service.get_space = AsyncMock(return_value=space)
    space_service.repo.one = AsyncMock(return_value=space)
    actor = MagicMock()
    actor.can_edit_assistants = MagicMock(return_value=can_edit)
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space = MagicMock(return_value=actor)
    tenant_service = MagicMock()
    tenant_service.update_widget_policy = AsyncMock(
        side_effect=lambda tenant_id, policy: SimpleNamespace(widget_policy=policy)
    )
    return WidgetService(
        user=user,
        repo=repo or _InMemoryRepo(),
        space_service=space_service,
        actor_manager=actor_manager,
        tenant_service=tenant_service,
    )


@pytest.fixture
def assistant():
    return SimpleNamespace(id=uuid4(), published=True)


async def test_create_requires_widgets_permission_and_space_edit_rights(assistant):
    space, _ = _space(uuid4(), assistant)

    with pytest.raises(UnauthorizedException):
        await _service(_user(), space).create_widget(
            space_id=space.id, target_id=assistant.id, name="w"
        )

    with pytest.raises(UnauthorizedException):
        await _service(_user(Permission.WIDGETS), space, can_edit=False).create_widget(
            space_id=space.id, target_id=assistant.id, name="w"
        )

    view = await _service(_user(Permission.WIDGETS), space).create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    assert view.widget.status == WidgetStatus.DRAFT
    assert view.activation_blockers == ["allowed_origins_empty"]


async def test_create_rejects_assistant_outside_space(assistant):
    space, _ = _space(uuid4(), assistant)
    with pytest.raises(NotFoundException):
        await _service(_user(Permission.WIDGETS), space).create_widget(
            space_id=space.id, target_id=uuid4(), name="w"
        )


async def test_widgets_are_tenant_isolated(assistant):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    owner = _user(Permission.WIDGETS)
    view = await _service(owner, space, repo=repo).create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    other = _service(_user(Permission.WIDGETS, Permission.ADMIN), space, repo=repo)
    with pytest.raises(NotFoundException):
        await other.get_widget(view.widget.id)


async def test_activation_requires_admin_and_reports_blockers(assistant):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    editor = _service(_user(Permission.WIDGETS), space, repo=repo)
    view = await editor.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )

    with pytest.raises(UnauthorizedException):
        await editor.activate_widget(view.widget.id)

    admin_user = _user(Permission.WIDGETS, Permission.ADMIN)
    admin_user.tenant_id = editor.user.tenant_id
    admin = _service(admin_user, space, repo=repo)
    with pytest.raises(BadRequestException) as exc:
        await admin.activate_widget(view.widget.id)
    assert "allowed_origins_empty" in str(exc.value)

    await admin.update_widget(
        view.widget.id,
        {
            "revision": view.widget.revision,
            "allowed_origins": ["https://www.kommun.se"],
        },
    )
    activated = await admin.activate_widget(view.widget.id)
    assert activated.widget.status == WidgetStatus.ACTIVE
    assert activated.activation_blockers == []


async def test_reactivating_an_active_widget_is_rejected(assistant):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    service = _service(_user(Permission.WIDGETS, Permission.ADMIN), space, repo=repo)
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="a"
    )
    await service.update_widget(
        view.widget.id,
        {"revision": view.widget.revision, "allowed_origins": ["https://a.se"]},
    )
    await service.activate_widget(view.widget.id)
    with pytest.raises(BadRequestException):
        await service.activate_widget(view.widget.id)


async def test_update_enforces_tenant_policy(assistant):
    space, _ = _space(uuid4(), assistant)
    user = _user(Permission.WIDGETS, widget_policy={"max_daily_token_budget": 50_000})
    service = _service(user, space)
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    with pytest.raises(BadRequestException) as exc:
        await service.update_widget(
            view.widget.id,
            {
                "revision": view.widget.revision,
                "limits": {"daily_token_budget": 100_000},
            },
        )
    assert "daily_token_budget_exceeds_policy" in str(exc.value)


async def test_admin_runs_the_lifecycle_outside_their_own_spaces(assistant):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    admin_user = _user(Permission.WIDGETS, Permission.ADMIN)
    editor = _service(admin_user, space, repo=repo)
    view = await editor.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    await editor.update_widget(
        view.widget.id,
        {"revision": view.widget.revision, "allowed_origins": ["https://a.se"]},
    )

    outsider = _service(admin_user, space, repo=repo)
    outsider.space_service.get_space = AsyncMock(
        side_effect=UnauthorizedException("not a member")
    )
    activated = await outsider.activate_widget(view.widget.id)
    assert activated.widget.status == WidgetStatus.ACTIVE
    paused = await outsider.pause_widget(view.widget.id)
    assert paused.widget.status == WidgetStatus.PAUSED
    archived = await outsider.archive_widget(view.widget.id)
    assert archived.widget.status == WidgetStatus.ARCHIVED


async def test_pause_is_allowed_for_editors_and_admins(assistant):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    admin_user = _user(Permission.WIDGETS, Permission.ADMIN)
    admin = _service(admin_user, space, repo=repo)
    view = await admin.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    await admin.update_widget(
        view.widget.id,
        {"revision": view.widget.revision, "allowed_origins": ["https://a.se"]},
    )
    await admin.activate_widget(view.widget.id)

    editor_user = _user(Permission.WIDGETS)
    editor_user.tenant_id = admin_user.tenant_id
    paused = await _service(editor_user, space, repo=repo).pause_widget(view.widget.id)
    assert paused.widget.status == WidgetStatus.PAUSED
    # 1 from the allowed_origins update, 1 from the pause.
    assert paused.widget.token_generation == 2

    viewer_user = _user()
    viewer_user.tenant_id = admin_user.tenant_id
    await admin.activate_widget(view.widget.id)
    with pytest.raises(UnauthorizedException):
        await _service(viewer_user, space, repo=repo).pause_widget(view.widget.id)


async def test_policy_update_merges_and_validates(assistant):
    space, _ = _space(uuid4(), assistant)
    service = _service(
        _user(Permission.ADMIN, widget_policy={"max_retention_days": 90}), space
    )
    policy = await service.update_policy({"max_daily_token_budget": 10_000})
    assert policy.max_retention_days == 90
    assert policy.max_daily_token_budget == 10_000

    with pytest.raises(BadRequestException):
        await service.update_policy({"min_retention_days": 400})

    with pytest.raises(UnauthorizedException):
        _service(_user(Permission.WIDGETS), space).read_policy()

    with pytest.raises(UnauthorizedException):
        await _service(_user(Permission.WIDGETS), space).update_policy({})

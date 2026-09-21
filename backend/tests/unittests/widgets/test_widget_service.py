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
        self.locked_reads: list = []

    async def add(self, widget: Widget) -> Widget:
        widget = widget.model_copy(update={"id": uuid4()})
        self.rows[widget.id] = widget
        return widget

    async def get(self, widget_id, *, for_update=False):
        if for_update:
            self.locked_reads.append(widget_id)
        return self.rows.get(widget_id)

    async def get_by_public_id(self, public_id):
        return next((w for w in self.rows.values() if w.public_id == public_id), None)

    async def list_by_space(self, space_id):
        return [w for w in self.rows.values() if w.space_id == space_id]

    async def list_by_template(self, template_id, *, include_archived=False):
        return [
            w
            for w in self.rows.values()
            if w.template_id == template_id
            and (include_archived or w.status != WidgetStatus.ARCHIVED)
        ]

    async def count_by_template(self, tenant_id):
        counts: dict = {}
        for w in self.rows.values():
            if w.tenant_id == tenant_id and w.template_id is not None:
                counts[w.template_id] = counts.get(w.template_id, 0) + 1
        return counts

    async def is_target_published(self, widget):
        return True

    async def update(self, widget: Widget, *, check_revision=True, only=None) -> Widget:
        self.last_update = {"check_revision": check_revision, "only": only}
        self.rows[widget.id] = widget
        return widget


class _InMemoryTemplateRepo:
    def __init__(self) -> None:
        self.rows: dict = {}
        self.locked_reads: list = []

    async def add(self, template):
        template = template.model_copy(update={"id": uuid4()})
        self.rows[template.id] = template
        return template

    async def get(self, template_id, *, for_update=False):
        if for_update:
            self.locked_reads.append(template_id)
        return self.rows.get(template_id)

    async def list_by_tenant(self, tenant_id):
        return [t for t in self.rows.values() if t.tenant_id == tenant_id]

    async def update(self, template):
        self.rows[template.id] = template
        return template

    async def delete(self, template_id):
        self.rows.pop(template_id, None)

    async def clear_default(self, tenant_id):
        return None


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


def _service(user, space, can_edit=True, repo=None, template_repo=None):
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
        template_repo=template_repo or _InMemoryTemplateRepo(),
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
    assert repo.locked_reads == []
    paused = await outsider.pause_widget(view.widget.id)
    assert paused.widget.status == WidgetStatus.PAUSED
    archived = await outsider.archive_widget(view.widget.id)
    assert archived.widget.status == WidgetStatus.ARCHIVED
    # Both write past the revision check, so both decide on a locked row.
    assert repo.locked_reads == [view.widget.id, view.widget.id]


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

    # The kill switch bypasses the revision check and writes lifecycle columns
    # only, so it can neither lose to an autosave nor overwrite one.
    assert repo.last_update == {
        "check_revision": False,
        "only": frozenset({"status", "paused_at", "token_generation"}),
    }

    viewer_user = _user()
    viewer_user.tenant_id = admin_user.tenant_id
    await admin.activate_widget(view.widget.id)
    with pytest.raises(UnauthorizedException):
        await _service(viewer_user, space, repo=repo).pause_widget(view.widget.id)


async def test_reading_widget_configuration_needs_the_widgets_permission(assistant):
    """Origins, limits and privacy are for widget managers, not every member."""
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    owner = _user(Permission.WIDGETS)
    view = await _service(owner, space, repo=repo).create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )

    member = _user()
    member.tenant_id = owner.tenant_id
    reader = _service(member, space, can_edit=False, repo=repo)
    with pytest.raises(UnauthorizedException):
        await reader.get_widget(view.widget.id)
    with pytest.raises(UnauthorizedException):
        await reader.list_widgets(space.id)

    admin = _user(Permission.ADMIN)
    admin.tenant_id = owner.tenant_id
    assert (
        await _service(admin, space, can_edit=False, repo=repo).get_widget(
            view.widget.id
        )
    ).widget.id == view.widget.id

    with pytest.raises(BadRequestException):
        await _service(owner, space, repo=repo).update_widget(
            view.widget.id, {"name": "no revision"}
        )


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


async def _linked_setup(assistant):
    from eneo.widgets.domain.widget import WidgetTheme
    from eneo.widgets.domain.widget_template import TemplateLockGroup, WidgetTemplate

    user = _user(Permission.WIDGETS)
    space, _ = _space(uuid4(), assistant)
    template_repo = _InMemoryTemplateRepo()
    template = WidgetTemplate.create(tenant_id=user.tenant_id, name="Kommunblå")
    template.theme = WidgetTheme(primary_color="#123456", radius=4)
    template.texts = template.texts.model_copy(
        update={"title": "Fråga oss", "footer_text": "Personuppgifter hanteras…"}
    )
    template.locked_groups = [
        TemplateLockGroup.APPEARANCE,
        TemplateLockGroup.LEGAL_TEXTS,
    ]
    template.publish(by=user.id)
    template = await template_repo.add(template)
    service = _service(user, space, template_repo=template_repo)
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="w", template_id=template.id
    )
    # The release is read under lock so a publication cannot slip in between.
    assert template_repo.locked_reads == [template.id]
    return service, view, template


async def test_linked_widget_copies_the_template_and_reports_the_link(assistant):
    service, view, template = await _linked_setup(assistant)
    widget = view.widget
    assert widget.template_id == template.id
    assert widget.theme.primary_color == "#123456"
    assert widget.texts.title == "Fråga oss"  # unlocked groups are copied once
    assert widget.texts.footer_text == "Personuppgifter hanteras…"
    assert view.template is not None and view.template.locked_groups == [
        "appearance",
        "legal_texts",
    ]
    fetched = await service.get_widget(widget.id)
    assert fetched.template is not None and fetched.template.id == template.id
    listed = await service.list_widgets(widget.space_id)
    assert listed[0].template is not None and listed[0].template.id == template.id


async def test_update_rejects_locked_parts_and_accepts_the_rest(assistant):
    from eneo.widgets.domain.exceptions import WidgetFieldLockedError

    service, view, template = await _linked_setup(assistant)
    widget = view.widget
    texts = widget.texts.model_dump()

    with pytest.raises(WidgetFieldLockedError) as locked:
        await service.update_widget(
            widget.id,
            {
                "revision": widget.revision,
                "theme": {**widget.theme.model_dump(), "primary_color": "#000000"},
            },
        )
    assert locked.value.fields == ["theme"]
    assert locked.value.code == "field_locked_by_template"

    with pytest.raises(WidgetFieldLockedError) as locked:
        await service.update_widget(
            widget.id,
            {"revision": widget.revision, "texts": {**texts, "footer_text": "Egen"}},
        )
    assert locked.value.fields == ["texts.footer_text"]

    # The texts group is sent whole: unchanged locked values pass and the
    # unlocked title (wording) is editable.
    updated = await service.update_widget(
        widget.id,
        {
            "revision": widget.revision,
            "texts": {**texts, "title": "Egen titel"},
            "theme": widget.theme.model_dump(),
            "language": widget.language.value,
        },
    )
    assert updated.widget.texts.title == "Egen titel"
    assert updated.widget.texts.footer_text == "Personuppgifter hanteras…"


async def test_detaching_keeps_values_and_frees_every_part(assistant):
    service, view, template = await _linked_setup(assistant)
    widget = view.widget

    detached = await service.detach_template(widget.id, revision=widget.revision)
    assert detached.widget.template_id is None
    assert detached.template is None
    assert detached.widget.theme.primary_color == "#123456"

    updated = await service.update_widget(
        detached.widget.id,
        {
            "revision": detached.widget.revision,
            "theme": {**widget.theme.model_dump(), "primary_color": "#000000"},
        },
    )
    assert updated.widget.theme.primary_color == "#000000"

    relinked = await service.link_template(
        updated.widget.id, template.id, revision=updated.widget.revision
    )
    assert relinked.widget.template_id == template.id
    assert relinked.widget.theme.primary_color == "#123456"
    assert service.template_repo.locked_reads == [template.id, template.id]


async def test_widgets_follow_only_published_templates(assistant):
    from eneo.widgets.domain.exceptions import WidgetTemplateNotPublishedError
    from eneo.widgets.domain.widget import WidgetTheme
    from eneo.widgets.domain.widget_template import WidgetTemplate

    user = _user(Permission.WIDGETS)
    space, _ = _space(uuid4(), assistant)
    template_repo = _InMemoryTemplateRepo()
    draft = await template_repo.add(
        WidgetTemplate.create(tenant_id=user.tenant_id, name="Utkast")
    )
    service = _service(user, space, template_repo=template_repo)

    with pytest.raises(WidgetTemplateNotPublishedError):
        await service.create_widget(
            space_id=space.id, target_id=assistant.id, name="w", template_id=draft.id
        )

    # Linking takes the published release, not the draft being edited.
    draft.theme = WidgetTheme(primary_color="#123456")
    draft.publish(by=user.id)
    draft.theme = WidgetTheme(primary_color="#000000")
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="w", template_id=draft.id
    )
    assert view.widget.theme.primary_color == "#123456"

    # A template of another organisation cannot be followed, whatever its id.
    foreign = await template_repo.add(
        WidgetTemplate.create(tenant_id=uuid4(), name="Främmande")
    )
    with pytest.raises(NotFoundException):
        await service.create_widget(
            space_id=space.id, target_id=assistant.id, name="w", template_id=foreign.id
        )

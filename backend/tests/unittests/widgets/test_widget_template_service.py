from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.widgets.application.widget_template_service import WidgetTemplateService
from eneo.widgets.domain.exceptions import WidgetTemplateInUseError
from eneo.widgets.domain.widget import Widget, WidgetLanguage, WidgetStatus, WidgetTheme
from eneo.widgets.domain.widget_template import (
    ALL_LOCK_GROUPS,
    TemplateLockGroup,
    WidgetTemplate,
)


class _InMemoryRepo:
    def __init__(self) -> None:
        self.rows: dict = {}

    async def add(self, template):
        template = template.model_copy(update={"id": uuid4()})
        self.rows[template.id] = template
        return template

    async def get(self, template_id):
        return self.rows.get(template_id)

    async def list_by_tenant(self, tenant_id):
        return sorted(
            (t for t in self.rows.values() if t.tenant_id == tenant_id),
            key=lambda t: (not t.is_default, t.name),
        )

    async def update(self, template):
        self.rows[template.id] = template
        return template

    async def delete(self, template_id):
        self.rows.pop(template_id, None)

    async def clear_default(self, tenant_id):
        for key, t in list(self.rows.items()):
            if t.tenant_id == tenant_id and t.is_default:
                self.rows[key] = t.model_copy(update={"is_default": False})


class _InMemoryWidgetRepo:
    def __init__(self) -> None:
        self.rows: dict = {}
        self.updates = 0

    async def add(self, widget):
        widget = widget.model_copy(update={"id": uuid4()})
        self.rows[widget.id] = widget
        return widget

    async def get(self, widget_id):
        return self.rows.get(widget_id)

    async def list_by_template(self, template_id):
        return [w for w in self.rows.values() if w.template_id == template_id]

    async def count_by_template(self, tenant_id):
        counts: dict = {}
        for w in self.rows.values():
            if w.tenant_id == tenant_id and w.template_id is not None:
                counts[w.template_id] = counts.get(w.template_id, 0) + 1
        return counts

    async def update(self, widget):
        self.updates += 1
        widget = widget.model_copy(update={"revision": widget.revision + 1})
        self.rows[widget.id] = widget
        return widget


def _user(*permissions: Permission, tenant_id=None):
    return SimpleNamespace(
        id=uuid4(), tenant_id=tenant_id or uuid4(), permissions=set(permissions)
    )


def _template_service(user, repo=None, widget_repo=None):
    return WidgetTemplateService(
        user, repo or _InMemoryRepo(), widget_repo or _InMemoryWidgetRepo()
    )


async def test_admin_creates_updates_and_swaps_default():
    repo = _InMemoryRepo()
    admin = _user(Permission.ADMIN)
    service = _template_service(admin, repo)

    first = await service.create_template(name="Kommunblå", is_default=True)
    second = await service.create_template(name="Sekundär", language=WidgetLanguage.EN)
    assert first.is_default is True
    assert second.texts.subtitle != first.texts.subtitle  # english default

    updated = (
        await service.update_template(
            second.id,
            {
                "is_default": True,
                "theme": WidgetTheme(primary_color="#123456"),
                "description": "  house   style ",
            },
        )
    ).template
    assert updated.is_default is True
    assert updated.theme.primary_color == "#123456"
    assert updated.description == "house style"
    assert (await repo.get(first.id)).is_default is False

    listed = await service.list_templates()
    assert [t.name for t in listed] == ["Sekundär", "Kommunblå"]

    with pytest.raises(BadRequestException):
        await service.update_template(second.id, {"name": "   "})

    deleted = await service.delete_template(first.id)
    assert deleted.id == first.id
    with pytest.raises(NotFoundException):
        await service.get_template(first.id)


async def test_editors_read_but_never_write():
    repo = _InMemoryRepo()
    tenant = uuid4()
    admin = _template_service(_user(Permission.ADMIN, tenant_id=tenant), repo)
    created = await admin.create_template(name="Mall")

    editor = _template_service(_user(Permission.WIDGETS, tenant_id=tenant), repo)
    assert [t.id for t in await editor.list_templates()] == [created.id]
    assert (await editor.get_template(created.id)).name == "Mall"
    with pytest.raises(UnauthorizedException):
        await editor.create_template(name="Nej")
    with pytest.raises(UnauthorizedException):
        await editor.update_template(created.id, {"name": "Nej"})
    with pytest.raises(UnauthorizedException):
        await editor.delete_template(created.id)

    nobody = _template_service(_user(tenant_id=tenant), repo)
    with pytest.raises(UnauthorizedException):
        await nobody.list_templates()

    other_tenant = _template_service(_user(Permission.ADMIN), repo)
    with pytest.raises(NotFoundException):
        await other_tenant.get_template(created.id)


def _widget_for(template, **texts):
    widget = Widget.create(
        tenant_id=template.tenant_id, space_id=uuid4(), target_id=uuid4(), name="w"
    )
    widget.texts = widget.texts.model_copy(
        update={"suggested_questions": ["Egen fråga"], **texts}
    )
    return widget


def _house_style():
    template = WidgetTemplate.create(tenant_id=uuid4(), name="Mall")
    template.theme = WidgetTheme(
        primary_color="#ABCDEF",
        radius=4,
        header_color="#112233",
        logo_url="https://x.se/l.png",
    )
    template.texts = template.texts.model_copy(
        update={
            "title": "Fråga oss",
            "footer_text": "Läs om personuppgifter",
            "suggested_questions": ["Mallfråga"],
        }
    )
    return template


def test_new_templates_lock_appearance_and_language_by_default():
    template = WidgetTemplate.create(tenant_id=uuid4(), name="Mall")
    assert template.locked_groups == [
        TemplateLockGroup.APPEARANCE,
        TemplateLockGroup.LANGUAGE,
    ]
    # Stored in a canonical order without duplicates, whatever the client sent.
    template.locked_groups = [
        TemplateLockGroup.WORDING,
        TemplateLockGroup.APPEARANCE,
        TemplateLockGroup.WORDING,
    ]
    assert template.locked_groups == [
        TemplateLockGroup.APPEARANCE,
        TemplateLockGroup.WORDING,
    ]


def test_linking_copies_every_templated_part_once():
    template = _house_style()
    widget = _widget_for(template)

    assert template.project_onto(widget, ALL_LOCK_GROUPS) is True
    assert widget.theme.primary_color == "#ABCDEF"
    assert widget.theme.logo_url == "https://x.se/l.png"
    assert widget.texts.title == "Fråga oss"
    assert widget.texts.footer_text == "Läs om personuppgifter"
    # Suggested questions belong to the widget, not the template.
    assert widget.texts.suggested_questions == ["Egen fråga"]
    assert template.project_onto(widget, ALL_LOCK_GROUPS) is False


def test_projection_touches_only_the_given_groups():
    template = _house_style()
    widget = _widget_for(template, title="Egen titel")
    widget.theme = WidgetTheme(primary_color="#000000")

    changed = template.project_onto(widget, [TemplateLockGroup.APPEARANCE])
    assert changed is True
    assert widget.theme.primary_color == "#ABCDEF"
    assert widget.texts.title == "Egen titel"
    assert widget.texts.footer_text == ""


def test_locked_changes_names_only_locked_parts_that_differ():
    template = _house_style()
    template.locked_groups = [
        TemplateLockGroup.APPEARANCE,
        TemplateLockGroup.LEGAL_TEXTS,
    ]
    widget = _widget_for(template)
    template.project_onto(widget, ALL_LOCK_GROUPS)
    texts = widget.texts.model_dump()

    assert template.locked_changes(widget, {"texts": {**texts, "title": "Ny"}}) == []
    assert template.locked_changes(
        widget, {"texts": {**texts, "footer_text": "Ändrad", "subtitle": "Annan"}}
    ) == ["texts.subtitle", "texts.footer_text"]
    assert template.locked_changes(
        widget, {"theme": {**widget.theme.model_dump(), "radius": 20}}
    ) == ["theme"]
    assert template.locked_changes(widget, {"theme": widget.theme.model_dump()}) == []
    assert template.locked_changes(widget, {"language": "en"}) == []
    template.locked_groups = [TemplateLockGroup.LANGUAGE]
    assert template.locked_changes(widget, {"language": "en"}) == ["language"]


def test_locking_legal_texts_requires_a_disclosure():
    template = _house_style()
    template.locked_groups = [TemplateLockGroup.LEGAL_TEXTS]
    assert template.lock_violations() == []
    template.texts = template.texts.model_copy(update={"subtitle": ""})
    assert template.lock_violations() == ["subtitle_required_for_legal_texts_lock"]


async def test_saving_a_template_updates_the_widgets_that_follow_it():
    repo = _InMemoryRepo()
    widgets = _InMemoryWidgetRepo()
    admin = _user(Permission.ADMIN)
    service = _template_service(admin, repo, widgets)
    template = await service.create_template(name="Kommunblå")

    def follower(**overrides):
        widget = Widget.create(
            tenant_id=admin.tenant_id, space_id=uuid4(), target_id=uuid4(), name="w"
        )
        widget.template_id = template.id
        for key, value in overrides.items():
            setattr(widget, key, value)
        return widget

    linked = await widgets.add(follower())
    archived = await widgets.add(follower(status=WidgetStatus.ARCHIVED))
    stranger = await widgets.add(
        Widget.create(
            tenant_id=admin.tenant_id, space_id=uuid4(), target_id=uuid4(), name="s"
        )
    )

    result = await service.update_template(
        template.id,
        {
            "theme": WidgetTheme(primary_color="#123456"),
            "texts": template.texts.model_copy(update={"title": "Fråga oss"}),
        },
    )
    assert [w.id for w in result.synced_widgets] == [linked.id]
    synced = await widgets.get(linked.id)
    assert synced.theme.primary_color == "#123456"
    assert synced.revision == linked.revision + 1
    # Wording is not locked by default: the title stays the widget's own.
    assert synced.texts.title == ""
    assert (await widgets.get(archived.id)).theme.primary_color != "#123456"
    assert (await widgets.get(stranger.id)).theme.primary_color != "#123456"

    # Locking a further group writes it onto the followers at once.
    result = await service.update_template(
        template.id,
        {"locked_groups": [TemplateLockGroup.APPEARANCE, TemplateLockGroup.WORDING]},
    )
    assert (await widgets.get(linked.id)).texts.title == "Fråga oss"
    # A save that changes nothing on the followers reports none.
    result = await service.update_template(template.id, {"description": "x"})
    assert result.synced_widgets == []

    with pytest.raises(BadRequestException):
        await service.update_template(
            template.id,
            {
                "locked_groups": [TemplateLockGroup.LEGAL_TEXTS],
                "texts": template.texts.model_copy(update={"subtitle": ""}),
            },
        )

    counts = await service.linked_widget_counts()
    assert counts == {template.id: 2}
    with pytest.raises(WidgetTemplateInUseError) as in_use:
        await service.delete_template(template.id)
    assert in_use.value.linked_widgets == 2

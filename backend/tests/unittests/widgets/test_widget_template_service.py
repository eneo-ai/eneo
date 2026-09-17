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
from eneo.widgets.domain.widget import Widget, WidgetLanguage, WidgetTheme
from eneo.widgets.domain.widget_template import WidgetTemplate


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


def _user(*permissions: Permission, tenant_id=None):
    return SimpleNamespace(
        id=uuid4(), tenant_id=tenant_id or uuid4(), permissions=set(permissions)
    )


async def test_admin_creates_updates_and_swaps_default():
    repo = _InMemoryRepo()
    admin = _user(Permission.ADMIN)
    service = WidgetTemplateService(admin, repo)

    first = await service.create_template(name="Kommunblå", is_default=True)
    second = await service.create_template(name="Sekundär", language=WidgetLanguage.EN)
    assert first.is_default is True
    assert second.texts.subtitle != first.texts.subtitle  # english default

    updated = await service.update_template(
        second.id,
        {
            "is_default": True,
            "theme": WidgetTheme(primary_color="#123456"),
            "description": "  house   style ",
        },
    )
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
    admin = WidgetTemplateService(_user(Permission.ADMIN, tenant_id=tenant), repo)
    created = await admin.create_template(name="Mall")

    editor = WidgetTemplateService(_user(Permission.WIDGETS, tenant_id=tenant), repo)
    assert [t.id for t in await editor.list_templates()] == [created.id]
    assert (await editor.get_template(created.id)).name == "Mall"
    with pytest.raises(UnauthorizedException):
        await editor.create_template(name="Nej")
    with pytest.raises(UnauthorizedException):
        await editor.update_template(created.id, {"name": "Nej"})
    with pytest.raises(UnauthorizedException):
        await editor.delete_template(created.id)

    nobody = WidgetTemplateService(_user(tenant_id=tenant), repo)
    with pytest.raises(UnauthorizedException):
        await nobody.list_templates()

    other_tenant = WidgetTemplateService(_user(Permission.ADMIN), repo)
    with pytest.raises(NotFoundException):
        await other_tenant.get_template(created.id)


def test_template_copies_onto_a_widget_as_a_snapshot():
    template = WidgetTemplate.create(tenant_id=uuid4(), name="Mall")
    template.theme = WidgetTheme(
        primary_color="#ABCDEF",
        radius=4,
        header_color="#112233",
        logo_url="https://x.se/l.png",
    )
    template.texts = template.texts.model_copy(
        update={"title": "Fråga oss", "suggested_questions": ["Mallfråga"]}
    )

    widget = Widget.create(
        tenant_id=template.tenant_id, space_id=uuid4(), target_id=uuid4(), name="w"
    )
    widget.texts = widget.texts.model_copy(
        update={"suggested_questions": ["Egen fråga"]}
    )
    from eneo.widgets.application.widget_service import WidgetService

    WidgetService._copy_template(widget, template)
    assert widget.theme.primary_color == "#ABCDEF"
    assert widget.theme.header_color == "#112233"
    assert widget.theme.logo_url == "https://x.se/l.png"
    assert widget.texts.title == "Fråga oss"
    # Suggested questions belong to the widget, not the template.
    assert widget.texts.suggested_questions == ["Egen fråga"]

    template.theme.primary_color = "#000000"
    template.texts = template.texts.model_copy(update={"title": "Ändrad"})
    assert widget.theme.primary_color == "#ABCDEF"
    assert widget.texts.title == "Fråga oss"

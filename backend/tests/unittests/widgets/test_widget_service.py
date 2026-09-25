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
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.domain import MembershipSnapshot
from eneo.spaces.oversight.oversight_repo import SpaceMembership, SpaceSummaryRow
from eneo.widgets.application.widget_service import WidgetService
from eneo.widgets.domain.exceptions import (
    WidgetActivationRequestMissingError,
    WidgetPolicyViolationError,
    WidgetRevisionConflictError,
    WidgetServingBlockedError,
)
from eneo.widgets.domain.widget import (
    ACTIVATION_REVIEW_FIELDS,
    BotProtection,
    Widget,
    WidgetStatus,
)


class _InMemoryRepo:
    def __init__(self) -> None:
        self.rows: dict = {}
        self.locked_reads: list = []
        # assistant id -> the space it is in, as the row lock would read it
        self.target_spaces: dict = {}
        self.revoked: list = []
        self.target_published = True

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
        return self.target_published

    async def lock_target_space(self, target_id):
        return self.target_spaces.get(target_id)

    async def list_by_target(self, target_id):
        return [
            w
            for w in self.rows.values()
            if w.target_id == target_id and w.status != WidgetStatus.ARCHIVED
        ]

    async def revoke_tokens(self, tenant_id, *, bot_protection):
        self.revoked.append((tenant_id, bot_protection))
        return 0

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

    async def lock_default(self, tenant_id):
        return None

    async def clear_default(self, tenant_id):
        return None


class _FakeOversightRepo:
    """The slim reads the widget service uses for admins; roles per user id."""

    def __init__(self) -> None:
        self.roles: dict = {}
        self.kind = "shared"
        self.configs: list = []

    async def effective_role(self, tenant_id, space_id, *, user_id, group_ids):
        return self.roles.get(user_id)

    async def space_summary(self, tenant_id, space_id):
        return SpaceSummaryRow(
            id=space_id, name="Ytan", kind=self.kind, security_classification=None
        )

    async def assistant_configs(self, tenant_id, space_id, *, assistant_ids=None, **_):
        return self.configs

    async def knowledge_sources(self, tenant_id, space_id, *, source_ids=None, **_):
        return []

    async def membership(self, tenant_id, space_id, *, extra_group_ids=()):
        return SpaceMembership(
            users=[],
            groups=[],
            snapshot=MembershipSnapshot(direct={}, groups={}),
            manageable_by_group={},
        )


def _user(*permissions: Permission, widget_policy=None):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=set(permissions),
        user_groups_ids=set(),
        tenant=SimpleNamespace(widget_policy=widget_policy or {}),
    )


def _space(space_id, assistant, *, can_edit=True):
    space = MagicMock()
    space.id = space_id
    space.assistant_ids = [assistant.id]
    space.get_assistant = MagicMock(
        side_effect=lambda aid: assistant
        if aid == assistant.id
        else (_ for _ in ()).throw(NotFoundException())
    )
    return space, can_edit


def _service(
    user, space, can_edit=True, repo=None, template_repo=None, oversight_repo=None
):
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
    repo = repo or _InMemoryRepo()
    for assistant_id in space.assistant_ids:
        repo.target_spaces.setdefault(assistant_id, space.id)
    return WidgetService(
        user=user,
        repo=repo,
        template_repo=template_repo or _InMemoryTemplateRepo(),
        space_service=space_service,
        actor_manager=actor_manager,
        tenant_service=tenant_service,
        oversight_repo=oversight_repo or _FakeOversightRepo(),
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
    with pytest.raises(WidgetServingBlockedError) as exc:
        await admin.activate_widget(view.widget.id)
    assert exc.value.blockers == ["allowed_origins_empty"]
    assert exc.value.details() == {"blockers": ["allowed_origins_empty"]}

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
    with pytest.raises(WidgetPolicyViolationError) as exc:
        await service.update_widget(
            view.widget.id,
            {
                "revision": view.widget.revision,
                "limits": {"daily_token_budget": 100_000},
            },
        )
    assert exc.value.code == "widget_policy_violation"
    assert exc.value.details() == {"violations": ["daily_token_budget_exceeds_policy"]}


async def _requested_widget(assistant, repo):
    """A configured draft whose editor asked for activation."""
    space, _ = _space(uuid4(), assistant)
    editor_user = _user(Permission.WIDGETS)
    editor = _service(editor_user, space, repo=repo)
    view = await editor.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    await editor.update_widget(
        view.widget.id,
        {"revision": view.widget.revision, "allowed_origins": ["https://a.se"]},
    )
    requested, changed = await editor.request_activation(view.widget.id)
    assert changed
    return space, editor, requested.widget


async def test_admin_runs_the_lifecycle_without_loading_the_space(assistant):
    """Activate, send back, pause, archive and review never load the space
    aggregate: that loader skips the tenant filter, hydrates attachments and
    decrypts website credentials. The widget row is tenant-checked, and the
    target's published flag is read on its own."""
    repo = _InMemoryRepo()
    space, editor, widget = await _requested_widget(assistant, repo)
    admin_user = _user(Permission.ADMIN)
    admin_user.tenant_id = editor.user.tenant_id
    outsider = _service(admin_user, space, repo=repo)
    loader_used = AssertionError("the space aggregate was loaded")
    outsider.space_service.get_space = AsyncMock(side_effect=loader_used)
    outsider.space_service.repo.one = AsyncMock(side_effect=loader_used)
    repo.locked_reads.clear()

    review = await outsider.review_widget(widget.id)
    assert review.view.activation_blockers == []
    assert review.space.kind == "shared"
    assert review.viewer_role is None
    assert review.viewer_membership is not None

    declined = await outsider.decline_activation_request(
        widget.id, "Skriv en tydligare välkomsttext"
    )
    assert declined.widget.activation_declined_by_user_id == admin_user.id
    await editor.request_activation(widget.id)

    activated = await outsider.activate_widget(widget.id)
    assert activated.widget.status == WidgetStatus.ACTIVE
    paused = await outsider.pause_widget(widget.id)
    assert paused.widget.status == WidgetStatus.PAUSED
    archived = await outsider.archive_widget(widget.id)
    assert archived.widget.status == WidgetStatus.ARCHIVED
    # The send-back, the new request, pause and archive write past the
    # revision check, so each decides on a locked row; activate does not.
    assert repo.locked_reads == [widget.id, widget.id, widget.id, widget.id]
    outsider.space_service.get_space.assert_not_awaited()
    outsider.space_service.repo.one.assert_not_awaited()


async def test_admin_lifecycle_reads_blockers_from_the_published_flag(assistant):
    repo = _InMemoryRepo()
    space, editor, widget = await _requested_widget(assistant, repo)
    admin_user = _user(Permission.ADMIN)
    admin_user.tenant_id = editor.user.tenant_id
    admin = _service(admin_user, space, repo=repo)
    repo.target_published = False
    with pytest.raises(WidgetServingBlockedError) as exc:
        await admin.activate_widget(widget.id)
    assert exc.value.blockers == ["target_not_published"]
    review = await admin.review_widget(widget.id)
    assert review.view.activation_blockers == ["target_not_published"]


async def test_requesting_activation_needs_the_widgets_permission_and_edit_rights(
    assistant,
):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    owner = _user(Permission.WIDGETS)
    service = _service(owner, space, repo=repo)
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )

    member = _user()
    member.tenant_id = owner.tenant_id
    with pytest.raises(UnauthorizedException):
        await _service(member, space, repo=repo).request_activation(view.widget.id)
    outside_editor = _user(Permission.WIDGETS)
    outside_editor.tenant_id = owner.tenant_id
    with pytest.raises(UnauthorizedException):
        await _service(
            outside_editor, space, can_edit=False, repo=repo
        ).request_activation(view.widget.id)

    # The request reruns activation's checks and reuses its error codes.
    with pytest.raises(WidgetServingBlockedError) as blocked:
        await service.request_activation(view.widget.id)
    assert blocked.value.blockers == ["allowed_origins_empty"]
    await service.update_widget(
        view.widget.id,
        {"revision": view.widget.revision, "allowed_origins": ["https://a.se"]},
    )
    owner.tenant.widget_policy = {"max_daily_token_budget": 100_000}
    with pytest.raises(WidgetPolicyViolationError) as violation:
        await service.request_activation(view.widget.id)
    assert violation.value.violations == ["daily_token_budget_exceeds_policy"]
    owner.tenant.widget_policy = {}

    requested, changed = await service.request_activation(view.widget.id)
    assert changed
    assert requested.widget.activation_requested_by_user_id == owner.id
    assert requested.widget.activation_requested_at is not None
    assert requested.widget.status == WidgetStatus.DRAFT
    assert repo.last_update == {
        "check_revision": False,
        "only": ACTIVATION_REVIEW_FIELDS,
    }
    assert repo.locked_reads[-1] == view.widget.id

    # A repeated request is a no-op: nothing written, nothing to audit.
    del repo.last_update
    again, changed = await service.request_activation(view.widget.id)
    assert not changed
    assert not hasattr(repo, "last_update")
    assert again.widget.activation_requested_at == (
        requested.widget.activation_requested_at
    )


async def test_withdrawing_is_idempotent(assistant):
    repo = _InMemoryRepo()
    _, editor, widget = await _requested_widget(assistant, repo)
    withdrawn, changed = await editor.withdraw_activation_request(widget.id)
    assert changed
    assert withdrawn.widget.activation_requested_at is None
    assert repo.last_update["only"] == ACTIVATION_REVIEW_FIELDS
    _, changed = await editor.withdraw_activation_request(widget.id)
    assert not changed


async def test_only_tenant_admins_send_a_request_back(assistant):
    repo = _InMemoryRepo()
    space, editor, widget = await _requested_widget(assistant, repo)
    with pytest.raises(UnauthorizedException):
        await editor.decline_activation_request(widget.id, "Skriv om texterna")

    admin_user = _user(Permission.ADMIN)
    admin_user.tenant_id = editor.user.tenant_id
    admin = _service(admin_user, space, repo=repo)
    # The reason arrives normalised by AuditedReason and is stored as given.
    declined = await admin.decline_activation_request(
        widget.id, "Skriv en tydligare välkomsttext"
    )
    assert declined.widget.activation_decline_reason == (
        "Skriv en tydligare välkomsttext"
    )
    assert declined.widget.activation_requested_at is None
    assert declined.settled_request is not None
    assert declined.settled_request.requested_by_user_id == editor.user.id
    assert repo.last_update["only"] == ACTIVATION_REVIEW_FIELDS

    with pytest.raises(WidgetActivationRequestMissingError):
        await admin.decline_activation_request(widget.id, "Skriv om texterna")

    # Asking again clears the send-back.
    again, _ = await editor.request_activation(widget.id)
    assert again.widget.activation_declined_at is None
    assert again.widget.activation_decline_reason is None


async def test_activation_is_pinned_to_the_reviewed_revision(assistant):
    repo = _InMemoryRepo()
    space, editor, widget = await _requested_widget(assistant, repo)
    admin_user = _user(Permission.ADMIN)
    admin_user.tenant_id = editor.user.tenant_id
    admin = _service(admin_user, space, repo=repo)

    with pytest.raises(WidgetRevisionConflictError):
        await admin.activate_widget(widget.id, revision=widget.revision - 1)
    assert repo.rows[widget.id].status == WidgetStatus.DRAFT

    activated = await admin.activate_widget(widget.id, revision=widget.revision)
    assert activated.widget.status == WidgetStatus.ACTIVE
    # The request it settled is kept for the audit entry, and cleared.
    assert activated.settled_request is not None
    assert activated.settled_request.requested_by_user_id == editor.user.id
    assert activated.widget.activation_requested_at is None


async def test_preview_tokens_follow_the_space_role(assistant):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    oversight = _FakeOversightRepo()
    editor_user = _user(Permission.WIDGETS)
    editor = _service(editor_user, space, repo=repo, oversight_repo=oversight)
    view = await editor.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    widget_id = view.widget.id

    def service_for(user):
        user.tenant_id = editor_user.tenant_id
        return _service(user, space, repo=repo, oversight_repo=oversight)

    # Editors test drafts, also of an unpublished assistant, as before.
    repo.target_published = False
    oversight.roles[editor_user.id] = SpaceRoleValue.EDITOR
    token, expires_in, public_id = await editor.preview_token(widget_id)
    assert token and expires_in > 0 and public_id == view.widget.public_id

    # A tenant admin who is a member tests only a published assistant.
    member_admin = _user(Permission.ADMIN)
    oversight.roles[member_admin.id] = SpaceRoleValue.VIEWER
    with pytest.raises(WidgetServingBlockedError) as blocked:
        await service_for(member_admin).preview_token(widget_id)
    assert blocked.value.blockers == ["target_not_published"]
    repo.target_published = True
    await service_for(member_admin).preview_token(widget_id)

    # Answers come from the space's knowledge: a non-member admin never
    # gets a token, with or without the widgets permission.
    with pytest.raises(UnauthorizedException):
        await service_for(_user(Permission.ADMIN)).preview_token(widget_id)
    with pytest.raises(UnauthorizedException):
        await service_for(_user(Permission.ADMIN, Permission.WIDGETS)).preview_token(
            widget_id
        )
    # A viewer without the admin permission gets none either.
    viewer = _user(Permission.WIDGETS)
    oversight.roles[viewer.id] = SpaceRoleValue.VIEWER
    with pytest.raises(UnauthorizedException):
        await service_for(viewer).preview_token(widget_id)


async def test_archived_widgets_cannot_be_previewed(assistant):
    space, _ = _space(uuid4(), assistant)
    oversight = _FakeOversightRepo()
    user = _user(Permission.WIDGETS, Permission.ADMIN)
    service = _service(user, space, oversight_repo=oversight)
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    await service.archive_widget(view.widget.id)
    oversight.roles[user.id] = SpaceRoleValue.ADMIN
    with pytest.raises(BadRequestException):
        await service.preview_token(view.widget.id)


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
    # only, so it can neither lose to an autosave nor overwrite one. The
    # activation review columns ride along so archive persists their clear.
    assert repo.last_update == {
        "check_revision": False,
        "only": frozenset(
            {
                "status",
                "paused_at",
                "token_generation",
                "activation_requested_at",
                "activation_requested_by_user_id",
                "activation_declined_at",
                "activation_declined_by_user_id",
                "activation_decline_reason",
            }
        ),
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

    # Editors read the policy so they can hold their fields to it.
    editor = _service(
        _user(Permission.WIDGETS, widget_policy={"max_retention_days": 90}), space
    )
    assert editor.read_policy().max_retention_days == 90
    with pytest.raises(UnauthorizedException):
        _service(_user(), space).read_policy()

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


async def _serving_widget(assistant, *, widget_policy=None):
    space, _ = _space(uuid4(), assistant)
    user = _user(Permission.WIDGETS, Permission.ADMIN, widget_policy=widget_policy)
    service = _service(user, space)
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    await service.update_widget(
        view.widget.id,
        {"revision": view.widget.revision, "allowed_origins": ["https://a.se"]},
    )
    return service, (await service.activate_widget(view.widget.id)).widget


@pytest.mark.parametrize(
    ("change", "blocker"),
    [
        (
            lambda w: {"texts": {**w.texts.model_dump(), "subtitle": ""}},
            "subtitle_empty",
        ),
        (lambda w: {"allowed_origins": []}, "allowed_origins_empty"),
    ],
)
async def test_an_active_widget_cannot_be_edited_out_of_serving(
    assistant, change, blocker
):
    service, widget = await _serving_widget(assistant)
    with pytest.raises(WidgetServingBlockedError) as exc:
        await service.update_widget(
            widget.id, {"revision": widget.revision, **change(widget)}
        )
    assert exc.value.code == "widget_serving_blocked"
    assert exc.value.blockers == [blocker]

    # A draft may pass through the same state on its way to activation.
    space, _ = _space(uuid4(), assistant)
    draft_service = _service(_user(Permission.WIDGETS), space)
    draft = (
        await draft_service.create_widget(
            space_id=space.id, target_id=assistant.id, name="d"
        )
    ).widget
    view = await draft_service.update_widget(
        draft.id, {"revision": draft.revision, **change(draft)}
    )
    assert blocker in view.activation_blockers


async def test_linking_an_active_widget_to_a_release_without_disclosure_is_refused(
    assistant,
):
    from eneo.widgets.domain.widget_template import TemplateLockGroup, WidgetTemplate

    service, widget = await _serving_widget(assistant)
    template = WidgetTemplate.create(tenant_id=service.user.tenant_id, name="Tyst")
    template.texts = template.texts.model_copy(update={"subtitle": ""})
    template.locked_groups = [TemplateLockGroup.APPEARANCE]
    template.publish(by=service.user.id)
    template = await service.template_repo.add(template)

    with pytest.raises(WidgetServingBlockedError) as exc:
        await service.link_template(widget.id, template.id, revision=widget.revision)
    assert exc.value.blockers == ["subtitle_empty"]


async def test_a_tightened_policy_holds_edits_to_the_settings_they_change(assistant):
    service, widget = await _serving_widget(assistant)
    assert widget.limits.daily_token_budget == 500_000
    service.user.tenant.widget_policy = {"max_daily_token_budget": 100_000}

    renamed = await service.update_widget(
        widget.id, {"revision": widget.revision, "name": "Nytt namn"}
    )
    assert renamed.widget.name == "Nytt namn"
    assert renamed.activation_blockers == ["daily_token_budget_exceeds_policy"]

    limits = widget.limits.model_dump()
    with pytest.raises(WidgetPolicyViolationError) as exc:
        await service.update_widget(
            widget.id,
            {
                "revision": widget.revision,
                "limits": {**limits, "daily_token_budget": 400_000},
            },
        )
    assert exc.value.violations == ["daily_token_budget_exceeds_policy"]

    compliant = await service.update_widget(
        widget.id,
        {
            "revision": widget.revision,
            "limits": {**limits, "daily_token_budget": 100_000},
        },
    )
    assert compliant.activation_blockers == []


async def test_activation_reports_policy_violations_as_structured_codes(assistant):
    space, _ = _space(uuid4(), assistant)
    user = _user(
        Permission.WIDGETS,
        Permission.ADMIN,
        widget_policy={"allow_bot_protection_none": True},
    )
    service = _service(user, space)
    view = await service.create_widget(
        space_id=space.id, target_id=assistant.id, name="w"
    )
    await service.update_widget(
        view.widget.id,
        {
            "revision": view.widget.revision,
            "allowed_origins": ["https://a.se"],
            "bot_protection": "none",
        },
    )
    user.tenant.widget_policy = {"allow_bot_protection_none": False}
    with pytest.raises(WidgetPolicyViolationError) as exc:
        await service.activate_widget(view.widget.id)
    assert exc.value.details() == {"violations": ["bot_protection_none_not_allowed"]}


async def test_forbidding_bot_protection_none_revokes_tokens_minted_without_it(
    assistant,
):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    user = _user(Permission.ADMIN, widget_policy={"allow_bot_protection_none": True})
    service = _service(user, space, repo=repo)

    await service.update_policy({"max_daily_token_budget": 10_000})
    await service.update_policy({"allow_bot_protection_none": True})
    assert repo.revoked == []

    await service.update_policy({"allow_bot_protection_none": False})
    assert repo.revoked == [(user.tenant_id, BotProtection.NONE)]


async def test_create_refuses_an_assistant_that_left_the_space_meanwhile(assistant):
    space, _ = _space(uuid4(), assistant)
    repo = _InMemoryRepo()
    service = _service(_user(Permission.WIDGETS), space, repo=repo)
    repo.target_spaces[assistant.id] = uuid4()
    with pytest.raises(NotFoundException):
        await service.create_widget(space_id=space.id, target_id=assistant.id, name="w")
    assert repo.rows == {}

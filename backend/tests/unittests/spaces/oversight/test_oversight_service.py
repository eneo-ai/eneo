from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import ApiKeyStateReasonCode
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.domain import (
    MANAGEABLE_USER_STATES,
    DirectMembership,
    GroupMembership,
    MembershipSnapshot,
)
from eneo.spaces.oversight.exceptions import (
    SpaceAdminMustJoinError,
    SpaceAlreadyMemberError,
    SpaceLastAdminError,
    SpaceSelfAccessError,
)
from eneo.spaces.oversight.oversight_repo import (
    DirectMemberRow,
    GroupMemberRow,
    MemberAggregate,
    SharedSpaceRow,
    SpaceMembership,
    SpaceSettingsRows,
    UsageCounts,
)
from eneo.spaces.oversight.oversight_service import SpaceOversightService

ADMIN = SpaceRoleValue.ADMIN
EDITOR = SpaceRoleValue.EDITOR
VIEWER = SpaceRoleValue.VIEWER
REASON = "Ärende KS 2026/123 – kontroll av underlag"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class _FakeRepo:
    """Keeps one shared space's members in memory, as the row-level SQL
    would, and records every write."""

    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.space = SharedSpaceRow(
            id=uuid4(),
            name="Socialtjänsten",
            description=None,
            icon_id=None,
            created_at=NOW,
            updated_at=NOW,
            data_retention_days=None,
            tenant_space_id=uuid4(),
            security_classification=None,
        )
        self.people: dict[UUID, tuple[str, str]] = {}
        self.tenant_admins: set[UUID] = set()
        self.users: dict[UUID, DirectMemberRow] = {}
        self.groups: dict[UUID, GroupMemberRow] = {}
        self.group_users: dict[UUID, frozenset[UUID]] = {}
        self.locks: list[UUID] = []
        self.writes: list[tuple] = []
        self.assistant_ids = [uuid4()]
        self.app_ids = [uuid4()]
        self.usage_counts = UsageCounts(
            questions=40, app_runs=3, active_users=5, widget_questions=7
        )

    # people and rows

    def person(self, *, state: str = "active") -> UUID:
        user_id = uuid4()
        self.people[user_id] = (f"user_{user_id.hex[:6]}", state)
        return user_id

    def member(self, user_id: UUID, role: SpaceRoleValue, **kwargs) -> None:
        username, state = self.people[user_id]
        self.users[user_id] = DirectMemberRow(
            user_id=user_id,
            username=username,
            email=f"{username}@kommun.se",
            state=state,
            role=role,
            is_tenant_admin=user_id in self.tenant_admins,
            oversight_joined_at=kwargs.get("joined_at"),
            oversight_join_reason=kwargs.get("reason"),
        )

    def group(self, role: SpaceRoleValue, *users: UUID, member=True) -> UUID:
        group_id = uuid4()
        self.group_users[group_id] = frozenset(users)
        if member:
            self.groups[group_id] = GroupMemberRow(
                group_id=group_id, name="Handläggare", role=role, user_count=len(users)
            )
        return group_id

    def _manageable(self, group_id: UUID) -> frozenset[UUID]:
        return frozenset(
            user
            for user in self.group_users.get(group_id, frozenset())
            if self.people[user][1] in MANAGEABLE_USER_STATES
        )

    # repo interface

    async def shared_space(self, tenant_id, space_id, *, lock=False):
        if tenant_id != self.tenant_id or space_id != self.space.id:
            raise NotFoundException("Space not found")
        if lock:
            self.locks.append(space_id)
        return self.space

    async def membership(self, tenant_id, space_id, *, extra_group_ids=()):
        wanted = {g for g, row in self.groups.items() if row.role == ADMIN}
        wanted |= set(extra_group_ids)
        by_group = {g: self._manageable(g) for g in wanted if self._manageable(g)}
        return SpaceMembership(
            users=list(self.users.values()),
            groups=list(self.groups.values()),
            snapshot=MembershipSnapshot(
                direct={
                    u: DirectMembership(
                        role=row.role, manageable=row.state in MANAGEABLE_USER_STATES
                    )
                    for u, row in self.users.items()
                },
                groups={
                    g: GroupMembership(
                        role=row.role,
                        manageable_user_ids=by_group.get(g, frozenset()),
                    )
                    for g, row in self.groups.items()
                },
            ),
            manageable_by_group=by_group,
        )

    async def member_aggregates(self, tenant_id, space_id=None):
        members = set(self.users)
        for group_id in self.groups:
            members |= self.group_users[group_id]
        return {
            self.space.id: MemberAggregate(
                member_count=len(members),
                manageable_admins=0,
                group_count=len(self.groups),
            )
        }

    async def is_tenant_admin(self, tenant_id, user_id):
        return tenant_id == self.tenant_id and user_id in self.tenant_admins

    async def insert_member(
        self,
        space_id,
        user_id,
        role,
        *,
        oversight_joined_at=None,
        oversight_join_reason=None,
    ):
        self.writes.append(("insert_member", user_id, role))
        if user_id in self.users:
            return False
        self.member(
            user_id, role, joined_at=oversight_joined_at, reason=oversight_join_reason
        )
        return True

    async def update_member_role(self, space_id, user_id, role):
        self.writes.append(("update_member_role", user_id, role))
        if user_id not in self.users:
            return False
        self.users[user_id] = replace(self.users[user_id], role=role)
        return True

    async def delete_member(self, space_id, user_id):
        self.writes.append(("delete_member", user_id))
        return self.users.pop(user_id, None) is not None

    async def insert_group(self, space_id, group_id, role):
        self.writes.append(("insert_group", group_id, role))
        if group_id in self.groups:
            return False
        self.groups[group_id] = GroupMemberRow(
            group_id=group_id,
            name="Handläggare",
            role=role,
            user_count=len(self.group_users.get(group_id, ())),
        )
        return True

    async def update_group_role(self, space_id, group_id, role):
        self.writes.append(("update_group_role", group_id, role))
        if group_id not in self.groups:
            return False
        self.groups[group_id] = replace(self.groups[group_id], role=role)
        return True

    async def delete_group(self, space_id, group_id):
        self.writes.append(("delete_group", group_id))
        return self.groups.pop(group_id, None) is not None

    async def resource_ids(self, tenant_id, space_id):
        return self.assistant_ids, self.app_ids

    # detail reads

    async def settings(self, tenant_id, space_id):
        return SpaceSettingsRows(
            completion_models=[],
            embedding_models=[],
            transcription_models=[],
            mcp_servers=[],
            capabilities=[],
        )

    async def widgets(self, tenant_id, space_id, *, target_ids=None):
        return []

    async def knowledge_links(self, tenant_id, space_id, *, assistant_ids=None):
        return []

    async def assistant_configs(self, tenant_id, space_id, **kwargs):
        return []

    async def apps(self, tenant_id, space_id):
        return []

    async def group_chats(self, tenant_id, space_id):
        return []

    async def knowledge_sources(self, tenant_id, space_id, **kwargs):
        return []

    async def inherited_knowledge_count(self, tenant_id, space):
        return 0

    async def usage(self, tenant_id, space_id, *, now):
        return self.usage_counts

    async def last_activity(self, tenant_id, now, space_id=None):
        return {}

    # list reads

    async def list_shared_spaces(self, tenant_id):
        return []

    async def admin_principals(self, tenant_id):
        return {}

    async def viewer_memberships(self, tenant_id, *, user_id, group_ids):
        return SimpleNamespace(direct={}, groups={})

    async def resource_counts(self, tenant_id):
        return {}

    async def widget_counts(self, tenant_id):
        return {}

    async def pending_widget_requests(self, tenant_id):
        return []


class _Harness:
    def __init__(self, *permissions: Permission) -> None:
        tenant_id = uuid4()
        self.repo = _FakeRepo(tenant_id)
        self.actor_id = self.repo.person()
        self.user = SimpleNamespace(
            id=self.actor_id,
            tenant_id=tenant_id,
            username="organisationsadmin",
            email="admin@kommun.se",
            permissions=set(permissions or {Permission.ADMIN}),
            user_groups_ids=set(),
        )
        self.audit_service = SimpleNamespace(log_required=AsyncMock())
        self.revoker = SimpleNamespace(revoke_member_keys=AsyncMock(return_value=2))
        self.visits = SimpleNamespace(open=AsyncMock(), close=AsyncMock())
        self.user_repo = SimpleNamespace(
            get_user_by_id_and_tenant_id=AsyncMock(side_effect=self._user)
        )
        self.groups_repo = SimpleNamespace(
            get_user_group=AsyncMock(side_effect=self._group)
        )
        self.foreign_groups: set[UUID] = set()
        self.service = SpaceOversightService(
            user=self.user,
            repo=self.repo,
            user_repo=self.user_repo,
            user_groups_repo=self.groups_repo,
            audit_service=self.audit_service,
            api_key_scope_revoker=self.revoker,
            visit_repo=self.visits,
        )

    @property
    def space_id(self) -> UUID:
        return self.repo.space.id

    async def _user(self, user_id, tenant_id):
        if tenant_id != self.user.tenant_id or user_id not in self.repo.people:
            return None
        username, state = self.repo.people[user_id]
        return SimpleNamespace(
            id=user_id, username=username, email=f"{username}@kommun.se", state=state
        )

    async def _group(self, group_id):
        if group_id not in self.repo.group_users:
            return None
        tenant = uuid4() if group_id in self.foreign_groups else self.user.tenant_id
        return SimpleNamespace(id=group_id, name="Handläggare", tenant_id=tenant)

    def audited(self) -> list[dict]:
        return [call.kwargs for call in self.audit_service.log_required.await_args_list]

    def with_admin(self) -> UUID:
        admin = self.repo.person()
        self.repo.member(admin, ADMIN)
        return admin


# --- authorisation and the gate ----------------------------------------------


def _space_calls(h: _Harness, space_id: UUID) -> list[Callable[[], Awaitable[Any]]]:
    target = uuid4()
    service = h.service
    return [
        lambda: service.get_space(space_id),
        lambda: service.add_member(space_id, target, VIEWER),
        lambda: service.change_member_role(space_id, target, VIEWER),
        lambda: service.remove_member(space_id, target),
        lambda: service.add_group(space_id, target, VIEWER),
        lambda: service.change_group_role(space_id, target, VIEWER),
        lambda: service.remove_group(space_id, target),
        lambda: service.join(space_id, VIEWER, REASON),
        lambda: service.leave(space_id),
    ]


async def test_every_method_needs_the_admin_permission():
    h = _Harness(Permission.WIDGETS)
    for call in [h.service.list_spaces, *_space_calls(h, h.space_id)]:
        with pytest.raises(UnauthorizedException):
            await call()
    assert h.repo.writes == []
    h.audit_service.log_required.assert_not_awaited()


async def test_an_unknown_personal_org_or_foreign_space_is_not_found():
    h = _Harness()
    for call in _space_calls(h, uuid4()):
        with pytest.raises(NotFoundException):
            await call()
    assert h.repo.writes == []


# --- self access ---------------------------------------------------------------


async def test_an_admin_cannot_target_their_own_membership():
    h = _Harness()
    h.with_admin()
    h.repo.member(h.actor_id, VIEWER)
    for call in (
        h.service.add_member(h.space_id, h.actor_id, ADMIN),
        h.service.change_member_role(h.space_id, h.actor_id, ADMIN),
        h.service.remove_member(h.space_id, h.actor_id),
    ):
        with pytest.raises(SpaceSelfAccessError):
            await call
    assert h.repo.writes == []


async def test_a_group_change_that_raises_your_own_role_is_refused():
    h = _Harness()
    h.with_admin()
    mine = h.repo.group(VIEWER, h.actor_id, member=False)
    h.user.user_groups_ids = {mine}
    with pytest.raises(SpaceSelfAccessError):
        await h.service.add_group(h.space_id, mine, EDITOR)

    h.repo.groups[mine] = GroupMemberRow(
        group_id=mine, name="Handläggare", role=VIEWER, user_count=1
    )
    with pytest.raises(SpaceSelfAccessError):
        await h.service.change_group_role(h.space_id, mine, ADMIN)
    assert h.repo.writes == []


async def test_a_group_containing_you_can_be_added_below_your_role_lowered_or_removed():
    h = _Harness()
    h.with_admin()
    h.repo.member(h.actor_id, EDITOR, joined_at=NOW, reason=REASON)
    mine = h.repo.group(VIEWER, h.actor_id, member=False)
    h.user.user_groups_ids = {mine}

    # Adding at or below your current role does not raise it.
    await h.service.add_group(h.space_id, mine, VIEWER)
    await h.service.change_group_role(h.space_id, mine, EDITOR)
    await h.service.change_group_role(h.space_id, mine, VIEWER)
    await h.service.remove_group(h.space_id, mine)
    assert [w[0] for w in h.repo.writes] == [
        "insert_group",
        "update_group_role",
        "update_group_role",
        "delete_group",
    ]


# --- duplicates and missing rows -----------------------------------------------


async def test_another_tenant_admin_is_not_added_or_promoted():
    h = _Harness()
    h.with_admin()
    colleague = h.repo.person()
    h.repo.tenant_admins.add(colleague)
    for role in (VIEWER, ADMIN):
        with pytest.raises(SpaceAdminMustJoinError):
            await h.service.add_member(h.space_id, colleague, role)

    h.repo.member(colleague, EDITOR)
    with pytest.raises(SpaceAdminMustJoinError):
        await h.service.change_member_role(h.space_id, colleague, ADMIN)
    assert h.repo.writes == []
    h.audit_service.log_required.assert_not_awaited()

    # Taking access away, or adding a group that contains one, is allowed.
    await h.service.change_member_role(h.space_id, colleague, VIEWER)
    await h.service.remove_member(h.space_id, colleague)
    group = h.repo.group(EDITOR, colleague, h.repo.person(), member=False)
    await h.service.add_group(h.space_id, group, EDITOR)
    assert [w[0] for w in h.repo.writes] == [
        "update_member_role",
        "delete_member",
        "insert_group",
    ]


async def test_adding_an_existing_member_or_group_conflicts():
    h = _Harness()
    h.with_admin()
    person = h.repo.person()
    h.repo.member(person, VIEWER)
    group = h.repo.group(VIEWER, h.repo.person())
    with pytest.raises(SpaceAlreadyMemberError):
        await h.service.add_member(h.space_id, person, EDITOR)
    with pytest.raises(SpaceAlreadyMemberError):
        await h.service.add_group(h.space_id, group, VIEWER)
    h.audit_service.log_required.assert_not_awaited()


async def test_unknown_users_groups_and_rows_are_not_found():
    h = _Harness()
    h.with_admin()
    with pytest.raises(NotFoundException):
        await h.service.add_member(h.space_id, uuid4(), VIEWER)
    stranger = h.repo.person()
    with pytest.raises(NotFoundException):
        await h.service.change_member_role(h.space_id, stranger, EDITOR)
    with pytest.raises(NotFoundException):
        await h.service.remove_member(h.space_id, stranger)
    with pytest.raises(NotFoundException):
        await h.service.add_group(h.space_id, uuid4(), VIEWER)
    # The group repository has no tenant filter; the service checks it.
    foreign = h.repo.group(VIEWER, h.repo.person(), member=False)
    h.foreign_groups.add(foreign)
    with pytest.raises(NotFoundException):
        await h.service.add_group(h.space_id, foreign, VIEWER)
    with pytest.raises(NotFoundException):
        await h.service.change_group_role(h.space_id, uuid4(), EDITOR)
    with pytest.raises(NotFoundException):
        await h.service.remove_group(h.space_id, uuid4())
    assert h.repo.writes == []


# --- last admin ----------------------------------------------------------------


async def test_the_last_manageable_admin_cannot_be_demoted_or_removed():
    h = _Harness()
    only = h.with_admin()
    with pytest.raises(SpaceLastAdminError):
        await h.service.change_member_role(h.space_id, only, EDITOR)
    with pytest.raises(SpaceLastAdminError):
        await h.service.remove_member(h.space_id, only)
    assert h.repo.writes == []


async def test_the_last_admin_group_cannot_be_demoted_or_removed():
    h = _Harness()
    group = h.repo.group(ADMIN, h.repo.person())
    with pytest.raises(SpaceLastAdminError):
        await h.service.change_group_role(h.space_id, group, VIEWER)
    with pytest.raises(SpaceLastAdminError):
        await h.service.remove_group(h.space_id, group)
    assert h.repo.writes == []


async def test_you_cannot_leave_as_the_last_admin():
    h = _Harness()
    h.repo.member(h.actor_id, ADMIN, joined_at=NOW, reason=REASON)
    with pytest.raises(SpaceLastAdminError):
        await h.service.leave(h.space_id)
    assert h.repo.writes == []


async def test_an_inactive_admin_does_not_keep_the_space_manageable():
    h = _Harness()
    manageable = h.with_admin()
    inactive = h.repo.person(state="inactive")
    h.repo.member(inactive, ADMIN)
    with pytest.raises(SpaceLastAdminError):
        await h.service.remove_member(h.space_id, manageable)


async def test_a_second_admin_through_a_group_lets_the_first_go():
    h = _Harness()
    first = h.with_admin()
    h.repo.group(ADMIN, h.repo.person())
    await h.service.change_member_role(h.space_id, first, VIEWER)
    await h.service.remove_member(h.space_id, first)


async def test_a_space_without_a_manageable_admin_can_always_be_fixed():
    h = _Harness()
    inactive = h.repo.person(state="inactive")
    h.repo.member(inactive, ADMIN)
    viewer = h.repo.person()
    h.repo.member(viewer, VIEWER)
    await h.service.remove_member(h.space_id, inactive)
    await h.service.change_member_role(h.space_id, viewer, ADMIN)
    assert h.repo.users[viewer].role == ADMIN


# --- no-ops ----------------------------------------------------------------------


async def test_setting_the_same_role_writes_and_audits_nothing():
    h = _Harness()
    admin = h.with_admin()
    group = h.repo.group(EDITOR, h.repo.person())
    members = await h.service.change_member_role(h.space_id, admin, ADMIN)
    await h.service.change_group_role(h.space_id, group, EDITOR)
    assert h.repo.writes == []
    h.audit_service.log_required.assert_not_awaited()
    assert [u.id for u in members.users] == [admin]


# --- join and leave --------------------------------------------------------------


async def test_join_refuses_a_direct_member_and_roles_not_above_the_group_role():
    h = _Harness()
    h.with_admin()
    h.repo.member(h.actor_id, VIEWER)
    with pytest.raises(SpaceAlreadyMemberError):
        await h.service.join(h.space_id, EDITOR, REASON)

    h = _Harness()
    h.with_admin()
    mine = h.repo.group(EDITOR, h.actor_id)
    h.user.user_groups_ids = {mine}
    for role in (VIEWER, EDITOR):
        with pytest.raises(BadRequestException):
            await h.service.join(h.space_id, role, REASON)
    assert h.repo.writes == []

    members = await h.service.join(h.space_id, ADMIN, REASON)
    assert members.viewer_membership.direct_role == ADMIN
    assert members.viewer_membership.group_role == EDITOR
    assert members.viewer_membership.joinable_roles == []


async def test_join_records_the_marker_and_audits_role_and_reason():
    h = _Harness()
    h.with_admin()
    members = await h.service.join(
        h.space_id, VIEWER, "  Ärende KS 2026/123\n– kontroll  "
    )
    row = h.repo.users[h.actor_id]
    assert row.oversight_joined_at is not None
    assert row.oversight_join_reason == "Ärende KS 2026/123 – kontroll"
    me = next(u for u in members.users if u.id == h.actor_id)
    assert me.oversight_join is not None
    assert me.oversight_join.reason == "Ärende KS 2026/123 – kontroll"
    assert h.repo.locks == [h.space_id]

    (entry,) = h.audited()
    assert entry["action"] == ActionType.SPACE_OVERSIGHT_JOINED
    assert entry["entity_type"] == EntityType.SPACE
    assert entry["entity_id"] == h.space_id
    assert "Ärende" not in entry["description"]
    extra = entry["metadata"]["extra"]
    assert extra == {
        "oversight": {"actor_is_member": False, "actor_role": None},
        "role": "viewer",
        "reason": "Ärende KS 2026/123 – kontroll",
        "prior_group_role": None,
    }
    target = entry["metadata"]["target"]
    assert target == {
        "id": str(h.space_id),
        "name": "Socialtjänsten",
        "space_id": str(h.space_id),
        "space_name": "Socialtjänsten",
    }


async def test_a_join_opens_a_visit_members_keep_seeing():
    h = _Harness()
    h.with_admin()
    await h.service.join(h.space_id, EDITOR, "  Ärende KS 2026/123\n– kontroll  ")

    row = h.repo.users[h.actor_id]
    h.visits.open.assert_awaited_once_with(
        tenant_id=h.user.tenant_id,
        space_id=h.space_id,
        user_id=h.actor_id,
        role=EDITOR,
        reason="Ärende KS 2026/123 – kontroll",
        joined_at=row.oversight_joined_at,
    )

    h.visits.open.reset_mock()
    with pytest.raises(SpaceAlreadyMemberError):
        await h.service.join(h.space_id, EDITOR, REASON)
    h.visits.open.assert_not_awaited()


async def test_leaving_or_being_removed_ends_the_visit():
    h = _Harness()
    h.with_admin()
    h.repo.member(h.actor_id, EDITOR, joined_at=NOW, reason=REASON)
    colleague = h.repo.person()
    h.repo.member(colleague, VIEWER, joined_at=NOW, reason=REASON)

    await h.service.leave(h.space_id)
    await h.service.remove_member(h.space_id, colleague)

    assert [
        (call.args, set(call.kwargs)) for call in h.visits.close.await_args_list
    ] == [
        ((h.space_id, h.actor_id), {"left_at"}),
        ((h.space_id, colleague), {"left_at"}),
    ]


async def test_leave_needs_a_direct_row_revokes_own_keys_and_audits():
    h = _Harness()
    h.with_admin()
    with pytest.raises(BadRequestException):
        await h.service.leave(h.space_id)

    mine = h.repo.group(VIEWER, h.actor_id)
    h.user.user_groups_ids = {mine}
    h.repo.member(h.actor_id, EDITOR, joined_at=NOW, reason=REASON)
    members = await h.service.leave(h.space_id)
    assert h.actor_id not in h.repo.users
    assert members.viewer_membership.group_role == VIEWER
    h.revoker.revoke_member_keys.assert_awaited_once_with(
        tenant_id=h.user.tenant_id,
        owner_user_id=h.actor_id,
        space_id=h.space_id,
        assistant_ids=h.repo.assistant_ids,
        app_ids=h.repo.app_ids,
        reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
        reason_text="Left the space",
        audit_in_transaction=True,
    )
    (entry,) = h.audited()
    assert entry["action"] == ActionType.SPACE_OVERSIGHT_LEFT
    assert entry["metadata"]["extra"] == {
        "oversight": {"actor_is_member": True, "actor_role": "editor"},
        "was_oversight_join": True,
        "remaining_group_role": "viewer",
        "api_keys_revoked": 2,
    }


# --- audit metadata of member management ------------------------------------------


async def test_member_changes_are_audited_with_the_member_and_the_actor_relation():
    h = _Harness()
    h.with_admin()
    person = h.repo.person()
    username = h.repo.people[person][0]
    member = {"id": str(person), "name": username, "email": f"{username}@kommun.se"}
    oversight = {"actor_is_member": False, "actor_role": None}

    await h.service.add_member(h.space_id, person, VIEWER)
    await h.service.change_member_role(h.space_id, person, EDITOR)
    await h.service.remove_member(h.space_id, person)

    added, changed, removed = h.audited()
    assert added["action"] == ActionType.SPACE_OVERSIGHT_MEMBER_ADDED
    assert added["metadata"]["extra"] == {
        "oversight": oversight,
        "member": member,
        "role": "viewer",
    }
    assert changed["action"] == ActionType.SPACE_OVERSIGHT_MEMBER_ROLE_CHANGED
    assert changed["metadata"]["changes"] == {
        "role": {"old": "viewer", "new": "editor"}
    }
    assert changed["metadata"]["extra"] == {"oversight": oversight, "member": member}
    assert removed["action"] == ActionType.SPACE_OVERSIGHT_MEMBER_REMOVED
    assert removed["metadata"]["extra"] == {
        "oversight": oversight,
        "member": member,
        "api_keys_revoked": 2,
    }
    for entry in (added, changed, removed):
        assert entry["entity_type"] == EntityType.SPACE
        assert entry["entity_id"] == h.space_id
        assert entry["user"] is h.user
        assert len(entry["description"]) <= 500


async def test_removing_a_member_revokes_their_space_keys():
    h = _Harness()
    h.with_admin()
    person = h.repo.person()
    h.repo.member(person, EDITOR)
    await h.service.remove_member(h.space_id, person)
    h.revoker.revoke_member_keys.assert_awaited_once_with(
        tenant_id=h.user.tenant_id,
        owner_user_id=person,
        space_id=h.space_id,
        assistant_ids=h.repo.assistant_ids,
        app_ids=h.repo.app_ids,
        reason_code=ApiKeyStateReasonCode.SCOPE_REMOVED,
        reason_text="Removed from space by an organisation administrator",
        audit_in_transaction=True,
    )
    assert h.audited()[0]["metadata"]["extra"]["api_keys_revoked"] == 2


async def test_group_changes_are_audited_with_the_group():
    h = _Harness()
    h.with_admin()
    mine = h.repo.group(VIEWER, h.actor_id)
    h.user.user_groups_ids = {mine}
    other = h.repo.group(VIEWER, h.repo.person(), h.repo.person(), member=False)

    await h.service.add_group(h.space_id, other, EDITOR)
    await h.service.change_group_role(h.space_id, other, VIEWER)
    await h.service.remove_group(h.space_id, other)

    added, changed, removed = h.audited()
    group = {"id": str(other), "name": "Handläggare", "user_count": 2}
    oversight = {"actor_is_member": True, "actor_role": "viewer"}
    assert added["metadata"]["extra"] == {
        "oversight": oversight,
        "group": group,
        "role": "editor",
    }
    assert changed["metadata"]["changes"] == {
        "role": {"old": "editor", "new": "viewer"}
    }
    assert changed["metadata"]["extra"] == {"oversight": oversight, "group": group}
    assert removed["metadata"]["extra"] == {"oversight": oversight, "group": group}
    # Removing a group does not revoke keys.
    h.revoker.revoke_member_keys.assert_not_awaited()


async def test_every_change_locks_the_space_row():
    h = _Harness()
    h.with_admin()
    person = h.repo.person()
    await h.service.add_member(h.space_id, person, VIEWER)
    await h.service.remove_member(h.space_id, person)
    await h.service.join(h.space_id, VIEWER, REASON)
    await h.service.leave(h.space_id)
    assert h.repo.locks == [h.space_id] * 4


# --- usage --------------------------------------------------------------------


@pytest.mark.parametrize(("active_users", "suppressed"), [(4, True), (5, False)])
async def test_usage_is_withheld_below_five_active_users(active_users, suppressed):
    h = _Harness()
    h.with_admin()
    h.repo.usage_counts = UsageCounts(
        questions=40, app_runs=3, active_users=active_users, widget_questions=7
    )
    usage = (await h.service.get_space(h.space_id)).usage
    assert usage.suppressed is suppressed
    if suppressed:
        assert (usage.questions, usage.app_runs, usage.active_users) == (
            None,
            None,
            None,
        )
    else:
        assert (usage.questions, usage.app_runs, usage.active_users) == (40, 3, 5)
    # Anonymous widget questions carry no identity and are never withheld.
    assert usage.widget_questions == 7


async def test_the_detail_flags_a_space_without_an_admin():
    h = _Harness()
    h.repo.member(h.repo.person(), VIEWER)
    detail = await h.service.get_space(h.space_id)
    assert detail.attention == ["no_admin"]
    assert detail.members.admins.manageable is False
    h.with_admin()
    assert (await h.service.get_space(h.space_id)).attention == []

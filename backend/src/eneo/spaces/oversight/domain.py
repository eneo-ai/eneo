# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Pure rules of tenant-admin space oversight: roles, manageable
administrators, what an administrator may join or leave, and how activity
is coarsened before it leaves the service."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional
from uuid import UUID

from eneo.spaces.api.space_models import SpaceRoleValue

# Fewer distinct signed-in users than this in the usage window and the
# usage counts are withheld: in a tiny space they describe one person's work.
K_ANONYMITY_THRESHOLD = 5
USAGE_WINDOW_DAYS = 30
# App runs have no index on app_id, so the last-activity probe only looks this
# far back in the tenant-wide app run index.
APP_RUN_ACTIVITY_WINDOW_DAYS = 90

# Users who can act in the product. Deleted users are filtered separately
# (deleted_at), so this is the state half of "live and able to manage".
MANAGEABLE_USER_STATES = frozenset({"active", "invited"})

ActivityBucket = Literal["past_week", "past_month", "past_quarter", "older", "none"]

ROLE_RANK: Mapping[SpaceRoleValue, int] = {
    SpaceRoleValue.VIEWER: 1,
    SpaceRoleValue.EDITOR: 2,
    SpaceRoleValue.ADMIN: 3,
}
ROLES_LOWEST_FIRST: tuple[SpaceRoleValue, ...] = tuple(
    sorted(ROLE_RANK, key=lambda role: ROLE_RANK[role])
)


def bucket_for(timestamp: Optional[datetime], now: datetime) -> ActivityBucket:
    if timestamp is None:
        return "none"
    age = now - timestamp
    if age <= timedelta(days=7):
        return "past_week"
    if age <= timedelta(days=30):
        return "past_month"
    if age <= timedelta(days=90):
        return "past_quarter"
    return "older"


def higher_role(
    first: Optional[SpaceRoleValue], second: Optional[SpaceRoleValue]
) -> Optional[SpaceRoleValue]:
    if first is None:
        return second
    if second is None:
        return first
    return first if ROLE_RANK[first] >= ROLE_RANK[second] else second


def highest_role(roles: Iterable[SpaceRoleValue]) -> Optional[SpaceRoleValue]:
    result: Optional[SpaceRoleValue] = None
    for role in roles:
        result = higher_role(result, role)
    return result


def raises_role(
    before: Optional[SpaceRoleValue], after: Optional[SpaceRoleValue]
) -> bool:
    return (ROLE_RANK[after] if after else 0) > (ROLE_RANK[before] if before else 0)


@dataclass(frozen=True)
class DirectMembership:
    role: SpaceRoleValue
    # A live user in an active or invited state.
    manageable: bool


@dataclass(frozen=True)
class GroupMembership:
    role: SpaceRoleValue
    # Live users of the group in an active or invited state. Loaded only for
    # admin groups and for a group a command is changing: the admin rule
    # never needs the members of any other group.
    manageable_user_ids: frozenset[UUID] = frozenset()


@dataclass(frozen=True)
class MembershipSnapshot:
    """A space's live direct and group memberships, read under the space
    lock. Commands evaluate their guards on a copy with the change applied."""

    direct: Mapping[UUID, DirectMembership]
    groups: Mapping[UUID, GroupMembership]

    def with_direct(
        self, user_id: UUID, membership: Optional[DirectMembership]
    ) -> "MembershipSnapshot":
        direct = dict(self.direct)
        if membership is None:
            direct.pop(user_id, None)
        else:
            direct[user_id] = membership
        return MembershipSnapshot(direct=direct, groups=self.groups)

    def with_group(
        self, group_id: UUID, membership: Optional[GroupMembership]
    ) -> "MembershipSnapshot":
        groups = dict(self.groups)
        if membership is None:
            groups.pop(group_id, None)
        else:
            groups[group_id] = membership
        return MembershipSnapshot(direct=self.direct, groups=groups)


def manageable_admin_ids(snapshot: MembershipSnapshot) -> frozenset[UUID]:
    """Users who can manage the space: live, active or invited, and holding
    the admin role directly or through a live group."""
    ids = {
        user_id
        for user_id, membership in snapshot.direct.items()
        if membership.role == SpaceRoleValue.ADMIN and membership.manageable
    }
    for membership in snapshot.groups.values():
        if membership.role == SpaceRoleValue.ADMIN:
            ids.update(membership.manageable_user_ids)
    return frozenset(ids)


def leaves_without_admin(before: MembershipSnapshot, after: MembershipSnapshot) -> bool:
    """A space with no manageable admin can always be changed; one that has
    one must keep at least one."""
    return bool(manageable_admin_ids(before)) and not manageable_admin_ids(after)


def direct_role(
    snapshot: MembershipSnapshot, user_id: UUID
) -> Optional[SpaceRoleValue]:
    membership = snapshot.direct.get(user_id)
    return membership.role if membership else None


def group_role(
    snapshot: MembershipSnapshot, group_ids: Iterable[UUID]
) -> Optional[SpaceRoleValue]:
    return highest_role(
        snapshot.groups[group_id].role
        for group_id in group_ids
        if group_id in snapshot.groups
    )


def effective_role(
    snapshot: MembershipSnapshot, user_id: UUID, group_ids: Iterable[UUID]
) -> Optional[SpaceRoleValue]:
    """The higher of the direct role and every role held through a group,
    as SpaceActor resolves it."""
    return higher_role(direct_role(snapshot, user_id), group_role(snapshot, group_ids))


def joinable_roles(
    direct: Optional[SpaceRoleValue], via_group: Optional[SpaceRoleValue]
) -> list[SpaceRoleValue]:
    """Roles an administrator may join with, lowest first. None with a
    direct row; otherwise only roles above the one held through a group, so
    a join always adds access."""
    if direct is not None:
        return []
    floor = ROLE_RANK[via_group] if via_group else 0
    return [role for role in ROLES_LOWEST_FIRST if ROLE_RANK[role] > floor]


def can_leave(snapshot: MembershipSnapshot, user_id: UUID) -> bool:
    """A direct row exists and removing it keeps a manageable admin (or the
    space had none to begin with)."""
    if user_id not in snapshot.direct:
        return False
    return not leaves_without_admin(snapshot, snapshot.with_direct(user_id, None))

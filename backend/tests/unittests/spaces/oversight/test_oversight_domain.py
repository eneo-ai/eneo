from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.oversight.domain import (
    DirectMembership,
    GroupMembership,
    MembershipSnapshot,
    bucket_for,
    can_leave,
    effective_role,
    joinable_roles,
    leaves_without_admin,
    manageable_admin_ids,
)

ADMIN = SpaceRoleValue.ADMIN
EDITOR = SpaceRoleValue.EDITOR
VIEWER = SpaceRoleValue.VIEWER


def _snapshot(direct=None, groups=None) -> MembershipSnapshot:
    return MembershipSnapshot(direct=direct or {}, groups=groups or {})


def test_manageable_admins_hold_the_admin_role_directly_or_through_a_group():
    direct_admin, via_group, editor = uuid4(), uuid4(), uuid4()
    group = uuid4()
    snapshot = _snapshot(
        direct={
            direct_admin: DirectMembership(role=ADMIN, manageable=True),
            editor: DirectMembership(role=EDITOR, manageable=True),
        },
        groups={
            group: GroupMembership(
                role=ADMIN, manageable_user_ids=frozenset({via_group})
            )
        },
    )
    assert manageable_admin_ids(snapshot) == {direct_admin, via_group}


def test_inactive_or_deleted_admins_and_empty_admin_groups_manage_nothing():
    # Deleted users never reach the snapshot; inactive ones are not manageable.
    inactive = uuid4()
    snapshot = _snapshot(
        direct={inactive: DirectMembership(role=ADMIN, manageable=False)},
        groups={uuid4(): GroupMembership(role=ADMIN, manageable_user_ids=frozenset())},
    )
    assert manageable_admin_ids(snapshot) == frozenset()


def test_a_non_admin_group_contributes_no_admins():
    member = uuid4()
    snapshot = _snapshot(
        groups={
            uuid4(): GroupMembership(
                role=EDITOR, manageable_user_ids=frozenset({member})
            )
        }
    )
    assert manageable_admin_ids(snapshot) == frozenset()


def test_the_last_admin_rule_only_guards_the_step_to_none():
    admin = uuid4()
    one_admin = _snapshot(direct={admin: DirectMembership(role=ADMIN, manageable=True)})
    assert leaves_without_admin(one_admin, one_admin.with_direct(admin, None))
    assert leaves_without_admin(
        one_admin,
        one_admin.with_direct(admin, DirectMembership(role=VIEWER, manageable=True)),
    )
    # A space without a manageable admin can always be changed.
    no_admin = _snapshot(direct={admin: DirectMembership(role=VIEWER, manageable=True)})
    assert not leaves_without_admin(no_admin, no_admin.with_direct(admin, None))


def test_snapshot_changes_do_not_mutate_the_original():
    user, group = uuid4(), uuid4()
    snapshot = _snapshot(
        direct={user: DirectMembership(role=ADMIN, manageable=True)},
        groups={group: GroupMembership(role=VIEWER)},
    )
    snapshot.with_direct(user, None)
    snapshot.with_group(group, None)
    assert user in snapshot.direct and group in snapshot.groups


@pytest.mark.parametrize(
    ("direct", "group_roles", "expected"),
    [
        (None, [], None),
        (VIEWER, [], VIEWER),
        (None, [EDITOR], EDITOR),
        (VIEWER, [EDITOR], EDITOR),
        (ADMIN, [VIEWER], ADMIN),
        (None, [VIEWER, ADMIN, EDITOR], ADMIN),
    ],
)
def test_effective_role_is_the_highest_of_direct_and_group_roles(
    direct, group_roles, expected
):
    user = uuid4()
    groups = {uuid4(): GroupMembership(role=role) for role in group_roles}
    snapshot = _snapshot(
        direct={user: DirectMembership(role=direct, manageable=True)} if direct else {},
        groups=groups,
    )
    assert effective_role(snapshot, user, groups.keys()) == expected


def test_effective_role_ignores_groups_the_user_is_not_in():
    user = uuid4()
    snapshot = _snapshot(groups={uuid4(): GroupMembership(role=ADMIN)})
    assert effective_role(snapshot, user, [uuid4()]) is None


@pytest.mark.parametrize(
    ("group_role", "expected"),
    [
        (None, [VIEWER, EDITOR, ADMIN]),
        (VIEWER, [EDITOR, ADMIN]),
        (EDITOR, [ADMIN]),
        (ADMIN, []),
    ],
)
def test_joinable_roles_are_above_the_group_role_lowest_first(group_role, expected):
    assert joinable_roles(None, group_role) == expected


@pytest.mark.parametrize("direct", [VIEWER, EDITOR, ADMIN])
def test_nothing_is_joinable_with_a_direct_membership(direct):
    assert joinable_roles(direct, None) == []
    assert joinable_roles(direct, VIEWER) == []


def test_can_leave_needs_a_direct_row_and_keeps_an_admin():
    me, other = uuid4(), uuid4()
    group = uuid4()
    assert not can_leave(_snapshot(), me)

    only_admin = _snapshot(direct={me: DirectMembership(role=ADMIN, manageable=True)})
    assert not can_leave(only_admin, me)

    with_other = only_admin.with_direct(
        other, DirectMembership(role=ADMIN, manageable=True)
    )
    assert can_leave(with_other, me)

    # Still an admin through a group after leaving the direct row.
    through_group = only_admin.with_group(
        group, GroupMembership(role=ADMIN, manageable_user_ids=frozenset({me}))
    )
    assert can_leave(through_group, me)

    viewer = _snapshot(
        direct={
            me: DirectMembership(role=VIEWER, manageable=True),
            other: DirectMembership(role=ADMIN, manageable=True),
        }
    )
    assert can_leave(viewer, me)

    # A space that had no manageable admin may be left.
    no_admin = _snapshot(direct={me: DirectMembership(role=VIEWER, manageable=True)})
    assert can_leave(no_admin, me)


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("age", "bucket"),
    [
        (timedelta(0), "past_week"),
        (timedelta(days=7), "past_week"),
        (timedelta(days=7, seconds=1), "past_month"),
        (timedelta(days=30), "past_month"),
        (timedelta(days=30, seconds=1), "past_quarter"),
        (timedelta(days=90), "past_quarter"),
        (timedelta(days=90, seconds=1), "older"),
        (timedelta(days=400), "older"),
    ],
)
def test_activity_is_reduced_to_a_bucket(age, bucket):
    assert bucket_for(NOW - age, NOW) == bucket


def test_no_activity_is_its_own_bucket():
    assert bucket_for(None, NOW) == "none"

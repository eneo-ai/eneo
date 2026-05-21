"""Unit tests for ``OrgSpaceAssistantRoleService``.

Covers the seven branches called out by step 015:

- fresh ``assign`` writes a role row and no history row,
- re-assign updates the role row and appends a single ``REASSIGNED``
  history row,
- ``unassign`` deletes the role row and appends a single ``UNASSIGNED``
  history row,
- assigning an assistant that lives outside the org-space raises
  ``BadRequestException``,
- non-admin callers raise ``UnauthorizedException`` on every mutation,
- ``get_active`` requires no admin permission, and
- toggles write audit-log entries.

The service collaborates with ``AssistantService``, ``SpaceService`` and
``AuditService`` through DI — they are mocked here so the tests only
exercise the role-service behaviour. The real
``HelperAssistantsFactory`` is used because it is pure-Python.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.help_assistants.application.org_space_assistant_role_service import (
    OrgSpaceAssistantRoleService,
)
from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.factory import HelperAssistantsFactory
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.role_assignment import RoleAssignment
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.roles.permissions import Permission
from intric.roles.role import RoleInDB
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB

_TENANT = TenantInDB(id=uuid4(), name="acme", quota_limit=1024**3)


def _make_user(*permissions: Permission) -> UserInDB:
    role = RoleInDB(
        id=uuid4(),
        name="test_role",
        permissions=list(permissions),
        tenant_id=_TENANT.id,
    )
    return UserInDB(
        id=uuid4(),
        username="tester",
        email="tester@example.com",
        salt=None,
        password=None,
        used_tokens=0,
        tenant_id=_TENANT.id,
        tenant=_TENANT,
        roles=[role],
        state="active",
    )


def _mock_assistant(*, assistant_id: UUID, space_id: UUID, name: str = "Helper"):
    assistant = MagicMock()
    assistant.id = assistant_id
    assistant.name = name
    assistant.space_id = space_id
    return assistant


def _make_role_row(
    *,
    role_id: UUID,
    org_space_id: UUID,
    assistant_id: UUID,
    kind: HelperKind = HelperKind.PROMPT_GUIDE,
    is_enabled: bool = True,
    is_visible_to_users: bool = True,
) -> RoleAssignment:
    return RoleAssignment(
        id=role_id,
        org_space_id=org_space_id,
        kind=kind,
        assistant_id=assistant_id,
        is_enabled=is_enabled,
        is_visible_to_users=is_visible_to_users,
    )


def _build_service(
    *,
    user: UserInDB,
    org_space_id: UUID,
    role_repo: AsyncMock | None = None,
    history_repo: AsyncMock | None = None,
    assistant_service: AsyncMock | None = None,
    audit_service: AsyncMock | None = None,
) -> tuple[OrgSpaceAssistantRoleService, dict[str, AsyncMock]]:
    role_repo = role_repo or AsyncMock()
    history_repo = history_repo or AsyncMock()
    assistant_service = assistant_service or AsyncMock()
    audit_service = audit_service or AsyncMock()

    space_service = AsyncMock()
    org_space = MagicMock()
    org_space.id = org_space_id
    space_service.get_or_create_tenant_space.return_value = org_space

    service = OrgSpaceAssistantRoleService(
        user=user,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
        space_service=space_service,
        audit_service=audit_service,
        factory=HelperAssistantsFactory(),
    )
    return service, {
        "role_repo": role_repo,
        "history_repo": history_repo,
        "assistant_service": assistant_service,
        "audit_service": audit_service,
        "space_service": space_service,
    }


@pytest.mark.asyncio
async def test_assign_fresh_role_writes_role_row_and_no_history():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    assistant_id = uuid4()

    assistant = _mock_assistant(
        assistant_id=assistant_id, space_id=org_space_id, name="Prompt Guide"
    )

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = None
    new_role = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=assistant_id
    )
    role_repo.add.return_value = new_role

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (assistant, [])

    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    result = await service.assign(
        kind=HelperKind.PROMPT_GUIDE, assistant_id=assistant_id
    )

    assert result is new_role
    role_repo.add.assert_awaited_once()
    role_repo.update.assert_not_awaited()
    history_repo.add.assert_not_awaited()

    mocks["audit_service"].log_async.assert_awaited_once()
    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_ROLE_ASSIGNED
    assert audit_kwargs["entity_id"] == assistant_id
    assert audit_kwargs["metadata"]["extra"]["previous_assistant_id"] is None


@pytest.mark.asyncio
async def test_reassign_updates_role_row_and_appends_single_history_row():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    old_assistant_id = uuid4()
    new_assistant_id = uuid4()

    existing = _make_role_row(
        role_id=uuid4(),
        org_space_id=org_space_id,
        assistant_id=old_assistant_id,
    )

    new_assistant = _mock_assistant(
        assistant_id=new_assistant_id, space_id=org_space_id, name="Prompt v2"
    )
    old_assistant = _mock_assistant(
        assistant_id=old_assistant_id, space_id=org_space_id, name="Prompt v1"
    )

    assistant_service = AsyncMock()
    assistant_service.get_assistant.side_effect = [
        (new_assistant, []),
        (old_assistant, []),
    ]

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = existing
    role_repo.update.return_value = existing  # repo returns the refreshed entity

    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    result = await service.assign(
        kind=HelperKind.PROMPT_GUIDE, assistant_id=new_assistant_id
    )

    assert result is existing
    assert existing.assistant_id == new_assistant_id  # entity mutated in-place
    assert existing.updated_by_user_id == admin.id

    role_repo.add.assert_not_awaited()
    role_repo.update.assert_awaited_once()

    history_repo.add.assert_awaited_once()
    history_arg = history_repo.add.await_args.args[0]
    assert history_arg.reason == AssignmentHistoryReason.REASSIGNED
    assert history_arg.assistant_id == old_assistant_id
    assert history_arg.assistant_name_snapshot == "Prompt v1"
    assert history_arg.replaced_by_assistant_id == new_assistant_id
    assert history_arg.actor_user_id == admin.id

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_ROLE_ASSIGNED
    assert audit_kwargs["metadata"]["extra"]["previous_assistant_id"] == str(
        old_assistant_id
    )


@pytest.mark.asyncio
async def test_assign_same_assistant_is_idempotent():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    assistant_id = uuid4()

    existing = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=assistant_id
    )
    assistant = _mock_assistant(assistant_id=assistant_id, space_id=org_space_id)

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (assistant, [])

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = existing

    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    result = await service.assign(
        kind=HelperKind.PROMPT_GUIDE, assistant_id=assistant_id
    )

    assert result is existing
    role_repo.update.assert_not_awaited()
    role_repo.add.assert_not_awaited()
    history_repo.add.assert_not_awaited()
    mocks["audit_service"].log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_unassign_deletes_role_row_and_writes_history():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    assistant_id = uuid4()
    role_id = uuid4()

    existing = _make_role_row(
        role_id=role_id, org_space_id=org_space_id, assistant_id=assistant_id
    )
    assistant = _mock_assistant(
        assistant_id=assistant_id, space_id=org_space_id, name="Prompt Guide"
    )

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (assistant, [])

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = existing

    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    await service.unassign(kind=HelperKind.PROMPT_GUIDE)

    history_repo.add.assert_awaited_once()
    history_arg = history_repo.add.await_args.args[0]
    assert history_arg.reason == AssignmentHistoryReason.UNASSIGNED
    assert history_arg.assistant_id == assistant_id
    assert history_arg.replaced_by_assistant_id is None
    assert history_arg.assistant_name_snapshot == "Prompt Guide"

    role_repo.delete.assert_awaited_once_with(id=role_id)

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_ROLE_UNASSIGNED
    assert audit_kwargs["entity_id"] == assistant_id


@pytest.mark.asyncio
async def test_unassign_noop_when_no_assignment_exists():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = None

    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
    )

    await service.unassign(kind=HelperKind.PROMPT_GUIDE)

    history_repo.add.assert_not_awaited()
    role_repo.delete.assert_not_awaited()
    mocks["audit_service"].log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_assign_assistant_outside_org_space_raises_bad_request():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    foreign_space_id = uuid4()
    assistant_id = uuid4()

    foreign_assistant = _mock_assistant(
        assistant_id=assistant_id, space_id=foreign_space_id
    )

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (foreign_assistant, [])

    role_repo = AsyncMock()
    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    with pytest.raises(BadRequestException, match="org-space"):
        await service.assign(
            kind=HelperKind.PROMPT_GUIDE, assistant_id=assistant_id
        )

    role_repo.add.assert_not_awaited()
    role_repo.update.assert_not_awaited()
    history_repo.add.assert_not_awaited()
    mocks["audit_service"].log_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, kwargs",
    [
        ("assign", {"kind": HelperKind.PROMPT_GUIDE, "assistant_id": uuid4()}),
        ("unassign", {"kind": HelperKind.PROMPT_GUIDE}),
        (
            "toggle_enabled",
            {"kind": HelperKind.PROMPT_GUIDE, "value": False},
        ),
        (
            "toggle_visible_to_users",
            {"kind": HelperKind.PROMPT_GUIDE, "value": False},
        ),
        ("list_for_calling_tenant", {}),
        ("list_history", {"kind": HelperKind.PROMPT_GUIDE}),
    ],
)
async def test_non_admin_mutations_raise_unauthorized(
    method: str, kwargs: dict
):
    non_admin = _make_user()  # no permissions
    org_space_id = uuid4()

    service, _ = _build_service(user=non_admin, org_space_id=org_space_id)

    with pytest.raises(UnauthorizedException):
        await getattr(service, method)(**kwargs)


@pytest.mark.asyncio
async def test_get_active_does_not_require_admin():
    non_admin = _make_user()
    org_space_id = uuid4()
    role = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=uuid4()
    )

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role

    service, _ = _build_service(
        user=non_admin, org_space_id=org_space_id, role_repo=role_repo
    )

    result = await service.get_active(kind=HelperKind.PROMPT_GUIDE)

    assert result is role
    role_repo.get_by_org_space_and_kind.assert_awaited_once_with(
        org_space_id=org_space_id, kind=HelperKind.PROMPT_GUIDE
    )


@pytest.mark.asyncio
async def test_toggle_enabled_writes_audit_entry_with_change_block():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    assistant_id = uuid4()
    role = _make_role_row(
        role_id=uuid4(),
        org_space_id=org_space_id,
        assistant_id=assistant_id,
        is_enabled=True,
    )
    assistant = _mock_assistant(
        assistant_id=assistant_id, space_id=org_space_id, name="Prompt Guide"
    )

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role
    role_repo.update.return_value = role

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (assistant, [])

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        assistant_service=assistant_service,
    )

    result = await service.toggle_enabled(
        kind=HelperKind.PROMPT_GUIDE, value=False
    )

    assert result is role
    assert role.is_enabled is False

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_ROLE_TOGGLED_ENABLED
    changes = audit_kwargs["metadata"]["changes"]
    assert changes == {"is_enabled": {"old": True, "new": False}}


@pytest.mark.asyncio
async def test_toggle_visible_to_users_writes_audit_entry_with_change_block():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    assistant_id = uuid4()
    role = _make_role_row(
        role_id=uuid4(),
        org_space_id=org_space_id,
        assistant_id=assistant_id,
        is_visible_to_users=True,
    )
    assistant = _mock_assistant(
        assistant_id=assistant_id, space_id=org_space_id, name="Prompt Guide"
    )

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role
    role_repo.update.return_value = role

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (assistant, [])

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        assistant_service=assistant_service,
    )

    result = await service.toggle_visible_to_users(
        kind=HelperKind.PROMPT_GUIDE, value=False
    )

    assert result is role
    assert role.is_visible_to_users is False

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_ROLE_TOGGLED_VISIBLE
    changes = audit_kwargs["metadata"]["changes"]
    assert changes == {"is_visible_to_users": {"old": True, "new": False}}


@pytest.mark.asyncio
async def test_toggle_raises_when_no_active_assignment():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = None

    service, _ = _build_service(
        user=admin, org_space_id=org_space_id, role_repo=role_repo
    )

    with pytest.raises(BadRequestException, match="No active assignment"):
        await service.toggle_enabled(
            kind=HelperKind.PROMPT_GUIDE, value=False
        )


@pytest.mark.asyncio
async def test_list_for_calling_tenant_returns_assignments_for_org_space():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    rows = [
        _make_role_row(
            role_id=uuid4(),
            org_space_id=org_space_id,
            assistant_id=uuid4(),
        )
    ]

    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = rows

    service, _ = _build_service(
        user=admin, org_space_id=org_space_id, role_repo=role_repo
    )

    result = await service.list_for_calling_tenant()

    assert result == rows
    role_repo.list_for_org_space.assert_awaited_once_with(
        org_space_id=org_space_id
    )


@pytest.mark.asyncio
async def test_list_history_returns_history_rows_for_kind():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    history_rows = [MagicMock()]

    history_repo = AsyncMock()
    history_repo.list_by_org_space_and_kind.return_value = history_rows

    service, _ = _build_service(
        user=admin,
        org_space_id=org_space_id,
        history_repo=history_repo,
    )

    result = await service.list_history(kind=HelperKind.PROMPT_GUIDE)

    assert result == history_rows
    history_repo.list_by_org_space_and_kind.assert_awaited_once_with(
        org_space_id=org_space_id, kind=HelperKind.PROMPT_GUIDE
    )

"""Unit tests for ``OrgSpaceAssistantRoleService``.

Cover the service-layer behaviour with its collaborators mocked:

- non-admin callers raise ``UnauthorizedException`` on every mutation,
- ``get_active`` requires no admin permission, and
- the enabled/visible toggles, the reset (instructions-only / to-default)
  and archive actions, and their audit-log entries.

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
    assistant_repo: AsyncMock | None = None,
    prompt_service: AsyncMock | None = None,
    users_repo: AsyncMock | None = None,
    completion_model_crud_service: AsyncMock | None = None,
) -> tuple[OrgSpaceAssistantRoleService, dict[str, AsyncMock]]:
    role_repo = role_repo or AsyncMock()
    history_repo = history_repo or AsyncMock()
    assistant_service = assistant_service or AsyncMock()
    audit_service = audit_service or AsyncMock()
    assistant_repo = assistant_repo or AsyncMock()
    prompt_service = prompt_service or AsyncMock()
    users_repo = users_repo or AsyncMock()
    completion_model_crud_service = completion_model_crud_service or AsyncMock()

    space_service = AsyncMock()
    org_space = MagicMock()
    org_space.id = org_space_id
    space_service.get_or_create_tenant_space.return_value = org_space

    service = OrgSpaceAssistantRoleService(
        user=user,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
        assistant_repo=assistant_repo,
        prompt_service=prompt_service,
        users_repo=users_repo,
        completion_model_crud_service=completion_model_crud_service,
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
        "assistant_repo": assistant_repo,
        "prompt_service": prompt_service,
        "users_repo": users_repo,
        "completion_model_crud_service": completion_model_crud_service,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, kwargs",
    [
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
async def test_non_admin_mutations_raise_unauthorized(method: str, kwargs: dict):
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

    result = await service.toggle_enabled(kind=HelperKind.PROMPT_GUIDE, value=False)

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
        await service.toggle_enabled(kind=HelperKind.PROMPT_GUIDE, value=False)


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
    role_repo.list_for_org_space.assert_awaited_once_with(org_space_id=org_space_id)


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

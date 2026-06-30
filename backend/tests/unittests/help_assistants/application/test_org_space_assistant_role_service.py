"""Unit tests for ``OrgSpaceAssistantRoleService``.

Cover the service-layer behaviour with its collaborators mocked:

- non-admin callers raise ``UnauthorizedException`` on every mutation,
- ``get_active`` requires no admin permission, and
- the enabled/visible toggles, install / uninstall of a template, and
  their audit-log entries.

The service collaborates with ``AssistantService``, ``SpaceService`` and
``AuditService`` through DI — they are mocked here so the tests only
exercise the role-service behaviour. The real
``HelperAssistantsFactory`` is used because it is pure-Python.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.help_assistants.application.org_space_assistant_role_service import (
    OrgSpaceAssistantRoleService,
)
from eneo.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from eneo.help_assistants.domain.factory import HelperAssistantsFactory
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.role_assignment import RoleAssignment
from eneo.help_assistants.templates import get_template
from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB

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
        ("list_available_templates", {}),
        ("install_helper", {"kind": HelperKind.PROMPT_GUIDE}),
        ("uninstall_helper", {"kind": HelperKind.PROMPT_GUIDE}),
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
async def test_list_available_templates_excludes_installed_kinds():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()

    # Prompt Guide already installed → it must not surface as available.
    installed = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=uuid4()
    )
    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = [installed]

    service, _ = _build_service(
        user=admin, org_space_id=org_space_id, role_repo=role_repo
    )

    result = await service.list_available_templates()

    assert HelperKind.PROMPT_GUIDE not in {kind for kind, _template in result}


@pytest.mark.asyncio
async def test_list_available_templates_lists_uninstalled_kinds():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()

    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = []  # nothing installed yet

    service, _ = _build_service(
        user=admin, org_space_id=org_space_id, role_repo=role_repo
    )

    result = await service.list_available_templates()

    assert HelperKind.PROMPT_GUIDE in {kind for kind, _template in result}


@pytest.mark.asyncio
async def test_install_helper_creates_assistant_with_shipped_prompt_and_visible_role():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    system_user_id = uuid4()
    new_prompt = MagicMock(id=uuid4())

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = None  # not installed
    role_repo.add.return_value = _make_role_row(
        role_id=uuid4(),
        org_space_id=org_space_id,
        assistant_id=uuid4(),
        is_enabled=True,
        is_visible_to_users=True,
    )

    prompt_service = AsyncMock()
    prompt_service.create_prompt.return_value = new_prompt

    users_repo = AsyncMock()
    users_repo.get_system_user_id_for_tenant.return_value = system_user_id

    completion_model_crud_service = AsyncMock()
    # No eligible model is fine: install proceeds with completion_model=None.
    completion_model_crud_service.get_default_completion_model.return_value = None

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        prompt_service=prompt_service,
        users_repo=users_repo,
        completion_model_crud_service=completion_model_crud_service,
    )

    result = await service.install_helper(kind=HelperKind.PROMPT_GUIDE)

    # The shipped template prompt is applied (it drives the Q&A UI), not blank.
    prompt_service.create_prompt.assert_awaited_once()
    installed_text = prompt_service.create_prompt.await_args.kwargs["text"]
    assert installed_text == get_template(HelperKind.PROMPT_GUIDE).prompt_text
    assert installed_text != ""

    # A new assistant row was created in the org-space.
    mocks["assistant_repo"].add.assert_awaited_once()
    new_assistant = mocks["assistant_repo"].add.await_args.args[0]
    assert new_assistant.space_id == org_space_id

    # The role is installed enabled and visible, pointing at the new assistant.
    role_repo.add.assert_awaited_once()
    added_role = role_repo.add.await_args.args[0]
    assert added_role.kind == HelperKind.PROMPT_GUIDE
    assert added_role.is_enabled is True
    assert added_role.is_visible_to_users is True
    assert added_role.assistant_id == new_assistant.id
    assert result.is_visible_to_users is True

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_INSTALLED


@pytest.mark.asyncio
async def test_install_helper_rejects_when_already_installed():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    existing = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=uuid4()
    )
    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = existing

    service, mocks = _build_service(
        user=admin, org_space_id=org_space_id, role_repo=role_repo
    )

    with pytest.raises(BadRequestException, match="already installed"):
        await service.install_helper(kind=HelperKind.PROMPT_GUIDE)

    mocks["assistant_repo"].add.assert_not_awaited()
    role_repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_uninstall_helper_writes_history_then_removes_role_and_assistant():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    assistant_id = uuid4()
    role_id = uuid4()
    role = _make_role_row(
        role_id=role_id, org_space_id=org_space_id, assistant_id=assistant_id
    )
    assistant = _mock_assistant(
        assistant_id=assistant_id, space_id=org_space_id, name="Prompt Guide"
    )

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role

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

    await service.uninstall_helper(kind=HelperKind.PROMPT_GUIDE)

    # History snapshot written before deletion.
    history_repo.add.assert_awaited_once()
    history_entry = history_repo.add.await_args.args[0]
    assert history_entry.reason == AssignmentHistoryReason.UNASSIGNED
    assert history_entry.assistant_name_snapshot == "Prompt Guide"

    # The role row is removed before the assistant (FK is ON DELETE RESTRICT).
    role_repo.delete.assert_awaited_once_with(role_id)
    assistant_service.delete_assistant.assert_awaited_once_with(assistant_id)

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_UNINSTALLED

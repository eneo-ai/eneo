"""Unit tests for the admin archive action on ``OrgSpaceAssistantRoleService``.

Step 017 covers:

- ``list_archivable_helpers`` returns every replaced helper (history row
  with non-NULL ``assistant_id``) minus the assistant currently filling
  the role slot for the requested kind. Already-archived assistants
  (history rows with ``assistant_id=NULL``) are naturally excluded
  because ``list_replaced_assistant_ids_by_org_space`` filters NULL ids
  out at the SQL layer.
- ``archive_helper`` refuses to delete an assistant that is currently
  filling any role (defense-in-depth), or an assistant that has no
  helper history at all in the org-space.
- ``archive_helper`` on an archivable helper routes through
  ``assistant_service.delete_assistant`` so existing cleanup paths
  (e.g. the API-key scope revoker, icon cleanup) run, and writes a
  ``HELP_ASSISTANT_ARCHIVED`` audit log entry carrying the captured
  ``assistant_name_snapshot``.

History-row survival after the hard delete is verified at the DB layer
by the integration test for the history repo (step 010); this layer
asserts the call shape only — ``assistant_repo``/``history_repo`` are
mocks.
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
) -> RoleAssignment:
    return RoleAssignment(
        id=role_id,
        org_space_id=org_space_id,
        kind=kind,
        assistant_id=assistant_id,
        is_enabled=True,
        is_visible_to_users=True,
    )


def _build_service(
    *,
    user: UserInDB,
    org_space_id: UUID,
    role_repo: AsyncMock | None = None,
    history_repo: AsyncMock | None = None,
    assistant_service: AsyncMock | None = None,
    assistant_repo: AsyncMock | None = None,
    prompt_service: AsyncMock | None = None,
    users_repo: AsyncMock | None = None,
    completion_model_crud_service: AsyncMock | None = None,
    audit_service: AsyncMock | None = None,
) -> tuple[OrgSpaceAssistantRoleService, dict[str, AsyncMock]]:
    role_repo = role_repo or AsyncMock()
    history_repo = history_repo or AsyncMock()
    assistant_service = assistant_service or AsyncMock()
    assistant_repo = assistant_repo or AsyncMock()
    prompt_service = prompt_service or AsyncMock()
    users_repo = users_repo or AsyncMock()
    completion_model_crud_service = completion_model_crud_service or AsyncMock()
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
        "assistant_repo": assistant_repo,
        "prompt_service": prompt_service,
        "users_repo": users_repo,
        "completion_model_crud_service": completion_model_crud_service,
        "audit_service": audit_service,
        "space_service": space_service,
    }


@pytest.mark.asyncio
async def test_list_archivable_helpers_includes_former_helpers_with_no_active_role():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    active_id = uuid4()
    former_id = uuid4()
    other_former_id = uuid4()

    active_role = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=active_id
    )
    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = [active_role]

    history_repo = AsyncMock()
    history_repo.list_replaced_assistant_ids_by_org_space.return_value = {
        former_id,
        other_former_id,
    }

    former_one = _mock_assistant(
        assistant_id=former_id, space_id=org_space_id, name="Old v1"
    )
    former_two = _mock_assistant(
        assistant_id=other_former_id, space_id=org_space_id, name="Old v2"
    )

    def _get_assistant(*, assistant_id: UUID):
        if assistant_id == former_id:
            return (former_one, [])
        if assistant_id == other_former_id:
            return (former_two, [])
        raise AssertionError(f"Unexpected get_assistant call for {assistant_id}")

    assistant_service = AsyncMock()
    assistant_service.get_assistant.side_effect = _get_assistant

    service, _ = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    result = await service.list_archivable_helpers(kind=HelperKind.PROMPT_GUIDE)

    result_ids = {a.id for a in result}
    assert result_ids == {former_id, other_former_id}
    assert active_id not in result_ids

    history_repo.list_replaced_assistant_ids_by_org_space.assert_awaited_once_with(
        org_space_id=org_space_id
    )
    role_repo.list_for_org_space.assert_awaited_once_with(org_space_id=org_space_id)


@pytest.mark.asyncio
async def test_list_archivable_helpers_excludes_currently_active_helper():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    active_id = uuid4()

    active_role = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=active_id
    )
    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = [active_role]

    # The active helper's id also appears in history (a defensive scenario
    # — e.g. a previous reassign back-and-forth left a row referencing it).
    # It must still be filtered out because it's currently filling a role.
    history_repo = AsyncMock()
    history_repo.list_replaced_assistant_ids_by_org_space.return_value = {active_id}

    assistant_service = AsyncMock()

    service, _ = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    result = await service.list_archivable_helpers(kind=HelperKind.PROMPT_GUIDE)

    assert result == []
    assistant_service.get_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_archivable_helpers_excludes_already_archived_assistants():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    active_id = uuid4()
    surviving_former_id = uuid4()

    # ``list_replaced_assistant_ids_by_org_space`` filters out NULL
    # ``assistant_id``s at the SQL layer (per step 010), so already-archived
    # history rows never appear in this set. The service relies on that
    # filter — no extra branch is required here.
    history_repo = AsyncMock()
    history_repo.list_replaced_assistant_ids_by_org_space.return_value = {
        surviving_former_id,
    }

    active_role = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=active_id
    )
    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = [active_role]

    surviving = _mock_assistant(
        assistant_id=surviving_former_id, space_id=org_space_id, name="Old v1"
    )
    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (surviving, [])

    service, _ = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    result = await service.list_archivable_helpers(kind=HelperKind.PROMPT_GUIDE)

    assert {a.id for a in result} == {surviving_former_id}


@pytest.mark.asyncio
async def test_list_archivable_helpers_requires_admin():
    non_admin = _make_user()
    service, _ = _build_service(user=non_admin, org_space_id=uuid4())

    with pytest.raises(UnauthorizedException):
        await service.list_archivable_helpers(kind=HelperKind.PROMPT_GUIDE)


@pytest.mark.asyncio
async def test_archive_helper_on_active_helper_raises_bad_request():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    active_id = uuid4()

    active_role = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=active_id
    )
    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = [active_role]

    # Pretend the active helper also appears in history (defensive scenario).
    history_repo = AsyncMock()
    history_repo.list_replaced_assistant_ids_by_org_space.return_value = {active_id}

    assistant_service = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    with pytest.raises(BadRequestException, match="currently assigned"):
        await service.archive_helper(assistant_id=active_id)

    assistant_service.delete_assistant.assert_not_awaited()
    mocks["audit_service"].log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_archive_helper_on_unknown_assistant_raises_bad_request():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    stranger_id = uuid4()

    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = []

    history_repo = AsyncMock()
    history_repo.list_replaced_assistant_ids_by_org_space.return_value = set()

    assistant_service = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    with pytest.raises(BadRequestException, match="not an archivable helper"):
        await service.archive_helper(assistant_id=stranger_id)

    assistant_service.delete_assistant.assert_not_awaited()
    mocks["audit_service"].log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_archive_helper_hard_deletes_via_assistant_service_and_audits():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    active_id = uuid4()
    archivable_id = uuid4()

    active_role = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=active_id
    )
    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = [active_role]

    history_repo = AsyncMock()
    history_repo.list_replaced_assistant_ids_by_org_space.return_value = {archivable_id}

    target_assistant = _mock_assistant(
        assistant_id=archivable_id,
        space_id=org_space_id,
        name="Replaced Prompt Guide",
    )

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (target_assistant, [])

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    await service.archive_helper(assistant_id=archivable_id)

    # Hard-delete routes through the existing assistant-service path so the
    # API-key revoker and icon cleanup run; the helper service itself does
    # not call ``assistant_repo.delete``.
    assistant_service.delete_assistant.assert_awaited_once_with(archivable_id)
    mocks["assistant_repo"].delete.assert_not_awaited()

    mocks["audit_service"].log_async.assert_awaited_once()
    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_ARCHIVED
    assert audit_kwargs["entity_id"] == archivable_id
    extra = audit_kwargs["metadata"]["extra"]
    assert extra["assistant_name_snapshot"] == "Replaced Prompt Guide"
    assert extra["org_space_id"] == str(org_space_id)


@pytest.mark.asyncio
async def test_archive_helper_captures_name_before_deletion():
    """Audit log carries the captured name so the trail survives the row.

    ``HelpAssistantAssignmentHistory.assistant_id`` is ``ON DELETE SET NULL``
    (per step 004) — after ``delete_assistant`` runs, the FK on every
    history row that referenced the assistant flips to NULL but the
    ``assistant_name_snapshot`` column survives. The audit log captures
    its own snapshot independently so future readers see the name even
    if every history row is later purged.
    """
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    archivable_id = uuid4()

    role_repo = AsyncMock()
    role_repo.list_for_org_space.return_value = []

    history_repo = AsyncMock()
    history_repo.list_replaced_assistant_ids_by_org_space.return_value = {archivable_id}

    target_assistant = _mock_assistant(
        assistant_id=archivable_id,
        space_id=org_space_id,
        name="Will be gone",
    )

    call_order: list[str] = []

    async def _get_assistant(*, assistant_id: UUID):
        call_order.append("get_assistant")
        return (target_assistant, [])

    async def _delete_assistant(assistant_id: UUID):
        call_order.append("delete_assistant")

    assistant_service = AsyncMock()
    assistant_service.get_assistant.side_effect = _get_assistant
    assistant_service.delete_assistant.side_effect = _delete_assistant

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
    )

    await service.archive_helper(assistant_id=archivable_id)

    # The assistant load must happen before deletion so the audit log
    # captures the name from a live row.
    assert call_order == ["get_assistant", "delete_assistant"]

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert (
        audit_kwargs["metadata"]["extra"]["assistant_name_snapshot"] == "Will be gone"
    )


@pytest.mark.asyncio
async def test_archive_helper_requires_admin():
    non_admin = _make_user()
    service, _ = _build_service(user=non_admin, org_space_id=uuid4())

    with pytest.raises(UnauthorizedException):
        await service.archive_helper(assistant_id=uuid4())

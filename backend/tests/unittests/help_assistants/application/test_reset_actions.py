"""Unit tests for the two admin reset actions on ``OrgSpaceAssistantRoleService``.

Step 016 covers:

- ``reset_instructions_only``: creates a new prompt attributed to the
  system user, flips ``PromptsAssistants.is_selected`` via ``_add_prompt``,
  writes an audit log, and **does not** append a history row.
- ``reset_to_default``: creates a fresh assistant in the org-space owned by
  the system user, swings the role assignment to it, writes a history row
  with ``reason=RESET_TO_DEFAULT`` and the captured ``assistant_name_snapshot``
  / ``replaced_by_assistant_id`` / ``actor_user_id`` fields, and writes an
  audit log. The previous helper assistant row remains in the DB
  untouched (archival is step 017).

Both gated on ``Permission.ADMIN``. DB round-trips are out of scope at
this layer — integration tests at ``tests/integration`` validate actual
``PromptsAssistants`` / ``Assistants`` row state.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from intric.audit.domain.action_types import ActionType
from intric.help_assistants.application.org_space_assistant_role_service import (
    OrgSpaceAssistantRoleService,
)
from intric.help_assistants.defaults import PROMPT_GUIDE_DEFAULTS
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
async def test_reset_instructions_only_creates_prompt_with_system_user_owner_and_no_history():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    assistant_id = uuid4()
    system_user_id = uuid4()
    new_prompt_id = uuid4()

    role_row = _make_role_row(
        role_id=uuid4(), org_space_id=org_space_id, assistant_id=assistant_id
    )
    helper_assistant = _mock_assistant(
        assistant_id=assistant_id, space_id=org_space_id, name="Prompt Guide"
    )
    new_prompt = MagicMock(id=new_prompt_id)

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role_row

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (helper_assistant, [])

    assistant_repo = AsyncMock()

    prompt_service = AsyncMock()
    prompt_service.create_prompt.return_value = new_prompt

    users_repo = AsyncMock()
    users_repo.get_system_user_id_for_tenant.return_value = system_user_id

    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
        assistant_repo=assistant_repo,
        prompt_service=prompt_service,
        users_repo=users_repo,
    )

    result = await service.reset_instructions_only(kind=HelperKind.PROMPT_GUIDE)

    assert result is helper_assistant

    prompt_service.create_prompt.assert_awaited_once_with(
        text=PROMPT_GUIDE_DEFAULTS.prompt_text,
        description="Reset to shipped default",
        owner_user_id=system_user_id,
    )
    # ``_add_prompt`` is the same flip-is_selected path that the standard
    # ``update_assistant`` flow uses internally — verify it was called for
    # the existing helper assistant (no new assistant row created).
    assistant_repo._add_prompt.assert_awaited_once_with(
        assistant_id=assistant_id, prompt=new_prompt
    )

    # Critical: no history row, no role-repo mutation.
    history_repo.add.assert_not_awaited()
    role_repo.add.assert_not_awaited()
    role_repo.update.assert_not_awaited()
    role_repo.delete.assert_not_awaited()

    mocks["audit_service"].log_async.assert_awaited_once()
    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_RESET_INSTRUCTIONS
    assert audit_kwargs["entity_id"] == assistant_id
    extra = audit_kwargs["metadata"]["extra"]
    assert extra["role_kind"] == HelperKind.PROMPT_GUIDE.value
    assert extra["new_prompt_id"] == str(new_prompt_id)


@pytest.mark.asyncio
async def test_reset_instructions_only_raises_when_no_active_assignment():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = None

    history_repo = AsyncMock()
    prompt_service = AsyncMock()
    assistant_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        prompt_service=prompt_service,
        assistant_repo=assistant_repo,
    )

    with pytest.raises(BadRequestException, match="No active assignment"):
        await service.reset_instructions_only(kind=HelperKind.PROMPT_GUIDE)

    prompt_service.create_prompt.assert_not_awaited()
    assistant_repo._add_prompt.assert_not_awaited()
    history_repo.add.assert_not_awaited()
    mocks["audit_service"].log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_instructions_only_requires_admin():
    non_admin = _make_user()  # no permissions
    org_space_id = uuid4()

    service, _ = _build_service(user=non_admin, org_space_id=org_space_id)

    with pytest.raises(UnauthorizedException):
        await service.reset_instructions_only(kind=HelperKind.PROMPT_GUIDE)


@pytest.mark.asyncio
async def test_reset_to_default_creates_new_helper_owned_by_system_user_and_swings_role():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    old_assistant_id = uuid4()
    role_id = uuid4()
    system_user_id = uuid4()
    new_prompt_id = uuid4()

    role_row = _make_role_row(
        role_id=role_id,
        org_space_id=org_space_id,
        assistant_id=old_assistant_id,
    )
    old_assistant = _mock_assistant(
        assistant_id=old_assistant_id,
        space_id=org_space_id,
        name="Customized Prompt Guide",
    )
    new_prompt = MagicMock(id=new_prompt_id)
    completion_model = MagicMock()
    completion_model.id = uuid4()

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role_row
    role_repo.update.return_value = role_row  # returned mutated in-place

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (old_assistant, [])

    assistant_repo = AsyncMock()
    prompt_service = AsyncMock()
    prompt_service.create_prompt.return_value = new_prompt

    users_repo = AsyncMock()
    users_repo.get_system_user_id_for_tenant.return_value = system_user_id

    completion_model_crud_service = AsyncMock()
    completion_model_crud_service.get_default_completion_model.return_value = (
        completion_model
    )

    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
        assistant_repo=assistant_repo,
        prompt_service=prompt_service,
        users_repo=users_repo,
        completion_model_crud_service=completion_model_crud_service,
    )

    new_assistant = await service.reset_to_default(kind=HelperKind.PROMPT_GUIDE)

    # New prompt created and attributed to the system user, not the admin.
    prompt_service.create_prompt.assert_awaited_once_with(
        text=PROMPT_GUIDE_DEFAULTS.prompt_text,
        description=PROMPT_GUIDE_DEFAULTS.description,
        owner_user_id=system_user_id,
    )

    # New assistant persisted exactly once via the repo (mirrors the seed
    # migration's direct-insert pattern, avoiding the actor-of-creator path).
    assistant_repo.add.assert_awaited_once()
    persisted = assistant_repo.add.await_args.args[0]
    assert persisted is new_assistant
    assert persisted.name == PROMPT_GUIDE_DEFAULTS.name
    assert persisted.description == PROMPT_GUIDE_DEFAULTS.description
    assert persisted.space_id == org_space_id
    assert persisted.user is not None
    assert persisted.user.id == system_user_id
    assert persisted.logging_enabled is False
    assert persisted.insight_enabled is False
    assert persisted.data_retention_days == PROMPT_GUIDE_DEFAULTS.data_retention_days
    assert persisted.prompt is new_prompt
    assert persisted.completion_model is completion_model
    assert persisted.id is not None  # service generates the UUID up front
    new_assistant_id = persisted.id

    # Role assignment swung to the new assistant; old role row is updated
    # (not deleted), preserving the ``UNIQUE(org_space_id, kind)`` slot.
    role_repo.update.assert_awaited_once()
    assert role_row.assistant_id == new_assistant_id
    assert role_row.updated_by_user_id == admin.id

    # History row written with the four required fields.
    history_repo.add.assert_awaited_once()
    history_entry = history_repo.add.await_args.args[0]
    assert history_entry.reason == AssignmentHistoryReason.RESET_TO_DEFAULT
    assert history_entry.assistant_id == old_assistant_id
    assert history_entry.assistant_name_snapshot == "Customized Prompt Guide"
    assert history_entry.replaced_by_assistant_id == new_assistant_id
    assert history_entry.actor_user_id == admin.id

    # Old assistant row is left in the DB (no delete/archive at this step).
    assistant_repo.delete.assert_not_called()
    assistant_repo.update.assert_not_awaited()

    audit_kwargs = mocks["audit_service"].log_async.await_args.kwargs
    assert audit_kwargs["action"] == ActionType.HELP_ASSISTANT_RESET_TO_DEFAULT
    assert audit_kwargs["entity_id"] == new_assistant_id
    extra = audit_kwargs["metadata"]["extra"]
    assert extra["role_kind"] == HelperKind.PROMPT_GUIDE.value
    assert extra["previous_assistant_id"] == str(old_assistant_id)
    assert extra["previous_assistant_name"] == "Customized Prompt Guide"


@pytest.mark.asyncio
async def test_reset_to_default_proceeds_without_completion_model_and_warns():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    old_assistant_id = uuid4()
    system_user_id = uuid4()

    role_row = _make_role_row(
        role_id=uuid4(),
        org_space_id=org_space_id,
        assistant_id=old_assistant_id,
    )
    old_assistant = _mock_assistant(
        assistant_id=old_assistant_id, space_id=org_space_id, name="Prompt Guide"
    )

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role_row
    role_repo.update.return_value = role_row

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (old_assistant, [])

    assistant_repo = AsyncMock()
    prompt_service = AsyncMock()
    prompt_service.create_prompt.return_value = MagicMock(id=uuid4())

    users_repo = AsyncMock()
    users_repo.get_system_user_id_for_tenant.return_value = system_user_id

    completion_model_crud_service = AsyncMock()
    completion_model_crud_service.get_default_completion_model.return_value = None

    history_repo = AsyncMock()

    service, _ = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
        assistant_repo=assistant_repo,
        prompt_service=prompt_service,
        users_repo=users_repo,
        completion_model_crud_service=completion_model_crud_service,
    )

    await service.reset_to_default(kind=HelperKind.PROMPT_GUIDE)

    persisted = assistant_repo.add.await_args.args[0]
    assert persisted.completion_model is None


@pytest.mark.asyncio
async def test_reset_to_default_raises_when_no_active_assignment():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = None

    assistant_repo = AsyncMock()
    prompt_service = AsyncMock()
    history_repo = AsyncMock()

    service, mocks = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_repo=assistant_repo,
        prompt_service=prompt_service,
    )

    with pytest.raises(BadRequestException, match="No active assignment"):
        await service.reset_to_default(kind=HelperKind.PROMPT_GUIDE)

    prompt_service.create_prompt.assert_not_awaited()
    assistant_repo.add.assert_not_awaited()
    history_repo.add.assert_not_awaited()
    mocks["audit_service"].log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_to_default_raises_when_system_user_missing():
    admin = _make_user(Permission.ADMIN)
    org_space_id = uuid4()
    old_assistant_id = uuid4()

    role_row = _make_role_row(
        role_id=uuid4(),
        org_space_id=org_space_id,
        assistant_id=old_assistant_id,
    )
    old_assistant = _mock_assistant(
        assistant_id=old_assistant_id, space_id=org_space_id, name="Prompt Guide"
    )

    role_repo = AsyncMock()
    role_repo.get_by_org_space_and_kind.return_value = role_row

    assistant_service = AsyncMock()
    assistant_service.get_assistant.return_value = (old_assistant, [])

    users_repo = AsyncMock()
    users_repo.get_system_user_id_for_tenant.return_value = None  # not seeded

    assistant_repo = AsyncMock()
    prompt_service = AsyncMock()
    history_repo = AsyncMock()

    service, _ = _build_service(
        user=admin,
        org_space_id=org_space_id,
        role_repo=role_repo,
        history_repo=history_repo,
        assistant_service=assistant_service,
        assistant_repo=assistant_repo,
        prompt_service=prompt_service,
        users_repo=users_repo,
    )

    with pytest.raises(BadRequestException, match="system user"):
        await service.reset_to_default(kind=HelperKind.PROMPT_GUIDE)

    prompt_service.create_prompt.assert_not_awaited()
    assistant_repo.add.assert_not_awaited()
    history_repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_to_default_requires_admin():
    non_admin = _make_user()
    org_space_id = uuid4()

    service, _ = _build_service(user=non_admin, org_space_id=org_space_id)

    with pytest.raises(UnauthorizedException):
        await service.reset_to_default(kind=HelperKind.PROMPT_GUIDE)

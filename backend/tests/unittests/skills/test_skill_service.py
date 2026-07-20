from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.skills.application.skill_service import SkillService
from eneo.skills.domain.skill import ResolvedSkillBinding, SkillBindingReference


def _binding(
    *,
    skill_id=None,
    revision_id=None,
    position: int = 0,
    active: bool = True,
) -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=skill_id or uuid4(),
        skill_revision_id=revision_id or uuid4(),
        slug="payroll",
        revision_number=1,
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the payroll handbook.",
        content_digest="a" * 64,
        position=position,
        is_active=active,
    )


def _binding_reference(binding: ResolvedSkillBinding) -> SkillBindingReference:
    return SkillBindingReference(
        skill_id=binding.skill_id,
        skill_revision_id=binding.skill_revision_id,
    )


def _service(*, space, actor=None, repo=None, permissions=None, active_api_key=None):
    actor = actor or MagicMock(
        can_read_assistant=MagicMock(return_value=True),
        can_edit_assistants=MagicMock(return_value=True),
        can_read_app=MagicMock(return_value=True),
        can_edit_apps=MagicMock(return_value=True),
        can_read_skills=MagicMock(return_value=True),
        can_create_skills=MagicMock(return_value=True),
        can_edit_skills=MagicMock(return_value=True),
        can_delete_skills=MagicMock(return_value=True),
    )
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor
    space_service = AsyncMock()
    space_service.get_space.return_value = space
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=space.tenant_id,
        permissions=permissions or {Permission.SKILLS, Permission.ASSISTANTS},
        active_api_key=active_api_key,
    )
    repo = repo or AsyncMock()
    repo.lock_assistant_space_for_update.return_value = space.id
    repo.lock_app_for_binding_update.return_value = True
    return SkillService(
        user=user,
        repo=repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )


def _space(*, personal=False, organization=False, default_assistant=False):
    assistant = SimpleNamespace(id=uuid4(), is_default=default_assistant)
    app = SimpleNamespace(id=uuid4())
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        get_assistant=MagicMock(return_value=assistant),
        get_app=MagicMock(return_value=app),
        is_personal=MagicMock(return_value=personal),
        is_organization=MagicMock(return_value=organization),
        assistant=assistant,
        app=app,
    )


async def test_reader_can_open_skill_detail_and_revision_history():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    revisions = [SimpleNamespace(id=uuid4())]
    repo = AsyncMock()
    repo.get.return_value = skill
    repo.list_revisions.return_value = revisions
    actor = MagicMock(
        can_read_skills=MagicMock(return_value=True),
        can_edit_skills=MagicMock(return_value=False),
    )
    service = _service(space=space, actor=actor, repo=repo)

    assert await service.get_skill(skill_id=skill.id) is skill
    assert await service.list_revisions(skill_id=skill.id) == revisions

    actor.can_read_skills.assert_called()
    actor.can_edit_skills.assert_not_called()


async def test_reader_cannot_create_skill_revision():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    actor = MagicMock(
        can_read_skills=MagicMock(return_value=True),
        can_edit_skills=MagicMock(return_value=False),
    )
    service = _service(space=space, actor=actor, repo=repo)

    with pytest.raises(UnauthorizedException, match="revise this Skill"):
        await service.create_revision(
            skill_id=skill.id,
            display_name="Payroll",
            description="Payroll guidance",
            instructions="Use the approved payroll guidance.",
        )

    repo.create_revision.assert_not_awaited()


async def test_same_space_skill_can_be_reused_by_multiple_parents():
    space = _space()
    binding = _binding()
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = []
    repo.resolve_references_for_binding_update.return_value = [binding]
    service = _service(space=space, repo=repo)

    first = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=uuid4(),
        references=[_binding_reference(binding)],
    )
    second = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=uuid4(),
        references=[_binding_reference(binding)],
    )

    assert first == [binding]
    assert second == [binding]
    assert repo.replace_assistant_bindings.await_count == 2


async def test_assistant_binding_update_rejects_a_concurrent_space_move():
    space = _space()
    repo = AsyncMock()
    service = _service(space=space, repo=repo)
    repo.lock_assistant_space_for_update.return_value = uuid4()

    with pytest.raises(NotFoundException):
        await service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=space.assistant.id,
            references=[],
        )

    repo.list_assistant_bindings.assert_not_awaited()
    repo.replace_assistant_bindings.assert_not_awaited()


async def test_missing_or_cross_space_revision_fails_before_replacing_bindings():
    space = _space()
    repo = AsyncMock()
    repo.list_app_bindings.return_value = []
    repo.resolve_references_for_binding_update.return_value = []
    service = _service(space=space, repo=repo)

    with pytest.raises(NotFoundException, match="do not exist in this Space"):
        await service.replace_app_bindings(
            space_id=space.id,
            app_id=space.app.id,
            references=[
                SkillBindingReference(
                    skill_id=uuid4(),
                    skill_revision_id=uuid4(),
                )
            ],
        )

    repo.replace_app_bindings.assert_not_awaited()


async def test_inactive_skill_cannot_receive_a_new_binding():
    space = _space()
    inactive = _binding(active=False)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = []
    repo.resolve_references_for_binding_update.return_value = [inactive]
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="Inactive Skills"):
        await service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=space.assistant.id,
            references=[_binding_reference(inactive)],
        )


async def test_existing_inactive_exact_revision_binding_can_be_reordered():
    space = _space()
    inactive = _binding(active=False)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [inactive]
    repo.resolve_references_for_binding_update.return_value = [inactive]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        references=[_binding_reference(inactive)],
    )

    assert result == [inactive]
    repo.replace_assistant_bindings.assert_awaited_once()


async def test_explicit_empty_reference_list_clears_all_app_bindings():
    space = _space()
    repo = AsyncMock()
    repo.list_app_bindings.return_value = [_binding()]
    repo.resolve_references_for_binding_update.return_value = []
    service = _service(space=space, repo=repo)

    result = await service.replace_app_bindings(
        space_id=space.id,
        app_id=space.app.id,
        references=[],
    )

    assert result == []
    repo.replace_app_bindings.assert_awaited_once_with(
        app_id=space.app.id,
        space_id=space.id,
        bindings=[],
    )


async def test_personal_default_assistant_direct_binding_fails_closed():
    space = _space(personal=True, default_assistant=True)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [_binding()]
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="invalid direct Skill bindings"):
        await service.list_assistant_bindings(
            space_id=space.id,
            assistant_id=space.assistant.id,
        )


@pytest.mark.parametrize(
    ("list_method", "parent_id_name", "parent_attribute", "read_permission"),
    [
        (
            "list_assistant_bindings",
            "assistant_id",
            "assistant",
            "can_read_assistant",
        ),
        ("list_app_bindings", "app_id", "app", "can_read_app"),
    ],
)
async def test_parent_reader_can_list_skill_bindings(
    list_method: str,
    parent_id_name: str,
    parent_attribute: str,
    read_permission: str,
):
    space = _space()
    parent = getattr(space, parent_attribute)
    binding = _binding()
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [binding]
    repo.list_app_bindings.return_value = [binding]
    actor = MagicMock(
        can_read_assistant=MagicMock(return_value=True),
        can_edit_assistants=MagicMock(return_value=False),
        can_read_app=MagicMock(return_value=True),
        can_edit_apps=MagicMock(return_value=False),
        can_read_skills=MagicMock(return_value=True),
    )
    service = _service(space=space, actor=actor, repo=repo)

    result = await getattr(service, list_method)(
        space_id=space.id,
        **{parent_id_name: parent.id},
    )

    assert result == [binding]
    getattr(actor, read_permission).assert_called_once_with(
        **{parent_attribute: parent}
    )


@pytest.mark.parametrize(
    ("list_method", "parent_id_name", "parent_attribute"),
    [
        ("list_assistant_bindings", "assistant_id", "assistant"),
        ("list_app_bindings", "app_id", "app"),
    ],
)
async def test_parent_reader_without_skill_read_permission_cannot_list_bindings(
    list_method: str,
    parent_id_name: str,
    parent_attribute: str,
):
    space = _space()
    parent = getattr(space, parent_attribute)
    repo = AsyncMock()
    actor = MagicMock(
        can_read_assistant=MagicMock(return_value=True),
        can_read_app=MagicMock(return_value=True),
        can_read_skills=MagicMock(return_value=False),
    )
    service = _service(space=space, actor=actor, repo=repo)

    with pytest.raises(UnauthorizedException, match="permission to read Skills"):
        await getattr(service, list_method)(
            space_id=space.id,
            **{parent_id_name: parent.id},
        )

    repo.list_assistant_bindings.assert_not_awaited()
    repo.list_app_bindings.assert_not_awaited()


@pytest.mark.parametrize(
    ("list_method", "parent_id_name", "parent_attribute"),
    [
        ("list_assistant_bindings", "assistant_id", "assistant"),
        ("list_app_bindings", "app_id", "app"),
    ],
)
async def test_unreadable_parent_skill_bindings_are_not_disclosed(
    list_method: str,
    parent_id_name: str,
    parent_attribute: str,
):
    space = _space()
    parent = getattr(space, parent_attribute)
    repo = AsyncMock()
    actor = MagicMock(
        can_read_assistant=MagicMock(return_value=False),
        can_read_app=MagicMock(return_value=False),
        can_read_skills=MagicMock(return_value=True),
    )
    service = _service(space=space, actor=actor, repo=repo)

    with pytest.raises(UnauthorizedException, match="permission to read this"):
        await getattr(service, list_method)(
            space_id=space.id,
            **{parent_id_name: parent.id},
        )

    repo.list_assistant_bindings.assert_not_awaited()
    repo.list_app_bindings.assert_not_awaited()


@pytest.mark.parametrize(
    ("replace_method", "parent_id_name", "parent_attribute"),
    [
        ("replace_assistant_bindings", "assistant_id", "assistant"),
        ("replace_app_bindings", "app_id", "app"),
    ],
)
async def test_parent_reader_cannot_replace_skill_bindings(
    replace_method: str,
    parent_id_name: str,
    parent_attribute: str,
):
    space = _space()
    parent = getattr(space, parent_attribute)
    repo = AsyncMock()
    actor = MagicMock(
        can_edit_assistants=MagicMock(return_value=False),
        can_edit_apps=MagicMock(return_value=False),
        can_read_skills=MagicMock(return_value=True),
    )
    service = _service(space=space, actor=actor, repo=repo)

    with pytest.raises(UnauthorizedException, match="permission to edit"):
        await getattr(service, replace_method)(
            space_id=space.id,
            **{parent_id_name: parent.id},
            references=[],
        )

    repo.replace_assistant_bindings.assert_not_awaited()
    repo.replace_app_bindings.assert_not_awaited()


@pytest.mark.parametrize(
    ("replace_method", "parent_id_name", "parent_id"),
    [
        ("replace_assistant_bindings", "assistant_id", uuid4()),
        ("replace_app_bindings", "app_id", uuid4()),
    ],
)
async def test_api_key_cannot_replace_parent_skill_bindings(
    replace_method: str,
    parent_id_name: str,
    parent_id,
):
    space = _space()
    repo = AsyncMock()
    service = _service(space=space, repo=repo, active_api_key=MagicMock())

    with pytest.raises(UnauthorizedException, match="session token"):
        await getattr(service, replace_method)(
            space_id=space.id,
            **{parent_id_name: parent_id},
            references=[],
        )

    repo.list_assistant_bindings.assert_not_awaited()
    repo.list_app_bindings.assert_not_awaited()


async def test_api_key_cannot_replace_governance_skill_bindings():
    space = _space(organization=True)
    repo = AsyncMock()
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
        active_api_key=MagicMock(),
    )

    with pytest.raises(UnauthorizedException, match="session token"):
        await service.replace_governance_bindings(
            policy_id=uuid4(),
            organization_space_id=space.id,
            references=[],
        )

    repo.list_policy_bindings.assert_not_awaited()


async def test_binding_abuse_guardrail_comes_from_deployment_settings():
    space = _space()
    repo = AsyncMock()
    repo.list_app_bindings.return_value = []
    service = _service(space=space, repo=repo)
    references = [
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
    ]

    with (
        patch(
            "eneo.skills.application.skill_service.get_settings",
            return_value=SimpleNamespace(skill_max_bindings=1),
        ),
        pytest.raises(BadRequestException, match="more than 1 Skills"),
    ):
        await service.replace_app_bindings(
            space_id=space.id,
            app_id=space.app.id,
            references=references,
        )

    repo.resolve_references_for_binding_update.assert_not_awaited()


async def test_governance_bindings_require_organization_space_in_same_tenant():
    space = _space(organization=False)
    service = _service(
        space=space,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    with pytest.raises(BadRequestException, match="organisation Space"):
        await service.replace_governance_bindings(
            policy_id=uuid4(),
            organization_space_id=space.id,
            references=[],
        )

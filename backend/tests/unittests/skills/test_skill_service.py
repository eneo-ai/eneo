from dataclasses import replace
from datetime import datetime, timezone
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
from eneo.skills.application.skill_service import SkillService
from eneo.skills.domain.skill import (
    SKILL_RUNTIME_POLICY_DEFAULTS,
    AssistantSkillBindingReplacement,
    ResolvedSkillBinding,
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingReference,
    SkillBindingSource,
    SkillCatalogEntry,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionSummary,
    SkillSlugConflictError,
)


def _binding(
    *,
    skill_id=None,
    revision_id=None,
    skill_space_id=None,
    position: int = 0,
    active: bool = True,
) -> ResolvedSkillBinding:
    resolved_skill_id = skill_id or uuid4()
    resolved_revision_id = revision_id or uuid4()
    return ResolvedSkillBinding(
        skill_id=resolved_skill_id,
        skill_revision_id=resolved_revision_id,
        current_revision_id=resolved_revision_id,
        skill_space_id=skill_space_id or uuid4(),
        slug="payroll",
        revision_number=1,
        current_revision_number=1,
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the payroll handbook.",
        content_digest="a" * 64,
        position=position,
        source=SkillBindingSource.SPACE,
        is_active=active,
    )


def _binding_reference(binding: ResolvedSkillBinding) -> SkillBindingReference:
    return SkillBindingReference(
        skill_id=binding.skill_id,
        skill_revision_id=binding.skill_revision_id,
    )


def _binding_intent(
    binding: ResolvedSkillBinding,
    *,
    activation_mode: SkillActivationMode | None = None,
) -> SkillBindingIntent:
    return SkillBindingIntent(
        reference=_binding_reference(binding),
        activation_mode=activation_mode,
    )


def _binding_intents(
    references: list[SkillBindingReference],
) -> list[SkillBindingIntent]:
    return [SkillBindingIntent(reference=reference) for reference in references]


def _revision(*, skill_id=None, revision_number: int = 1) -> SkillRevision:
    return SkillRevision(
        id=uuid4(),
        skill_id=skill_id or uuid4(),
        revision_number=revision_number,
        display_name=f"Payroll {revision_number}",
        description=f"Payroll guidance {revision_number}",
        instructions=f"Use approved payroll guidance {revision_number}.",
        content_digest=str(revision_number) * 64,
        created_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
    )


def _revision_summary(
    *, skill_id=None, revision_number: int = 1
) -> SkillRevisionSummary:
    return SkillRevisionSummary(
        id=uuid4(),
        skill_id=skill_id or uuid4(),
        revision_number=revision_number,
        display_name=f"Payroll {revision_number}",
        created_at=datetime.now(timezone.utc),
    )


def _catalog_entry(*, space_id, slug: str) -> SkillCatalogEntry:
    now = datetime.now(timezone.utc)
    return SkillCatalogEntry(
        id=uuid4(),
        space_id=space_id,
        slug=slug,
        is_active=True,
        current_revision_id=uuid4(),
        current_revision_number=1,
        display_name=slug.replace("-", " ").title(),
        description=f"Description for {slug}",
        content_digest="a" * 64,
        created_by_user_id=uuid4(),
        created_at=now,
        updated_at=now,
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
        permissions=(
            permissions
            if permissions is not None
            else {Permission.SKILLS, Permission.ASSISTANTS}
        ),
        active_api_key=active_api_key,
    )
    repo = repo or AsyncMock()
    repo.lock_assistant_space_for_update.return_value = space.id
    repo.lock_app_for_binding_update.return_value = True
    if not isinstance(repo.list_active_execution_blocks.return_value, dict):
        repo.list_active_execution_blocks.return_value = {}
    repo.get_or_seed_runtime_policy.return_value = SKILL_RUNTIME_POLICY_DEFAULTS
    return SkillService(
        user=user,
        repo=repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )


async def test_skill_slug_collision_is_reported_without_leaking_persistence_details():
    space = _space()
    repo = AsyncMock()
    repo.create.side_effect = SkillSlugConflictError
    service = _service(space=space, repo=repo)

    with pytest.raises(SkillSlugConflictError):
        await service.create_skill(
            space_id=space.id,
            slug="payroll",
            display_name="Payroll",
            description="Answers payroll questions",
            instructions="Use approved guidance.",
        )


async def test_organisation_skill_availability_uses_publication_not_status_toggle():
    space = _space(organization=True)
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="controlled by publication"):
        await service.set_active(skill_id=skill.id, is_active=False)

    repo.set_active.assert_not_awaited()


async def test_generic_space_create_rejects_organisation_skills_before_write():
    space = _space(organization=True)
    repo = AsyncMock()
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="organisation Skill workflow"):
        await service.create_skill(
            space_id=space.id,
            slug="payroll",
            display_name="Payroll",
            description="Answers payroll questions",
            instructions="Use approved guidance.",
        )

    repo.create.assert_not_awaited()


async def test_generic_space_revision_rejects_organisation_skills_before_write():
    space = _space(organization=True)
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="organisation Skill workflow"):
        await service.create_revision(
            skill_id=skill.id,
            display_name="Payroll",
            description="Answers payroll questions",
            instructions="Use approved guidance.",
        )

    repo.create_revision.assert_not_awaited()


async def test_generic_space_restore_rejects_organisation_skills_before_write():
    space = _space(organization=True)
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="organisation Skill workflow"):
        await service.restore_revision(
            space_id=space.id,
            skill_id=skill.id,
            source_revision_id=uuid4(),
            reviewed_current_revision_id=uuid4(),
        )

    repo.get_revision.assert_not_awaited()
    repo.create_revision.assert_not_awaited()


async def test_generic_space_delete_rejects_organisation_skills_before_write():
    space = _space(organization=True)
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="organisation Skill workflow"):
        await service.delete_skill(skill_id=skill.id)

    repo.delete.assert_not_awaited()


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


async def test_skill_catalog_uses_stable_bounded_slug_pages_without_duplicates():
    space = _space()
    entries = [
        _catalog_entry(space_id=space.id, slug=slug)
        for slug in ("alpha", "beta", "charlie", "delta")
    ]
    repo = AsyncMock()
    repo.list_catalog_entries.side_effect = [entries[:3], entries[2:]]
    repo.count_catalog_entries.return_value = len(entries)
    service = _service(space=space, repo=repo)

    first = await service.list_skills(
        space_id=space.id,
        limit=2,
        cursor=None,
        query="   ",
    )
    second = await service.list_skills(
        space_id=space.id,
        limit=2,
        cursor=first.next_cursor,
        query=None,
    )

    assert [item.slug for item in first.items] == ["alpha", "beta"]
    assert [item.slug for item in second.items] == ["charlie", "delta"]
    assert len(first.items) <= first.limit == 2
    assert len(second.items) <= second.limit == 2
    assert first.next_cursor == "beta"
    assert second.next_cursor is None
    assert first.total_count == second.total_count == 4
    assert not ({item.id for item in first.items} & {item.id for item in second.items})
    assert repo.list_catalog_entries.await_args_list[0].kwargs == {
        "space_id": space.id,
        "limit": 3,
        "after_slug": None,
        "query": None,
    }
    assert repo.list_catalog_entries.await_args_list[1].kwargs == {
        "space_id": space.id,
        "limit": 3,
        "after_slug": "beta",
        "query": None,
    }


async def test_skill_catalog_normalizes_search_and_rejects_invalid_inputs():
    space = _space()
    repo = AsyncMock()
    repo.list_catalog_entries.return_value = []
    repo.count_catalog_entries.return_value = 0
    service = _service(space=space, repo=repo)

    await service.list_skills(
        space_id=space.id,
        limit=25,
        cursor=None,
        query="  Payroll guidance  ",
    )

    repo.list_catalog_entries.assert_awaited_once_with(
        space_id=space.id,
        limit=26,
        after_slug=None,
        query="Payroll guidance",
    )
    repo.count_catalog_entries.assert_awaited_once_with(
        space_id=space.id,
        query="Payroll guidance",
    )

    for limit, cursor, query in (
        (0, None, None),
        (101, None, None),
        (25, "not a canonical cursor", None),
        (25, None, "x" * 201),
    ):
        with pytest.raises(BadRequestException, match="Skill catalog"):
            await service.list_skills(
                space_id=space.id,
                limit=limit,
                cursor=cursor,
                query=query,
            )


async def test_reader_can_open_skill_detail_and_bounded_revision_history():
    space = _space()
    skill = SimpleNamespace(
        id=uuid4(),
        space_id=space.id,
        current_revision_number=5,
    )
    revisions = [
        _revision_summary(skill_id=skill.id, revision_number=5),
        _revision_summary(skill_id=skill.id, revision_number=4),
        _revision_summary(skill_id=skill.id, revision_number=3),
    ]
    repo = AsyncMock()
    repo.get.return_value = skill
    repo.list_revision_summaries.return_value = revisions
    repo.count_revisions.return_value = 5
    actor = MagicMock(
        can_read_skills=MagicMock(return_value=True),
        can_edit_skills=MagicMock(return_value=False),
    )
    service = _service(space=space, actor=actor, repo=repo)

    assert await service.get_skill(skill_id=skill.id) is skill
    page = await service.list_revision_summaries(
        space_id=space.id,
        skill_id=skill.id,
        limit=2,
        cursor="6",
    )

    assert [revision.revision_number for revision in page.items] == [5, 4]
    assert page.next_cursor == 4
    assert page.total_count == 5
    repo.list_revision_summaries.assert_awaited_once_with(
        skill_id=skill.id,
        limit=3,
        before_revision_number=6,
    )
    repo.count_revisions.assert_awaited_once_with(skill_id=skill.id)
    actor.can_read_skills.assert_called()
    actor.can_edit_skills.assert_not_called()


@pytest.mark.parametrize("cursor", ["0", "-1", "not-a-number"])
async def test_revision_history_rejects_invalid_cursors(cursor: str):
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="revision cursor"):
        await service.list_revision_summaries(
            space_id=space.id,
            skill_id=skill.id,
            limit=25,
            cursor=cursor,
        )

    repo.list_revision_summaries.assert_not_awaited()


async def test_reader_can_get_one_exact_skill_revision():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    revision = _revision(skill_id=skill.id, revision_number=2)
    repo = AsyncMock()
    repo.get.return_value = skill
    repo.get_revision.return_value = revision
    actor = MagicMock(
        can_read_skills=MagicMock(return_value=True),
        can_edit_skills=MagicMock(return_value=False),
    )
    service = _service(space=space, actor=actor, repo=repo)

    result = await service.get_revision(
        space_id=space.id,
        skill_id=skill.id,
        revision_id=revision.id,
    )

    assert result is revision
    repo.get_revision.assert_awaited_once_with(
        skill_id=skill.id,
        revision_id=revision.id,
    )
    actor.can_edit_skills.assert_not_called()


async def test_exact_skill_revision_rejects_a_different_space_path():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    service = _service(space=space, repo=repo)

    with pytest.raises(NotFoundException):
        await service.get_revision(
            space_id=uuid4(),
            skill_id=skill.id,
            revision_id=uuid4(),
        )

    repo.get_revision.assert_not_awaited()


async def test_missing_or_cross_skill_revision_is_not_found():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    repo.get_revision.return_value = None
    service = _service(space=space, repo=repo)

    with pytest.raises(NotFoundException):
        await service.get_revision(
            space_id=space.id,
            skill_id=skill.id,
            revision_id=uuid4(),
        )


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


async def test_editor_restores_exact_historical_content_as_a_new_revision():
    space = _space()
    skill_id = uuid4()
    source = _revision(skill_id=skill_id, revision_number=2)
    restored = _revision(skill_id=skill_id, revision_number=5)
    skill = SimpleNamespace(id=skill_id, space_id=space.id)
    change = SkillRevisionChange(
        skill=skill,
        revision=restored,
        created=True,
        previous_revision_number=4,
    )
    repo = AsyncMock()
    repo.get.return_value = skill
    repo.get_revision.return_value = source
    repo.create_revision.return_value = change
    service = _service(space=space, repo=repo)
    reviewed_current_revision_id = uuid4()

    outcome = await service.restore_revision(
        space_id=space.id,
        skill_id=skill.id,
        source_revision_id=source.id,
        reviewed_current_revision_id=reviewed_current_revision_id,
    )

    assert outcome.change.skill is skill
    assert outcome.source_revision is source
    assert outcome.change is change
    repo.get_revision.assert_awaited_once_with(
        skill_id=skill.id,
        revision_id=source.id,
    )
    repo.create_revision.assert_awaited_once_with(
        skill_id=skill.id,
        display_name=source.display_name,
        description=source.description,
        instructions=source.instructions,
        content_digest=source.content_digest,
        created_by_user_id=service.user.id,
        expected_current_revision_id=reviewed_current_revision_id,
    )


async def test_restore_rejects_a_different_space_before_reading_the_source():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    service = _service(space=space, repo=repo)

    with pytest.raises(NotFoundException):
        await service.restore_revision(
            space_id=uuid4(),
            skill_id=skill.id,
            source_revision_id=uuid4(),
            reviewed_current_revision_id=uuid4(),
        )

    repo.get_revision.assert_not_awaited()
    repo.create_revision.assert_not_awaited()


async def test_reader_cannot_restore_a_skill_revision():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    actor = MagicMock(
        can_read_skills=MagicMock(return_value=True),
        can_edit_skills=MagicMock(return_value=False),
    )
    service = _service(space=space, actor=actor, repo=repo)

    with pytest.raises(UnauthorizedException, match="restore this Skill"):
        await service.restore_revision(
            space_id=space.id,
            skill_id=skill.id,
            source_revision_id=uuid4(),
            reviewed_current_revision_id=uuid4(),
        )

    repo.get_revision.assert_not_awaited()
    repo.create_revision.assert_not_awaited()


async def test_missing_or_cross_skill_restore_source_is_not_found():
    space = _space()
    skill = SimpleNamespace(id=uuid4(), space_id=space.id)
    repo = AsyncMock()
    repo.get.return_value = skill
    repo.get_revision.return_value = None
    service = _service(space=space, repo=repo)

    with pytest.raises(NotFoundException):
        await service.restore_revision(
            space_id=space.id,
            skill_id=skill.id,
            source_revision_id=uuid4(),
            reviewed_current_revision_id=uuid4(),
        )

    repo.create_revision.assert_not_awaited()


async def test_same_space_skill_can_be_reused_by_multiple_parents():
    space = _space()
    binding = _binding(skill_space_id=space.id)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = []
    repo.resolve_local_references_for_binding_update.return_value = [binding]
    service = _service(space=space, repo=repo)

    first = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=uuid4(),
        intents=[_binding_intent(binding)],
    )
    second = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=uuid4(),
        intents=[_binding_intent(binding)],
    )

    assert first == AssistantSkillBindingReplacement(
        bindings=(binding,), on_demand_skill_ids_requiring_validation=frozenset()
    )
    assert second == AssistantSkillBindingReplacement(
        bindings=(binding,), on_demand_skill_ids_requiring_validation=frozenset()
    )
    assert repo.replace_assistant_bindings.await_count == 2


@pytest.mark.parametrize(
    ("replace_method", "parent_id_name", "parent_attribute", "list_method"),
    [
        (
            "replace_assistant_bindings",
            "assistant_id",
            "assistant",
            "list_assistant_bindings",
        ),
        ("replace_app_bindings", "app_id", "app", "list_app_bindings"),
    ],
)
async def test_resource_binding_resolves_local_and_published_catalogue_skills(
    replace_method: str,
    parent_id_name: str,
    parent_attribute: str,
    list_method: str,
):
    space = _space()
    local = _binding(skill_space_id=space.id)
    published = _binding()
    repo = AsyncMock()
    getattr(repo, list_method).return_value = []
    repo.resolve_local_references_for_binding_update.return_value = [local]
    repo.resolve_published_references_for_binding_update.return_value = [published]
    service = _service(space=space, repo=repo)

    references = [_binding_reference(local), _binding_reference(published)]
    if replace_method == "replace_assistant_bindings":
        replacement = await service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=getattr(space, parent_attribute).id,
            intents=[SkillBindingIntent(reference=value) for value in references],
        )
        result = list(replacement.bindings)
    else:
        result = await getattr(service, replace_method)(
            space_id=space.id,
            **{parent_id_name: getattr(space, parent_attribute).id},
            references=references,
        )

    assert result == [local, replace(published, position=1)]
    repo.resolve_local_references_for_binding_update.assert_awaited_once_with(
        space_id=space.id,
        references=[_binding_reference(local), _binding_reference(published)],
    )
    repo.resolve_published_references_for_binding_update.assert_awaited_once_with(
        tenant_id=space.tenant_id,
        references=[_binding_reference(published)],
    )


@pytest.mark.parametrize("owner", ["assistant", "app", "governance"])
async def test_blocked_organization_skill_cannot_receive_new_binding(owner: str):
    space = _space(organization=owner == "governance")
    blocked = _binding()
    repo = AsyncMock()
    repo.list_active_execution_blocks.return_value = {blocked.skill_id: MagicMock()}
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    with pytest.raises(
        BadRequestException,
        match="Blocked organisation Skills cannot receive new or changed bindings",
    ):
        if owner == "assistant":
            await service.replace_assistant_bindings(
                space_id=space.id,
                assistant_id=space.assistant.id,
                intents=[_binding_intent(blocked)],
            )
        elif owner == "app":
            await service.replace_app_bindings(
                space_id=space.id,
                app_id=space.app.id,
                references=[_binding_reference(blocked)],
            )
        else:
            await service.replace_governance_bindings(
                policy_id=uuid4(),
                organization_space_id=space.id,
                intents=[_binding_intent(blocked)],
            )


@pytest.mark.parametrize("owner", ["assistant", "app", "governance"])
async def test_blocked_organization_skill_cannot_change_revision(owner: str):
    space = _space(organization=owner == "governance")
    existing = _binding()
    changed = _binding(skill_id=existing.skill_id)
    repo = AsyncMock()
    repo.list_active_execution_blocks.return_value = {changed.skill_id: MagicMock()}
    if owner == "assistant":
        repo.list_assistant_bindings.return_value = [existing]
    elif owner == "app":
        repo.list_app_bindings.return_value = [existing]
    else:
        repo.list_policy_bindings.return_value = [existing]
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    with pytest.raises(
        BadRequestException,
        match="Blocked organisation Skills cannot receive new or changed bindings",
    ):
        if owner == "assistant":
            await service.replace_assistant_bindings(
                space_id=space.id,
                assistant_id=space.assistant.id,
                intents=[_binding_intent(changed)],
            )
        elif owner == "app":
            await service.replace_app_bindings(
                space_id=space.id,
                app_id=space.app.id,
                references=[_binding_reference(changed)],
            )
        else:
            await service.replace_governance_bindings(
                policy_id=uuid4(),
                organization_space_id=space.id,
                intents=[_binding_intent(changed)],
            )


@pytest.mark.parametrize(
    ("existing_mode", "requested_mode"),
    [
        (SkillActivationMode.ALWAYS, SkillActivationMode.ON_DEMAND),
        (SkillActivationMode.ON_DEMAND, SkillActivationMode.ALWAYS),
    ],
)
async def test_blocked_retained_assistant_binding_cannot_change_activation_mode(
    existing_mode: SkillActivationMode,
    requested_mode: SkillActivationMode,
):
    space = _space()
    blocked = replace(
        _binding(),
        source=SkillBindingSource.ORGANIZATION,
        activation_mode=existing_mode,
    )
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [blocked]
    repo.resolve_bound_references_for_binding_update.return_value = [blocked]
    repo.list_active_execution_blocks.return_value = {blocked.skill_id: MagicMock()}
    service = _service(space=space, repo=repo)

    with pytest.raises(
        BadRequestException,
        match="Blocked organisation Skills cannot receive new or changed bindings",
    ):
        await service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=space.assistant.id,
            intents=[_binding_intent(blocked, activation_mode=requested_mode)],
        )

    repo.replace_assistant_bindings.assert_not_awaited()


@pytest.mark.parametrize("existing_mode", list(SkillActivationMode))
@pytest.mark.parametrize("explicit_mode", [False, True])
async def test_blocked_retained_assistant_binding_accepts_unchanged_mode(
    existing_mode: SkillActivationMode,
    explicit_mode: bool,
):
    space = _space()
    blocked = replace(
        _binding(),
        source=SkillBindingSource.ORGANIZATION,
        activation_mode=existing_mode,
    )
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [blocked]
    repo.resolve_bound_references_for_binding_update.return_value = [blocked]
    repo.list_active_execution_blocks.return_value = {blocked.skill_id: MagicMock()}
    service = _service(space=space, repo=repo)

    replacement = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[
            _binding_intent(
                blocked,
                activation_mode=existing_mode if explicit_mode else None,
            )
        ],
    )

    assert replacement.bindings[0].activation_mode is existing_mode
    persisted = repo.replace_assistant_bindings.await_args.kwargs["bindings"]
    assert persisted[0].activation_mode is existing_mode


@pytest.mark.parametrize("owner", ["assistant", "app", "governance"])
async def test_blocked_retained_bindings_can_be_reordered(owner: str):
    space = _space(organization=owner == "governance")
    first = _binding(position=0)
    second = _binding(position=1)
    repo = AsyncMock()
    repo.resolve_bound_references_for_binding_update.return_value = [second, first]
    if owner == "assistant":
        repo.list_assistant_bindings.return_value = [first, second]
    elif owner == "app":
        repo.list_app_bindings.return_value = [first, second]
    else:
        repo.list_policy_bindings.return_value = [first, second]
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )
    reversed_references = [_binding_reference(second), _binding_reference(first)]

    if owner == "assistant":
        result = await service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=space.assistant.id,
            intents=[
                SkillBindingIntent(reference=reference)
                for reference in reversed_references
            ],
        )
    elif owner == "app":
        result = await service.replace_app_bindings(
            space_id=space.id,
            app_id=space.app.id,
            references=reversed_references,
        )
    else:
        result = await service.replace_governance_bindings(
            policy_id=uuid4(),
            organization_space_id=space.id,
            intents=_binding_intents(reversed_references),
        )

    bindings = result.bindings if owner == "assistant" else result
    assert [binding.skill_id for binding in bindings] == [
        second.skill_id,
        first.skill_id,
    ]
    assert [binding.position for binding in bindings] == [0, 1]
    repo.list_active_execution_blocks.assert_not_awaited()


async def test_assistant_binding_projection_derives_block_state_for_current_tenant():
    space = _space()
    blocked = _binding(position=0)
    available = _binding(position=1)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [blocked, available]
    repo.list_active_execution_blocks.return_value = {
        blocked.skill_id: MagicMock(skill_id=blocked.skill_id)
    }
    service = _service(space=space, repo=repo)

    projections = await service.list_assistant_binding_projections(
        space_id=space.id,
        assistant_id=space.assistant.id,
    )

    assert [projection.binding for projection in projections] == [
        blocked,
        available,
    ]
    assert [projection.execution_blocked for projection in projections] == [
        True,
        False,
    ]
    repo.list_active_execution_blocks.assert_awaited_once_with(
        tenant_id=space.tenant_id,
        skill_ids=[blocked.skill_id, available.skill_id],
    )


@pytest.mark.parametrize(
    ("replace_method", "parent_id_name", "parent_attribute", "list_method"),
    [
        (
            "replace_assistant_bindings",
            "assistant_id",
            "assistant",
            "list_assistant_bindings",
        ),
        ("replace_app_bindings", "app_id", "app", "list_app_bindings"),
    ],
)
async def test_organization_space_resource_rejects_unpublished_skill_revision(
    replace_method: str,
    parent_id_name: str,
    parent_attribute: str,
    list_method: str,
):
    space = _space(organization=True)
    draft = _binding(skill_space_id=space.id)
    repo = AsyncMock()
    getattr(repo, list_method).return_value = []
    repo.resolve_published_references_for_binding_update.return_value = []
    service = _service(space=space, repo=repo)

    with pytest.raises(NotFoundException, match="unavailable"):
        if replace_method == "replace_assistant_bindings":
            await service.replace_assistant_bindings(
                space_id=space.id,
                assistant_id=getattr(space, parent_attribute).id,
                intents=[_binding_intent(draft)],
            )
        else:
            await getattr(service, replace_method)(
                space_id=space.id,
                **{parent_id_name: getattr(space, parent_attribute).id},
                references=[_binding_reference(draft)],
            )

    repo.resolve_local_references_for_binding_update.assert_not_awaited()


async def test_existing_unpublished_catalogue_binding_can_remain_on_resource():
    space = _space()
    existing = _binding(active=False)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [existing]
    repo.resolve_bound_references_for_binding_update.return_value = [existing]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[_binding_intent(existing)],
    )

    assert result.bindings == (existing,)
    assert result.on_demand_skill_ids_requiring_validation == frozenset()
    repo.resolve_bound_references_for_binding_update.assert_awaited_once_with(
        tenant_id=space.tenant_id,
        parent_space_id=space.id,
        references=[_binding_reference(existing)],
    )
    repo.resolve_local_references_for_binding_update.assert_not_awaited()
    repo.resolve_published_references_for_binding_update.assert_not_awaited()


async def test_assistant_binding_update_rejects_a_concurrent_space_move():
    space = _space()
    repo = AsyncMock()
    service = _service(space=space, repo=repo)
    repo.lock_assistant_space_for_update.return_value = uuid4()

    with pytest.raises(NotFoundException):
        await service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=space.assistant.id,
            intents=[],
        )

    repo.list_assistant_bindings.assert_not_awaited()
    repo.replace_assistant_bindings.assert_not_awaited()


async def test_missing_or_cross_space_revision_fails_before_replacing_bindings():
    space = _space()
    repo = AsyncMock()
    repo.list_app_bindings.return_value = []
    repo.resolve_local_references_for_binding_update.return_value = []
    repo.resolve_published_references_for_binding_update.return_value = []
    service = _service(space=space, repo=repo)

    with pytest.raises(NotFoundException, match="unavailable"):
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
    repo.resolve_local_references_for_binding_update.return_value = [inactive]
    service = _service(space=space, repo=repo)

    with pytest.raises(BadRequestException, match="Inactive Skills"):
        await service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=space.assistant.id,
            intents=[_binding_intent(inactive)],
        )


async def test_existing_inactive_exact_revision_binding_can_be_reordered():
    space = _space()
    inactive = _binding(active=False)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [inactive]
    repo.resolve_bound_references_for_binding_update.return_value = [inactive]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[_binding_intent(inactive)],
    )

    assert result.bindings == (inactive,)
    assert result.on_demand_skill_ids_requiring_validation == frozenset()
    repo.replace_assistant_bindings.assert_awaited_once()


async def test_explicit_empty_reference_list_clears_all_app_bindings():
    space = _space()
    repo = AsyncMock()
    repo.list_app_bindings.return_value = [_binding()]
    service = _service(space=space, repo=repo)

    result = await service.replace_app_bindings(
        space_id=space.id,
        app_id=space.app.id,
        references=[],
    )

    assert result == []
    repo.replace_app_bindings.assert_awaited_once_with(
        app_id=space.app.id,
        tenant_id=space.tenant_id,
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
        if replace_method == "replace_assistant_bindings":
            await service.replace_assistant_bindings(
                space_id=space.id,
                assistant_id=parent.id,
                intents=[],
            )
        else:
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
        if replace_method == "replace_assistant_bindings":
            await service.replace_assistant_bindings(
                space_id=space.id,
                assistant_id=parent_id,
                intents=[],
            )
        else:
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
            intents=[],
        )

    repo.list_policy_bindings.assert_not_awaited()


async def test_governance_binding_accepts_only_exact_published_new_revision():
    space = _space(organization=True)
    published = _binding()
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = []
    repo.resolve_published_references_for_binding_update.return_value = [published]
    actor = MagicMock(
        can_read_skills=MagicMock(return_value=True),
        can_edit_skills=MagicMock(return_value=False),
    )
    service = _service(
        space=space,
        actor=actor,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    result = await service.replace_governance_bindings(
        policy_id=uuid4(),
        organization_space_id=space.id,
        intents=[_binding_intent(published)],
    )

    assert result == [published]
    repo.resolve_published_references_for_binding_update.assert_awaited_once_with(
        tenant_id=space.tenant_id,
        references=[_binding_reference(published)],
    )
    repo.resolve_bound_references_for_binding_update.assert_not_awaited()
    repo.resolve_local_references_for_binding_update.assert_not_awaited()


async def test_governance_binding_rejects_unpublished_or_unapproved_new_revision():
    space = _space(organization=True)
    draft = _binding()
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = []
    repo.resolve_published_references_for_binding_update.return_value = []
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    with pytest.raises(
        BadRequestException, match="published organisation Skill versions"
    ):
        await service.replace_governance_bindings(
            policy_id=uuid4(),
            organization_space_id=space.id,
            intents=[_binding_intent(draft)],
        )

    repo.replace_policy_bindings.assert_not_awaited()


async def test_existing_unpublished_governance_binding_can_remain():
    space = _space(organization=True)
    existing = _binding(active=False)
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = [existing]
    repo.resolve_bound_references_for_binding_update.return_value = [existing]
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    result = await service.replace_governance_bindings(
        policy_id=uuid4(),
        organization_space_id=space.id,
        intents=[_binding_intent(existing)],
    )

    assert result == [existing]
    repo.resolve_bound_references_for_binding_update.assert_awaited_once_with(
        tenant_id=space.tenant_id,
        parent_space_id=space.id,
        references=[_binding_reference(existing)],
    )
    repo.resolve_published_references_for_binding_update.assert_not_awaited()
    repo.replace_policy_bindings.assert_awaited_once()


async def test_tenant_admin_without_space_skill_use_can_replace_governance_bindings():
    space = _space(organization=True)
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = []
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN},
    )

    result = await service.replace_governance_bindings(
        policy_id=uuid4(),
        organization_space_id=space.id,
        intents=[],
    )

    assert result == []
    repo.list_policy_bindings.assert_awaited_once()
    repo.replace_policy_bindings.assert_awaited_once()


async def test_skill_user_without_tenant_admin_cannot_replace_governance_bindings():
    space = _space(organization=True)
    repo = AsyncMock()
    actor = MagicMock(can_read_skills=MagicMock(return_value=True))
    service = _service(
        space=space,
        actor=actor,
        repo=repo,
        permissions={Permission.SKILLS},
    )

    with pytest.raises(UnauthorizedException, match="permission admin"):
        await service.replace_governance_bindings(
            policy_id=uuid4(),
            organization_space_id=space.id,
            intents=[],
        )

    repo.list_policy_bindings.assert_not_awaited()


async def test_binding_abuse_guardrail_comes_from_stored_runtime_policy():
    space = _space()
    repo = AsyncMock()
    repo.list_app_bindings.return_value = []
    service = _service(space=space, repo=repo)
    repo.get_or_seed_runtime_policy.return_value = replace(
        SKILL_RUNTIME_POLICY_DEFAULTS, max_attached_skills=1
    )
    references = [
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
    ]

    with pytest.raises(BadRequestException, match="more than 1 Skills"):
        await service.replace_app_bindings(
            space_id=space.id,
            app_id=space.app.id,
            references=references,
        )

    repo.get_or_seed_runtime_policy.assert_awaited_once_with(
        tenant_id=space.tenant_id, shared_lock=True
    )
    repo.resolve_bound_references_for_binding_update.assert_not_awaited()
    repo.resolve_local_references_for_binding_update.assert_not_awaited()


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
            intents=[],
        )


async def test_retained_assistant_binding_keeps_activation_mode_on_resave():
    space = _space()
    existing = replace(_binding(), activation_mode=SkillActivationMode.ON_DEMAND)
    freshly_resolved = replace(existing, activation_mode=SkillActivationMode.ALWAYS)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [existing]
    repo.resolve_bound_references_for_binding_update.return_value = [freshly_resolved]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[_binding_intent(existing)],
    )

    assert result.bindings[0].activation_mode is SkillActivationMode.ON_DEMAND
    assert result.on_demand_skill_ids_requiring_validation == frozenset()
    persisted = repo.replace_assistant_bindings.await_args.kwargs["bindings"]
    assert [binding.activation_mode for binding in persisted] == [
        SkillActivationMode.ON_DEMAND
    ]


async def test_retained_governance_binding_keeps_activation_mode_on_resave():
    space = _space(organization=True)
    existing = replace(_binding(), activation_mode=SkillActivationMode.ON_DEMAND)
    freshly_resolved = replace(existing, activation_mode=SkillActivationMode.ALWAYS)
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = [existing]
    repo.resolve_bound_references_for_binding_update.return_value = [freshly_resolved]
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    result = await service.replace_governance_bindings(
        policy_id=uuid4(),
        organization_space_id=space.id,
        intents=[_binding_intent(existing)],
    )

    assert result[0].activation_mode is SkillActivationMode.ON_DEMAND
    persisted = repo.replace_policy_bindings.await_args.kwargs["bindings"]
    assert [binding.activation_mode for binding in persisted] == [
        SkillActivationMode.ON_DEMAND
    ]


async def test_retained_governance_binding_applies_explicit_activation_mode():
    space = _space(organization=True)
    existing = replace(_binding(), activation_mode=SkillActivationMode.ALWAYS)
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = [existing]
    repo.resolve_bound_references_for_binding_update.return_value = [existing]
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    result = await service.replace_governance_bindings(
        policy_id=uuid4(),
        organization_space_id=space.id,
        intents=[
            _binding_intent(
                existing,
                activation_mode=SkillActivationMode.ON_DEMAND,
            )
        ],
    )

    assert result[0].activation_mode is SkillActivationMode.ON_DEMAND
    persisted = repo.replace_policy_bindings.await_args.kwargs["bindings"]
    assert [binding.activation_mode for binding in persisted] == [
        SkillActivationMode.ON_DEMAND
    ]


async def test_blocked_governance_binding_rejects_activation_mode_change():
    space = _space(organization=True)
    blocked = replace(
        _binding(),
        source=SkillBindingSource.ORGANIZATION,
        activation_mode=SkillActivationMode.ALWAYS,
    )
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = [blocked]
    repo.resolve_bound_references_for_binding_update.return_value = [blocked]
    repo.list_active_execution_blocks.return_value = {blocked.skill_id: MagicMock()}
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    with pytest.raises(
        BadRequestException,
        match="Blocked organisation Skills cannot receive new or changed bindings",
    ):
        await service.replace_governance_bindings(
            policy_id=uuid4(),
            organization_space_id=space.id,
            intents=[
                _binding_intent(
                    blocked,
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )

    repo.replace_policy_bindings.assert_not_awaited()


async def test_new_binding_defaults_to_always_activation_mode():
    space = _space()
    added = _binding()
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = []
    repo.resolve_local_references_for_binding_update.return_value = [added]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[_binding_intent(added)],
    )

    assert [binding.activation_mode for binding in result.bindings] == [
        SkillActivationMode.ALWAYS
    ]
    assert result.on_demand_skill_ids_requiring_validation == frozenset()


async def test_explicit_assistant_mode_only_change_is_persisted_and_reported():
    space = _space()
    existing = replace(_binding(), activation_mode=SkillActivationMode.ALWAYS)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [existing]
    repo.resolve_bound_references_for_binding_update.return_value = [existing]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[
            _binding_intent(
                existing,
                activation_mode=SkillActivationMode.ON_DEMAND,
            )
        ],
    )

    assert result.on_demand_skill_ids_requiring_validation == frozenset(
        {existing.skill_id}
    )
    assert result.bindings[0].activation_mode is SkillActivationMode.ON_DEMAND
    persisted = repo.replace_assistant_bindings.await_args.kwargs["bindings"]
    assert persisted[0].activation_mode is SkillActivationMode.ON_DEMAND


async def test_assistant_reorder_preserves_omitted_mode_and_applies_explicit_mode():
    space = _space()
    first = replace(
        _binding(position=0),
        activation_mode=SkillActivationMode.ON_DEMAND,
    )
    second = replace(
        _binding(position=1),
        activation_mode=SkillActivationMode.ALWAYS,
    )
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [first, second]
    repo.resolve_bound_references_for_binding_update.return_value = [second, first]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[
            _binding_intent(
                second,
                activation_mode=SkillActivationMode.ON_DEMAND,
            ),
            _binding_intent(first),
        ],
    )

    assert [binding.skill_id for binding in result.bindings] == [
        second.skill_id,
        first.skill_id,
    ]
    assert [binding.position for binding in result.bindings] == [0, 1]
    assert [binding.activation_mode for binding in result.bindings] == [
        SkillActivationMode.ON_DEMAND,
        SkillActivationMode.ON_DEMAND,
    ]
    assert result.on_demand_skill_ids_requiring_validation == frozenset(
        {second.skill_id}
    )


async def test_assistant_revision_upgrade_keeps_activation_mode():
    space = _space()
    existing = replace(_binding(), activation_mode=SkillActivationMode.ON_DEMAND)
    upgraded = replace(
        _binding(skill_id=existing.skill_id),
        activation_mode=SkillActivationMode.ALWAYS,
    )
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [existing]
    repo.resolve_local_references_for_binding_update.return_value = [upgraded]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[_binding_intent(upgraded)],
    )

    assert [binding.activation_mode for binding in result.bindings] == [
        SkillActivationMode.ON_DEMAND
    ]
    assert result.on_demand_skill_ids_requiring_validation == frozenset(
        {existing.skill_id}
    )
    persisted = repo.replace_assistant_bindings.await_args.kwargs["bindings"]
    assert [binding.activation_mode for binding in persisted] == [
        SkillActivationMode.ON_DEMAND
    ]


async def test_assistant_revision_upgrade_applies_explicit_mode_change():
    space = _space()
    existing = replace(_binding(), activation_mode=SkillActivationMode.ON_DEMAND)
    upgraded = replace(
        _binding(skill_id=existing.skill_id),
        activation_mode=SkillActivationMode.ALWAYS,
    )
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [existing]
    repo.resolve_local_references_for_binding_update.return_value = [upgraded]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[
            _binding_intent(
                upgraded,
                activation_mode=SkillActivationMode.ALWAYS,
            )
        ],
    )

    assert result.bindings[0].skill_revision_id == upgraded.skill_revision_id
    assert result.bindings[0].activation_mode is SkillActivationMode.ALWAYS
    assert result.on_demand_skill_ids_requiring_validation == frozenset()


async def test_echoing_existing_on_demand_mode_is_not_reported_as_a_change():
    space = _space()
    existing = replace(_binding(), activation_mode=SkillActivationMode.ON_DEMAND)
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = [existing]
    repo.resolve_bound_references_for_binding_update.return_value = [existing]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[
            _binding_intent(
                existing,
                activation_mode=SkillActivationMode.ON_DEMAND,
            )
        ],
    )

    assert result.bindings[0].activation_mode is SkillActivationMode.ON_DEMAND
    assert result.on_demand_skill_ids_requiring_validation == frozenset()


async def test_new_on_demand_binding_is_reported_as_a_change():
    space = _space()
    added = _binding()
    repo = AsyncMock()
    repo.list_assistant_bindings.return_value = []
    repo.resolve_local_references_for_binding_update.return_value = [added]
    service = _service(space=space, repo=repo)

    result = await service.replace_assistant_bindings(
        space_id=space.id,
        assistant_id=space.assistant.id,
        intents=[
            _binding_intent(
                added,
                activation_mode=SkillActivationMode.ON_DEMAND,
            )
        ],
    )

    assert result.bindings[0].activation_mode is SkillActivationMode.ON_DEMAND
    assert result.on_demand_skill_ids_requiring_validation == frozenset(
        {added.skill_id}
    )


async def test_governance_revision_upgrade_keeps_activation_mode():
    space = _space(organization=True)
    existing = replace(_binding(), activation_mode=SkillActivationMode.ON_DEMAND)
    upgraded = replace(
        _binding(skill_id=existing.skill_id),
        activation_mode=SkillActivationMode.ALWAYS,
    )
    repo = AsyncMock()
    repo.list_policy_bindings.return_value = [existing]
    repo.resolve_published_references_for_binding_update.return_value = [upgraded]
    service = _service(
        space=space,
        repo=repo,
        permissions={Permission.ADMIN, Permission.SKILLS},
    )

    result = await service.replace_governance_bindings(
        policy_id=uuid4(),
        organization_space_id=space.id,
        intents=[_binding_intent(upgraded)],
    )

    assert [binding.activation_mode for binding in result] == [
        SkillActivationMode.ON_DEMAND
    ]
    persisted = repo.replace_policy_bindings.await_args.kwargs["bindings"]
    assert [binding.activation_mode for binding in persisted] == [
        SkillActivationMode.ON_DEMAND
    ]

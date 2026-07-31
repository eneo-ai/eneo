from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    SkillRevisionConflictException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.skills.application.organization_skill_service import (
    OrganizationSkillService,
)
from eneo.skills.domain.skill import (
    PersonalChatPinAdvance,
    PersonalChatPinAdvanceOutcome,
    PersonalChatPinAdvanceStage,
    PersonalChatPinConfirmOutcome,
    PersonalChatPinOverride,
    PersonalDefaultsSnapshot,
    PublishedSkillDeletionError,
    SkillAdoptionCursor,
    SkillAdoptionDrift,
    SkillAdoptionPersonalChat,
    SkillAdoptionProjectionPage,
    SkillAdoptionResource,
    SkillAdoptionResourceKind,
    SkillAdoptionRevisionCount,
    SkillAdoptionSummary,
    SkillBlockedForBindingError,
    SkillNotPublishedForBindingError,
    SkillPublicationChange,
    SkillRevision,
    SkillRevisionChange,
    SkillRevisionConflictError,
    SkillRevisionSummary,
    SkillSlugConflictError,
)


def _organization():
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        is_organization=MagicMock(return_value=True),
    )


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


def _service(*, organization, permissions, repo=None):
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=organization.tenant_id,
        permissions=permissions,
    )
    space_service = AsyncMock()
    space_service.get_or_create_tenant_space.return_value = organization
    repo = repo or AsyncMock()
    if not isinstance(repo.list_active_execution_blocks.return_value, dict):
        repo.list_active_execution_blocks.return_value = {}
    return OrganizationSkillService(
        user=user,
        repo=repo,
        space_service=space_service,
        # unsafe: the real method name starts with assert_, which mock guards.
        assistant_service=AsyncMock(unsafe=True),
        app_service=AsyncMock(),
        audit_service=AsyncMock(),
    )


async def test_use_permission_lists_only_published_tenant_skills():
    organization = _organization()
    summaries = [
        SimpleNamespace(id=uuid4(), slug="absence"),
        SimpleNamespace(id=uuid4(), slug="payroll"),
        SimpleNamespace(id=uuid4(), slug="travel"),
    ]
    repo = AsyncMock()
    repo.list_published_for_tenant.return_value = summaries
    repo.list_active_execution_blocks.return_value = {
        summaries[1].id: SimpleNamespace(skill_id=summaries[1].id)
    }
    service = _service(
        organization=organization,
        permissions={Permission.SKILLS},
        repo=repo,
    )

    page = await service.list_catalogue(
        limit=2,
        cursor="benefits",
        search=" payroll ",
    )

    assert [item.skill for item in page.items] == summaries[:2]
    assert [item.execution_blocked for item in page.items] == [False, True]
    assert page.next_cursor == "payroll"
    repo.list_published_for_tenant.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        limit=3,
        after_slug="benefits",
        search="payroll",
    )
    repo.list_active_execution_blocks.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_ids=[summaries[0].id, summaries[1].id],
    )


async def test_catalogue_is_denied_without_use_permission():
    organization = _organization()
    repo = AsyncMock()
    service = _service(organization=organization, permissions=set(), repo=repo)

    with pytest.raises(UnauthorizedException):
        await service.list_catalogue(limit=25, cursor=None)

    repo.list_published_for_tenant.assert_not_awaited()


async def test_use_permission_reads_only_the_published_revision():
    organization = _organization()
    published = SimpleNamespace(summary=SimpleNamespace(id=uuid4()))
    repo = AsyncMock()
    repo.get_published_for_tenant.return_value = published
    repo.list_active_execution_blocks.return_value = {
        published.summary.id: SimpleNamespace(skill_id=published.summary.id)
    }
    service = _service(
        organization=organization,
        permissions={Permission.SKILLS},
        repo=repo,
    )

    result = await service.get_catalogue_skill(skill_id=published.summary.id)

    assert result.skill is published
    assert result.execution_blocked is True
    repo.get_published_for_tenant.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_id=published.summary.id,
    )
    repo.list_active_execution_blocks.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_ids=[published.summary.id],
    )


async def test_non_admin_cannot_list_organisation_drafts():
    organization = _organization()
    summaries = [SimpleNamespace(slug="payroll")]
    repo = AsyncMock()
    repo.list_organization_for_tenant.return_value = summaries
    service = _service(
        organization=organization,
        permissions={Permission.SKILLS, Permission.SKILLS_MANAGEMENT},
        repo=repo,
    )

    with pytest.raises(UnauthorizedException):
        await service.list_organization_skills(
            limit=25,
            cursor=None,
            search=" payroll ",
        )

    repo.list_organization_for_tenant.assert_not_awaited()


async def test_admin_list_derives_execution_blocks_in_one_tenant_scoped_read():
    organization = _organization()
    blocked = SimpleNamespace(id=uuid4(), slug="blocked")
    available = SimpleNamespace(id=uuid4(), slug="available")
    repo = AsyncMock()
    repo.list_organization_for_tenant.return_value = [blocked, available]
    repo.list_active_execution_blocks.return_value = {
        blocked.id: SimpleNamespace(skill_id=blocked.id)
    }
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    page = await service.list_organization_skills(limit=25, cursor=None)

    assert [item.skill for item in page.items] == [blocked, available]
    assert [item.execution_blocked for item in page.items] == [True, False]
    repo.list_active_execution_blocks.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_ids=[blocked.id, available.id],
    )


async def test_admin_detail_derives_execution_block_for_current_tenant():
    organization = _organization()
    blocked = SimpleNamespace(id=uuid4())
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = blocked
    repo.list_active_execution_blocks.return_value = {
        blocked.id: SimpleNamespace(skill_id=blocked.id)
    }
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    projection = await service.get_organization_skill_projection(skill_id=blocked.id)

    assert projection.skill is blocked
    assert projection.execution_blocked is True
    repo.list_active_execution_blocks.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_ids=[blocked.id],
    )


async def test_admin_creates_in_the_tenant_organisation_space():
    organization = _organization()
    created = SimpleNamespace(id=uuid4())
    repo = AsyncMock()
    repo.create.return_value = created
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    result = await service.create_organization_skill(
        slug="payroll",
        display_name=" Payroll ",
        description=" Answers payroll questions ",
        instructions=" Use the handbook. ",
    )

    assert result is created
    repo.create.assert_awaited_once()
    create_call = repo.create.await_args.kwargs
    assert create_call["space_id"] == organization.id
    assert create_call["display_name"] == "Payroll"
    assert create_call["description"] == "Answers payroll questions"
    assert create_call["instructions"] == "Use the handbook."
    assert create_call["is_active"] is False


async def test_invalid_organisation_space_fails_closed():
    organization = _organization()
    organization.is_organization.return_value = False
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
    )

    with pytest.raises(RuntimeError, match="organisation Space is invalid"):
        await service.create_organization_skill(
            slug="payroll",
            display_name="Payroll",
            description="Answers payroll questions",
            instructions="Use the handbook.",
        )


async def test_organisation_slug_collision_has_a_stable_application_error():
    organization = _organization()
    repo = AsyncMock()
    repo.create.side_effect = SkillSlugConflictError
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(SkillSlugConflictError):
        await service.create_organization_skill(
            slug="payroll",
            display_name="Payroll",
            description="Answers payroll questions",
            instructions="Use approved guidance.",
        )


async def test_admin_creates_an_immutable_revision():
    organization = _organization()
    skill = SimpleNamespace(id=uuid4())
    revision = _revision(skill_id=skill.id, revision_number=2)
    change = SkillRevisionChange(
        skill=skill,
        revision=revision,
        created=True,
        previous_revision_number=1,
    )
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = skill
    repo.create_revision.return_value = change
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    result = await service.create_revision(
        skill_id=skill.id,
        display_name="Payroll",
        description="Payroll guidance",
        instructions="Use approved guidance.",
    )

    assert result is change
    repo.create_revision.assert_awaited_once()


async def test_admin_lists_tenant_skill_history_with_a_stable_cursor():
    organization = _organization()
    skill = SimpleNamespace(id=uuid4())
    revisions = [
        SkillRevisionSummary(
            id=uuid4(),
            skill_id=skill.id,
            revision_number=3,
            display_name="Payroll 3",
            created_at=datetime.now(timezone.utc),
        ),
        SkillRevisionSummary(
            id=uuid4(),
            skill_id=skill.id,
            revision_number=2,
            display_name="Payroll 2",
            created_at=datetime.now(timezone.utc),
        ),
        SkillRevisionSummary(
            id=uuid4(),
            skill_id=skill.id,
            revision_number=1,
            display_name="Payroll 1",
            created_at=datetime.now(timezone.utc),
        ),
    ]
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = skill
    repo.list_revision_summaries.return_value = revisions
    repo.count_revisions.return_value = 3
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    page = await service.list_revision_summaries(
        skill_id=skill.id,
        limit=2,
        cursor=None,
    )

    assert page.items == tuple(revisions[:2])
    assert page.next_cursor == 2
    assert page.total_count == 3
    repo.list_revision_summaries.assert_awaited_once_with(
        skill_id=skill.id,
        limit=3,
        before_revision_number=None,
    )
    repo.count_revisions.assert_awaited_once_with(skill_id=skill.id)


@pytest.mark.parametrize("cursor", ["0", "-1", "not-a-number"])
async def test_organisation_history_rejects_invalid_cursors(cursor: str):
    organization = _organization()
    skill = SimpleNamespace(id=uuid4())
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = skill
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(BadRequestException, match="revision cursor"):
        await service.list_revision_summaries(
            skill_id=skill.id,
            limit=25,
            cursor=cursor,
        )

    repo.list_revision_summaries.assert_not_awaited()


async def test_restore_copies_tenant_history_into_the_next_revision():
    organization = _organization()
    skill = SimpleNamespace(id=uuid4())
    reviewed_current_revision_id = uuid4()
    source = _revision(skill_id=skill.id, revision_number=1)
    restored = _revision(skill_id=skill.id, revision_number=3)
    change = SkillRevisionChange(
        skill=skill,
        revision=restored,
        created=True,
        previous_revision_number=2,
    )
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = skill
    repo.get_revision.return_value = source
    repo.create_revision.return_value = change
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    result = await service.restore_revision(
        skill_id=skill.id,
        source_revision_id=source.id,
        reviewed_current_revision_id=reviewed_current_revision_id,
    )

    assert result.source_revision is source
    assert result.change is change
    repo.create_revision.assert_awaited_once_with(
        skill_id=skill.id,
        display_name=source.display_name,
        description=source.description,
        instructions=source.instructions,
        content_digest=source.content_digest,
        created_by_user_id=service.user.id,
        expected_current_revision_id=reviewed_current_revision_id,
    )


async def test_restore_rejects_a_revision_that_changed_after_review():
    organization = _organization()
    skill = SimpleNamespace(id=uuid4(), current_revision=SimpleNamespace(id=uuid4()))
    source = _revision(skill_id=skill.id, revision_number=1)
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = skill
    repo.get_revision.return_value = source
    repo.create_revision.side_effect = SkillRevisionConflictError
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(
        SkillRevisionConflictException, match="changed after you reviewed"
    ):
        await service.restore_revision(
            skill_id=skill.id,
            source_revision_id=source.id,
            reviewed_current_revision_id=skill.current_revision.id,
        )


async def test_manage_permission_does_not_grant_publication():
    organization = _organization()
    repo = AsyncMock()
    service = _service(
        organization=organization,
        permissions={Permission.SKILLS, Permission.SKILLS_MANAGEMENT},
        repo=repo,
    )

    with pytest.raises(UnauthorizedException):
        await service.publish(
            skill_id=uuid4(),
            expected_revision_id=uuid4(),
        )

    repo.publish_organization.assert_not_awaited()


async def test_admin_publish_uses_the_exact_reviewed_revision():
    organization = _organization()
    outcome = SkillPublicationChange(
        skill=SimpleNamespace(),
        changed=True,
        previous_published_revision_number=None,
        previous_is_active=True,
    )
    repo = AsyncMock()
    repo.publish_organization.return_value = outcome
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )
    skill_id = uuid4()
    revision_id = uuid4()

    result = await service.publish(
        skill_id=skill_id,
        expected_revision_id=revision_id,
    )

    assert result is outcome
    repo.publish_organization.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_id=skill_id,
        expected_revision_id=revision_id,
    )


async def test_publish_explains_a_stale_revision_conflict():
    organization = _organization()
    repo = AsyncMock()
    repo.publish_organization.side_effect = SkillRevisionConflictError
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(
        SkillRevisionConflictException, match="changed since you reviewed"
    ):
        await service.publish(
            skill_id=uuid4(),
            expected_revision_id=uuid4(),
        )


async def test_admin_can_unpublish_without_changing_revision_history():
    organization = _organization()
    outcome = SkillPublicationChange(
        skill=SimpleNamespace(),
        changed=True,
        previous_published_revision_number=2,
        previous_is_active=True,
    )
    repo = AsyncMock()
    repo.unpublish_organization.return_value = outcome
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )
    skill_id = uuid4()

    result = await service.unpublish(skill_id=skill_id)

    assert result is outcome
    repo.unpublish_organization.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_id=skill_id,
    )


async def test_previously_published_skill_cannot_be_deleted():
    organization = _organization()
    repo = AsyncMock()
    repo.delete_organization.side_effect = PublishedSkillDeletionError
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(PublishedSkillDeletionError):
        await service.delete(skill_id=uuid4())


async def test_missing_tenant_skill_is_not_exposed():
    organization = _organization()
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = None
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(NotFoundException):
        await service.get_organization_skill(skill_id=uuid4())


async def test_skills_permission_does_not_grant_adoption_projection_access():
    organization = _organization()
    repo = AsyncMock()
    service = _service(
        organization=organization,
        permissions={Permission.SKILLS},
        repo=repo,
    )

    with pytest.raises(UnauthorizedException):
        await service.get_adoption_projection(
            skill_id=uuid4(),
            limit=25,
            cursor=None,
        )

    repo.get_organization_for_tenant.assert_not_awaited()
    repo.get_organization_adoption_projection_page.assert_not_awaited()


async def test_missing_tenant_skill_has_no_adoption_projection():
    organization = _organization()
    skill_id = uuid4()
    repo = AsyncMock()
    repo.get_organization_adoption_projection_page.return_value = None
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(NotFoundException):
        await service.get_adoption_projection(
            skill_id=skill_id,
            limit=25,
            cursor=None,
        )

    repo.get_organization_adoption_projection_page.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_id=skill_id,
        limit=25,
        after=None,
    )


async def test_adoption_projection_uses_an_opaque_stable_cursor_without_duplicates():
    organization = _organization()
    skill = SimpleNamespace(id=uuid4(), published_revision_number=2)
    revision_one_id = uuid4()
    revision_two_id = uuid4()
    summary = SkillAdoptionSummary(
        assistant_count=1,
        app_count=2,
        distinct_space_count=2,
        behind_published_count=2,
        personal_chat=SkillAdoptionPersonalChat(
            revision_id=revision_one_id,
            revision_number=1,
            drift=SkillAdoptionDrift.BEHIND,
        ),
        revision_counts=(
            SkillAdoptionRevisionCount(
                revision_id=revision_one_id,
                revision_number=1,
                assistant_count=1,
                app_count=1,
                personal_chat_pinned=True,
            ),
            SkillAdoptionRevisionCount(
                revision_id=revision_two_id,
                revision_number=2,
                assistant_count=0,
                app_count=1,
                personal_chat_pinned=False,
            ),
        ),
    )
    resources = (
        SkillAdoptionResource(
            kind=SkillAdoptionResourceKind.ASSISTANT,
            resource_id=uuid4(),
            name="Payroll assistant",
            space_id=uuid4(),
            space_name="Payroll",
            revision_id=revision_one_id,
            revision_number=1,
            drift=SkillAdoptionDrift.BEHIND,
        ),
        SkillAdoptionResource(
            kind=SkillAdoptionResourceKind.APP,
            resource_id=uuid4(),
            name="Payroll app",
            space_id=uuid4(),
            space_name="Payroll",
            revision_id=revision_one_id,
            revision_number=1,
            drift=SkillAdoptionDrift.BEHIND,
        ),
        SkillAdoptionResource(
            kind=SkillAdoptionResourceKind.APP,
            resource_id=uuid4(),
            name="Payroll review app",
            space_id=uuid4(),
            space_name="Finance",
            revision_id=revision_two_id,
            revision_number=2,
            drift=SkillAdoptionDrift.CURRENT,
        ),
    )
    repo = AsyncMock()
    first_projection = SkillAdoptionProjectionPage(
        summary=summary,
        items=resources[:2],
        limit=2,
        next_cursor=SkillAdoptionCursor(
            kind=resources[1].kind,
            resource_id=resources[1].resource_id,
        ).serialize(),
    )
    second_projection = SkillAdoptionProjectionPage(
        summary=None,
        items=resources[2:],
        limit=2,
        next_cursor=None,
    )
    repo.get_organization_adoption_projection_page.side_effect = [
        first_projection,
        second_projection,
    ]
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    first_page = await service.get_adoption_projection(
        skill_id=skill.id,
        limit=2,
        cursor=None,
    )
    assert first_page.summary is summary
    assert first_page.items == resources[:2]
    assert first_page.next_cursor is not None

    decoded_cursor = SkillAdoptionCursor.parse(first_page.next_cursor)
    assert decoded_cursor == SkillAdoptionCursor(
        kind=resources[1].kind,
        resource_id=resources[1].resource_id,
    )

    second_page = await service.get_adoption_projection(
        skill_id=skill.id,
        limit=2,
        cursor=first_page.next_cursor,
    )
    assert second_page.summary is None
    assert second_page.items == resources[2:]
    assert second_page.next_cursor is None
    assert {
        resource.resource_id for resource in first_page.items + second_page.items
    } == {resource.resource_id for resource in resources}

    assert repo.get_organization_adoption_projection_page.await_args_list == [
        call(
            tenant_id=organization.tenant_id,
            skill_id=skill.id,
            limit=2,
            after=None,
        ),
        call(
            tenant_id=organization.tenant_id,
            skill_id=skill.id,
            limit=2,
            after=decoded_cursor,
        ),
    ]


@pytest.mark.parametrize("cursor", ["not-base64!", "dW5rbm93bjox"])
async def test_adoption_projection_rejects_malformed_cursors(cursor: str):
    organization = _organization()
    skill = SimpleNamespace(id=uuid4(), published_revision_number=1)
    repo = AsyncMock()
    repo.get_organization_for_tenant.return_value = skill
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(BadRequestException, match="adoption cursor"):
        await service.get_adoption_projection(
            skill_id=skill.id,
            limit=25,
            cursor=cursor,
        )

    repo.get_organization_adoption_projection_page.assert_not_awaited()


def _advance(outcome, *, to_number=2):
    return PersonalChatPinAdvance(
        outcome=outcome,
        from_revision_id=uuid4(),
        from_revision_number=1,
        to_revision_id=uuid4(),
        to_revision_number=to_number,
    )


def _stage(outcome, *, to_number=2):
    return PersonalChatPinAdvanceStage(
        advance=_advance(outcome, to_number=to_number),
        policy_id=uuid4(),
        policy_version="1234",
        personal_defaults_snapshot=PersonalDefaultsSnapshot(
            assistant_count=1,
            row_versions_digest=None,
            runtime_policy_version="5678",
        ),
    )


async def test_pin_advance_requires_the_tenant_administrator():
    organization = _organization()
    repo = AsyncMock()
    service = _service(
        organization=organization, permissions={Permission.SKILLS}, repo=repo
    )

    with pytest.raises(UnauthorizedException):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )
    repo.stage_personal_chat_skill_pin_advance.assert_not_awaited()


async def test_pin_advance_validates_the_governed_fit_only_when_it_wrote():
    organization = _organization()
    repo = AsyncMock()
    stage = _stage(PersonalChatPinAdvanceOutcome.ADVANCED)
    repo.stage_personal_chat_skill_pin_advance.return_value = stage
    repo.confirm_personal_chat_skill_pin_advance.return_value = (
        PersonalChatPinConfirmOutcome.CONFIRMED
    )
    service = _service(
        organization=organization, permissions={Permission.ADMIN}, repo=repo
    )

    skill_id = uuid4()
    expected_pinned_revision_id = uuid4()
    expected_published_revision_id = uuid4()
    advanced = await service.advance_personal_chat_binding(
        skill_id=skill_id,
        expected_pinned_revision_id=expected_pinned_revision_id,
        expected_published_revision_id=expected_published_revision_id,
    )
    assert advanced.outcome is PersonalChatPinAdvanceOutcome.ADVANCED
    fit = service.assistant_service.assert_personal_default_governance_context_fit
    fit.assert_awaited_once_with(
        personal_chat_pin_override=PersonalChatPinOverride(
            skill_id=skill_id,
            from_revision_id=stage.advance.from_revision_id,
            to_revision_id=stage.advance.to_revision_id,
        )
    )
    repo.confirm_personal_chat_skill_pin_advance.assert_awaited_once_with(
        tenant_id=service.user.tenant_id,
        skill_id=skill_id,
        policy_id=stage.policy_id,
        policy_version=stage.policy_version,
        personal_defaults_snapshot=stage.personal_defaults_snapshot,
        expected_pinned_revision_id=expected_pinned_revision_id,
        expected_published_revision_id=expected_published_revision_id,
    )

    repo.stage_personal_chat_skill_pin_advance.return_value = _stage(
        PersonalChatPinAdvanceOutcome.ALREADY_CURRENT
    )
    unchanged = await service.advance_personal_chat_binding(
        skill_id=uuid4(),
        expected_pinned_revision_id=uuid4(),
        expected_published_revision_id=uuid4(),
    )
    assert unchanged.outcome is PersonalChatPinAdvanceOutcome.ALREADY_CURRENT
    # Nothing changed, so nothing new to validate and nothing to confirm.
    fit.assert_awaited_once()
    repo.confirm_personal_chat_skill_pin_advance.assert_awaited_once()


async def test_pin_advance_refused_confirm_maps_to_the_conflict_contract():
    organization = _organization()
    repo = AsyncMock()
    repo.stage_personal_chat_skill_pin_advance.return_value = _stage(
        PersonalChatPinAdvanceOutcome.ADVANCED
    )
    service = _service(
        organization=organization, permissions={Permission.ADMIN}, repo=repo
    )

    for refused in (
        PersonalChatPinConfirmOutcome.POLICY_CHANGED,
        PersonalChatPinConfirmOutcome.PUBLICATION_CHANGED,
        PersonalChatPinConfirmOutcome.PERSONAL_DEFAULTS_CHANGED,
    ):
        repo.confirm_personal_chat_skill_pin_advance.return_value = refused
        with pytest.raises(
            SkillRevisionConflictException, match="changed while the move"
        ):
            await service.advance_personal_chat_binding(
                skill_id=uuid4(),
                expected_pinned_revision_id=uuid4(),
                expected_published_revision_id=uuid4(),
            )

    repo.confirm_personal_chat_skill_pin_advance.return_value = (
        PersonalChatPinConfirmOutcome.BLOCKED
    )
    with pytest.raises(SkillBlockedForBindingError):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )


async def test_pin_advance_confirms_only_after_the_fit_validation_passed():
    organization = _organization()
    repo = AsyncMock()
    repo.stage_personal_chat_skill_pin_advance.return_value = _stage(
        PersonalChatPinAdvanceOutcome.ADVANCED
    )
    service = _service(
        organization=organization, permissions={Permission.ADMIN}, repo=repo
    )
    service.assistant_service.assert_personal_default_governance_context_fit.side_effect = BadRequestException(
        "does not fit"
    )

    with pytest.raises(BadRequestException, match="does not fit"):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )
    repo.confirm_personal_chat_skill_pin_advance.assert_not_awaited()


async def test_pin_advance_maps_each_refusal_to_its_established_response():
    organization = _organization()
    repo = AsyncMock()
    service = _service(
        organization=organization, permissions={Permission.ADMIN}, repo=repo
    )

    repo.stage_personal_chat_skill_pin_advance.return_value = None
    with pytest.raises(NotFoundException):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )

    repo.stage_personal_chat_skill_pin_advance.return_value = _stage(
        PersonalChatPinAdvanceOutcome.NOT_BOUND
    )
    with pytest.raises(NotFoundException):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )

    repo.stage_personal_chat_skill_pin_advance.return_value = _stage(
        PersonalChatPinAdvanceOutcome.NOT_PUBLISHED
    )
    with pytest.raises(SkillNotPublishedForBindingError):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )

    repo.stage_personal_chat_skill_pin_advance.return_value = _stage(
        PersonalChatPinAdvanceOutcome.BLOCKED
    )
    with pytest.raises(SkillBlockedForBindingError):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )

    fit = service.assistant_service.assert_personal_default_governance_context_fit
    fit.assert_not_awaited()


async def test_pin_advance_conflict_keeps_the_reviewed_revision_contract():
    organization = _organization()
    repo = AsyncMock()
    repo.stage_personal_chat_skill_pin_advance.side_effect = SkillRevisionConflictError
    service = _service(
        organization=organization, permissions={Permission.ADMIN}, repo=repo
    )

    with pytest.raises(
        SkillRevisionConflictException, match="changed after you reviewed"
    ):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )


async def test_pin_advance_rejection_from_the_fit_owner_propagates():
    organization = _organization()
    repo = AsyncMock()
    repo.stage_personal_chat_skill_pin_advance.return_value = _stage(
        PersonalChatPinAdvanceOutcome.ADVANCED
    )
    service = _service(
        organization=organization, permissions={Permission.ADMIN}, repo=repo
    )
    service.assistant_service.assert_personal_default_governance_context_fit.side_effect = BadRequestException(
        "does not fit"
    )

    with pytest.raises(BadRequestException, match="does not fit"):
        await service.advance_personal_chat_binding(
            skill_id=uuid4(),
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=uuid4(),
        )

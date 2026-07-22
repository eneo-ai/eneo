from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.skills.application.organization_skill_service import (
    OrganizationSkillService,
)
from eneo.skills.domain.skill import (
    PublishedSkillDeletionError,
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
    return OrganizationSkillService(
        user=user,
        repo=repo or AsyncMock(),
        space_service=space_service,
    )


async def test_use_permission_lists_only_published_tenant_skills():
    organization = _organization()
    summaries = [
        SimpleNamespace(slug="absence"),
        SimpleNamespace(slug="payroll"),
        SimpleNamespace(slug="travel"),
    ]
    repo = AsyncMock()
    repo.list_published_for_tenant.return_value = summaries
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

    assert page.items == tuple(summaries[:2])
    assert page.next_cursor == "payroll"
    repo.list_published_for_tenant.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        limit=3,
        after_slug="benefits",
        search="payroll",
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
    service = _service(
        organization=organization,
        permissions={Permission.SKILLS},
        repo=repo,
    )

    result = await service.get_catalogue_skill(skill_id=published.summary.id)

    assert result is published
    repo.get_published_for_tenant.assert_awaited_once_with(
        tenant_id=organization.tenant_id,
        skill_id=published.summary.id,
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

    with pytest.raises(NameCollisionException, match="slug 'payroll'"):
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

    with pytest.raises(NameCollisionException, match="changed since you reviewed"):
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


async def test_published_skill_must_be_unpublished_before_deletion():
    organization = _organization()
    repo = AsyncMock()
    repo.delete_organization.side_effect = PublishedSkillDeletionError
    service = _service(
        organization=organization,
        permissions={Permission.ADMIN},
        repo=repo,
    )

    with pytest.raises(NameCollisionException, match="Unpublish"):
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

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.jobs.job_models import Task
from eneo.main.exceptions import NameCollisionException, NotFoundException
from eneo.main.models import Status
from eneo.skills.domain.skill import (
    PublishedSkillDeletionError,
    SkillBindingReference,
    SkillBindingSource,
    SkillExecutionReference,
    SkillPublicationState,
    SkillRevisionConflictError,
)


async def _organization_space(session, *, tenant_id):
    return await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )


def _serialize_provenance(
    provenance: tuple[SkillExecutionReference, ...],
) -> list[dict[str, object]]:
    return [
        {
            "skill_id": str(reference.skill_id),
            "skill_revision_id": str(reference.skill_revision_id),
            "revision_number": reference.revision_number,
            "content_digest": reference.content_digest,
            "position": reference.position,
        }
        for reference in provenance
    ]


async def test_catalogue_reads_only_the_tenants_exact_published_revision(
    db_container,
    admin_user,
    tenant_factory,
    user_factory,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        other_tenant = await tenant_factory(
            session,
            name=f"Catalogue tenant {uuid4()}",
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        other_organization = Spaces(
            tenant_id=other_tenant.id,
            name="Other organisation",
            user_id=None,
            tenant_space_id=None,
        )
        session.add(other_organization)
        await session.flush()

        repo = container.skill_repo()
        local = await repo.create(
            space_id=organization.id,
            slug="payroll",
            display_name="Payroll",
            description="Published description",
            instructions="Published instructions",
            content_digest="1" * 64,
            created_by_user_id=admin_user.id,
        )
        foreign = await repo.create(
            space_id=other_organization.id,
            slug="foreign",
            display_name="Foreign",
            description="Foreign description",
            instructions="Foreign instructions",
            content_digest="f" * 64,
            created_by_user_id=other_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=local.id,
            expected_revision_id=local.current_revision.id,
        )
        await repo.publish_organization(
            tenant_id=other_tenant.id,
            skill_id=foreign.id,
            expected_revision_id=foreign.current_revision.id,
        )
        await repo.create_revision(
            skill_id=local.id,
            display_name="Payroll draft",
            description="Draft description",
            instructions="Draft instructions",
            content_digest="2" * 64,
            created_by_user_id=admin_user.id,
        )

        catalogue = await repo.list_published_for_tenant(
            tenant_id=admin_user.tenant_id,
            limit=25,
            after_slug=None,
            search="payroll",
        )
        management = await repo.list_organization_for_tenant(
            tenant_id=admin_user.tenant_id,
            limit=25,
            after_slug=None,
            search="draft",
        )
        detail = await repo.get_published_for_tenant(
            tenant_id=admin_user.tenant_id,
            skill_id=local.id,
        )

        assert [entry.id for entry in catalogue] == [local.id]
        assert catalogue[0].display_name == "Payroll"
        assert catalogue[0].revision_id == local.current_revision.id
        assert management[0].display_name == "Payroll draft"
        assert management[0].publication_state is SkillPublicationState.UPDATE_PENDING
        assert detail is not None
        assert detail.revision.instructions == "Published instructions"
        assert (
            await repo.get_published_for_tenant(
                tenant_id=admin_user.tenant_id,
                skill_id=foreign.id,
            )
            is None
        )

        approved = await repo.resolve_published_references_for_binding_update(
            tenant_id=admin_user.tenant_id,
            references=[
                SkillBindingReference(
                    skill_id=local.id,
                    skill_revision_id=local.current_revision.id,
                ),
                SkillBindingReference(
                    skill_id=foreign.id,
                    skill_revision_id=foreign.current_revision.id,
                ),
                SkillBindingReference(
                    skill_id=local.id,
                    skill_revision_id=management[0].current_revision_id,
                ),
            ],
        )

        assert [binding.skill_revision_id for binding in approved] == [
            local.current_revision.id
        ]


async def test_published_catalogue_skill_binds_and_executes_across_tenant_spaces(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    app_factory,
    tenant_factory,
    user_factory,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        model = await completion_model_factory(session, "catalogue-binding-model")
        target_space = await space_factory(
            session,
            "Catalogue binding target",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=target_space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Catalogue Assistant",
            model.id,
            space_id=target_space.id,
        )
        app = await app_factory(
            session,
            "Catalogue App",
            model.id,
            space_id=target_space.id,
        )
        sibling_space = await space_factory(
            session,
            "Catalogue binding sibling",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=sibling_space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        other_tenant = await tenant_factory(
            session,
            name=f"Foreign catalogue tenant {uuid4()}",
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        other_organization = Spaces(
            tenant_id=other_tenant.id,
            name="Foreign catalogue organisation",
            user_id=None,
            tenant_space_id=None,
        )
        session.add(other_organization)
        await session.flush()

        repo = container.skill_repo()
        published = await repo.create(
            space_id=organization.id,
            slug=f"approved-{uuid4().hex[:8]}",
            display_name="Approved guidance",
            description="Approved catalogue guidance",
            instructions="Use the approved catalogue instructions.",
            content_digest="1" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=published.id,
            expected_revision_id=published.current_revision.id,
        )
        draft = await repo.create_revision(
            skill_id=published.id,
            display_name="Unapproved draft",
            description="Draft catalogue guidance",
            instructions="Do not execute these draft instructions.",
            content_digest="2" * 64,
            created_by_user_id=admin_user.id,
        )
        assert draft is not None

        foreign = await repo.create(
            space_id=other_organization.id,
            slug=f"foreign-{uuid4().hex[:8]}",
            display_name="Foreign guidance",
            description="Foreign catalogue guidance",
            instructions="Foreign tenant instructions.",
            content_digest="f" * 64,
            created_by_user_id=other_user.id,
        )
        await repo.publish_organization(
            tenant_id=other_tenant.id,
            skill_id=foreign.id,
            expected_revision_id=foreign.current_revision.id,
        )
        sibling = await repo.create(
            space_id=sibling_space.id,
            slug=f"sibling-{uuid4().hex[:8]}",
            display_name="Sibling Space guidance",
            description="Same-tenant guidance from another regular Space",
            instructions="Sibling Space instructions.",
            content_digest="3" * 64,
            created_by_user_id=admin_user.id,
        )

        approved_reference = SkillBindingReference(
            skill_id=published.id,
            skill_revision_id=published.current_revision.id,
        )
        service = container.skill_service()
        assistant_bindings = await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=assistant.id,
            references=[approved_reference],
        )
        app_bindings = await service.replace_app_bindings(
            space_id=target_space.id,
            app_id=app.id,
            references=[approved_reference],
        )

        assert assistant_bindings[0].skill_space_id == organization.id
        assert app_bindings[0].skill_space_id == organization.id
        assert assistant_bindings[0].source is SkillBindingSource.ORGANIZATION
        assert app_bindings[0].source is SkillBindingSource.ORGANIZATION
        assert assistant_bindings[0].current_revision_id == draft.revision.id
        assert (
            assistant_bindings[0].attachable_revision_id
            == published.current_revision.id
        )
        assert assistant_bindings[0].attachable_revision_number == 1
        assert (
            "approved catalogue instructions"
            in (
                await service.compose_for_assistant(
                    assistant_id=assistant.id,
                    base_instructions="Assistant base",
                )
            ).prompt
        )
        app_composition = await service.compose_for_app(
            app_id=app.id,
            base_instructions="App base",
        )
        assert "approved catalogue instructions" in app_composition.prompt
        job_id = uuid4()
        app_run_id = uuid4()
        session.add(
            Jobs(
                id=job_id,
                user_id=admin_user.id,
                task=Task.RUN_APP.value,
                status=Status.COMPLETE.value,
            )
        )
        session.add(
            AppRuns(
                id=app_run_id,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                app_id=app.id,
                job_id=job_id,
                completion_model_id=model.id,
                skill_provenance=_serialize_provenance(app_composition.provenance),
            )
        )
        await session.flush()

        for reference in (
            SkillBindingReference(
                skill_id=published.id,
                skill_revision_id=draft.revision.id,
            ),
            SkillBindingReference(
                skill_id=foreign.id,
                skill_revision_id=foreign.current_revision.id,
            ),
            SkillBindingReference(
                skill_id=sibling.id,
                skill_revision_id=sibling.current_revision.id,
            ),
        ):
            with pytest.raises(NotFoundException, match="unavailable"):
                await service.replace_assistant_bindings(
                    space_id=target_space.id,
                    assistant_id=assistant.id,
                    references=[reference],
                )
            with pytest.raises(NotFoundException, match="unavailable"):
                await service.replace_app_bindings(
                    space_id=target_space.id,
                    app_id=app.id,
                    references=[reference],
                )

        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=published.id,
            expected_revision_id=draft.revision.id,
        )
        [published_update] = await repo.list_assistant_bindings(
            assistant_id=assistant.id
        )
        assert published_update.skill_revision_id == published.current_revision.id
        assert published_update.attachable_revision_id == draft.revision.id
        assert published_update.attachable_revision_number == 2

        await repo.unpublish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=published.id,
        )
        [unpublished_binding] = await repo.list_assistant_bindings(
            assistant_id=assistant.id
        )
        assert unpublished_binding.skill_revision_id == published.current_revision.id
        assert unpublished_binding.source is SkillBindingSource.ORGANIZATION
        assert unpublished_binding.attachable_revision_id is None
        assert unpublished_binding.attachable_revision_number is None
        assert unpublished_binding.is_active is False
        await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=assistant.id,
            references=[approved_reference],
        )
        await service.replace_app_bindings(
            space_id=target_space.id,
            app_id=app.id,
            references=[approved_reference],
        )
        snapshot = await service.compose_for_execution_snapshot(
            tenant_id=admin_user.tenant_id,
            space_id=target_space.id,
            provenance=app_composition.provenance,
            base_instructions="App base",
        )

        assert snapshot.provenance == app_composition.provenance
        assert "approved catalogue instructions" in snapshot.prompt
        await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=assistant.id,
            references=[],
        )
        await service.replace_app_bindings(
            space_id=target_space.id,
            app_id=app.id,
            references=[],
        )
        with pytest.raises(NameCollisionException, match="retained for audit history"):
            await container.organization_skill_service().delete(skill_id=published.id)
        retained_revision = await repo.get_revision(
            skill_id=published.id,
            revision_id=app_composition.provenance[0].skill_revision_id,
        )
        retained_app_run = await session.get(AppRuns, app_run_id)
        assert retained_revision is not None
        assert (
            retained_revision.content_digest
            == app_composition.provenance[0].content_digest
        )
        assert retained_app_run is not None
        assert retained_app_run.skill_provenance == _serialize_provenance(
            app_composition.provenance
        )


async def test_catalogue_search_treats_like_metacharacters_as_literals(
    db_container,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        repo = container.skill_repo()
        matching = await repo.create(
            space_id=organization.id,
            slug=f"special-{uuid4().hex[:8]}",
            display_name="Payroll_% guide",
            description="Contains literal search characters",
            instructions="Special instructions",
            content_digest="3" * 64,
            created_by_user_id=admin_user.id,
        )
        regular = await repo.create(
            space_id=organization.id,
            slug=f"regular-{uuid4().hex[:8]}",
            display_name="Regular guide",
            description="No literal search characters",
            instructions="Regular instructions",
            content_digest="4" * 64,
            created_by_user_id=admin_user.id,
        )
        for skill in (matching, regular):
            await repo.publish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                expected_revision_id=skill.current_revision.id,
            )

        for search in ("%", "_"):
            management = await repo.list_organization_for_tenant(
                tenant_id=admin_user.tenant_id,
                limit=25,
                after_slug=None,
                search=search,
            )
            catalogue = await repo.list_published_for_tenant(
                tenant_id=admin_user.tenant_id,
                limit=25,
                after_slug=None,
                search=search,
            )

            assert [skill.id for skill in management] == [matching.id]
            assert [skill.id for skill in catalogue] == [matching.id]


async def test_publication_mutations_are_stale_safe_and_idempotent(
    db_container,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"benefits-{uuid4().hex[:8]}",
            display_name="Benefits",
            description="Benefits description",
            instructions="Benefits instructions",
            content_digest="1" * 64,
            created_by_user_id=admin_user.id,
        )
        revised = await repo.create_revision(
            skill_id=skill.id,
            display_name="Benefits revised",
            description="Revised description",
            instructions="Revised instructions",
            content_digest="2" * 64,
            created_by_user_id=admin_user.id,
        )
        assert revised is not None

        with pytest.raises(SkillRevisionConflictError):
            await repo.publish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                expected_revision_id=skill.current_revision.id,
            )

        published = await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revised.revision.id,
        )
        repeated = await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revised.revision.id,
        )

        assert published is not None and published.changed is True
        assert published.previous_is_active is True
        assert repeated is not None and repeated.changed is False
        assert repeated.previous_is_active is True
        assert repeated.skill.first_published_at == published.skill.first_published_at

        pending = await repo.create_revision(
            skill_id=skill.id,
            display_name="Benefits pending review",
            description="Pending description",
            instructions="Pending instructions",
            content_digest="3" * 64,
            created_by_user_id=admin_user.id,
        )
        assert pending is not None
        assert pending.skill.publication_state is SkillPublicationState.UPDATE_PENDING

        with pytest.raises(PublishedSkillDeletionError):
            await repo.delete_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
            )

        unpublished = await repo.unpublish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
        )
        assert unpublished is not None
        assert unpublished.previous_is_active is True
        assert unpublished.skill.publication_state is SkillPublicationState.UNPUBLISHED
        assert unpublished.skill.is_active is False
        assert (
            await repo.get_published_for_tenant(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
            )
            is None
        )
        with pytest.raises(PublishedSkillDeletionError):
            await repo.delete_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
            )
        retained = await repo.get_organization_for_tenant(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
        )
        assert retained is not None
        assert retained.first_published_at == unpublished.skill.first_published_at
        retained_revision = await repo.get_revision(
            skill_id=skill.id,
            revision_id=pending.revision.id,
        )
        assert retained_revision == pending.revision

        republished = await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=pending.revision.id,
        )
        assert republished is not None
        assert republished.previous_is_active is False
        assert republished.skill.publication_state is SkillPublicationState.PUBLISHED
        assert republished.skill.is_active is True

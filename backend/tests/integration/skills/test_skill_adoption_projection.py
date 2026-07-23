from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.skills.domain.skill import (
    SkillAdoptionDrift,
    SkillAdoptionResourceKind,
    SkillBindingReference,
)


async def _organization_space(session, *, tenant_id: UUID) -> Spaces:
    organization = await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert organization is not None
    return organization


async def test_adoption_projection_counts_exact_revisions_and_distinct_spaces(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    app_factory,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        model = await completion_model_factory(session, "skill-adoption-model")
        shared_space = await space_factory(
            session,
            "Shared adoption Space",
            [model.id],
        )
        second_space = await space_factory(
            session,
            "Second adoption Space",
            [model.id],
        )
        session.add_all(
            [
                SpacesUsers(
                    space_id=shared_space.id,
                    user_id=admin_user.id,
                    role="admin",
                ),
                SpacesUsers(
                    space_id=second_space.id,
                    user_id=admin_user.id,
                    role="admin",
                ),
            ]
        )
        assistant_behind = await assistant_factory(
            session,
            "Assistant pinned behind",
            model.id,
            id=UUID("00000000-0000-0000-0000-000000000011"),
            space_id=shared_space.id,
        )
        assistant_current = await assistant_factory(
            session,
            "Assistant on current",
            model.id,
            id=UUID("00000000-0000-0000-0000-000000000012"),
            space_id=second_space.id,
        )
        app_behind = await app_factory(
            session,
            "App pinned behind",
            model.id,
            id=UUID("00000000-0000-0000-0000-000000000021"),
            space_id=shared_space.id,
        )

        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"adoption-{uuid4().hex[:8]}",
            display_name="Adoption projection",
            description="Tests exact structural adoption.",
            instructions="Follow the approved instructions.",
            content_digest="1" * 64,
            created_by_user_id=admin_user.id,
        )
        revision_one = skill.current_revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revision_one.id,
        )
        revision_one_reference = SkillBindingReference(
            skill_id=skill.id,
            skill_revision_id=revision_one.id,
        )
        skill_service = container.skill_service()
        await skill_service.replace_assistant_bindings(
            space_id=shared_space.id,
            assistant_id=assistant_behind.id,
            references=[revision_one_reference],
        )
        await skill_service.replace_app_bindings(
            space_id=shared_space.id,
            app_id=app_behind.id,
            references=[revision_one_reference],
        )
        policy = GovernancePolicies(
            tenant_id=admin_user.tenant_id,
            scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT.value,
        )
        session.add(policy)
        await session.flush()
        resolved_revision_one = (
            await repo.resolve_published_references_for_binding_update(
                tenant_id=admin_user.tenant_id,
                references=[revision_one_reference],
            )
        )
        await repo.replace_policy_bindings(
            policy_id=policy.id,
            tenant_id=admin_user.tenant_id,
            skill_space_id=organization.id,
            bindings=resolved_revision_one,
        )

        revision_two_change = await repo.create_revision(
            skill_id=skill.id,
            display_name="Adoption projection v2",
            description="Tests current and behind structural adoption.",
            instructions="Follow the second approved revision.",
            content_digest="2" * 64,
            created_by_user_id=admin_user.id,
        )
        assert revision_two_change is not None
        revision_two = revision_two_change.revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revision_two.id,
        )
        await skill_service.replace_assistant_bindings(
            space_id=second_space.id,
            assistant_id=assistant_current.id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id,
                    skill_revision_id=revision_two.id,
                )
            ],
        )

        summary = await repo.get_organization_adoption_summary(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            published_revision_number=revision_two.revision_number,
        )
        resources = await repo.list_organization_adoption_resources(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            published_revision_number=revision_two.revision_number,
            limit=10,
            after=None,
        )

        assert summary.assistant_count == 2
        assert summary.app_count == 1
        assert summary.distinct_space_count == 2
        assert summary.behind_published_count == 3
        assert summary.personal_chat is not None
        assert summary.personal_chat.revision_id == revision_one.id
        assert summary.personal_chat.drift is SkillAdoptionDrift.BEHIND
        assert [
            (
                count.revision_number,
                count.assistant_count,
                count.app_count,
                count.personal_chat_pinned,
            )
            for count in summary.revision_counts
        ] == [
            (1, 1, 1, True),
            (2, 1, 0, False),
        ]
        assert [
            (resource.kind, resource.name, resource.drift) for resource in resources
        ] == [
            (
                SkillAdoptionResourceKind.ASSISTANT,
                "Assistant pinned behind",
                SkillAdoptionDrift.BEHIND,
            ),
            (
                SkillAdoptionResourceKind.ASSISTANT,
                "Assistant on current",
                SkillAdoptionDrift.CURRENT,
            ),
            (
                SkillAdoptionResourceKind.APP,
                "App pinned behind",
                SkillAdoptionDrift.BEHIND,
            ),
        ]

        captured_statements: list[tuple[str, tuple[object, ...]]] = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            parameters,
            _context,
            _executemany,
        ) -> None:
            assert isinstance(parameters, tuple)
            captured_statements.append((statement, parameters))

        assert session.bind is not None
        sync_engine = session.bind.sync_engine
        sa.event.listen(
            sync_engine,
            "before_cursor_execute",
            capture_statement,
        )
        try:
            adoption_service = container.organization_skill_service()
            first_page = await adoption_service.get_adoption_projection(
                skill_id=skill.id,
                limit=1,
                cursor=None,
            )
        finally:
            sa.event.remove(
                sync_engine,
                "before_cursor_execute",
                capture_statement,
            )

        assert len(captured_statements) == 4
        adoption_statements = [
            (statement, parameters)
            for statement, parameters in captured_statements
            if "organization_skill_adoption_" in statement
        ]
        assert len(adoption_statements) == 3
        resource_statements = [
            statement
            for statement, _parameters in adoption_statements
            if "organization_skill_adoption_resources" in statement
        ]
        assert len(resource_statements) == 1
        assert "UNION ALL" in resource_statements[0]
        assert "ORDER BY" in resource_statements[0]
        assert "LIMIT" in resource_statements[0]

        connection = await session.connection()
        await connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
        plans: list[str] = []
        for statement, parameters in adoption_statements:
            explained = await connection.exec_driver_sql(
                f"EXPLAIN (COSTS OFF) {statement}",
                parameters,
            )
            plans.append("\n".join(str(row[0]) for row in explained))
        combined_plan = "\n".join(plans)
        assert plans[-1].startswith("Limit")
        assert "Append" in plans[-1]
        assert "Seq Scan" not in combined_plan

        assert [
            (resource.kind, resource.resource_id) for resource in first_page.items
        ] == [(SkillAdoptionResourceKind.ASSISTANT, assistant_behind.id)]
        assert first_page.next_cursor is not None
        second_page = await adoption_service.get_adoption_projection(
            skill_id=skill.id,
            limit=1,
            cursor=first_page.next_cursor,
        )
        assert [
            (resource.kind, resource.resource_id) for resource in second_page.items
        ] == [(SkillAdoptionResourceKind.ASSISTANT, assistant_current.id)]
        assert second_page.next_cursor is not None
        third_page = await adoption_service.get_adoption_projection(
            skill_id=skill.id,
            limit=1,
            cursor=second_page.next_cursor,
        )
        assert [
            (resource.kind, resource.resource_id) for resource in third_page.items
        ] == [(SkillAdoptionResourceKind.APP, app_behind.id)]
        assert third_page.next_cursor is None
        assert (
            len(
                {
                    resource.resource_id
                    for page in (first_page, second_page, third_page)
                    for resource in page.items
                }
            )
            == 3
        )


async def test_unpublished_skill_without_bindings_has_an_empty_projection(
    db_container,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"empty-adoption-{uuid4().hex[:8]}",
            display_name="Empty adoption projection",
            description="No resources use this draft.",
            instructions="Draft instructions.",
            content_digest="e" * 64,
            created_by_user_id=admin_user.id,
        )

        summary = await repo.get_organization_adoption_summary(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            published_revision_number=None,
        )
        resources = await repo.list_organization_adoption_resources(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            published_revision_number=None,
            limit=10,
            after=None,
        )

        assert summary.assistant_count == 0
        assert summary.app_count == 0
        assert summary.distinct_space_count == 0
        assert summary.behind_published_count == 0
        assert summary.personal_chat is None
        assert summary.revision_counts == ()
        assert resources == []


async def test_adoption_projection_repo_does_not_cross_tenant_boundary(
    db_container,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"isolated-adoption-{uuid4().hex[:8]}",
            display_name="Tenant-isolated adoption projection",
            description="Must not be visible through another tenant boundary.",
            instructions="Keep this Skill inside its owning tenant.",
            content_digest="f" * 64,
            created_by_user_id=admin_user.id,
        )

        foreign_tenant_id = uuid4()
        summary = await repo.get_organization_adoption_summary(
            tenant_id=foreign_tenant_id,
            skill_id=skill.id,
            published_revision_number=skill.published_revision_number,
        )
        resources = await repo.list_organization_adoption_resources(
            tenant_id=foreign_tenant_id,
            skill_id=skill.id,
            published_revision_number=skill.published_revision_number,
            limit=10,
            after=None,
        )

        assert summary.assistant_count == 0
        assert summary.app_count == 0
        assert summary.distinct_space_count == 0
        assert summary.behind_published_count == 0
        assert summary.personal_chat is None
        assert summary.revision_counts == ()
        assert resources == []

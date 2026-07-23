import asyncio
from collections.abc import Mapping
from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.skill_table import (
    AppSkillBindings,
    AssistantSkillBindings,
)
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.skills.domain.skill import (
    SkillAdoptionCursor,
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


def _walk_plan(node: Mapping[str, object]) -> list[Mapping[str, object]]:
    nodes = [node]
    children = node.get("Plans")
    if not isinstance(children, list):
        return nodes
    for child in children:
        if isinstance(child, dict):
            nodes.extend(_walk_plan(child))
    return nodes


async def _explain_captured_statement(
    session,
    *,
    statement: str,
    parameters: tuple[object, ...],
) -> list[Mapping[str, object]]:
    connection = await session.connection()
    await connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
    explained = await connection.exec_driver_sql(
        f"EXPLAIN (ANALYZE, COSTS OFF, SUMMARY OFF, FORMAT JSON) {statement}",
        parameters,
    )
    document = explained.scalar_one()
    assert isinstance(document, list)
    assert len(document) == 1
    root = document[0]
    assert isinstance(root, dict)
    plan = root.get("Plan")
    assert isinstance(plan, dict)
    return _walk_plan(plan)


def _assert_bounded_composite_scan(
    nodes: list[Mapping[str, object]],
    *,
    index_name: str,
    range_column: str,
    maximum_rows: int,
) -> None:
    index_node = next(
        (node for node in nodes if node.get("Index Name") == index_name),
        None,
    )
    assert index_node is not None
    condition = index_node.get("Index Cond")
    assert isinstance(condition, str)
    assert "skill_id" in condition
    assert range_column in condition
    actual_rows = index_node.get("Actual Rows")
    actual_loops = index_node.get("Actual Loops")
    assert isinstance(actual_rows, int | float)
    assert isinstance(actual_loops, int | float)
    assert actual_rows * actual_loops <= maximum_rows


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

        projection = await repo.get_organization_adoption_projection_page(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            limit=10,
            after=None,
        )
        assert projection is not None
        assert projection.summary is not None
        summary = projection.summary
        resources = projection.items

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

        assert len(captured_statements) == 1
        adoption_statements = [
            (statement, parameters)
            for statement, parameters in captured_statements
            if "organization_skill_adoption_" in statement
        ]
        assert len(adoption_statements) == 1
        projection_statement, projection_parameters = adoption_statements[0]
        assert "organization_skill_adoption_resources" in projection_statement
        assert "organization_skill_adoption_facts" in projection_statement
        assert "organization_skill_adoption_totals" in projection_statement
        assert "UNION ALL" in projection_statement
        assert "ORDER BY" in projection_statement
        assert "LIMIT" in projection_statement

        connection = await session.connection()
        await connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
        explained = await connection.exec_driver_sql(
            f"EXPLAIN (COSTS OFF) {projection_statement}",
            projection_parameters,
        )
        plan = "\n".join(str(row[0]) for row in explained)
        assert "Append" in plan
        assert "Seq Scan" not in plan

        assert first_page.summary is not None
        assert [
            (resource.kind, resource.resource_id) for resource in first_page.items
        ] == [(SkillAdoptionResourceKind.ASSISTANT, assistant_behind.id)]
        assert first_page.next_cursor is not None
        captured_statements.clear()
        sa.event.listen(
            sync_engine,
            "before_cursor_execute",
            capture_statement,
        )
        try:
            second_page = await adoption_service.get_adoption_projection(
                skill_id=skill.id,
                limit=1,
                cursor=first_page.next_cursor,
            )
        finally:
            sa.event.remove(
                sync_engine,
                "before_cursor_execute",
                capture_statement,
            )
        assert second_page.summary is None
        assert len(captured_statements) == 1
        continuation_statement = captured_statements[0][0]
        assert "organization_skill_adoption_resources" in continuation_statement
        assert "organization_skill_adoption_facts" not in continuation_statement
        assert "organization_skill_adoption_totals" not in continuation_statement
        assert (
            "organization_skill_adoption_revision_counts" not in continuation_statement
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
        assert third_page.summary is None
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


async def test_adoption_continuations_seek_composite_binding_indexes(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
):
    page_limit = 5
    resource_count = 40

    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        model = await completion_model_factory(session, "skill-adoption-plan-model")
        shared_space = await space_factory(
            session,
            "Skill adoption plan Space",
            [model.id],
        )
        repo = container.skill_repo()
        target = await repo.create(
            space_id=organization.id,
            slug=f"adoption-plan-{uuid4().hex[:8]}",
            display_name="Adoption plan target",
            description="Exercises bounded adoption continuations.",
            instructions="Use the target Skill.",
            content_digest="3" * 64,
            created_by_user_id=admin_user.id,
        )
        unrelated = await repo.create(
            space_id=organization.id,
            slug=f"adoption-plan-unrelated-{uuid4().hex[:8]}",
            display_name="Unrelated adoption plan Skill",
            description="Creates unrelated binding rows.",
            instructions="Use the unrelated Skill.",
            content_digest="4" * 64,
            created_by_user_id=admin_user.id,
        )

        assistants = [
            Assistants(
                id=UUID(int=1_000 + offset),
                name=f"Plan Assistant {offset:03}",
                user_id=admin_user.id,
                completion_model_id=model.id,
                completion_model_kwargs={},
                logging_enabled=True,
                is_default=False,
                published=False,
                space_id=shared_space.id,
            )
            for offset in range(resource_count)
        ]
        apps = [
            Apps(
                id=UUID(int=2_000 + offset),
                name=f"Plan App {offset:03}",
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                space_id=shared_space.id,
                completion_model_id=model.id,
                completion_model_kwargs={},
                published=False,
            )
            for offset in range(resource_count)
        ]
        session.add_all([*assistants, *apps])
        await session.flush()
        session.add_all(
            [
                binding
                for assistant in assistants
                for binding in (
                    AssistantSkillBindings(
                        assistant_id=assistant.id,
                        tenant_id=admin_user.tenant_id,
                        space_id=shared_space.id,
                        skill_space_id=organization.id,
                        skill_id=target.id,
                        skill_revision_id=target.current_revision.id,
                        position=0,
                    ),
                    AssistantSkillBindings(
                        assistant_id=assistant.id,
                        tenant_id=admin_user.tenant_id,
                        space_id=shared_space.id,
                        skill_space_id=organization.id,
                        skill_id=unrelated.id,
                        skill_revision_id=unrelated.current_revision.id,
                        position=1,
                    ),
                )
            ]
            + [
                binding
                for app in apps
                for binding in (
                    AppSkillBindings(
                        app_id=app.id,
                        tenant_id=admin_user.tenant_id,
                        space_id=shared_space.id,
                        skill_space_id=organization.id,
                        skill_id=target.id,
                        skill_revision_id=target.current_revision.id,
                        position=0,
                    ),
                    AppSkillBindings(
                        app_id=app.id,
                        tenant_id=admin_user.tenant_id,
                        space_id=shared_space.id,
                        skill_space_id=organization.id,
                        skill_id=unrelated.id,
                        skill_revision_id=unrelated.current_revision.id,
                        position=1,
                    ),
                )
            ]
        )
        await session.flush()

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
            if "organization_skill_adoption_" in statement:
                captured_statements.append((statement, parameters))

        assert session.bind is not None
        sync_engine = session.bind.sync_engine
        sa.event.listen(sync_engine, "before_cursor_execute", capture_statement)
        try:
            assistant_page = await repo.get_organization_adoption_projection_page(
                tenant_id=admin_user.tenant_id,
                skill_id=target.id,
                limit=page_limit,
                after=SkillAdoptionCursor(
                    kind=SkillAdoptionResourceKind.ASSISTANT,
                    resource_id=assistants[9].id,
                ),
            )
        finally:
            sa.event.remove(sync_engine, "before_cursor_execute", capture_statement)
        assert assistant_page is not None
        assert len(captured_statements) == 1
        assistant_nodes = await _explain_captured_statement(
            session,
            statement=captured_statements[0][0],
            parameters=captured_statements[0][1],
        )
        _assert_bounded_composite_scan(
            assistant_nodes,
            index_name="ix_assistant_skill_bindings_skill_id_assistant_id",
            range_column="assistant_id",
            maximum_rows=page_limit + 1,
        )

        captured_statements.clear()
        sa.event.listen(sync_engine, "before_cursor_execute", capture_statement)
        try:
            app_page = await repo.get_organization_adoption_projection_page(
                tenant_id=admin_user.tenant_id,
                skill_id=target.id,
                limit=page_limit,
                after=SkillAdoptionCursor(
                    kind=SkillAdoptionResourceKind.APP,
                    resource_id=apps[9].id,
                ),
            )
        finally:
            sa.event.remove(sync_engine, "before_cursor_execute", capture_statement)
        assert app_page is not None
        assert len(captured_statements) == 1
        app_nodes = await _explain_captured_statement(
            session,
            statement=captured_statements[0][0],
            parameters=captured_statements[0][1],
        )
        _assert_bounded_composite_scan(
            app_nodes,
            index_name="ix_app_skill_bindings_skill_id_app_id",
            range_column="app_id",
            maximum_rows=page_limit + 1,
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

        projection = await repo.get_organization_adoption_projection_page(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            limit=10,
            after=None,
        )
        assert projection is not None
        assert projection.summary is not None
        summary = projection.summary

        assert summary.assistant_count == 0
        assert summary.app_count == 0
        assert summary.distinct_space_count == 0
        assert summary.behind_published_count == 0
        assert summary.personal_chat is None
        assert summary.revision_counts == ()
        assert projection.items == ()


async def test_adoption_projection_uses_one_consistent_statement_snapshot(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
):
    async with db_container() as setup_container:
        setup_session = setup_container.session()
        organization = await _organization_space(
            setup_session,
            tenant_id=admin_user.tenant_id,
        )
        model = await completion_model_factory(
            setup_session,
            "skill-adoption-snapshot-model",
        )
        shared_space = await space_factory(
            setup_session,
            "Adoption snapshot Space",
            [model.id],
        )
        setup_session.add(
            SpacesUsers(
                space_id=shared_space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            setup_session,
            "Snapshot-bound Assistant",
            model.id,
            space_id=shared_space.id,
        )
        setup_repo = setup_container.skill_repo()
        skill = await setup_repo.create(
            space_id=organization.id,
            slug=f"snapshot-adoption-{uuid4().hex[:8]}",
            display_name="Snapshot adoption projection",
            description="Keeps summary and resources on one database snapshot.",
            instructions="Use one consistent projection.",
            content_digest="a" * 64,
            created_by_user_id=admin_user.id,
        )
        revision = skill.current_revision
        await setup_repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revision.id,
        )
        await setup_container.skill_service().replace_assistant_bindings(
            space_id=shared_space.id,
            assistant_id=assistant.id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id,
                    skill_revision_id=revision.id,
                )
            ],
        )
        assistant_id = assistant.id
        skill_id = skill.id
        await setup_session.commit()

    statement_finished = asyncio.Event()
    mutation_finished = asyncio.Event()
    async with (
        db_container(user=admin_user) as reader_container,
        db_container(user=admin_user) as writer_container,
    ):
        reader_session = reader_container.session()
        original_execute = reader_session.execute

        async def execute_then_pause(*args, **kwargs):
            result = await original_execute(*args, **kwargs)
            statement_finished.set()
            await mutation_finished.wait()
            return result

        monkeypatch.setattr(reader_session, "execute", execute_then_pause)
        projection_task = asyncio.create_task(
            reader_container.skill_repo().get_organization_adoption_projection_page(
                tenant_id=admin_user.tenant_id,
                skill_id=skill_id,
                limit=10,
                after=None,
            )
        )
        await statement_finished.wait()

        writer_session = writer_container.session()
        await writer_session.execute(
            sa.delete(AssistantSkillBindings).where(
                AssistantSkillBindings.assistant_id == assistant_id,
                AssistantSkillBindings.skill_id == skill_id,
            )
        )
        await writer_session.commit()
        mutation_finished.set()
        projection = await projection_task

    assert projection is not None
    assert projection.summary is not None
    assert projection.summary.assistant_count == 1
    assert [(resource.kind, resource.resource_id) for resource in projection.items] == [
        (SkillAdoptionResourceKind.ASSISTANT, assistant_id)
    ]

    async with db_container(user=admin_user) as verify_container:
        updated_projection = await verify_container.skill_repo().get_organization_adoption_projection_page(
            tenant_id=admin_user.tenant_id,
            skill_id=skill_id,
            limit=10,
            after=None,
        )
        assert updated_projection is not None
        assert updated_projection.summary is not None
        assert updated_projection.summary.assistant_count == 0
        assert updated_projection.items == ()


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
        projection = await repo.get_organization_adoption_projection_page(
            tenant_id=foreign_tenant_id,
            skill_id=skill.id,
            limit=10,
            after=None,
        )

        assert projection is None

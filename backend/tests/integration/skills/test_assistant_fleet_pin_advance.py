import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.skill_table import AssistantSkillBindings, Skills
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.skills.domain.skill import (
    AssistantPinAdvanceOutcome,
    SkillBindingIntent,
    SkillBindingReference,
    SkillBlockedForBindingError,
    SkillNotPublishedForBindingError,
    SkillRevisionConflictError,
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


async def _create_revision(repo, *, skill_id: UUID, user_id: UUID, number: int):
    change = await repo.create_revision(
        skill_id=skill_id,
        display_name=f"Fleet revision {number}",
        description=f"Fleet revision {number}",
        instructions=f"Fleet instructions {number}",
        content_digest=str(number) * 64,
        created_by_user_id=user_id,
    )
    assert change is not None
    return change.revision


@dataclass(frozen=True)
class _FleetSeed:
    space_id: UUID
    skill_id: UUID
    old_revision_id: UUID
    published_revision_id: UUID
    assistant_ids: tuple[UUID, ...]


async def _seed_behind_fleet(
    container,
    *,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    size: int = 2,
) -> _FleetSeed:
    session = container.session()
    model = await completion_model_factory(
        session,
        f"fleet-write-{uuid4().hex[:8]}",
    )
    space = await space_factory(
        session,
        f"Fleet write {uuid4().hex[:8]}",
        [model.id],
    )
    session.add(
        SpacesUsers(
            space_id=space.id,
            user_id=admin_user.id,
            role="admin",
        )
    )
    assistants = [
        await assistant_factory(
            session,
            f"Fleet writer {index}",
            model.id,
            space_id=space.id,
        )
        for index in range(size)
    ]
    organization = await _organization_space(
        session,
        tenant_id=admin_user.tenant_id,
    )
    repo = container.skill_repo()
    skill = await repo.create(
        space_id=organization.id,
        slug=f"fleet-write-{uuid4().hex[:8]}",
        display_name="Fleet write",
        description="Fleet write",
        instructions="Fleet instructions 1",
        content_digest="1" * 64,
        created_by_user_id=admin_user.id,
    )
    old_revision = skill.current_revision
    await repo.publish_organization(
        tenant_id=admin_user.tenant_id,
        skill_id=skill.id,
        expected_revision_id=old_revision.id,
    )
    for assistant in assistants:
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=old_revision.id,
                    )
                )
            ],
        )
    published = await _create_revision(
        repo,
        skill_id=skill.id,
        user_id=admin_user.id,
        number=2,
    )
    await repo.publish_organization(
        tenant_id=admin_user.tenant_id,
        skill_id=skill.id,
        expected_revision_id=published.id,
    )
    return _FleetSeed(
        space_id=space.id,
        skill_id=skill.id,
        old_revision_id=old_revision.id,
        published_revision_id=published.id,
        assistant_ids=tuple(assistant.id for assistant in assistants),
    )


async def _discover(container, *, tenant_id: UUID, seed: _FleetSeed):
    (
        targets,
        next_after,
    ) = await container.skill_repo().list_assistant_pin_advance_targets(
        tenant_id=tenant_id,
        skill_id=seed.skill_id,
        expected_published_revision_id=seed.published_revision_id,
        after_assistant_id=None,
        limit=100,
    )
    assert next_after is None
    return targets


async def _wait_until_database_lock(db_container, *, pid: int) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        async with db_container() as observer:
            wait_event_type = await observer.session().scalar(
                sa.text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": pid},
            )
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Database session {pid} did not wait for the parent lock")


def _walk_plan(node: Mapping[str, object]) -> list[Mapping[str, object]]:
    nodes = [node]
    children = node.get("Plans")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                nodes.extend(_walk_plan(child))
    return nodes


async def _explain_statement(
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
    root = document[0]
    assert isinstance(root, dict)
    plan = root.get("Plan")
    assert isinstance(plan, dict)
    return _walk_plan(plan)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_walks_all_old_revision_cohorts_with_a_keyset_cursor(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            f"fleet-discovery-{uuid4().hex[:8]}",
        )
        space = await space_factory(
            session,
            f"Fleet discovery {uuid4().hex[:8]}",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        first = await assistant_factory(
            session,
            "Fleet first",
            model.id,
            id=UUID("00000000-0000-0000-0000-000000000011"),
            space_id=space.id,
        )
        second = await assistant_factory(
            session,
            "Fleet second",
            model.id,
            id=UUID("00000000-0000-0000-0000-000000000012"),
            space_id=space.id,
        )
        current = await assistant_factory(
            session,
            "Fleet current",
            model.id,
            id=UUID("00000000-0000-0000-0000-000000000013"),
            space_id=space.id,
        )
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-discovery-{uuid4().hex[:8]}",
            display_name="Fleet discovery",
            description="Fleet discovery",
            instructions="Fleet instructions 1",
            content_digest="1" * 64,
            created_by_user_id=admin_user.id,
        )
        revision_one = skill.current_revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revision_one.id,
        )
        skill_service = container.skill_service()
        await skill_service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=first.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=revision_one.id,
                    )
                )
            ],
        )
        revision_two = await _create_revision(
            repo,
            skill_id=skill.id,
            user_id=admin_user.id,
            number=2,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revision_two.id,
        )
        await skill_service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=second.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=revision_two.id,
                    )
                )
            ],
        )
        revision_three = await _create_revision(
            repo,
            skill_id=skill.id,
            user_id=admin_user.id,
            number=3,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=revision_three.id,
        )
        await skill_service.replace_assistant_bindings(
            space_id=space.id,
            assistant_id=current.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=revision_three.id,
                    )
                )
            ],
        )

        first_page, next_after = await repo.list_assistant_pin_advance_targets(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_published_revision_id=revision_three.id,
            after_assistant_id=None,
            limit=1,
        )
        second_page, complete = await repo.list_assistant_pin_advance_targets(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_published_revision_id=revision_three.id,
            after_assistant_id=next_after,
            limit=1,
        )

        assert [
            (target.assistant_id, target.from_revision_id, target.from_revision_number)
            for target in [*first_page, *second_page]
        ] == [
            (first.id, revision_one.id, 1),
            (second.id, revision_two.id, 2),
        ]
        assert first_page[0].assistant_row_version
        assert next_after == first.id
        assert complete is None

        results = await repo.advance_assistant_skill_pins(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_published_revision_id=revision_three.id,
            targets=[*first_page, *second_page],
        )

        assert [result.outcome for result in results] == [
            AssistantPinAdvanceOutcome.ADVANCED,
            AssistantPinAdvanceOutcome.ADVANCED,
        ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_advance_preserves_binding_rows_and_only_touches_parent_versions(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        other = await container.skill_repo().create(
            space_id=organization.id,
            slug=f"fleet-other-{uuid4().hex[:8]}",
            display_name="Fleet other",
            description="Unrelated binding",
            instructions="Unrelated instructions",
            content_digest="9" * 64,
            created_by_user_id=admin_user.id,
        )
        await container.skill_repo().publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=other.id,
            expected_revision_id=other.current_revision.id,
        )
        await container.skill_service().replace_assistant_bindings(
            space_id=seed.space_id,
            assistant_id=seed.assistant_ids[0],
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=seed.skill_id,
                        skill_revision_id=seed.old_revision_id,
                    )
                ),
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=other.id,
                        skill_revision_id=other.current_revision.id,
                    )
                ),
            ],
        )
        other_skill_id = other.id

    async with db_container() as container:
        session = container.session()
        binding_columns = tuple(AssistantSkillBindings.__table__.c)
        assistant_columns = tuple(Assistants.__table__.c)
        before_bindings = (
            (
                await session.execute(
                    sa.select(*binding_columns)
                    .where(AssistantSkillBindings.assistant_id.in_(seed.assistant_ids))
                    .order_by(
                        AssistantSkillBindings.assistant_id,
                        AssistantSkillBindings.skill_id,
                    )
                )
            )
            .mappings()
            .all()
        )
        before_parents = (
            (
                await session.execute(
                    sa.select(
                        *assistant_columns,
                        sa.cast(sa.literal_column("assistants.xmin"), sa.Text).label(
                            "xmin"
                        ),
                    )
                    .where(Assistants.id.in_(seed.assistant_ids))
                    .order_by(Assistants.id)
                )
            )
            .mappings()
            .all()
        )
        (
            targets,
            next_after,
        ) = await container.skill_repo().list_assistant_pin_advance_targets(
            tenant_id=admin_user.tenant_id,
            skill_id=seed.skill_id,
            expected_published_revision_id=seed.published_revision_id,
            after_assistant_id=None,
            limit=100,
        )
        assert next_after is None

        results = await container.skill_repo().advance_assistant_skill_pins(
            tenant_id=admin_user.tenant_id,
            skill_id=seed.skill_id,
            expected_published_revision_id=seed.published_revision_id,
            targets=targets,
        )

        after_bindings = (
            (
                await session.execute(
                    sa.select(*binding_columns)
                    .where(AssistantSkillBindings.assistant_id.in_(seed.assistant_ids))
                    .order_by(
                        AssistantSkillBindings.assistant_id,
                        AssistantSkillBindings.skill_id,
                    )
                )
            )
            .mappings()
            .all()
        )
        after_parents = (
            (
                await session.execute(
                    sa.select(
                        *assistant_columns,
                        sa.cast(sa.literal_column("assistants.xmin"), sa.Text).label(
                            "xmin"
                        ),
                    )
                    .where(Assistants.id.in_(seed.assistant_ids))
                    .order_by(Assistants.id)
                )
            )
            .mappings()
            .all()
        )

        assert all(
            result.outcome is AssistantPinAdvanceOutcome.ADVANCED for result in results
        )
        for before, after in zip(before_bindings, after_bindings, strict=True):
            changed = {
                column.name
                for column in binding_columns
                if before[column.name] != after[column.name]
            }
            if before["skill_id"] == seed.skill_id:
                assert changed == {"skill_revision_id"}
                assert after["skill_revision_id"] == seed.published_revision_id
            else:
                assert before["skill_id"] == other_skill_id
                assert changed == set()
        for before, after in zip(before_parents, after_parents, strict=True):
            changed = {
                column.name
                for column in assistant_columns
                if before[column.name] != after[column.name]
            }
            assert changed == {"updated_at"}
            assert before["xmin"] != after["xmin"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_excludes_personal_default_assistants(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            size=1,
        )
        personal_space = await container.space_init_service().get_personal_space()
        assert personal_space.id is not None
        assert personal_space.default_assistant is not None
        default_id = personal_space.default_assistant.id
        assert default_id is not None
        skill_space_id = await container.session().scalar(
            sa.select(Skills.space_id).where(Skills.id == seed.skill_id)
        )
        assert skill_space_id is not None
        container.session().add(
            AssistantSkillBindings(
                assistant_id=default_id,
                tenant_id=admin_user.tenant_id,
                space_id=personal_space.id,
                skill_space_id=skill_space_id,
                skill_id=seed.skill_id,
                skill_revision_id=seed.old_revision_id,
                position=0,
                activation_mode="always",
            )
        )
        await container.session().flush()

        targets = await _discover(
            container,
            tenant_id=admin_user.tenant_id,
            seed=seed,
        )

        assert [target.assistant_id for target in targets] == list(seed.assistant_ids)
        assert default_id not in {target.assistant_id for target in targets}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parent_change_after_discovery_skips_only_that_assistant(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
    async with db_container() as container:
        targets = await _discover(
            container,
            tenant_id=admin_user.tenant_id,
            seed=seed,
        )
    changed_id = targets[0].assistant_id
    async with db_container() as editor:
        await editor.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == changed_id)
            .values(description="Concurrent Assistant save")
        )
    async with db_container() as writer:
        results = await writer.skill_repo().advance_assistant_skill_pins(
            tenant_id=admin_user.tenant_id,
            skill_id=seed.skill_id,
            expected_published_revision_id=seed.published_revision_id,
            targets=targets,
        )
    async with db_container() as verifier:
        revisions = dict(
            (
                await verifier.session().execute(
                    sa.select(
                        AssistantSkillBindings.assistant_id,
                        AssistantSkillBindings.skill_revision_id,
                    ).where(AssistantSkillBindings.skill_id == seed.skill_id)
                )
            ).all()
        )

    assert {result.assistant_id: result.outcome for result in results} == {
        changed_id: AssistantPinAdvanceOutcome.CONCURRENT_CHANGE,
        targets[1].assistant_id: AssistantPinAdvanceOutcome.ADVANCED,
    }
    assert revisions[changed_id] == seed.old_revision_id
    assert revisions[targets[1].assistant_id] == seed.published_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_binding_change_after_discovery_is_not_overwritten(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            size=1,
        )
    async with db_container() as container:
        targets = await _discover(
            container,
            tenant_id=admin_user.tenant_id,
            seed=seed,
        )
    async with db_container() as editor:
        third = await _create_revision(
            editor.skill_repo(),
            skill_id=seed.skill_id,
            user_id=admin_user.id,
            number=3,
        )
        await editor.session().execute(
            sa.update(AssistantSkillBindings)
            .where(
                AssistantSkillBindings.assistant_id == seed.assistant_ids[0],
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
            .values(skill_revision_id=third.id)
        )
        third_revision_id = third.id
    async with db_container() as writer:
        results = await writer.skill_repo().advance_assistant_skill_pins(
            tenant_id=admin_user.tenant_id,
            skill_id=seed.skill_id,
            expected_published_revision_id=seed.published_revision_id,
            targets=targets,
        )
    async with db_container() as verifier:
        revision_id = await verifier.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_ids[0],
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )

    assert results[0].outcome is AssistantPinAdvanceOutcome.CONCURRENT_CHANGE
    assert revision_id == third_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_in_flight_parent_save_drains_before_xmin_guard(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            size=1,
        )
    async with db_container() as container:
        targets = await _discover(
            container,
            tenant_id=admin_user.tenant_id,
            seed=seed,
        )

    parent_locked = asyncio.Event()
    release_parent = asyncio.Event()

    async def hold_parent_save() -> None:
        async with db_container() as blocker:
            await blocker.session().execute(
                sa.select(Assistants.id)
                .where(Assistants.id == seed.assistant_ids[0])
                .with_for_update()
            )
            await blocker.session().execute(
                sa.update(Assistants)
                .where(Assistants.id == seed.assistant_ids[0])
                .values(description="In-flight Assistant save")
            )
            parent_locked.set()
            await release_parent.wait()

    async def write_chunk():
        async with db_container() as writer:
            pid = await writer.session().scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            result_task_pid.set_result(pid)
            return await writer.skill_repo().advance_assistant_skill_pins(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                expected_published_revision_id=seed.published_revision_id,
                targets=targets,
            )

    result_task_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    blocker_task = asyncio.create_task(hold_parent_save())
    await asyncio.wait_for(parent_locked.wait(), timeout=5)
    writer_task = asyncio.create_task(write_chunk())
    pid = await asyncio.wait_for(result_task_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_container, pid=pid)
    finally:
        release_parent.set()
    await blocker_task
    results = await writer_task

    assert results[0].outcome is AssistantPinAdvanceOutcome.CONCURRENT_CHANGE


@pytest.mark.parametrize(
    ("terminal_state", "expected_error"),
    [
        ("unpublished", SkillNotPublishedForBindingError),
        ("republished", SkillRevisionConflictError),
        ("blocked", SkillBlockedForBindingError),
    ],
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_state_rolls_back_current_chunk_but_keeps_prior_chunk(
    terminal_state,
    expected_error,
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
    async with db_container() as container:
        targets = await _discover(
            container,
            tenant_id=admin_user.tenant_id,
            seed=seed,
        )
        first_result = await container.skill_repo().advance_assistant_skill_pins(
            tenant_id=admin_user.tenant_id,
            skill_id=seed.skill_id,
            expected_published_revision_id=seed.published_revision_id,
            targets=targets[:1],
        )
        assert first_result[0].outcome is AssistantPinAdvanceOutcome.ADVANCED
    async with db_container() as mutator:
        repo = mutator.skill_repo()
        if terminal_state == "unpublished":
            await repo.unpublish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
            )
        elif terminal_state == "republished":
            third = await _create_revision(
                repo,
                skill_id=seed.skill_id,
                user_id=admin_user.id,
                number=3,
            )
            await repo.publish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                expected_revision_id=third.id,
            )
        else:
            blocked = await repo.block_organization_skill(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                blocked_by_user_id=admin_user.id,
                reason="Confirmed unsafe instructions",
            )
            assert blocked is not None
    async with db_container() as writer:
        with pytest.raises(expected_error):
            await writer.skill_repo().advance_assistant_skill_pins(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                expected_published_revision_id=seed.published_revision_id,
                targets=targets[1:],
            )
    async with db_container() as verifier:
        revisions = dict(
            (
                await verifier.session().execute(
                    sa.select(
                        AssistantSkillBindings.assistant_id,
                        AssistantSkillBindings.skill_revision_id,
                    ).where(AssistantSkillBindings.skill_id == seed.skill_id)
                )
            ).all()
        )

    assert revisions[targets[0].assistant_id] == seed.published_revision_id
    assert revisions[targets[1].assistant_id] == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_chunks_advance_each_assistant_at_most_once(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            size=10,
        )
    async with db_container() as container:
        targets = await _discover(
            container,
            tenant_id=admin_user.tenant_id,
            seed=seed,
        )

    async def write_chunk():
        async with db_container() as writer:
            return await writer.skill_repo().advance_assistant_skill_pins(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                expected_published_revision_id=seed.published_revision_id,
                targets=targets,
            )

    first_results, second_results = await asyncio.gather(
        write_chunk(),
        write_chunk(),
    )
    outcomes = [result.outcome for result in [*first_results, *second_results]]
    async with db_container() as verifier:
        current_count = await verifier.session().scalar(
            sa.select(sa.func.count())
            .select_from(AssistantSkillBindings)
            .where(
                AssistantSkillBindings.skill_id == seed.skill_id,
                AssistantSkillBindings.skill_revision_id == seed.published_revision_id,
            )
        )

    assert outcomes.count(AssistantPinAdvanceOutcome.ADVANCED) == len(
        seed.assistant_ids
    )
    assert outcomes.count(AssistantPinAdvanceOutcome.CONCURRENT_CHANGE) == len(
        seed.assistant_ids
    )
    assert current_count == len(seed.assistant_ids)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_scales_as_one_bounded_forward_index_walk(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            size=0,
        )
        session = container.session()
        assistant_ids = tuple(UUID(int=(1 << 120) + index) for index in range(10_000))
        await session.execute(
            sa.insert(Assistants),
            [
                {
                    "id": assistant_id,
                    "name": f"Fleet scale {index}",
                    "user_id": admin_user.id,
                    "completion_model_id": None,
                    "completion_model_kwargs": {},
                    "logging_enabled": True,
                    "is_default": False,
                    "published": False,
                    "space_id": seed.space_id,
                }
                for index, assistant_id in enumerate(assistant_ids)
            ],
        )
        skill_space_id = await session.scalar(
            sa.select(Skills.space_id).where(Skills.id == seed.skill_id)
        )
        assert skill_space_id is not None
        await session.execute(
            sa.insert(AssistantSkillBindings),
            [
                {
                    "assistant_id": assistant_id,
                    "tenant_id": admin_user.tenant_id,
                    "space_id": seed.space_id,
                    "skill_space_id": skill_space_id,
                    "skill_id": seed.skill_id,
                    "skill_revision_id": seed.old_revision_id,
                    "position": 0,
                    "activation_mode": "always",
                }
                for assistant_id in assistant_ids
            ],
        )

        discovery_queries = 0
        captured_statement: tuple[str, tuple[object, ...]] | None = None

        def capture_discovery(
            _connection,
            _cursor,
            statement,
            parameters,
            _context,
            _executemany,
        ) -> None:
            nonlocal discovery_queries, captured_statement
            if (
                "FROM assistant_skill_bindings" in statement
                and "ORDER BY assistant_skill_bindings.assistant_id" in statement
            ):
                discovery_queries += 1
                if "assistant_skill_bindings.assistant_id >" in statement:
                    assert isinstance(parameters, tuple)
                    captured_statement = (statement, parameters)

        assert session.bind is not None
        sync_engine = session.bind.sync_engine
        sa.event.listen(sync_engine, "before_cursor_execute", capture_discovery)
        after: UUID | None = None
        seen: list[UUID] = []
        peak_targets = 0
        per_chunk_queries: list[int] = []
        try:
            while True:
                before_count = discovery_queries
                (
                    targets,
                    next_after,
                ) = await container.skill_repo().list_assistant_pin_advance_targets(
                    tenant_id=admin_user.tenant_id,
                    skill_id=seed.skill_id,
                    expected_published_revision_id=seed.published_revision_id,
                    after_assistant_id=after,
                    limit=100,
                )
                per_chunk_queries.append(discovery_queries - before_count)
                peak_targets = max(peak_targets, len(targets))
                seen.extend(target.assistant_id for target in targets)
                if next_after is None:
                    break
                assert targets
                assert next_after == targets[-1].assistant_id
                assert after is None or next_after > after
                after = next_after
        finally:
            sa.event.remove(
                sync_engine,
                "before_cursor_execute",
                capture_discovery,
            )

        assert seen == list(assistant_ids)
        assert peak_targets == 100
        assert per_chunk_queries == [1] * 100
        assert captured_statement is not None
        plan_nodes = await _explain_statement(
            session,
            statement=captured_statement[0],
            parameters=captured_statement[1],
        )
        index_node = next(
            (
                node
                for node in plan_nodes
                if node.get("Index Name")
                == "ix_assistant_skill_bindings_skill_id_assistant_id"
            ),
            None,
        )
        assert index_node is not None, {
            node.get("Index Name")
            for node in plan_nodes
            if node.get("Index Name") is not None
        }
        condition = index_node.get("Index Cond")
        assert isinstance(condition, str)
        assert "skill_id" in condition
        assert "assistant_id" in condition

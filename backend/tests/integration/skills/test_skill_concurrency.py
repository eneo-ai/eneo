import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.apps.app_runs.app_run_repo import _serialize_skill_provenance
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.jobs.job_models import Task
from eneo.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
)
from eneo.main.models import Status
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    SkillBindingIntent,
    SkillBindingReference,
    SkillRuntimePolicy,
)


@dataclass(frozen=True)
class SkillConcurrencyResources:
    tenant_id: UUID
    user_id: UUID
    completion_model_id: UUID
    space_id: UUID
    target_space_id: UUID
    assistant_id: UUID
    app_id: UUID
    first_skill_id: UUID
    first_revision_id: UUID
    second_skill_id: UUID
    second_revision_id: UUID

    @property
    def first_reference(self) -> SkillBindingReference:
        return SkillBindingReference(
            skill_id=self.first_skill_id,
            skill_revision_id=self.first_revision_id,
        )

    @property
    def second_reference(self) -> SkillBindingReference:
        return SkillBindingReference(
            skill_id=self.second_skill_id,
            skill_revision_id=self.second_revision_id,
        )


@pytest.fixture
async def skill_concurrency_resources(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    app_factory,
    admin_user,
) -> SkillConcurrencyResources:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "skills-concurrency-model")
        space = await space_factory(
            session,
            "Skills concurrency space",
            [model.id],
        )
        target_space = await space_factory(
            session,
            "Skills concurrency target space",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
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
            "Skills concurrency assistant",
            model.id,
            space_id=space.id,
        )
        app = await app_factory(
            session,
            "Skills concurrency app",
            model.id,
            space_id=space.id,
        )
        first = await container.skill_repo().create(
            space_id=space.id,
            slug="first-skill",
            display_name="First Skill",
            description="First concurrency Skill",
            instructions="First instructions",
            content_digest="1" * 64,
            created_by_user_id=admin_user.id,
        )
        second = await container.skill_repo().create(
            space_id=space.id,
            slug="second-skill",
            display_name="Second Skill",
            description="Second concurrency Skill",
            instructions="Second instructions",
            content_digest="2" * 64,
            created_by_user_id=admin_user.id,
        )
        space_id = space.id
        assistant_id = assistant.id
        app_id = app.id
        completion_model_id = model.id
        target_space_id = target_space.id

    return SkillConcurrencyResources(
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        completion_model_id=completion_model_id,
        space_id=space_id,
        target_space_id=target_space_id,
        assistant_id=assistant_id,
        app_id=app_id,
        first_skill_id=first.id,
        first_revision_id=first.current_revision.id,
        second_skill_id=second.id,
        second_revision_id=second.current_revision.id,
    )


async def _wait_until_database_lock(db_session, *, pid: int) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        async with db_session() as session:
            wait_event_type = await session.scalar(
                sa.text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ).bindparams(pid=pid)
            )
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Database session {pid} did not wait for the expected lock")


async def _backend_pid(container) -> int:
    pid = await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
    assert isinstance(pid, int)
    return pid


async def _wait_for_held_write(
    event: asyncio.Event, writer: asyncio.Task[object]
) -> None:
    event_waiter = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait(
            {event_waiter, writer},
            timeout=5,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if writer in done:
            await writer
            raise AssertionError("Writer completed without holding its transaction")
        if event_waiter not in done:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            raise AssertionError("Writer did not reach the held transaction state")
        await event_waiter
    finally:
        if not event_waiter.done():
            event_waiter.cancel()
            await asyncio.gather(event_waiter, return_exceptions=True)


async def test_fresh_install_owner_has_every_tenant_permission(admin_user):
    assert admin_user.permissions == set(Permission) - {Permission.EDITOR}


async def test_binding_projection_keeps_pinned_and_current_revision_identity(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
):
    resources = skill_concurrency_resources
    async with db_container() as container:
        await container.skill_service().replace_assistant_bindings(
            space_id=resources.space_id,
            assistant_id=resources.assistant_id,
            intents=[SkillBindingIntent(reference=resources.first_reference)],
        )
        change = await container.skill_service().create_revision(
            skill_id=resources.first_skill_id,
            display_name="First Skill",
            description="First concurrency Skill",
            instructions="Updated first instructions",
        )

    async with db_container() as container:
        bindings = await container.skill_repo().list_assistant_bindings(
            assistant_id=resources.assistant_id
        )

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.skill_revision_id == resources.first_revision_id
    assert binding.revision_number == 1
    assert binding.current_revision_id == change.revision.id
    assert binding.current_revision_number == 2


@pytest.mark.parametrize("parent_kind", ["assistant", "app"])
@pytest.mark.parametrize("second_clears", [False, True])
async def test_parent_binding_replacements_are_serialized(
    parent_kind: str,
    second_clears: bool,
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    first_finished = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def replace(container, references: list[SkillBindingReference]):
        service = container.skill_service()
        if parent_kind == "assistant":
            return await service.replace_assistant_bindings(
                space_id=resources.space_id,
                assistant_id=resources.assistant_id,
                intents=[
                    SkillBindingIntent(reference=reference) for reference in references
                ],
            )
        return await service.replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=references,
        )

    async def first_writer():
        async with db_container() as container:
            result = await replace(container, [resources.first_reference])
            first_finished.set()
            await release_first.wait()
            return result

    async def second_writer():
        async with db_container() as container:
            second_pid.set_result(await _backend_pid(container))
            references = [] if second_clears else [resources.second_reference]
            return await replace(container, references)

    first_task = asyncio.create_task(first_writer())
    await _wait_for_held_write(first_finished, first_task)
    second_task = asyncio.create_task(second_writer())
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    await asyncio.gather(first_task, second_task)

    async with db_container() as container:
        repo = container.skill_repo()
        if parent_kind == "assistant":
            bindings = await repo.list_assistant_bindings(
                assistant_id=resources.assistant_id
            )
        else:
            bindings = await repo.list_app_bindings(app_id=resources.app_id)

    expected_ids = [] if second_clears else [resources.second_skill_id]
    assert [binding.skill_id for binding in bindings] == expected_ids
    assert [binding.position for binding in bindings] == list(range(len(expected_ids)))


@pytest.mark.parametrize("first_operation", ["move", "bind"])
async def test_assistant_move_and_skill_binding_update_are_serialized(
    first_operation: str,
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    first_finished = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def move(container):
        return await container.resource_mover_service().move_assistant_to_space(
            assistant_id=resources.assistant_id,
            space_id=resources.target_space_id,
        )

    async def bind(container):
        return await container.skill_service().replace_assistant_bindings(
            space_id=resources.space_id,
            assistant_id=resources.assistant_id,
            intents=[SkillBindingIntent(reference=resources.first_reference)],
        )

    first_action = move if first_operation == "move" else bind
    second_action = bind if first_operation == "move" else move
    second_error = (
        NotFoundException if first_operation == "move" else BadRequestException
    )

    async def first_writer():
        async with db_container() as container:
            result = await first_action(container)
            first_finished.set()
            await release_first.wait()
            return result

    async def second_writer():
        async with db_container() as container:
            second_pid.set_result(await _backend_pid(container))
            with pytest.raises(second_error):
                await second_action(container)

    first_task = asyncio.create_task(first_writer())
    await _wait_for_held_write(first_finished, first_task)
    second_task = asyncio.create_task(second_writer())
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    await asyncio.gather(first_task, second_task)

    async with db_container() as container:
        assistant_space_id = await container.session().scalar(
            sa.select(Assistants.space_id).where(
                Assistants.id == resources.assistant_id
            )
        )
        bindings = await container.skill_repo().list_assistant_bindings(
            assistant_id=resources.assistant_id
        )

    if first_operation == "move":
        assert assistant_space_id == resources.target_space_id
        assert bindings == []
    else:
        assert assistant_space_id == resources.space_id
        assert [binding.skill_id for binding in bindings] == [resources.first_skill_id]


async def test_deactivation_serializes_with_new_binding_validation(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    deactivation_finished = asyncio.Event()
    release_deactivation = asyncio.Event()
    binding_pid = asyncio.get_running_loop().create_future()

    async def deactivate():
        async with db_container() as container:
            change = await container.skill_service().set_active(
                skill_id=resources.first_skill_id,
                is_active=False,
            )
            deactivation_finished.set()
            await release_deactivation.wait()
            return change

    async def attach():
        async with db_container() as container:
            binding_pid.set_result(await _backend_pid(container))
            with pytest.raises(BadRequestException, match="Inactive Skills"):
                await container.skill_service().replace_app_bindings(
                    space_id=resources.space_id,
                    app_id=resources.app_id,
                    references=[resources.first_reference],
                )

    deactivation_task = asyncio.create_task(deactivate())
    await _wait_for_held_write(deactivation_finished, deactivation_task)
    binding_task = asyncio.create_task(attach())
    pid = await asyncio.wait_for(binding_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_deactivation.set()
    change, _ = await asyncio.gather(deactivation_task, binding_task)

    assert change.changed is True
    assert change.previous_is_active is True
    async with db_container() as container:
        skill = await container.skill_repo().get(skill_id=resources.first_skill_id)
        bindings = await container.skill_repo().list_app_bindings(
            app_id=resources.app_id
        )
    assert skill is not None and skill.is_active is False
    assert bindings == []


async def test_delete_serializes_before_new_binding_validation(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    delete_finished = asyncio.Event()
    release_delete = asyncio.Event()
    binding_pid = asyncio.get_running_loop().create_future()

    async def delete():
        async with db_container() as container:
            deleted = await container.skill_service().delete_skill(
                skill_id=resources.first_skill_id
            )
            delete_finished.set()
            await release_delete.wait()
            return deleted

    async def attach():
        async with db_container() as container:
            binding_pid.set_result(await _backend_pid(container))
            with pytest.raises(NotFoundException, match="Skill revisions"):
                await container.skill_service().replace_app_bindings(
                    space_id=resources.space_id,
                    app_id=resources.app_id,
                    references=[resources.first_reference],
                )

    delete_task = asyncio.create_task(delete())
    await _wait_for_held_write(delete_finished, delete_task)
    binding_task = asyncio.create_task(attach())
    pid = await asyncio.wait_for(binding_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_delete.set()
    deleted, _ = await asyncio.gather(delete_task, binding_task)

    assert deleted.id == resources.first_skill_id
    async with db_container() as container:
        skill = await container.skill_repo().get(skill_id=resources.first_skill_id)
        bindings = await container.skill_repo().list_app_bindings(
            app_id=resources.app_id
        )
    assert skill is None
    assert bindings == []


async def test_new_binding_serializes_before_delete_validation(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    binding_finished = asyncio.Event()
    release_binding = asyncio.Event()
    delete_pid = asyncio.get_running_loop().create_future()

    async def attach():
        async with db_container() as container:
            bindings = await container.skill_service().replace_app_bindings(
                space_id=resources.space_id,
                app_id=resources.app_id,
                references=[resources.first_reference],
            )
            binding_finished.set()
            await release_binding.wait()
            return bindings

    async def delete():
        async with db_container() as container:
            delete_pid.set_result(await _backend_pid(container))
            with pytest.raises(NameCollisionException, match="still attached"):
                await container.skill_service().delete_skill(
                    skill_id=resources.first_skill_id
                )

    binding_task = asyncio.create_task(attach())
    await _wait_for_held_write(binding_finished, binding_task)
    delete_task = asyncio.create_task(delete())
    pid = await asyncio.wait_for(delete_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_binding.set()
    bindings, _ = await asyncio.gather(binding_task, delete_task)

    assert [binding.skill_id for binding in bindings] == [resources.first_skill_id]
    async with db_container() as container:
        skill = await container.skill_repo().get(skill_id=resources.first_skill_id)
        persisted = await container.skill_repo().list_app_bindings(
            app_id=resources.app_id
        )
    assert skill is not None
    assert [binding.skill_id for binding in persisted] == [resources.first_skill_id]


@pytest.mark.parametrize("parent_kind", ["assistant", "app", "governance"])
async def test_block_winning_skill_lock_rejects_concurrent_binding_change(
    parent_kind: str,
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
    admin_user,
):
    resources = skill_concurrency_resources
    block_locked = asyncio.Event()
    release_block = asyncio.Event()
    binding_pid = asyncio.get_running_loop().create_future()

    async with db_container() as container:
        session = container.session()
        organization_space = await session.scalar(
            sa.select(Spaces).where(
                Spaces.tenant_id == resources.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization_space is not None
        session.add(
            SpacesUsers(
                space_id=organization_space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        policy = GovernancePolicies(
            tenant_id=resources.tenant_id,
            scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT.value,
        )
        session.add(policy)
        await session.flush()
        repo = container.skill_repo()
        existing_skill = await repo.create(
            space_id=organization_space.id,
            slug=f"existing-concurrent-block-{uuid4().hex[:8]}",
            display_name="Existing concurrent binding",
            description="Remains bound when a blocked replacement is rejected.",
            instructions="Use the existing approved guidance.",
            content_digest="a" * 64,
            created_by_user_id=admin_user.id,
        )
        blocked_skill = await repo.create(
            space_id=organization_space.id,
            slug=f"blocked-concurrent-binding-{uuid4().hex[:8]}",
            display_name="Concurrent block target",
            description="Must not become bound after its block commits.",
            instructions="Use the target approved guidance.",
            content_digest="b" * 64,
            created_by_user_id=admin_user.id,
        )
        for skill in (existing_skill, blocked_skill):
            await repo.publish_organization(
                tenant_id=resources.tenant_id,
                skill_id=skill.id,
                expected_revision_id=skill.current_revision.id,
            )
        organization_space_id = organization_space.id
        policy_id = policy.id
        existing_reference = SkillBindingReference(
            skill_id=existing_skill.id,
            skill_revision_id=existing_skill.current_revision.id,
        )
        blocked_reference = SkillBindingReference(
            skill_id=blocked_skill.id,
            skill_revision_id=blocked_skill.current_revision.id,
        )

        service = container.skill_service()
        if parent_kind == "assistant":
            await service.replace_assistant_bindings(
                space_id=resources.space_id,
                assistant_id=resources.assistant_id,
                intents=[SkillBindingIntent(reference=existing_reference)],
            )
        elif parent_kind == "app":
            await service.replace_app_bindings(
                space_id=resources.space_id,
                app_id=resources.app_id,
                references=[existing_reference],
            )
        else:
            await service.replace_governance_bindings(
                policy_id=policy_id,
                organization_space_id=organization_space_id,
                references=[existing_reference],
            )

    async def hold_block():
        async with db_container() as container:
            change = await container.skill_repo().block_organization_skill(
                tenant_id=resources.tenant_id,
                skill_id=blocked_skill.id,
                blocked_by_user_id=admin_user.id,
                reason="Concurrent incident",
            )
            assert change is not None
            block_locked.set()
            await release_block.wait()
            return change

    async def replace_while_block_commits():
        async with db_container() as container:
            binding_pid.set_result(await _backend_pid(container))
            service = container.skill_service()
            references = [existing_reference, blocked_reference]
            if parent_kind == "assistant":
                return await service.replace_assistant_bindings(
                    space_id=resources.space_id,
                    assistant_id=resources.assistant_id,
                    intents=[
                        SkillBindingIntent(reference=reference)
                        for reference in references
                    ],
                )
            if parent_kind == "app":
                return await service.replace_app_bindings(
                    space_id=resources.space_id,
                    app_id=resources.app_id,
                    references=references,
                )
            return await service.replace_governance_bindings(
                policy_id=policy_id,
                organization_space_id=organization_space_id,
                references=references,
            )

    block_task = asyncio.create_task(hold_block())
    await _wait_for_held_write(block_locked, block_task)
    binding_task = asyncio.create_task(replace_while_block_commits())
    pid = await asyncio.wait_for(binding_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_block.set()

    await block_task
    with pytest.raises(BadRequestException, match="Blocked organisation Skills"):
        await binding_task

    async with db_container() as container:
        repo = container.skill_repo()
        if parent_kind == "assistant":
            bindings = await repo.list_assistant_bindings(
                assistant_id=resources.assistant_id
            )
        elif parent_kind == "app":
            bindings = await repo.list_app_bindings(app_id=resources.app_id)
        else:
            bindings = await repo.list_policy_bindings(policy_id=policy_id)

    assert [binding.skill_id for binding in bindings] == [existing_skill.id]


@pytest.mark.parametrize("terminal_status", [Status.COMPLETE, Status.FAILED])
async def test_queued_app_run_snapshot_blocks_concurrent_skill_deletion_until_terminal(
    terminal_status: Status,
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    snapshot_ready = asyncio.Event()
    persist_snapshot = asyncio.Event()
    snapshot_persisted = asyncio.Event()
    release_snapshot = asyncio.Event()
    delete_pid = asyncio.get_running_loop().create_future()

    async with db_container() as container:
        await container.skill_service().replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=[resources.first_reference],
        )

    async def queue_snapshot():
        async with db_container() as container:
            composition = await container.skill_service().compose_for_app(
                app_id=resources.app_id,
                base_instructions="App instructions",
            )
            snapshot_ready.set()
            await persist_snapshot.wait()
            job_id = uuid4()
            app_run_id = uuid4()
            container.session().add(
                Jobs(
                    id=job_id,
                    user_id=resources.user_id,
                    task=Task.RUN_APP.value,
                    status=Status.QUEUED.value,
                )
            )
            container.session().add(
                AppRuns(
                    id=app_run_id,
                    tenant_id=resources.tenant_id,
                    user_id=resources.user_id,
                    app_id=resources.app_id,
                    job_id=job_id,
                    completion_model_id=resources.completion_model_id,
                    skill_provenance=_serialize_skill_provenance(
                        composition.provenance
                    ),
                )
            )
            await container.session().flush()
            snapshot_persisted.set()
            await release_snapshot.wait()
            return composition.provenance, job_id, app_run_id

    async def delete():
        async with db_container() as container:
            delete_pid.set_result(await _backend_pid(container))
            with pytest.raises(
                NameCollisionException, match="queued or running App run"
            ):
                await container.skill_service().delete_skill(
                    skill_id=resources.first_skill_id
                )

    snapshot_task = asyncio.create_task(queue_snapshot())
    await _wait_for_held_write(snapshot_ready, snapshot_task)

    async with db_container() as container:
        await container.skill_service().replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=[],
        )

    persist_snapshot.set()
    await _wait_for_held_write(snapshot_persisted, snapshot_task)

    delete_task = asyncio.create_task(delete())
    pid = await asyncio.wait_for(delete_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_snapshot.set()

    snapshot, _ = await asyncio.gather(snapshot_task, delete_task)
    provenance, job_id, app_run_id = snapshot

    async with db_container() as container:
        skill = await container.skill_repo().get(skill_id=resources.first_skill_id)
        composition = await container.skill_service().compose_for_execution_snapshot(
            tenant_id=resources.tenant_id,
            space_id=resources.space_id,
            provenance=provenance,
            base_instructions="App instructions",
        )

    assert skill is not None
    assert composition.provenance == provenance
    assert "First instructions" in composition.prompt

    async with db_container() as container:
        await container.session().execute(
            sa.update(Jobs)
            .where(Jobs.id == job_id)
            .values(status=terminal_status.value)
        )
        deleted = await container.skill_service().delete_skill(
            skill_id=resources.first_skill_id
        )

    assert deleted.id == resources.first_skill_id
    async with db_container() as container:
        repo = container.skill_repo()
        retained_app_run = await container.app_run_repo().get(app_run_id)
        persisted_app_run = await container.session().get(AppRuns, app_run_id)

        assert await repo.get(skill_id=resources.first_skill_id) is None
        assert (
            await repo.get_revision(
                skill_id=resources.first_skill_id,
                revision_id=resources.first_revision_id,
            )
            is None
        )
        assert retained_app_run is not None
        assert retained_app_run.skill_provenance == provenance
        assert persisted_app_run is not None
        assert persisted_app_run.skill_provenance is not None
        assert set(persisted_app_run.skill_provenance[0]) == {
            "skill_id",
            "skill_revision_id",
            "revision_number",
            "content_digest",
            "position",
        }


async def test_concurrent_same_content_revision_has_one_created_outcome(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    first_finished = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def revise(*, hold: bool):
        async with db_container() as container:
            if not hold:
                second_pid.set_result(await _backend_pid(container))
            change = await container.skill_service().create_revision(
                skill_id=resources.first_skill_id,
                display_name="Revised Skill",
                description="Concurrent revision",
                instructions="The same submitted instructions",
            )
            if hold:
                first_finished.set()
                await release_first.wait()
            return change

    first_task = asyncio.create_task(revise(hold=True))
    await _wait_for_held_write(first_finished, first_task)
    second_task = asyncio.create_task(revise(hold=False))
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    first_change, second_change = await asyncio.gather(first_task, second_task)

    assert first_change.created is True
    assert second_change.created is False
    assert first_change.revision.id == second_change.revision.id
    assert first_change.previous_revision_number == 1
    assert second_change.previous_revision_number == 2
    async with db_container() as container:
        repo = container.skill_repo()
        revisions = await repo.list_revision_summaries(
            skill_id=resources.first_skill_id,
            limit=3,
            before_revision_number=None,
        )
        revision_count = await repo.count_revisions(skill_id=resources.first_skill_id)
        exact_revision = await repo.get_revision(
            skill_id=resources.first_skill_id,
            revision_id=first_change.revision.id,
        )
        cross_skill_revision = await repo.get_revision(
            skill_id=resources.first_skill_id,
            revision_id=resources.second_revision_id,
        )
    assert [revision.revision_number for revision in revisions] == [2, 1]
    assert revision_count == 2
    assert exact_revision == first_change.revision
    assert cross_skill_revision is None


async def test_restore_appends_history_without_repointing_existing_bindings(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
):
    resources = skill_concurrency_resources

    async with db_container() as container:
        service = container.skill_service()
        second = await service.create_revision(
            skill_id=resources.first_skill_id,
            display_name="Second revision",
            description="Second revision description",
            instructions="Second revision instructions",
        )
        third = await service.create_revision(
            skill_id=resources.first_skill_id,
            display_name="Third revision",
            description="Third revision description",
            instructions="Third revision instructions",
        )
        await service.replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=[resources.first_reference],
        )

        restored = await service.restore_revision(
            space_id=resources.space_id,
            skill_id=resources.first_skill_id,
            source_revision_id=second.revision.id,
            reviewed_current_revision_id=third.revision.id,
        )
        first_page = await service.list_revision_summaries(
            space_id=resources.space_id,
            skill_id=resources.first_skill_id,
            limit=2,
            cursor=None,
        )
        second_page = await service.list_revision_summaries(
            space_id=resources.space_id,
            skill_id=resources.first_skill_id,
            limit=2,
            cursor=first_page.next_cursor,
        )
        bindings = await container.skill_repo().list_app_bindings(
            app_id=resources.app_id
        )

    assert restored.change.created is True
    assert restored.change.revision.revision_number == 4
    assert restored.change.revision.instructions == second.revision.instructions
    assert [revision.revision_number for revision in first_page.items] == [4, 3]
    assert first_page.next_cursor == 3
    assert [revision.revision_number for revision in second_page.items] == [2, 1]
    assert second_page.next_cursor is None
    assert [binding.skill_revision_id for binding in bindings] == [
        resources.first_revision_id
    ]


async def test_concurrent_identical_status_change_has_one_changed_outcome(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    first_finished = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def deactivate(*, hold: bool):
        async with db_container() as container:
            if not hold:
                second_pid.set_result(await _backend_pid(container))
            change = await container.skill_service().set_active(
                skill_id=resources.first_skill_id,
                is_active=False,
            )
            if hold:
                first_finished.set()
                await release_first.wait()
            return change

    first_task = asyncio.create_task(deactivate(hold=True))
    await _wait_for_held_write(first_finished, first_task)
    second_task = asyncio.create_task(deactivate(hold=False))
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    first_change, second_change = await asyncio.gather(first_task, second_task)

    assert first_change.changed is True
    assert first_change.previous_is_active is True
    assert second_change.changed is False
    assert second_change.previous_is_active is False


async def test_concurrent_delete_has_one_deleted_outcome(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    resources = skill_concurrency_resources
    first_finished = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def first_delete():
        async with db_container() as container:
            deleted = await container.skill_service().delete_skill(
                skill_id=resources.first_skill_id
            )
            first_finished.set()
            await release_first.wait()
            return deleted

    async def second_delete():
        async with db_container() as container:
            second_pid.set_result(await _backend_pid(container))
            with pytest.raises(NotFoundException):
                await container.skill_service().delete_skill(
                    skill_id=resources.first_skill_id
                )

    first_task = asyncio.create_task(first_delete())
    await _wait_for_held_write(first_finished, first_task)
    second_task = asyncio.create_task(second_delete())
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    deleted, _ = await asyncio.gather(first_task, second_task)

    assert deleted.id == resources.first_skill_id
    async with db_container() as container:
        assert (
            await container.skill_repo().get(skill_id=resources.first_skill_id) is None
        )


async def test_binding_write_waits_for_concurrent_policy_lowering(
    skill_concurrency_resources: SkillConcurrencyResources,
    db_container,
    db_session,
):
    """A binding save must validate against the limit an admin just applied,
    not the superseded one its snapshot could otherwise read."""
    resources = skill_concurrency_resources
    lowered = SkillRuntimePolicy(
        selective_activation_enabled=False,
        max_attached_skills=1,
        context_share_percent=10,
        max_activations_per_turn=10,
    )
    admin_locked = asyncio.Event()
    release_admin = asyncio.Event()
    writer_pid = asyncio.get_running_loop().create_future()

    async def holding_admin_lowerer():
        async with db_container() as container:
            change = await container.skill_repo().update_runtime_policy(
                tenant_id=resources.tenant_id,
                policy=lowered,
            )
            admin_locked.set()
            await release_admin.wait()
            return change

    async def blocked_binding_writer():
        async with db_container() as container:
            writer_pid.set_result(await _backend_pid(container))
            return await container.skill_service().replace_assistant_bindings(
                space_id=resources.space_id,
                assistant_id=resources.assistant_id,
                intents=[
                    SkillBindingIntent(reference=resources.first_reference),
                    SkillBindingIntent(reference=resources.second_reference),
                ],
            )

    admin_task = asyncio.create_task(holding_admin_lowerer())
    await _wait_for_held_write(admin_locked, admin_task)
    writer_task = asyncio.create_task(blocked_binding_writer())
    pid = await asyncio.wait_for(writer_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_admin.set()

    change = await admin_task
    assert change.new == lowered
    with pytest.raises(BadRequestException, match="more than 1 Skills"):
        await writer_task

    async with db_container() as container:
        assert (
            await container.skill_repo().list_assistant_bindings(
                assistant_id=resources.assistant_id
            )
            == []
        )

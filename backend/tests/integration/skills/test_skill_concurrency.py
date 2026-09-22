import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.apps.app_runs.app_run_repo import _serialize_skill_provenance
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.skill_table import Skills
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.jobs.job_models import Task
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
)
from eneo.main.models import Status
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    SkillBindingIntent,
    SkillBindingReference,
    SkillHasActiveAppRunsError,
    SkillHasBindingsError,
    SkillRemovalBusyError,
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
            with pytest.raises(SkillHasBindingsError):
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
                intents=[SkillBindingIntent(reference=existing_reference)],
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
                intents=[
                    SkillBindingIntent(reference=reference) for reference in references
                ],
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
            with pytest.raises(SkillHasActiveAppRunsError):
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


@pytest.fixture
async def organization_removal_skills(db_container, admin_user):
    async with db_container() as container:
        organization = await container.session().scalar(
            sa.select(Spaces).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization is not None
        skills = []
        for index in range(2):
            skill = await container.skill_repo().create(
                space_id=organization.id,
                slug=f"removal-{index}",
                display_name=f"Removal {index}",
                description="Concurrent removal",
                instructions="Retained instructions",
                content_digest=str(index) * 64,
                created_by_user_id=admin_user.id,
            )
            await container.skill_repo().publish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                expected_revision_id=skill.current_revision.id,
            )
            skills.append(skill)
    return skills


async def test_bulk_removal_refuses_a_concurrent_binding_save_without_partial_writes(
    db_container,
    skill_concurrency_resources,
    organization_removal_skills,
    admin_user,
):
    resources = skill_concurrency_resources
    skills = organization_removal_skills
    # Bind the later ID so removal has acquired another row lock before NOWAIT fails.
    ordered = sorted(skills, key=lambda skill: skill.id)
    bound = ordered[1]
    reference = SkillBindingReference(
        skill_id=bound.id, skill_revision_id=bound.current_revision.id
    )
    async with db_container() as writer:
        await writer.skill_service().replace_app_bindings(
            space_id=resources.space_id, app_id=resources.app_id, references=[reference]
        )
        with pytest.raises(SkillRemovalBusyError):
            async with db_container() as remover:
                await asyncio.wait_for(
                    remover.organization_skill_service().remove_many(
                        skill_ids=[skill.id for skill in skills]
                    ),
                    timeout=2,
                )
    async with db_container() as container:
        with pytest.raises(SkillHasBindingsError) as caught:
            await container.organization_skill_service().remove_many(
                skill_ids=[skill.id for skill in skills]
            )
        assert caught.value.details == {"skill_ids": [str(bound.id)]}
        for skill in skills:
            retained = await container.skill_repo().get_organization_for_tenant(
                tenant_id=admin_user.tenant_id, skill_id=skill.id
            )
            assert retained is not None and retained.removed_at is None


async def test_removal_winning_lock_rejects_a_waiting_binding_save(
    db_container,
    db_session,
    skill_concurrency_resources,
    organization_removal_skills,
    admin_user,
):
    resources = skill_concurrency_resources
    skill = organization_removal_skills[0]
    writer_pid = asyncio.get_running_loop().create_future()

    async def attach():
        async with db_container() as container:
            writer_pid.set_result(await _backend_pid(container))
            await container.skill_service().replace_app_bindings(
                space_id=resources.space_id,
                app_id=resources.app_id,
                references=[
                    SkillBindingReference(
                        skill_id=skill.id, skill_revision_id=skill.current_revision.id
                    )
                ],
            )

    async with db_container() as remover:
        await remover.organization_skill_service().delete(skill_id=skill.id)
        task = asyncio.create_task(attach())
        try:
            pid = await asyncio.wait_for(writer_pid, timeout=5)
            await _wait_until_database_lock(db_session, pid=pid)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    with pytest.raises(NotFoundException):
        await asyncio.wait_for(task, timeout=5)
    async with db_container() as container:
        assert (
            await container.skill_repo().list_app_bindings(app_id=resources.app_id)
            == []
        )


@pytest.mark.parametrize("status", [Status.QUEUED, Status.IN_PROGRESS])
async def test_bulk_removal_waits_for_active_app_runs_and_retains_finished_run_provenance(
    db_container,
    skill_concurrency_resources,
    organization_removal_skills,
    status,
):
    resources = skill_concurrency_resources
    skills = organization_removal_skills
    skill = skills[0]
    async with db_container() as container:
        service = container.skill_service()
        await service.replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id, skill_revision_id=skill.current_revision.id
                )
            ],
        )
        composition = await service.compose_for_app(
            app_id=resources.app_id, base_instructions="App instructions"
        )
        job_id, run_id = uuid4(), uuid4()
        container.session().add(
            Jobs(
                id=job_id,
                user_id=resources.user_id,
                task=Task.RUN_APP.value,
                status=status.value,
            )
        )
        container.session().add(
            AppRuns(
                id=run_id,
                tenant_id=resources.tenant_id,
                user_id=resources.user_id,
                app_id=resources.app_id,
                job_id=job_id,
                completion_model_id=resources.completion_model_id,
                skill_provenance=_serialize_skill_provenance(composition.provenance),
            )
        )
        await container.session().flush()
        await service.replace_app_bindings(
            space_id=resources.space_id, app_id=resources.app_id, references=[]
        )
        with pytest.raises(SkillHasActiveAppRunsError) as caught:
            await container.organization_skill_service().remove_many(
                skill_ids=[item.id for item in skills]
            )
        assert caught.value.details == {"skill_ids": [str(skill.id)]}
        for item in skills:
            retained = await container.skill_repo().get(skill_id=item.id)
            assert retained is not None and retained.removed_at is None
        await container.session().execute(
            sa.update(Jobs)
            .where(Jobs.id == job_id)
            .values(status=Status.COMPLETE.value)
        )
        await container.organization_skill_service().remove_many(
            skill_ids=[item.id for item in skills]
        )
        run = await container.session().get(AppRuns, run_id)
        assert run is not None and run.skill_provenance == _serialize_skill_provenance(
            composition.provenance
        )
        historical = await service.compose_for_execution_snapshot(
            tenant_id=resources.tenant_id,
            space_id=resources.space_id,
            provenance=composition.provenance,
            base_instructions="App instructions",
        )
        assert historical.provenance == composition.provenance


async def test_personal_chat_binding_blocks_the_whole_removal_batch(
    db_container,
    organization_removal_skills,
    admin_user,
):
    skills = organization_removal_skills
    async with db_container() as container:
        container.session().add(
            SpacesUsers(
                space_id=skills[0].space_id, user_id=admin_user.id, role="admin"
            )
        )
        policy = GovernancePolicies(
            tenant_id=admin_user.tenant_id,
            scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT.value,
        )
        container.session().add(policy)
        await container.session().flush()
        await container.skill_service().replace_governance_bindings(
            policy_id=policy.id,
            organization_space_id=skills[0].space_id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skills[0].id,
                        skill_revision_id=skills[0].current_revision.id,
                    )
                )
            ],
        )
        with pytest.raises(SkillHasBindingsError) as caught:
            await container.organization_skill_service().remove_many(
                skill_ids=[skill.id for skill in skills]
            )
        assert caught.value.details == {"skill_ids": [str(skills[0].id)]}
        counts = await container.skill_repo().get_usage_counts(
            tenant_id=admin_user.tenant_id, skill_ids=[skill.id for skill in skills]
        )
        assert counts[skills[0].id].personal_chat_pinned
        assert counts[skills[0].id].distinct_space_count == 0
        assert await container.skill_repo().get(skill_id=skills[1].id) is not None


async def _bind_everywhere(container, resources, skill, admin_user):
    """Bind one organisation Skill to the fixture Assistant, App and Personal Chat."""
    reference = SkillBindingReference(
        skill_id=skill.id, skill_revision_id=skill.current_revision.id
    )
    service = container.skill_service()
    await service.replace_assistant_bindings(
        space_id=resources.space_id,
        assistant_id=resources.assistant_id,
        intents=[SkillBindingIntent(reference=reference)],
    )
    await service.replace_app_bindings(
        space_id=resources.space_id, app_id=resources.app_id, references=[reference]
    )
    container.session().add(
        SpacesUsers(space_id=skill.space_id, user_id=admin_user.id, role="admin")
    )
    policy = GovernancePolicies(
        tenant_id=admin_user.tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT.value,
    )
    container.session().add(policy)
    await container.session().flush()
    await service.replace_governance_bindings(
        policy_id=policy.id,
        organization_space_id=skill.space_id,
        intents=[SkillBindingIntent(reference=reference)],
    )
    return policy.id


async def test_detaching_removal_deletes_every_binding_and_bumps_each_parent(
    db_container,
    skill_concurrency_resources,
    organization_removal_skills,
    admin_user,
):
    resources = skill_concurrency_resources
    skills = organization_removal_skills
    bound, free = skills

    async def row_version(container, table, row_id):
        # The pin-update guards compare xmin, so that is what must change.
        return await container.session().scalar(
            sa.select(
                sa.cast(sa.literal_column(f"{table.__tablename__}.xmin"), sa.Text)
            )
            .select_from(table)
            .where(table.id == row_id)
        )

    async with db_container() as container:
        policy_id = await _bind_everywhere(container, resources, bound, admin_user)
    parents = (
        (Assistants, resources.assistant_id),
        (Apps, resources.app_id),
        (GovernancePolicies, policy_id),
    )
    async with db_container() as container:
        before = {
            table: await row_version(container, table, row_id)
            for table, row_id in parents
        }
        outcomes = await container.organization_skill_service().remove_many(
            skill_ids=[bound.id, free.id], detach_bindings=True
        )

        by_id = {outcome.skill.id: outcome for outcome in outcomes}
        assert by_id[bound.id].detached.assistant_ids == (resources.assistant_id,)
        assert by_id[bound.id].detached.app_ids == (resources.app_id,)
        assert by_id[bound.id].detached.policy_ids == (policy_id,)
        assert by_id[free.id].detached.is_empty
        repo = container.skill_repo()
        assert (
            await repo.list_assistant_bindings(assistant_id=resources.assistant_id)
            == []
        )
        assert await repo.list_app_bindings(app_id=resources.app_id) == []
        assert await repo.list_policy_bindings(policy_id=policy_id) == []
        for skill in skills:
            retained = await repo.get_organization_for_tenant(
                tenant_id=admin_user.tenant_id, skill_id=skill.id
            )
            assert retained is not None and retained.removed_at is not None
    async with db_container() as container:
        # Parent rows were rewritten, so staged pin updates re-validate against them.
        for table, row_id in parents:
            assert await row_version(container, table, row_id) != before[table]
        # A second call is idempotent and reports nothing new detached.
        again = await container.organization_skill_service().remove_many(
            skill_ids=[bound.id], detach_bindings=True
        )
        assert again[0].detached.is_empty


async def test_detaching_removal_still_refuses_active_app_runs(
    db_container,
    skill_concurrency_resources,
    organization_removal_skills,
):
    resources = skill_concurrency_resources
    skill = organization_removal_skills[0]
    async with db_container() as container:
        service = container.skill_service()
        reference = SkillBindingReference(
            skill_id=skill.id, skill_revision_id=skill.current_revision.id
        )
        await service.replace_app_bindings(
            space_id=resources.space_id, app_id=resources.app_id, references=[reference]
        )
        composition = await service.compose_for_app(
            app_id=resources.app_id, base_instructions="App instructions"
        )
        job_id = uuid4()
        container.session().add(
            Jobs(
                id=job_id,
                user_id=resources.user_id,
                task=Task.RUN_APP.value,
                status=Status.IN_PROGRESS.value,
            )
        )
        container.session().add(
            AppRuns(
                id=uuid4(),
                tenant_id=resources.tenant_id,
                user_id=resources.user_id,
                app_id=resources.app_id,
                job_id=job_id,
                completion_model_id=resources.completion_model_id,
                skill_provenance=_serialize_skill_provenance(composition.provenance),
            )
        )
        await container.session().flush()

        with pytest.raises(SkillHasActiveAppRunsError):
            await container.organization_skill_service().remove_many(
                skill_ids=[skill.id], detach_bindings=True
            )
        # Nothing was detached before the refusal.
        assert (
            len(await container.skill_repo().list_app_bindings(app_id=resources.app_id))
            == 1
        )


async def test_detaching_removal_fails_fast_while_a_binding_save_holds_its_parent(
    db_container,
    skill_concurrency_resources,
    organization_removal_skills,
):
    resources = skill_concurrency_resources
    skill = organization_removal_skills[0]
    async with db_container() as container:
        await container.skill_service().replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id, skill_revision_id=skill.current_revision.id
                )
            ],
        )
    async with db_container() as writer:
        # A binding save locks its parent first; hold only that lock so the
        # removal gets past the Skill rows and meets the parent NOWAIT.
        assert await writer.skill_repo().lock_app_for_binding_update(
            app_id=resources.app_id
        )
        with pytest.raises(SkillRemovalBusyError):
            async with db_container() as remover:
                await asyncio.wait_for(
                    remover.organization_skill_service().remove_many(
                        skill_ids=[skill.id], detach_bindings=True
                    ),
                    timeout=2,
                )
    async with db_container() as container:
        assert (
            len(await container.skill_repo().list_app_bindings(app_id=resources.app_id))
            == 1
        )
        retained = await container.skill_repo().get(skill_id=skill.id)
        assert retained is not None and retained.removed_at is None


async def test_execution_plan_read_waiting_behind_detaching_removal_sees_no_binding(
    db_container,
    db_session,
    skill_concurrency_resources,
    organization_removal_skills,
):
    resources = skill_concurrency_resources
    skill = organization_removal_skills[0]
    reader_pid = asyncio.get_running_loop().create_future()

    async def prepare_run():
        async with db_container() as container:
            reader_pid.set_result(await _backend_pid(container))
            return await container.skill_repo().list_app_bindings_for_execution_plan(
                app_id=resources.app_id
            )

    async with db_container() as container:
        await container.skill_service().replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id, skill_revision_id=skill.current_revision.id
                )
            ],
        )
    async with db_container() as remover:
        await remover.organization_skill_service().remove_many(
            skill_ids=[skill.id], detach_bindings=True
        )
        # The run's share lock on the Skill row queues behind the removal's
        # exclusive lock; after commit it must re-evaluate against the
        # removed row, not compose the Skill from its pre-removal snapshot.
        task = asyncio.create_task(prepare_run())
        try:
            pid = await asyncio.wait_for(reader_pid, timeout=5)
            await _wait_until_database_lock(db_session, pid=pid)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    assert await asyncio.wait_for(task, timeout=5) == []


async def test_detaching_removal_rolls_back_entirely_when_the_audit_write_fails(
    db_container,
    skill_concurrency_resources,
    organization_removal_skills,
    admin_user,
    monkeypatch,
):
    resources = skill_concurrency_resources
    skill = organization_removal_skills[0]

    async def row_versions(container):
        versions = {}
        for table, row_id in parents:
            versions[table] = await container.session().scalar(
                sa.select(
                    sa.cast(sa.literal_column(f"{table.__tablename__}.xmin"), sa.Text)
                )
                .select_from(table)
                .where(table.id == row_id)
            )
        return versions

    async with db_container() as container:
        policy_id = await _bind_everywhere(container, resources, skill, admin_user)
    parents = (
        (Assistants, resources.assistant_id),
        (Apps, resources.app_id),
        (GovernancePolicies, policy_id),
    )
    async with db_container() as container:
        before = await row_versions(container)

    async def audit_down(**_kwargs):
        raise RuntimeError("audit store unavailable")

    with pytest.raises(RuntimeError, match="audit store unavailable"):
        async with db_container() as container:
            service = container.organization_skill_service()
            monkeypatch.setattr(service.audit_service, "log", audit_down)
            await service.remove_many(skill_ids=[skill.id], detach_bindings=True)

    async with db_container() as container:
        repo = container.skill_repo()
        # Deletes ran before the audit call; none of them may survive it.
        assert (
            len(await repo.list_assistant_bindings(assistant_id=resources.assistant_id))
            == 1
        )
        assert len(await repo.list_app_bindings(app_id=resources.app_id)) == 1
        assert len(await repo.list_policy_bindings(policy_id=policy_id)) == 1
        assert await row_versions(container) == before
        retained = await repo.get(skill_id=skill.id)
        assert retained is not None and retained.removed_at is None
        assert (
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == skill.id)
            )
            == 0
        )


async def test_execution_plan_never_composes_a_removed_skill(
    db_container,
    skill_concurrency_resources,
    organization_removal_skills,
):
    resources = skill_concurrency_resources
    skill = organization_removal_skills[0]
    async with db_container() as container:
        await container.skill_service().replace_app_bindings(
            space_id=resources.space_id,
            app_id=resources.app_id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id, skill_revision_id=skill.current_revision.id
                )
            ],
        )
        # Simulate the Read Committed race: the binding row still exists when
        # the run prepares, but the Skill row has been marked removed.
        await container.session().execute(
            sa.update(Skills)
            .where(Skills.id == skill.id)
            .values(
                removed_at=sa.func.now(),
                is_active=False,
                published_revision_number=None,
            )
        )
        repo = container.skill_repo()
        assert len(await repo.list_app_bindings(app_id=resources.app_id)) == 1
        assert (
            await repo.list_app_bindings_for_execution_plan(app_id=resources.app_id)
            == []
        )

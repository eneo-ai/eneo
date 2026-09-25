import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from eneo.skills.domain.skill import (
    SKILL_RUNTIME_POLICY_DEFAULTS,
    SkillRuntimePolicy,
)
from tests.integration.skills.test_skill_concurrency import (
    _backend_pid,
    _wait_for_held_write,
    _wait_until_database_lock,
)

pytestmark = pytest.mark.integration


async def test_runtime_policy_seeds_once_and_round_trips_per_tenant(
    db_container,
    admin_user,
    tenant_factory,
):
    async with db_container() as container:
        session = container.session()
        repo = container.skill_repo()

        first = await repo.get_or_seed_runtime_policy(tenant_id=admin_user.tenant_id)
        assert first == SKILL_RUNTIME_POLICY_DEFAULTS
        assert first.selective_activation_enabled is True

        updated = SkillRuntimePolicy(
            selective_activation_enabled=True,
            max_attached_skills=25,
            context_share_percent=5,
            max_activations_per_turn=3,
        )
        change = await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=updated,
        )
        assert change.old == first
        assert change.new == updated
        assert change.changed is True

        # A repeated read is idempotent and returns the stored values, not the
        # seed.
        assert (
            await repo.get_or_seed_runtime_policy(tenant_id=admin_user.tenant_id)
            == updated
        )

        other_tenant = await tenant_factory(
            session,
            name=f"Runtime policy tenant {uuid4()}",
        )
        foreign = await repo.get_or_seed_runtime_policy(tenant_id=other_tenant.id)
        assert foreign == SKILL_RUNTIME_POLICY_DEFAULTS

        unchanged = await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=updated,
        )
        assert unchanged.changed is False

        lowered = await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=replace(updated, max_activations_per_turn=1),
        )
        assert lowered.old == updated
        assert lowered.new.max_activations_per_turn == 1


async def test_established_policy_read_issues_no_write_statement(
    db_container,
    admin_user,
):
    async with db_container() as container:
        repo = container.skill_repo()
        await repo.get_or_seed_runtime_policy(tenant_id=admin_user.tenant_id)

        session = container.session()
        bind = session.get_bind()
        engine = getattr(bind, "engine", bind)
        statements: list[str] = []

        def record(
            conn: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            repeated = await repo.get_or_seed_runtime_policy(
                tenant_id=admin_user.tenant_id
            )
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert repeated == SKILL_RUNTIME_POLICY_DEFAULTS
        policy_statements = [
            statement
            for statement in statements
            if "skill_runtime_policies" in statement
        ]
        assert policy_statements, "expected the read to touch the policy table"
        assert all(
            statement.lstrip().upper().startswith("SELECT")
            for statement in policy_statements
        )


async def test_concurrent_first_reads_seed_exactly_one_policy_row(
    db_container,
    db_session,
    tenant_factory,
):
    async with db_container() as container:
        tenant = await tenant_factory(
            container.session(),
            name=f"Concurrent policy seed {uuid4()}",
        )
        tenant_id = tenant.id

    first_read = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def holding_first_reader():
        async with db_container() as container:
            policy = await container.skill_repo().get_or_seed_runtime_policy(
                tenant_id=tenant_id
            )
            first_read.set()
            await release_first.wait()
            return policy

    async def blocked_second_reader():
        async with db_container() as container:
            second_pid.set_result(await _backend_pid(container))
            return await container.skill_repo().get_or_seed_runtime_policy(
                tenant_id=tenant_id
            )

    first_task = asyncio.create_task(holding_first_reader())
    await _wait_for_held_write(first_read, first_task)
    second_task = asyncio.create_task(blocked_second_reader())
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    first_policy, second_policy = await asyncio.gather(first_task, second_task)

    assert first_policy == SKILL_RUNTIME_POLICY_DEFAULTS
    assert second_policy == SKILL_RUNTIME_POLICY_DEFAULTS
    async with db_session() as session:
        row_count = await session.scalar(
            sa.text(
                "SELECT count(*) FROM skill_runtime_policies "
                "WHERE tenant_id = :tenant_id"
            ).bindparams(tenant_id=tenant_id)
        )
    assert row_count == 1


async def test_serialized_updates_report_truthful_old_values(
    db_container,
    db_session,
    tenant_factory,
):
    async with db_container() as container:
        tenant = await tenant_factory(
            container.session(),
            name=f"Serialized policy update {uuid4()}",
        )
        tenant_id = tenant.id
        await container.skill_repo().get_or_seed_runtime_policy(tenant_id=tenant_id)

    first_policy = SkillRuntimePolicy(
        selective_activation_enabled=False,
        max_attached_skills=30,
        context_share_percent=10,
        max_activations_per_turn=10,
    )
    second_policy = SkillRuntimePolicy(
        selective_activation_enabled=True,
        max_attached_skills=60,
        context_share_percent=20,
        max_activations_per_turn=5,
    )
    first_updated = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def holding_first_updater():
        async with db_container() as container:
            change = await container.skill_repo().update_runtime_policy(
                tenant_id=tenant_id,
                policy=first_policy,
            )
            first_updated.set()
            await release_first.wait()
            return change

    async def blocked_second_updater():
        async with db_container() as container:
            second_pid.set_result(await _backend_pid(container))
            return await container.skill_repo().update_runtime_policy(
                tenant_id=tenant_id,
                policy=second_policy,
            )

    first_task = asyncio.create_task(holding_first_updater())
    await _wait_for_held_write(first_updated, first_task)
    second_task = asyncio.create_task(blocked_second_updater())
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    first_change, second_change = await asyncio.gather(first_task, second_task)

    assert first_change.old == SKILL_RUNTIME_POLICY_DEFAULTS
    assert first_change.new == first_policy
    # The blocked update re-reads the row after the first commit, so its audit
    # old value is the first writer's committed policy, not the seed.
    assert second_change.old == first_policy
    assert second_change.new == second_policy

    async with db_container() as container:
        assert (
            await container.skill_repo().get_or_seed_runtime_policy(tenant_id=tenant_id)
            == second_policy
        )

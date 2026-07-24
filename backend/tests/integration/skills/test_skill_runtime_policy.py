from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import event

from eneo.skills.domain.skill import (
    SKILL_RUNTIME_POLICY_DEFAULTS,
    SkillRuntimePolicy,
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

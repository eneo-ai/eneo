"""Integration tests for ``SkillRepo.advance_personal_chat_skill_pin``.

The tenant's Personal Chat policy pins each bound Skill to an exact revision.
Advancing that pin to the published revision is an admin operation that may
change ``skill_revision_id`` and nothing else: order, activation mode, other
bindings and every policy field stay untouched. The write is guarded by the
revision the administrator reviewed, so a concurrent change loses cleanly
instead of being overwritten, and a blocked or unpublished Skill stops the
operation.

Real Postgres via testcontainers; seeds follow
``test_skill_adoption_projection.py``.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.skill_table import GovernancePolicySkillBindings
from eneo.database.tables.spaces_table import Spaces
from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.skills.domain.skill import (
    PersonalChatPinAdvanceOutcome,
    SkillBindingReference,
    SkillRevisionConflictError,
)


async def _org_space_id(session, *, tenant_id: UUID) -> UUID:
    row = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert row is not None
    return row


async def _published_skill(repo, *, space_id: UUID, tenant_id: UUID, user_id: UUID):
    skill = await repo.create(
        space_id=space_id,
        slug=f"pin-advance-{uuid4().hex[:8]}",
        display_name="Pin advance",
        description="Approved guidance.",
        instructions="Follow the approved instructions.",
        content_digest="1" * 64,
        created_by_user_id=user_id,
    )
    await repo.publish_organization(
        tenant_id=tenant_id,
        skill_id=skill.id,
        expected_revision_id=skill.current_revision.id,
    )
    return skill


async def _bind_to_personal_chat(
    repo, session, *, tenant_id: UUID, org_space_id: UUID, references
) -> UUID:
    policy = GovernancePolicies(
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT.value,
    )
    session.add(policy)
    await session.flush()
    resolved = await repo.resolve_published_references_for_binding_update(
        tenant_id=tenant_id,
        references=references,
    )
    await repo.replace_policy_bindings(
        policy_id=policy.id,
        tenant_id=tenant_id,
        skill_space_id=org_space_id,
        bindings=resolved,
    )
    return policy.id


async def _publish_second_revision(
    repo, *, tenant_id: UUID, skill_id: UUID, user_id: UUID
):
    change = await repo.create_revision(
        skill_id=skill_id,
        display_name="Pin advance",
        description="Approved guidance, revised.",
        instructions="Follow the second approved revision.",
        content_digest="2" * 64,
        created_by_user_id=user_id,
    )
    assert change is not None
    await repo.publish_organization(
        tenant_id=tenant_id,
        skill_id=skill_id,
        expected_revision_id=change.revision.id,
    )
    return change.revision


async def _binding_row(session, *, policy_id: UUID, skill_id: UUID):
    return (
        await session.execute(
            sa.select(
                GovernancePolicySkillBindings.skill_revision_id,
                GovernancePolicySkillBindings.position,
                GovernancePolicySkillBindings.activation_mode,
            ).where(
                GovernancePolicySkillBindings.policy_id == policy_id,
                GovernancePolicySkillBindings.skill_id == skill_id,
            )
        )
    ).one()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_advances_only_the_reviewed_pin_and_preserves_everything_else(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.skill_repo()
        org = await _org_space_id(session, tenant_id=admin_user.tenant_id)

        skill = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        other = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        old_revision = skill.current_revision
        policy_id = await _bind_to_personal_chat(
            repo,
            session,
            tenant_id=admin_user.tenant_id,
            org_space_id=org,
            references=[
                SkillBindingReference(
                    skill_id=skill.id, skill_revision_id=old_revision.id
                ),
                SkillBindingReference(
                    skill_id=other.id,
                    skill_revision_id=other.current_revision.id,
                ),
            ],
        )
        # The mode is part of what the administrator configured; it must ride
        # through the pin change untouched.
        await session.execute(
            sa.update(GovernancePolicySkillBindings)
            .where(
                GovernancePolicySkillBindings.policy_id == policy_id,
                GovernancePolicySkillBindings.skill_id == skill.id,
            )
            .values(activation_mode="on_demand")
        )
        published = await _publish_second_revision(
            repo,
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            user_id=admin_user.id,
        )

        advance = await repo.advance_personal_chat_skill_pin(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_pinned_revision_id=old_revision.id,
            expected_published_revision_id=published.id,
        )

        assert advance is not None
        assert advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED
        assert advance.from_revision_number == 1
        assert advance.to_revision_number == 2

        moved = await _binding_row(session, policy_id=policy_id, skill_id=skill.id)
        assert moved.skill_revision_id == published.id
        assert moved.position == 0
        assert moved.activation_mode == "on_demand"

        untouched = await _binding_row(session, policy_id=policy_id, skill_id=other.id)
        assert untouched.skill_revision_id == other.current_revision.id
        assert untouched.position == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_repeating_the_advance_is_a_typed_no_op(db_container, admin_user):
    async with db_container() as container:
        session = container.session()
        repo = container.skill_repo()
        org = await _org_space_id(session, tenant_id=admin_user.tenant_id)

        skill = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        old_revision = skill.current_revision
        await _bind_to_personal_chat(
            repo,
            session,
            tenant_id=admin_user.tenant_id,
            org_space_id=org,
            references=[
                SkillBindingReference(
                    skill_id=skill.id, skill_revision_id=old_revision.id
                )
            ],
        )
        published = await _publish_second_revision(
            repo,
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            user_id=admin_user.id,
        )

        first = await repo.advance_personal_chat_skill_pin(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_pinned_revision_id=old_revision.id,
            expected_published_revision_id=published.id,
        )
        assert first is not None
        assert first.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

        # A retry with the now-current pin as the reviewed revision reports
        # already-current instead of failing or writing again.
        second = await repo.advance_personal_chat_skill_pin(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_pinned_revision_id=published.id,
            expected_published_revision_id=published.id,
        )
        assert second is not None
        assert second.outcome is PersonalChatPinAdvanceOutcome.ALREADY_CURRENT
        assert second.to_revision_number == 2

        # Once the pin is current there is no write left to guard, so even a
        # stale reviewed revision is a clean no-op instead of a conflict.
        # This is what makes re-running an interrupted rollout safe.
        retried = await repo.advance_personal_chat_skill_pin(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_pinned_revision_id=uuid4(),
            expected_published_revision_id=published.id,
        )
        assert retried is not None
        assert retried.outcome is PersonalChatPinAdvanceOutcome.ALREADY_CURRENT


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_reviewed_revision_loses_instead_of_overwriting(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.skill_repo()
        org = await _org_space_id(session, tenant_id=admin_user.tenant_id)

        skill = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        old_revision = skill.current_revision
        policy_id = await _bind_to_personal_chat(
            repo,
            session,
            tenant_id=admin_user.tenant_id,
            org_space_id=org,
            references=[
                SkillBindingReference(
                    skill_id=skill.id, skill_revision_id=old_revision.id
                )
            ],
        )
        published = await _publish_second_revision(
            repo,
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            user_id=admin_user.id,
        )

        with pytest.raises(SkillRevisionConflictError):
            await repo.advance_personal_chat_skill_pin(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                expected_pinned_revision_id=uuid4(),  # reviewed some other state
                expected_published_revision_id=published.id,
            )

        # The reviewed target must also be the live published revision: a
        # publish that lands after the review may not be applied silently.
        with pytest.raises(SkillRevisionConflictError):
            await repo.advance_personal_chat_skill_pin(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                expected_pinned_revision_id=old_revision.id,
                expected_published_revision_id=old_revision.id,  # stale target
            )

        row = await _binding_row(session, policy_id=policy_id, skill_id=skill.id)
        assert row.skill_revision_id == old_revision.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unbound_unpublished_blocked_and_foreign_skills_stop_cleanly(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = container.skill_repo()
        org = await _org_space_id(session, tenant_id=admin_user.tenant_id)

        unbound = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        not_bound = await repo.advance_personal_chat_skill_pin(
            tenant_id=admin_user.tenant_id,
            skill_id=unbound.id,
            expected_pinned_revision_id=unbound.current_revision.id,
            expected_published_revision_id=unbound.current_revision.id,
        )
        assert not_bound is not None
        assert not_bound.outcome is PersonalChatPinAdvanceOutcome.NOT_BOUND

        bound = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        old_revision = bound.current_revision
        policy_id = await _bind_to_personal_chat(
            repo,
            session,
            tenant_id=admin_user.tenant_id,
            org_space_id=org,
            references=[
                SkillBindingReference(
                    skill_id=bound.id, skill_revision_id=old_revision.id
                )
            ],
        )
        await _publish_second_revision(
            repo,
            tenant_id=admin_user.tenant_id,
            skill_id=bound.id,
            user_id=admin_user.id,
        )

        await repo.unpublish_organization(
            tenant_id=admin_user.tenant_id, skill_id=bound.id
        )
        unpublished = await repo.advance_personal_chat_skill_pin(
            tenant_id=admin_user.tenant_id,
            skill_id=bound.id,
            expected_pinned_revision_id=old_revision.id,
            expected_published_revision_id=old_revision.id,
        )
        assert unpublished is not None
        assert unpublished.outcome is PersonalChatPinAdvanceOutcome.NOT_PUBLISHED

        republished = await repo.get_organization_for_tenant(
            tenant_id=admin_user.tenant_id, skill_id=bound.id
        )
        assert republished is not None
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=bound.id,
            expected_revision_id=republished.current_revision.id,
        )
        blocked = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=bound.id,
            blocked_by_user_id=admin_user.id,
            reason="Confirmed unsafe instructions",
        )
        assert blocked is not None
        stopped = await repo.advance_personal_chat_skill_pin(
            tenant_id=admin_user.tenant_id,
            skill_id=bound.id,
            expected_pinned_revision_id=old_revision.id,
            expected_published_revision_id=old_revision.id,
        )
        assert stopped is not None
        assert stopped.outcome is PersonalChatPinAdvanceOutcome.BLOCKED
        row = await _binding_row(session, policy_id=policy_id, skill_id=bound.id)
        assert row.skill_revision_id == old_revision.id

        assert (
            await repo.advance_personal_chat_skill_pin(
                tenant_id=uuid4(),  # no such tenant
                skill_id=bound.id,
                expected_pinned_revision_id=old_revision.id,
                expected_published_revision_id=old_revision.id,
            )
            is None
        )


# Lock-wait helpers mirroring test_skill_concurrency.py.


async def _backend_pid(container) -> int:
    pid = await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
    assert isinstance(pid, int)
    return pid


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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_advances_to_different_skills_serialize_on_the_policy_row(
    db_container, db_session, admin_user
):
    """Two concurrent advances must not both validate a partial baseline.

    The fit validation that follows an advance judges the whole Personal Chat
    policy, so the advance takes the policy-row lock — the same lock every
    policy save takes. Without it, two advances to different Skills could each
    pass validation against the other's uncommitted state and jointly commit
    an over-budget configuration (write skew). This pins the serialization:
    the second advance waits on the policy lock until the first commits.
    """
    async with db_container() as container:
        session = container.session()
        repo = container.skill_repo()
        org = await _org_space_id(session, tenant_id=admin_user.tenant_id)
        first = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        second = await _published_skill(
            repo, space_id=org, tenant_id=admin_user.tenant_id, user_id=admin_user.id
        )
        first_old = first.current_revision
        second_old = second.current_revision
        await _bind_to_personal_chat(
            repo,
            session,
            tenant_id=admin_user.tenant_id,
            org_space_id=org,
            references=[
                SkillBindingReference(
                    skill_id=first.id, skill_revision_id=first_old.id
                ),
                SkillBindingReference(
                    skill_id=second.id, skill_revision_id=second_old.id
                ),
            ],
        )
        published_by_skill = {}
        for skill in (first, second):
            published_by_skill[skill.id] = await _publish_second_revision(
                repo,
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                user_id=admin_user.id,
            )

    first_finished = asyncio.Event()
    release_first = asyncio.Event()
    second_pid = asyncio.get_running_loop().create_future()

    async def first_writer():
        async with db_container() as container:
            advance = await container.skill_repo().advance_personal_chat_skill_pin(
                tenant_id=admin_user.tenant_id,
                skill_id=first.id,
                expected_pinned_revision_id=first_old.id,
                expected_published_revision_id=published_by_skill[first.id].id,
            )
            first_finished.set()
            await release_first.wait()
            return advance

    async def second_writer():
        async with db_container() as container:
            second_pid.set_result(await _backend_pid(container))
            return await container.skill_repo().advance_personal_chat_skill_pin(
                tenant_id=admin_user.tenant_id,
                skill_id=second.id,
                expected_pinned_revision_id=second_old.id,
                expected_published_revision_id=published_by_skill[second.id].id,
            )

    first_task = asyncio.create_task(first_writer())
    await _wait_for_held_write(first_finished, first_task)
    second_task = asyncio.create_task(second_writer())
    pid = await asyncio.wait_for(second_pid, timeout=5)
    try:
        await _wait_until_database_lock(db_session, pid=pid)
    finally:
        release_first.set()
    first_advance, second_advance = await asyncio.gather(first_task, second_task)

    assert first_advance is not None
    assert first_advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED
    assert second_advance is not None
    assert second_advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

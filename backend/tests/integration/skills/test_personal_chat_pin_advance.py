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

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.governance_policy_table import GovernancePolicies
from eneo.database.tables.skill_table import GovernancePolicySkillBindings
from eneo.database.tables.spaces_table import Spaces
from eneo.governance_policy.domain.governance_policy import PolicyScope
from eneo.skills.domain.skill import (
    PersonalChatPinAdvanceOutcome,
    PersonalChatPinConfirmOutcome,
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


async def _advance(
    repo,
    *,
    tenant_id: UUID,
    skill_id: UUID,
    expected_pinned_revision_id: UUID,
    expected_published_revision_id: UUID,
):
    """Stage + confirm, the way the service drives the repo (fit scan aside)."""
    stage = await repo.stage_personal_chat_skill_pin_advance(
        tenant_id=tenant_id,
        skill_id=skill_id,
        expected_pinned_revision_id=expected_pinned_revision_id,
        expected_published_revision_id=expected_published_revision_id,
    )
    if stage is None:
        return None
    if stage.advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED:
        confirm = await repo.confirm_personal_chat_skill_pin_advance(
            tenant_id=tenant_id,
            skill_id=skill_id,
            policy_id=stage.policy_id,
            policy_version=stage.policy_version,
            expected_published_revision_id=expected_published_revision_id,
        )
        assert confirm is PersonalChatPinConfirmOutcome.CONFIRMED
    return stage.advance


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

        advance = await _advance(
            repo,
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

        first = await _advance(
            repo,
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_pinned_revision_id=old_revision.id,
            expected_published_revision_id=published.id,
        )
        assert first is not None
        assert first.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

        # A retry with the now-current pin as the reviewed revision reports
        # already-current instead of failing or writing again.
        second = await _advance(
            repo,
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
        retried = await _advance(
            repo,
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
            await _advance(
                repo,
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                expected_pinned_revision_id=uuid4(),  # reviewed some other state
                expected_published_revision_id=published.id,
            )

        # The reviewed target must also be the live published revision: a
        # publish that lands after the review may not be applied silently.
        with pytest.raises(SkillRevisionConflictError):
            await _advance(
                repo,
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
        not_bound = await _advance(
            repo,
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
        unpublished = await _advance(
            repo,
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
        stopped = await _advance(
            repo,
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
            await _advance(
                repo,
                tenant_id=uuid4(),  # no such tenant
                skill_id=bound.id,
                expected_pinned_revision_id=old_revision.id,
                expected_published_revision_id=old_revision.id,
            )
            is None
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_validation_runs_without_policy_or_skill_write_locks(
    db_container, admin_user
):
    """Between stage and confirm — where the fleet fit scan runs — neither
    the policy row nor the Skill row may be write-locked, so governance
    saves, publication changes, and emergency blocks stay unblocked."""
    import sqlalchemy as sa2

    from eneo.database.tables.skill_table import Skills

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

    async with db_container() as staging:
        stage = await staging.skill_repo().stage_personal_chat_skill_pin_advance(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_pinned_revision_id=old_revision.id,
            expected_published_revision_id=published.id,
        )
        assert stage is not None
        assert stage.advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

        # While the staging transaction is open (the fit scan would run
        # here), another session must be able to write-lock both rows.
        async with db_container() as prober:
            probe = prober.session()
            locked_policy = await probe.scalar(
                sa2.select(GovernancePolicies.id)
                .where(GovernancePolicies.id == stage.policy_id)
                .with_for_update(nowait=True)
            )
            assert locked_policy == stage.policy_id
            locked_skill = await probe.scalar(
                sa2.select(Skills.id)
                .where(Skills.id == skill.id)
                .with_for_update(nowait=True)
            )
            assert locked_skill == skill.id
            await probe.rollback()

        confirm = await staging.skill_repo().confirm_personal_chat_skill_pin_advance(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            policy_id=stage.policy_id,
            policy_version=stage.policy_version,
            expected_published_revision_id=published.id,
        )
        assert confirm is PersonalChatPinConfirmOutcome.CONFIRMED


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_policy_change_during_validation_refuses_the_apply(
    db_container, admin_user
):
    """A policy save that commits while the fit scan runs must refuse the
    staged apply: the validation no longer describes the state it guards."""
    import sqlalchemy as sa2

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

    async with db_container() as staging:
        stage = await staging.skill_repo().stage_personal_chat_skill_pin_advance(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_pinned_revision_id=old_revision.id,
            expected_published_revision_id=published.id,
        )
        assert stage is not None
        assert stage.advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

        # A concurrent policy save commits mid-scan. Every save rewrites the
        # policy row, which is exactly what the version marker watches.
        async with db_container() as editor:
            await editor.session().execute(
                sa2.update(GovernancePolicies)
                .where(GovernancePolicies.id == stage.policy_id)
                .values(updated_at=sa2.func.now())
            )

        confirm = await staging.skill_repo().confirm_personal_chat_skill_pin_advance(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            policy_id=stage.policy_id,
            policy_version=stage.policy_version,
            expected_published_revision_id=published.id,
        )
        assert confirm is PersonalChatPinConfirmOutcome.POLICY_CHANGED
        await staging.session().rollback()

    async with db_container() as verifier:
        # This is what the service's raise produces: the staged pin is gone.
        binding = await verifier.session().execute(
            sa.select(GovernancePolicySkillBindings.skill_revision_id).where(
                GovernancePolicySkillBindings.policy_id == stage.policy_id,
                GovernancePolicySkillBindings.skill_id == skill.id,
            )
        )
        assert binding.scalar_one() == old_revision.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_advances_cannot_jointly_commit_unvalidated_state(
    db_container, admin_user
):
    """The write-skew regression: two advances to different Skills validate
    concurrently, but the first confirmed apply bumps the policy row, so the
    second must refuse and revalidate instead of committing blind."""
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
        published = {}
        for skill in (first, second):
            published[skill.id] = await _publish_second_revision(
                repo,
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                user_id=admin_user.id,
            )

    async with db_container() as session_a:
        stage_a = await session_a.skill_repo().stage_personal_chat_skill_pin_advance(
            tenant_id=admin_user.tenant_id,
            skill_id=first.id,
            expected_pinned_revision_id=first_old.id,
            expected_published_revision_id=published[first.id].id,
        )
        assert stage_a is not None
        assert stage_a.advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

        async with db_container() as session_b:
            # B stages and validates while A's transaction is still open —
            # neither sees the other's uncommitted pin.
            stage_b = (
                await session_b.skill_repo().stage_personal_chat_skill_pin_advance(
                    tenant_id=admin_user.tenant_id,
                    skill_id=second.id,
                    expected_pinned_revision_id=second_old.id,
                    expected_published_revision_id=published[second.id].id,
                )
            )
            assert stage_b is not None
            assert stage_b.advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

            # A confirms and commits first (context exit commits).
            confirm_a = (
                await session_a.skill_repo().confirm_personal_chat_skill_pin_advance(
                    tenant_id=admin_user.tenant_id,
                    skill_id=first.id,
                    policy_id=stage_a.policy_id,
                    policy_version=stage_a.policy_version,
                    expected_published_revision_id=published[first.id].id,
                )
            )
            assert confirm_a is PersonalChatPinConfirmOutcome.CONFIRMED
            await session_a.session().commit()

            confirm_b = (
                await session_b.skill_repo().confirm_personal_chat_skill_pin_advance(
                    tenant_id=admin_user.tenant_id,
                    skill_id=second.id,
                    policy_id=stage_b.policy_id,
                    policy_version=stage_b.policy_version,
                    expected_published_revision_id=published[second.id].id,
                )
            )
            assert confirm_b is PersonalChatPinConfirmOutcome.POLICY_CHANGED
            await session_b.session().rollback()

    # A fresh retry revalidates against the committed state and succeeds.
    async with db_container() as retry:
        advance = await _advance(
            retry.skill_repo(),
            tenant_id=admin_user.tenant_id,
            skill_id=second.id,
            expected_pinned_revision_id=second_old.id,
            expected_published_revision_id=published[second.id].id,
        )
        assert advance is not None
        assert advance.outcome is PersonalChatPinAdvanceOutcome.ADVANCED

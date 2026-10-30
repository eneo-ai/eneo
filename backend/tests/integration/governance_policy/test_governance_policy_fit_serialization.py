"""A personal chat policy save and a personal chat save cannot jointly commit
a baseline that the personal chat cannot run.

Each save validates against the state it can see. Without serialization, an
administrator could add a Skill that only fits the current model while a person
switches to a smaller one, and both would commit. The policy save validates
without the fit token first, then takes it exclusively and validates again when
any personal chat changed meanwhile (docs/adr/personal-chat-skill-layers.md,
section 6).
"""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_service import AssistantService
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.skill_table import SkillRuntimePolicies
from eneo.main.exceptions import BadRequestException
from eneo.skills.domain.skill import SkillBindingIntent, SkillBindingReference


async def _wait_until_lock_wait(db_container, *, pid: int, task) -> None:
    """Observe a real PostgreSQL lock wait instead of relying on scheduling."""
    async with asyncio.timeout(10):
        while True:
            async with db_container() as observer:
                waiting = await observer.session().scalar(
                    sa.text(
                        "SELECT wait_event_type = 'Lock' "
                        "FROM pg_stat_activity WHERE pid = :pid"
                    ),
                    {"pid": pid},
                )
            if waiting:
                return
            if task.done():
                await task
                pytest.fail("The second save did not wait for the first")
            await asyncio.sleep(0.01)


async def _personal_chat_with_two_models(db_container, test_settings, factory):
    """A personal chat on a large model, a small model it can switch to, and a
    published organisation Skill that only fits the large one."""
    reserve = test_settings.attachment_context_reserve_tokens
    async with db_container() as container:
        session = container.session()
        space = await container.space_init_service().get_personal_space()
        assert space.default_assistant is not None
        default = space.get_assistant(space.default_assistant.id)
        assert default.completion_model is not None
        large_id = default.completion_model.id
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == large_id)
            .values(max_input_tokens=reserve + 8000, vision=False)
        )
        small = await factory(
            session, "small-personal-chat-model", max_input_tokens=reserve + 1000
        )
        small_id = small.id
        # Seed the tenant's runtime policy row up front, as an established tenant
        # has it. Otherwise both saves race to insert it on first access, and
        # that insert conflict, not the fit protocol, makes one wait.
        await container.skill_repo().get_runtime_policy_snapshot(
            tenant_id=container.user().tenant_id
        )
        skills = container.organization_skill_service()
        skill = await skills.create_organization_skill(
            slug=f"fits-large-only-{uuid4().hex[:8]}",
            display_name="Fits the large model only",
            description="Serialization fixture",
            instructions="guidance " * 3000,
        )
        skill = (
            await skills.publish(
                skill_id=skill.id, expected_revision_id=skill.current_revision.id
            )
        ).skill
    return default.id, large_id, small_id, skill


async def _save_policy_with(container, skill) -> None:
    """The personal chat policy save, as the admin route drives it."""
    service = container.governance_policy_service()
    await service.get_policy_for_update()
    await service.update_policy(
        skill_intents=[
            SkillBindingIntent(
                reference=SkillBindingReference(
                    skill_id=skill.id,
                    skill_revision_id=skill.current_revision.id,
                )
            )
        ]
    )
    await container.assistant_service().confirm_personal_default_governance_fit()


async def _switch_model(container, assistant_id, model_id) -> None:
    await container.assistant_service().update_assistant(
        assistant_id=assistant_id,
        update=AssistantUpdateCommand(completion_model_id=model_id),
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy_first", [False, True], ids=["model-first", "policy-first"]
)
async def test_policy_save_and_model_switch_cannot_commit_an_unusable_baseline(
    db_container, test_settings, completion_model_factory, policy_first
):
    default_id, large_id, small_id, skill = await _personal_chat_with_two_models(
        db_container, test_settings, completion_model_factory
    )

    async def first_save(container):
        if policy_first:
            await _save_policy_with(container, skill)
        else:
            await _switch_model(container, default_id, small_id)

    async def second_save(container):
        if policy_first:
            await _switch_model(container, default_id, small_id)
        else:
            await _save_policy_with(container, skill)

    async with db_container() as first:
        with pytest.raises(BadRequestException, match="context window"):
            async with db_container() as second:
                pid = await second.session().scalar(sa.text("SELECT pg_backend_pid()"))
                await first_save(first)
                pending = asyncio.create_task(second_save(second))
                try:
                    await _wait_until_lock_wait(db_container, pid=pid, task=pending)
                    await first.session().commit()
                    await asyncio.wait_for(pending, timeout=10)
                finally:
                    if not pending.done():
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)

    async with db_container() as verifier:
        space = await verifier.space_repo().get_space_by_assistant(default_id)
        saved = space.get_assistant(default_id)
        assert saved.completion_model is not None
        policy = await verifier.governance_policy_service().get_policy()
        bindings = await verifier.governance_policy_service().get_skill_bindings(policy)
        if policy_first:
            assert saved.completion_model.id == large_id
            assert [binding.skill_id for binding in bindings] == [skill.id]
        else:
            assert saved.completion_model.id == small_id
            assert bindings == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_policy_save_without_concurrent_changes_validates_once(
    db_container, test_settings, completion_model_factory, monkeypatch
):
    _, _, _, skill = await _personal_chat_with_two_models(
        db_container, test_settings, completion_model_factory
    )
    calls = 0
    validate = AssistantService.assert_personal_default_governance_context_fit

    async def counting_validate(self, **kwargs):
        nonlocal calls
        calls += 1
        await validate(self, **kwargs)

    monkeypatch.setattr(
        AssistantService,
        "assert_personal_default_governance_context_fit",
        counting_validate,
    )
    async with db_container() as container:
        await _save_policy_with(container, skill)

    assert calls == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_fit_protocol_runs_under_read_committed(db_container):
    """The recheck under the fit token must see saves committed after the
    transaction began. A stricter isolation level would read a stale snapshot
    and let the policy save skip its second validation."""
    async with db_container() as container:
        level = await container.session().scalar(sa.text("SHOW transaction_isolation"))
    assert level == "read committed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_tenant_without_a_runtime_policy_row_serializes_without_deadlock(
    db_container, test_settings, completion_model_factory
):
    """The runtime-policy row is created on first read. A policy save creates it
    during its lock-free validation; a personal chat save that then starts must
    wait for that row before it takes the fit token, or the two deadlock."""
    default_id, _, small_id, skill = await _personal_chat_with_two_models(
        db_container, test_settings, completion_model_factory
    )
    async with db_container() as container:
        await container.session().execute(
            sa.delete(SkillRuntimePolicies).where(
                SkillRuntimePolicies.tenant_id == container.user().tenant_id
            )
        )

    async with db_container() as admin:
        service = admin.governance_policy_service()
        await service.get_policy_for_update()
        await service.update_policy(
            skill_intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=skill.current_revision.id,
                    )
                )
            ]
        )
        # Validation reads the runtime policy and so creates the missing row.
        await admin.skill_repo().get_runtime_policy_snapshot(
            tenant_id=admin.user().tenant_id
        )
        with pytest.raises(BadRequestException, match="context window"):
            async with db_container() as person:
                pid = await person.session().scalar(sa.text("SELECT pg_backend_pid()"))
                pending = asyncio.create_task(
                    _switch_model(person, default_id, small_id)
                )
                try:
                    await _wait_until_lock_wait(db_container, pid=pid, task=pending)
                    await asyncio.wait_for(
                        admin.assistant_service().confirm_personal_default_governance_fit(),
                        timeout=10,
                    )
                    await admin.session().commit()
                    await asyncio.wait_for(pending, timeout=10)
                finally:
                    if not pending.done():
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)

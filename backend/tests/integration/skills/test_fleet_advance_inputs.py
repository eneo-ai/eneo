from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.main.exceptions import BadRequestException
from eneo.skills.domain.skill import (
    AssistantPinAdvanceIncompatibleReason,
    PersonalChatPinOverride,
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingReference,
    SkillRuntimePolicy,
    SkillRuntimeResolution,
)


async def _organization_space(session, *, tenant_id):
    return await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_runtime_resolution_query_count_is_independent_of_assistant_count(
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
            f"fleet-resolution-{uuid4().hex[:8]}",
        )
        space = await space_factory(
            session,
            f"Fleet resolution {uuid4().hex[:8]}",
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
                f"Fleet Assistant {index} {uuid4().hex[:8]}",
                model.id,
                space_id=space.id,
            )
            for index in range(25)
        ]
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-resolution-{uuid4().hex[:8]}",
            display_name="Fleet resolution",
            description="Batch resolution contract",
            instructions="Resolved once per Assistant",
            content_digest="a" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )
        intent = SkillBindingIntent(
            reference=SkillBindingReference(
                skill_id=skill.id,
                skill_revision_id=skill.current_revision.id,
            )
        )
        skill_service = container.skill_service()
        for assistant in assistants[:-1]:
            await skill_service.replace_assistant_bindings(
                space_id=space.id,
                assistant_id=assistant.id,
                intents=[intent],
            )
        blocked = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            blocked_by_user_id=admin_user.id,
            reason="Batch resolution test",
        )
        assert blocked is not None

        query_count = 0

        def count_queries(
            _connection,
            _cursor,
            _statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            nonlocal query_count
            query_count += 1

        assert session.bind is not None
        sync_engine = session.bind.sync_engine

        async def resolve_counted(assistant_ids):
            nonlocal query_count
            query_count = 0
            sa.event.listen(sync_engine, "before_cursor_execute", count_queries)
            try:
                result = (
                    await skill_service.resolve_assistant_bindings_for_runtime_batch(
                        assistant_ids
                    )
                )
            finally:
                sa.event.remove(sync_engine, "before_cursor_execute", count_queries)
            return result, query_count

        one, one_count = await resolve_counted([assistants[0].id])
        all_resolutions, all_count = await resolve_counted(
            [assistant.id for assistant in assistants]
        )

        assert one_count == all_count
        assert one[assistants[0].id].blocked
        assert all_resolutions[assistants[-1].id] == SkillRuntimeResolution(
            eligible=(),
            blocked=(),
        )
        for assistant in assistants:
            assert all_resolutions[assistant.id] == (
                await skill_service.resolve_assistant_bindings_for_runtime(
                    assistant_id=assistant.id
                )
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preflight_adapter_batch_loads_one_shared_provider_once(
    db_container,
    completion_model_factory,
):
    async with db_container() as container:
        session = container.session()
        records = [
            await completion_model_factory(
                session,
                f"fleet-preflight-{uuid4().hex[:8]}",
                provider="openai",
            )
            for _ in range(5)
        ]
        models = [
            await container.completion_model_crud_service().get_completion_model(
                record.id
            )
            for record in records
        ]

        provider_queries = 0

        def count_provider_queries(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            nonlocal provider_queries
            if "FROM model_providers" in statement:
                provider_queries += 1

        assert session.bind is not None
        sync_engine = session.bind.sync_engine
        sa.event.listen(sync_engine, "before_cursor_execute", count_provider_queries)
        try:
            adapters = await container.completion_service().load_skill_activation_preflight_adapters(
                models
            )
        finally:
            sa.event.remove(
                sync_engine,
                "before_cursor_execute",
                count_provider_queries,
            )

        assert set(adapters) == {model.id for model in models}
        assert provider_queries == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_candidate_pin_fit_matches_current_save_and_reports_oversized_revision(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        model_record = await completion_model_factory(
            session,
            f"fleet-fit-{uuid4().hex[:8]}",
            max_input_tokens=8_000,
        )
        model_record.supports_tool_calling = True
        space_record = await space_factory(
            session,
            f"Fleet fit {uuid4().hex[:8]}",
            [model_record.id],
        )
        session.add(
            SpacesUsers(
                space_id=space_record.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant_record = await assistant_factory(
            session,
            f"Fleet fit Assistant {uuid4().hex[:8]}",
            model_record.id,
            space_id=space_record.id,
        )
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-fit-{uuid4().hex[:8]}",
            display_name="Fleet fit",
            description="Candidate fit contract",
            instructions="Small current instructions",
            content_digest="b" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )
        on_demand_skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-fit-on-demand-{uuid4().hex[:8]}",
            display_name="Fleet fit on demand",
            description="On-demand fit candidate",
            instructions="Small on-demand instructions",
            content_digest="d" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=on_demand_skill.id,
            expected_revision_id=on_demand_skill.current_revision.id,
        )
        blocked_skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-fit-blocked-{uuid4().hex[:8]}",
            display_name="Fleet fit blocked",
            description="Blocked fit binding",
            instructions="Small blocked instructions",
            content_digest="e" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=blocked_skill.id,
            expected_revision_id=blocked_skill.current_revision.id,
        )
        await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=100,
                max_activations_per_turn=10,
            ),
        )
        skill_service = container.skill_service()
        await skill_service.replace_assistant_bindings(
            space_id=space_record.id,
            assistant_id=assistant_record.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=skill.current_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ALWAYS,
                ),
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=on_demand_skill.id,
                        skill_revision_id=on_demand_skill.current_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                ),
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=blocked_skill.id,
                        skill_revision_id=blocked_skill.current_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ALWAYS,
                ),
            ],
        )
        blocked = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=blocked_skill.id,
            blocked_by_user_id=admin_user.id,
            reason="Confirmed unsafe instructions",
        )
        assert blocked is not None
        current_revision_id = skill.current_revision.id
        oversized = await repo.create_revision(
            skill_id=skill.id,
            display_name="Fleet fit oversized",
            description="Oversized candidate",
            instructions="overflow " * 10_000,
            content_digest="c" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=oversized.revision.id,
        )
        candidate_bindings = await repo.resolve_references_for_execution_snapshot(
            tenant_id=admin_user.tenant_id,
            parent_space_id=space_record.id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id,
                    skill_revision_id=oversized.revision.id,
                )
            ],
        )
        assert len(candidate_bindings) == 1
        resolution = (
            await skill_service.resolve_assistant_bindings_for_runtime_batch(
                [assistant_record.id]
            )
        )[assistant_record.id]
        runtime_policy = await repo.get_or_seed_runtime_policy(
            tenant_id=admin_user.tenant_id
        )
        loaded_space = await container.space_repo().get_space_by_assistant(
            assistant_record.id
        )
        assistant = loaded_space.get_assistant(assistant_record.id)
        assistant_service = container.assistant_service()
        assert assistant.completion_model is not None
        preflight_adapters = await container.completion_service().load_skill_activation_preflight_adapters(
            [assistant.completion_model]
        )
        current_candidate_binding = next(
            binding for binding in resolution.eligible if binding.skill_id == skill.id
        )

        await assistant_service._validate_attachments_fit(
            assistant,
            space=loaded_space,
            validate_all_on_demand_candidates=True,
        )
        current_verdict = await assistant_service.assert_assistant_fits_candidate_pin(
            assistant=assistant,
            space_is_personal=loaded_space.is_personal(),
            candidate=PersonalChatPinOverride(
                skill_id=skill.id,
                from_revision_id=current_revision_id,
                to_revision_id=current_revision_id,
            ),
            candidate_binding=current_candidate_binding,
            resolution=resolution,
            runtime_policy=runtime_policy,
            preflight_adapters=preflight_adapters,
        )
        oversized_verdict = await assistant_service.assert_assistant_fits_candidate_pin(
            assistant=assistant,
            space_is_personal=loaded_space.is_personal(),
            candidate=PersonalChatPinOverride(
                skill_id=skill.id,
                from_revision_id=current_revision_id,
                to_revision_id=oversized.revision.id,
            ),
            candidate_binding=candidate_bindings[0],
            resolution=resolution,
            runtime_policy=runtime_policy,
            preflight_adapters=preflight_adapters,
        )

        assert current_verdict is None
        assert oversized_verdict is AssistantPinAdvanceIncompatibleReason.CONTEXT_WINDOW

        await skill_service.replace_assistant_bindings(
            space_id=space_record.id,
            assistant_id=assistant_record.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=oversized.revision.id,
                    ),
                    activation_mode=SkillActivationMode.ALWAYS,
                ),
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=on_demand_skill.id,
                        skill_revision_id=on_demand_skill.current_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                ),
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=blocked_skill.id,
                        skill_revision_id=blocked_skill.current_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ALWAYS,
                ),
            ],
        )
        candidate_space = await container.space_repo().get_space_by_assistant(
            assistant_record.id
        )
        candidate_assistant = candidate_space.get_assistant(assistant_record.id)
        try:
            await assistant_service._validate_attachments_fit(
                candidate_assistant,
                space=candidate_space,
                validate_all_on_demand_candidates=True,
            )
        except BadRequestException:
            ordinary_candidate_verdict = (
                AssistantPinAdvanceIncompatibleReason.CONTEXT_WINDOW
            )
        else:
            ordinary_candidate_verdict = None

        assert oversized_verdict is ordinary_candidate_verdict

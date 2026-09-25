from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.completion_models.domain.skill_activation import (
    SKILL_ACTIVATION_TOOL_NAME,
    ProviderToolCall,
)
from eneo.completion_models.domain.skill_context import SkillContextMeasurement
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
    AssistantsFiles,
)
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.skill_table import AssistantSkillBindings
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingReference,
    SkillRuntimePolicy,
    SkillTurnEffectiveMode,
)
from eneo.tokens.token_utils import TokenCount, TokenCountSource


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def _persisted_assistant_state(db_container, *, assistant_id):
    async with db_container() as container:
        session = container.session()
        name = await session.scalar(
            sa.select(Assistants.name).where(Assistants.id == assistant_id)
        )
        bindings = (
            (
                await session.execute(
                    sa.select(
                        AssistantSkillBindings.skill_id,
                        AssistantSkillBindings.skill_revision_id,
                        AssistantSkillBindings.position,
                        AssistantSkillBindings.activation_mode,
                        AssistantSkillBindings.tenant_id,
                        AssistantSkillBindings.space_id,
                        AssistantSkillBindings.skill_space_id,
                    )
                    .where(AssistantSkillBindings.assistant_id == assistant_id)
                    .order_by(AssistantSkillBindings.position)
                )
            )
            .tuples()
            .all()
        )
    return name, tuple(bindings)


async def _persisted_attachment_ids(db_container, *, assistant_id):
    async with db_container() as container:
        return tuple(
            (
                await container.session().scalars(
                    sa.select(AssistantsFiles.file_id)
                    .where(AssistantsFiles.assistant_id == assistant_id)
                    .order_by(AssistantsFiles.file_id)
                )
            ).all()
        )


async def _persisted_mcp_server_ids(db_container, *, assistant_id):
    async with db_container() as container:
        return tuple(
            (
                await container.session().scalars(
                    sa.select(AssistantMCPServers.mcp_server_id)
                    .where(AssistantMCPServers.assistant_id == assistant_id)
                    .order_by(AssistantMCPServers.mcp_server_id)
                )
            ).all()
        )


async def _organization_space(session, *, tenant_id):
    return await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )


async def _create_on_demand_save_contract(
    container,
    *,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    model_name,
    space_name,
    assistant_name,
    skill_slug,
    skill_name,
    skill_description,
    skill_instructions,
    organization_skill=False,
):
    session = container.session()
    model = await completion_model_factory(
        session,
        model_name,
        max_input_tokens=8_000,
    )
    model.supports_tool_calling = True
    space = await space_factory(session, space_name, [model.id])
    session.add(
        SpacesUsers(
            space_id=space.id,
            user_id=admin_user.id,
            role="admin",
        )
    )
    assistant = await assistant_factory(
        session,
        assistant_name,
        model.id,
        space_id=space.id,
    )
    repo = container.skill_repo()
    await repo.update_runtime_policy(
        tenant_id=admin_user.tenant_id,
        policy=SkillRuntimePolicy(
            selective_activation_enabled=True,
            max_attached_skills=100,
            context_share_percent=100,
            max_activations_per_turn=10,
        ),
    )
    skill_space = space
    if organization_skill:
        skill_space = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert skill_space is not None
    skill = await repo.create(
        space_id=skill_space.id,
        slug=f"{skill_slug}-{uuid4().hex[:8]}",
        display_name=skill_name,
        description=skill_description,
        instructions=skill_instructions,
        content_digest=uuid4().hex * 2,
        created_by_user_id=admin_user.id,
    )
    if organization_skill:
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )
    await container.skill_service().replace_assistant_bindings(
        space_id=space.id,
        assistant_id=assistant.id,
        intents=[
            SkillBindingIntent(
                reference=SkillBindingReference(
                    skill_id=skill.id,
                    skill_revision_id=skill.current_revision.id,
                ),
                activation_mode=SkillActivationMode.ON_DEMAND,
            )
        ],
    )
    return session, space, assistant, skill


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assistant_mode_rejection_rolls_back_parent_and_bindings(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            f"assistant-save-contract-{uuid4().hex[:8]}",
        )
        space = await space_factory(
            session,
            "Assistant Skill save contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Original Assistant name",
            model.id,
            space_id=space.id,
        )

        repo = container.skill_repo()
        first_skill = await repo.create(
            space_id=space.id,
            slug=f"first-{uuid4().hex[:8]}",
            display_name="First Skill",
            description="First on-demand candidate",
            instructions="Use the first Skill when it is relevant.",
            content_digest="a" * 64,
            created_by_user_id=admin_user.id,
        )
        second_skill = await repo.create(
            space_id=space.id,
            slug=f"second-{uuid4().hex[:8]}",
            display_name="Second Skill",
            description="Second on-demand candidate",
            instructions="Use the second Skill when it is relevant.",
            content_digest="b" * 64,
            created_by_user_id=admin_user.id,
        )
        references = [
            SkillBindingReference(
                skill_id=first_skill.id,
                skill_revision_id=first_skill.current_revision.id,
            ),
            SkillBindingReference(
                skill_id=second_skill.id,
                skill_revision_id=second_skill.current_revision.id,
            ),
        ]
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[SkillBindingIntent(reference=value) for value in references],
        )
        assistant_id = assistant.id
        first_skill_id = first_skill.id
        first_revision_id = first_skill.current_revision.id
        second_skill_id = second_skill.id
        second_revision_id = second_skill.current_revision.id

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert original_name == "Original Assistant name"
    assert len(original_bindings) == 2

    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Rejected Assistant name",
            "skill_bindings": [
                {
                    "skill_id": str(second_skill_id),
                    "skill_revision_id": str(second_revision_id),
                },
                {
                    "skill_id": str(first_skill_id),
                    "skill_revision_id": str(first_revision_id),
                    "activation_mode": "on_demand",
                },
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text

    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_name == original_name
    assert persisted_bindings == original_bindings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_on_demand_revision_upgrade_rejection_rolls_back_parent_and_binding(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            "gpt-4o",
            max_input_tokens=2_000,
        )
        model.supports_tool_calling = True
        space = await space_factory(
            session,
            "Assistant Skill revision fit contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Original revision-fit Assistant",
            model.id,
            space_id=space.id,
        )
        repo = container.skill_repo()
        await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=10,
                max_activations_per_turn=10,
            ),
        )
        skill = await repo.create(
            space_id=space.id,
            slug=f"revision-fit-{uuid4().hex[:8]}",
            display_name="Revision fit Skill",
            description="Use for revision-fit questions",
            instructions="The initial body fits.",
            content_digest="c" * 64,
            created_by_user_id=admin_user.id,
        )
        original_revision_id = skill.current_revision.id
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=original_revision_id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )
        revision_change = await repo.create_revision(
            skill_id=skill.id,
            display_name="Revision fit Skill",
            description="Use for revision-fit questions",
            instructions="oversized " * 20_000,
            content_digest="d" * 64,
            created_by_user_id=admin_user.id,
        )
        assert revision_change is not None
        oversized_revision_id = revision_change.revision.id
        assistant_id = assistant.id
        skill_id = skill.id

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert original_name == "Original revision-fit Assistant"
    assert len(original_bindings) == 1
    assert original_bindings[0].skill_revision_id == original_revision_id
    assert original_bindings[0].activation_mode == SkillActivationMode.ON_DEMAND.value

    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Rejected revision-fit Assistant",
            "skill_bindings": [
                {
                    "skill_id": str(skill_id),
                    "skill_revision_id": str(oversized_revision_id),
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_name == original_name
    assert persisted_bindings == original_bindings


@pytest.mark.parametrize(
    ("activated_tokens", "expected_status"),
    [(7_000, 200), (7_001, 400)],
    ids=("fits-reserved-ceiling", "exceeds-reserved-ceiling"),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_retained_on_demand_candidate_rejection_rolls_back_new_always_binding(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    activated_tokens,
    expected_status,
):
    monkeypatch.setattr(
        "eneo.files.attachment_budget.get_settings",
        lambda: SimpleNamespace(attachment_context_reserve_tokens=1_000),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens",
        lambda *_args, **_kwargs: 100,
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **_kwargs: 0,
    )

    def measure_provider_payload(messages, _tools, _model_route):
        activated = any(message.get("role") == "tool" for message in messages)
        return TokenCount(
            tokens=activated_tokens if activated else 100,
            source=TokenCountSource.LITELLM,
        )

    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        measure_provider_payload,
    )

    async with db_container() as container:
        session, space, assistant, candidate = await _create_on_demand_save_contract(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            model_name="gpt-4o",
            space_name="Retained candidate save contract",
            assistant_name="Original retained-candidate Assistant",
            skill_slug="retained-candidate",
            skill_name="Retained candidate Skill",
            skill_description="Use for retained-candidate questions",
            skill_instructions="This candidate must remain activatable.",
        )
        repo = container.skill_repo()
        always = await repo.create(
            space_id=space.id,
            slug=f"new-always-{uuid4().hex[:8]}",
            display_name="New always Skill",
            description="Always-on context added by the save",
            instructions="This body expands the required prompt.",
            content_digest="2" * 64,
            created_by_user_id=admin_user.id,
        )
        assistant_id = assistant.id
        candidate_id = candidate.id
        candidate_revision_id = candidate.current_revision.id
        always_id = always.id
        always_revision_id = always.current_revision.id

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Rejected retained-candidate Assistant",
            "skill_bindings": [
                {
                    "skill_id": str(candidate_id),
                    "skill_revision_id": str(candidate_revision_id),
                    "activation_mode": "on_demand",
                },
                {
                    "skill_id": str(always_id),
                    "skill_revision_id": str(always_revision_id),
                    "activation_mode": "always",
                },
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == expected_status, response.text
    if expected_status == 400:
        assert (
            'on-demand Skill "Retained candidate Skill"' in response.json()["message"]
        )
    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    if expected_status == 200:
        assert persisted_name == "Rejected retained-candidate Assistant"
        assert [binding.skill_id for binding in persisted_bindings] == [
            candidate_id,
            always_id,
        ]
        assert [binding.activation_mode for binding in persisted_bindings] == [
            SkillActivationMode.ON_DEMAND.value,
            SkillActivationMode.ALWAYS.value,
        ]
    else:
        assert persisted_name == original_name
        assert persisted_bindings == original_bindings


@pytest.mark.parametrize(
    ("blocked_mode", "boundary_tokens", "expected_status"),
    [
        (SkillActivationMode.ON_DEMAND, 7_000, 200),
        (SkillActivationMode.ON_DEMAND, 7_001, 400),
        (SkillActivationMode.ALWAYS, 100, 200),
        (SkillActivationMode.ALWAYS, 101, 400),
    ],
    ids=(
        "blocked-on-demand-fits",
        "blocked-on-demand-overflows",
        "blocked-always-fits",
        "blocked-always-overflows",
    ),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_blocked_binding_is_staged_before_binding_save(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    blocked_mode,
    boundary_tokens,
    expected_status,
):
    always_instructions = "Required context restored after unblock."
    monkeypatch.setattr(
        "eneo.files.attachment_budget.get_settings",
        lambda: SimpleNamespace(attachment_context_reserve_tokens=1_000),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens",
        lambda *_args, **_kwargs: 100,
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **_kwargs: 0,
    )

    def measure_provider_payload(messages, _tools, _model_route):
        activated = any(message.get("role") == "tool" for message in messages)
        return TokenCount(
            tokens=(
                boundary_tokens
                if activated and blocked_mode is SkillActivationMode.ON_DEMAND
                else 100
            ),
            source=TokenCountSource.LITELLM,
        )

    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        measure_provider_payload,
    )
    if blocked_mode is SkillActivationMode.ALWAYS:

        def measure_skill_context(*, composed_instructions, tools=None, **_kwargs):
            includes_post_unblock_plan = (
                always_instructions in composed_instructions and bool(tools)
            )
            return SkillContextMeasurement(
                tokens=boundary_tokens if includes_post_unblock_plan else 50,
                limit=100,
                source=TokenCountSource.LITELLM,
            )

        monkeypatch.setattr(
            "eneo.completion_models.domain.skill_activation.measure_skill_context",
            measure_skill_context,
        )

    async with db_container() as container:
        (
            session,
            target_space,
            assistant,
            candidate,
        ) = await _create_on_demand_save_contract(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            model_name="gpt-4o",
            space_name="Blocked candidate save contract",
            assistant_name="Original blocked-candidate Assistant",
            skill_slug="blocked-candidate",
            skill_name="Blocked candidate Skill",
            skill_description="Use for blocked-candidate questions",
            skill_instructions=("This exact reviewed body must remain activatable."),
            organization_skill=True,
        )
        organization_space = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization_space is not None
        repo = container.skill_repo()
        always = await repo.create(
            space_id=organization_space.id,
            slug=f"blocked-always-{uuid4().hex[:8]}",
            display_name="Retained always Skill",
            description="Required context retained during an incident",
            instructions=always_instructions,
            content_digest="4" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=always.id,
            expected_revision_id=always.current_revision.id,
        )
        if blocked_mode is SkillActivationMode.ALWAYS:
            await container.skill_service().replace_assistant_bindings(
                space_id=target_space.id,
                assistant_id=assistant.id,
                intents=[
                    SkillBindingIntent(
                        reference=SkillBindingReference(
                            skill_id=candidate.id,
                            skill_revision_id=candidate.current_revision.id,
                        ),
                        activation_mode=SkillActivationMode.ON_DEMAND,
                    ),
                    SkillBindingIntent(
                        reference=SkillBindingReference(
                            skill_id=always.id,
                            skill_revision_id=always.current_revision.id,
                        ),
                        activation_mode=SkillActivationMode.ALWAYS,
                    ),
                ],
            )
        blocked_skill = (
            candidate if blocked_mode is SkillActivationMode.ON_DEMAND else always
        )
        blocked = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=blocked_skill.id,
            blocked_by_user_id=admin_user.id,
            reason="Confirmed unsafe instructions",
        )
        assert blocked is not None
        assistant_id = assistant.id
        candidate_id = candidate.id
        candidate_revision_id = candidate.current_revision.id
        always_id = always.id
        always_revision_id = always.current_revision.id
        block_id = blocked.block.id
        blocked_skill_id = blocked_skill.id
        model_route = "openai/gpt-4o"

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Staged blocked-candidate Assistant",
            "skill_bindings": [
                {
                    "skill_id": str(candidate_id),
                    "skill_revision_id": str(candidate_revision_id),
                    "activation_mode": "on_demand",
                },
                {
                    "skill_id": str(always_id),
                    "skill_revision_id": str(always_revision_id),
                    "activation_mode": "always",
                },
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == expected_status, response.text
    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    if expected_status == 400:
        if blocked_mode is SkillActivationMode.ON_DEMAND:
            assert (
                'on-demand Skill "Blocked candidate Skill"'
                in response.json()["message"]
            )
        assert persisted_name == original_name
        assert persisted_bindings == original_bindings
        return

    assert persisted_name == "Staged blocked-candidate Assistant"
    assert [binding.skill_id for binding in persisted_bindings] == [
        candidate_id,
        always_id,
    ]
    unblock_response = await client.post(
        f"/api/v1/settings/skills/{blocked_skill_id}/execution-block/unblock",
        json={
            "expected_block_id": str(block_id),
            "reason": "The reviewed instructions are safe again",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert unblock_response.status_code == 200, unblock_response.text
    async with db_container() as container:
        skill_service = container.skill_service()
        resolution = await skill_service.resolve_assistant_bindings_for_runtime(
            assistant_id=assistant_id
        )
        plan = await skill_service.create_turn_plan(
            base_instructions="",
            resolution=resolution,
        )
        runtime = plan.to_activation_runtime(
            selected_model_route=model_route,
            max_input_tokens=8_000,
            supports_tool_calling=True,
        )
        candidate_key = next(
            binding.activation_key
            for binding in plan.available
            if binding.binding.skill_id == candidate_id
        )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": runtime.prompt},
            {"role": "user", "content": "Use the restored Skill"},
        ]
        runtime.apply_provider_tool_calls(
            calls=(
                ProviderToolCall(
                    call_id="activate-restored",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments=f'{{"skill_key":"{candidate_key}"}}',
                ),
            ),
            messages=messages,
        )

    assert runtime.snapshot().effective_mode is SkillTurnEffectiveMode.SELECTIVE
    assert runtime.snapshot().accepted == (candidate_key,)


@pytest.mark.parametrize(
    ("activated_tokens", "expected_status"),
    [(7_000, 200), (7_001, 400)],
    ids=("fits-reserved-ceiling", "exceeds-reserved-ceiling"),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_on_demand_candidate_and_persistent_attachment_overflow_rolls_back(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    activated_tokens,
    expected_status,
):
    monkeypatch.setattr(
        "eneo.files.attachment_budget.get_settings",
        lambda: SimpleNamespace(attachment_context_reserve_tokens=1_000),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens",
        lambda text, *_args, **_kwargs: (
            6_500 if "candidate-persistent-overflow" in text else 100
        ),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda *, text_files, image_files, model_name: (2_000 if text_files else 0),
    )

    def measure_provider_payload(messages, _tools, _model_route):
        activated = any(message.get("role") == "tool" for message in messages)
        if activated:
            assert "persistent attachment" in str(messages)
        return TokenCount(
            tokens=activated_tokens if activated else 100,
            source=TokenCountSource.LITELLM,
        )

    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        measure_provider_payload,
    )

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            "gpt-4o",
            max_input_tokens=8_000,
        )
        model.supports_tool_calling = True
        space = await space_factory(
            session,
            "Assistant candidate attachment contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Original attachment-fit Assistant",
            model.id,
            space_id=space.id,
        )
        repo = container.skill_repo()
        await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=100,
                max_activations_per_turn=10,
            ),
        )
        skill = await repo.create(
            space_id=space.id,
            slug=f"candidate-attachment-{uuid4().hex[:8]}",
            display_name="Candidate attachment Skill",
            description="Use for candidate attachment questions",
            instructions="candidate-persistent-overflow",
            content_digest="e" * 64,
            created_by_user_id=admin_user.id,
        )
        assistant_id = assistant.id
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=skill.current_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )

    headers = {"Authorization": f"Bearer {admin_token}"}
    upload = await client.post(
        "/api/v1/files/",
        files={
            "upload_file": (
                "persistent.txt",
                b"persistent attachment",
                "text/plain",
            )
        },
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    attachment_id = upload.json()["id"]
    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert (
        await _persisted_attachment_ids(
            db_container,
            assistant_id=assistant_id,
        )
        == ()
    )
    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Rejected attachment-fit Assistant",
            "attachments": [{"id": attachment_id}],
        },
        headers=headers,
    )

    assert response.status_code == expected_status, response.text
    if expected_status == 400:
        assert (
            'on-demand Skill "Candidate attachment Skill"' in response.json()["message"]
        )
    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_name == (
        "Rejected attachment-fit Assistant" if expected_status == 200 else original_name
    )
    assert persisted_bindings == original_bindings
    assert await _persisted_attachment_ids(
        db_container,
        assistant_id=assistant_id,
    ) == ((UUID(attachment_id),) if expected_status == 200 else ())


@pytest.mark.parametrize(
    ("activated_tokens", "expected_status"),
    [(7_000, 200), (7_001, 400)],
    ids=("fits-reserved-ceiling", "exceeds-reserved-ceiling"),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_schema_activation_preflight_is_atomic(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    activated_tokens,
    expected_status,
):
    monkeypatch.setattr(
        "eneo.files.attachment_budget.get_settings",
        lambda: SimpleNamespace(attachment_context_reserve_tokens=1_000),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens",
        lambda *_args, **_kwargs: 100,
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **_kwargs: 0,
    )
    measured_tool_names: list[set[str]] = []

    def measure_provider_payload(messages, tools, _model_route):
        measured_tool_names.append(
            {
                tool["function"]["name"]
                for tool in tools
                if isinstance(tool.get("function"), dict)
            }
        )
        activated = any(message.get("role") == "tool" for message in messages)
        return TokenCount(
            tokens=activated_tokens if activated else 100,
            source=TokenCountSource.LITELLM,
        )

    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        measure_provider_payload,
    )

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            "gpt-4o",
            max_input_tokens=8_000,
        )
        model.supports_tool_calling = True
        space = await space_factory(
            session,
            "Assistant activation tool contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Original activation-tool Assistant",
            model.id,
            space_id=space.id,
        )
        mcp_server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Save contract MCP",
            description="Approved warehouse contract",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=False,
        )
        session.add(mcp_server)
        await session.flush()
        mcp_tool = MCPServerTools(
            mcp_server_id=mcp_server.id,
            name="warehouse_query",
            title="Warehouse query",
            description="Query the approved warehouse",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "SQL query"}},
                "required": ["query"],
            },
            is_enabled_by_default=True,
            requires_approval=False,
            removed_from_remote=False,
        )
        session.add(mcp_tool)
        await session.flush()
        session.add_all(
            [
                SpacesMCPServers(
                    space_id=space.id,
                    mcp_server_id=mcp_server.id,
                ),
                AssistantMCPServers(
                    assistant_id=assistant.id,
                    mcp_server_id=mcp_server.id,
                ),
                AssistantMCPServerTools(
                    assistant_id=assistant.id,
                    mcp_server_tool_id=mcp_tool.id,
                    is_enabled=True,
                ),
            ]
        )
        repo = container.skill_repo()
        await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=100,
                max_activations_per_turn=10,
            ),
        )
        skill = await repo.create(
            space_id=space.id,
            slug=f"activation-tool-{uuid4().hex[:8]}",
            display_name="Activation tool Skill",
            description="Use for activation-tool questions",
            instructions="This candidate body fits.",
            content_digest="f" * 64,
            created_by_user_id=admin_user.id,
        )
        assistant_id = assistant.id
        mcp_server_id = mcp_server.id
        mcp_tool_id = mcp_tool.id
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=skill.current_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Staged MCP Assistant",
            "mcp_servers": [{"id": str(mcp_server_id)}],
            "mcp_tools": [
                {
                    "tool_id": str(mcp_tool_id),
                    "is_enabled": True,
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == expected_status, response.text
    assert any(
        "save_contract_mcp__warehouse_query" in tool_names
        for tool_names in measured_tool_names
    )
    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_name == (
        "Staged MCP Assistant" if expected_status == 200 else original_name
    )
    assert persisted_bindings == original_bindings


@pytest.mark.parametrize(
    ("activated_tokens", "expected_status"),
    [(7_000, 200), (7_001, 400)],
    ids=("fits-reserved-ceiling", "exceeds-reserved-ceiling"),
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_mcp_route_rejects_overflow_without_persisting_association(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
    activated_tokens,
    expected_status,
):
    monkeypatch.setattr(
        "eneo.files.attachment_budget.get_settings",
        lambda: SimpleNamespace(attachment_context_reserve_tokens=1_000),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens",
        lambda *_args, **_kwargs: 100,
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda **_kwargs: 0,
    )
    measured_tool_names: list[set[str]] = []

    def measure_provider_payload(messages, tools, _model_route):
        measured_tool_names.append(
            {
                tool["function"]["name"]
                for tool in tools
                if isinstance(tool.get("function"), dict)
            }
        )
        activated = any(message.get("role") == "tool" for message in messages)
        return TokenCount(
            tokens=activated_tokens if activated else 100,
            source=TokenCountSource.LITELLM,
        )

    monkeypatch.setattr(
        "eneo.completion_models.domain.skill_activation.measure_provider_input_tokens",
        measure_provider_payload,
    )

    async with db_container() as container:
        session, space, assistant, _skill = await _create_on_demand_save_contract(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            model_name="gpt-4o",
            space_name="Dedicated MCP add save contract",
            assistant_name="Original dedicated-MCP Assistant",
            skill_slug="dedicated-mcp",
            skill_name="Dedicated MCP candidate Skill",
            skill_description="Use for warehouse export questions",
            skill_instructions="Use the approved warehouse export tool.",
        )
        mcp_server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Dedicated add MCP",
            description="Approved warehouse contract",
            http_url="http://localhost:9001/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=False,
        )
        session.add(mcp_server)
        await session.flush()
        mcp_tool = MCPServerTools(
            mcp_server_id=mcp_server.id,
            name="warehouse_export",
            title="Warehouse export",
            description="Export approved warehouse data",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "SQL query"}},
                "required": ["query"],
            },
            is_enabled_by_default=True,
            requires_approval=False,
            removed_from_remote=False,
        )
        session.add(mcp_tool)
        await session.flush()
        session.add_all(
            [
                SpacesMCPServers(
                    space_id=space.id,
                    mcp_server_id=mcp_server.id,
                ),
                # A previous association can leave this explicit override behind.
                # Re-adding the server must stage the tool exactly as runtime will.
                AssistantMCPServerTools(
                    assistant_id=assistant.id,
                    mcp_server_tool_id=mcp_tool.id,
                    is_enabled=True,
                ),
            ]
        )
        assistant_id = assistant.id
        mcp_server_id = mcp_server.id

    assert (
        await _persisted_mcp_server_ids(
            db_container,
            assistant_id=assistant_id,
        )
        == ()
    )
    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/mcp-servers/{mcp_server_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == expected_status, response.text
    if expected_status == 400:
        assert (
            'on-demand Skill "Dedicated MCP candidate Skill"'
            in response.json()["message"]
        )
    assert any(
        "dedicated_add_mcp__warehouse_export" in tool_names
        for tool_names in measured_tool_names
    )
    persisted_mcp_server_ids = await _persisted_mcp_server_ids(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_mcp_server_ids == (
        (mcp_server_id,) if expected_status == 200 else ()
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assistant_skill_configuration_requires_skill_read_access(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        user = await user_factory(session, tenant_id=admin_user.tenant_id)
        assistant_reader_role = Roles(
            name=f"Assistant reader {uuid4().hex[:8]}",
            permissions=[Permission.ASSISTANTS.value],
            tenant_id=admin_user.tenant_id,
        )
        session.add(assistant_reader_role)
        await session.flush()
        await session.execute(
            users_roles_table.insert().values(
                user_id=user.id,
                role_id=assistant_reader_role.id,
            )
        )
        model = await completion_model_factory(
            session,
            f"assistant-skill-read-{uuid4().hex[:8]}",
        )
        space = await space_factory(
            session,
            "Assistant Skill read contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=user.id,
                role="viewer",
            )
        )
        assistant = await assistant_factory(
            session,
            "Readable Assistant",
            model.id,
            space_id=space.id,
        )
        token = container.auth_service().create_access_token_for_user(user)
        space_id = space.id
        assistant_id = assistant.id

    headers = {"Authorization": f"Bearer {token}"}
    assistant_response = await client.get(
        f"/api/v1/assistants/{assistant_id}/",
        headers=headers,
    )
    assert assistant_response.status_code == 200, assistant_response.text

    configuration_response = await client.get(
        f"/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/",
        headers=headers,
    )

    assert configuration_response.status_code == 403, configuration_response.text

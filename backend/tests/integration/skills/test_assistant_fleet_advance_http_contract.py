import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
)
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.database.tables.skill_table import (
    AssistantSkillBindings,
    SkillRuntimePolicies,
)
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.main.exceptions import BadRequestException
from eneo.skills.domain.skill import (
    AssistantFleetAdvanceCursor,
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingReference,
    SkillRuntimePolicy,
)
from eneo.skills.infrastructure.skill_repo_impl import SkillRepoImpl
from eneo.tokens.token_utils import TokenCount, TokenCountSource


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def regular_token(
    db_container,
    patch_auth_service_jwt,
    user_factory,
    admin_user,
):
    async with db_container() as container:
        regular_user = await user_factory(
            container.session(),
            tenant_id=admin_user.tenant_id,
        )
        return container.auth_service().create_access_token_for_user(regular_user)


async def _create_published_skill(client, *, headers):
    created = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": f"fleet-http-{uuid4().hex[:8]}",
            "display_name": "Fleet HTTP",
            "description": "Fleet advance HTTP contract",
            "instructions": "Use the reviewed instructions.",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    skill = created.json()
    published = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/publish/",
        json={"expected_revision_id": skill["current_revision"]["id"]},
        headers=headers,
    )
    assert published.status_code == 200, published.text
    return skill


@dataclass(frozen=True)
class _FleetSeed:
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
        f"fleet-http-{uuid4().hex[:8]}",
        max_input_tokens=8_000,
    )
    space = await space_factory(
        session,
        f"Fleet HTTP {uuid4().hex[:8]}",
        [model.id],
    )
    session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
    assistants = [
        await assistant_factory(
            session,
            f"Fleet HTTP Assistant {index}",
            model.id,
            space_id=space.id,
        )
        for index in range(size)
    ]
    organization = await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == admin_user.tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert organization is not None
    repo = container.skill_repo()
    skill = await repo.create(
        space_id=organization.id,
        slug=f"fleet-http-{uuid4().hex[:8]}",
        display_name="Fleet HTTP",
        description="Fleet advance HTTP contract",
        instructions="Use the original instructions.",
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
    change = await repo.create_revision(
        skill_id=skill.id,
        display_name="Fleet HTTP",
        description="Fleet advance HTTP contract",
        instructions="Use the reviewed instructions.",
        content_digest="2" * 64,
        created_by_user_id=admin_user.id,
    )
    assert change is not None
    await repo.publish_organization(
        tenant_id=admin_user.tenant_id,
        skill_id=skill.id,
        expected_revision_id=change.revision.id,
    )
    return _FleetSeed(
        skill_id=skill.id,
        old_revision_id=old_revision.id,
        published_revision_id=change.revision.id,
        assistant_ids=tuple(assistant.id for assistant in assistants),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_target_chunk_completes_without_a_cursor_or_outcomes(
    client,
    admin_token,
    db_container,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    skill = await _create_published_skill(client, headers=headers)

    response = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/assistants/advance/",
        json={
            "expected_published_revision_id": skill["current_revision"]["id"],
            "cursor": None,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["next_cursor"] is None
    assert payload["counts"] == {
        "advanced": 0,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert payload["outcomes"] == []
    async with db_container() as container:
        audit_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.entity_id == UUID(skill["id"]),
                AuditLog.action == ActionType.SKILL_BINDINGS_ADVANCED.value,
            )
        )
    assert audit_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_empty_pages_still_enforce_skill_lifecycle(
    client,
    admin_token,
    db_container,
    admin_user,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    missing = await client.post(
        f"/api/v1/skills/organization/{uuid4()}/assistants/advance/",
        json={"expected_published_revision_id": str(uuid4()), "cursor": None},
        headers=headers,
    )
    assert missing.status_code == 404, missing.text

    created = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": f"fleet-empty-{uuid4().hex[:8]}",
            "display_name": "Fleet empty",
            "description": "Empty lifecycle contract",
            "instructions": "Original instructions.",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    skill_id = UUID(created.json()["id"])
    first_revision_id = UUID(created.json()["current_revision"]["id"])

    unpublished = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(first_revision_id),
            "cursor": None,
        },
        headers=headers,
    )
    assert unpublished.status_code == 400, unpublished.text
    assert unpublished.json()["eneo_error_code"] == 9053

    published = await client.post(
        f"/api/v1/skills/organization/{skill_id}/publish/",
        json={"expected_revision_id": str(first_revision_id)},
        headers=headers,
    )
    assert published.status_code == 200, published.text
    async with db_container() as container:
        block = await container.skill_repo().block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill_id,
            blocked_by_user_id=admin_user.id,
            reason="Lifecycle guard test",
        )
        assert block is not None

    blocked = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(first_revision_id),
            "cursor": None,
        },
        headers=headers,
    )
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["eneo_error_code"] == 9054

    async with db_container() as container:
        await container.skill_repo().unblock_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill_id,
            expected_block_id=block.block.id,
            unblocked_by_user_id=admin_user.id,
            reason="Continue lifecycle guard test",
        )
        change = await container.skill_repo().create_revision(
            skill_id=skill_id,
            display_name="Fleet empty",
            description="Empty lifecycle contract",
            instructions="Republished instructions.",
            content_digest="e" * 64,
            created_by_user_id=admin_user.id,
        )
        assert change is not None
        await container.skill_repo().publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill_id,
            expected_revision_id=change.revision.id,
        )

    stale_cursor = AssistantFleetAdvanceCursor(
        skill_id=skill_id,
        expected_published_revision_id=first_revision_id,
        run_id=uuid4(),
        after_assistant_id=uuid4(),
    )
    republished = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(first_revision_id),
            "cursor": stale_cursor.serialize(),
        },
        headers=headers,
    )
    assert republished.status_code == 409, republished.text
    assert republished.json()["eneo_error_code"] == 9043


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_is_admin_only(client, regular_token):
    response = await client.post(
        f"/api/v1/skills/organization/{uuid4()}/assistants/advance/",
        json={
            "expected_published_revision_id": str(uuid4()),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {regular_token}"},
    )

    assert response.status_code == 403, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cursor_must_be_well_formed_and_match_the_request(
    client,
    admin_token,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    skill = await _create_published_skill(client, headers=headers)
    skill_id = UUID(skill["id"])
    revision_id = UUID(skill["current_revision"]["id"])

    malformed = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(revision_id),
            "cursor": "not-a-cursor",
        },
        headers=headers,
    )
    assert malformed.status_code == 400, malformed.text

    mismatched = AssistantFleetAdvanceCursor(
        skill_id=uuid4(),
        expected_published_revision_id=revision_id,
        run_id=uuid4(),
        after_assistant_id=None,
    )
    wrong_skill = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(revision_id),
            "cursor": mismatched.serialize(),
        },
        headers=headers,
    )
    assert wrong_skill.status_code == 400, wrong_skill.text

    mismatched_revision = AssistantFleetAdvanceCursor(
        skill_id=skill_id,
        expected_published_revision_id=uuid4(),
        run_id=uuid4(),
        after_assistant_id=None,
    )
    wrong_revision = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(revision_id),
            "cursor": mismatched_revision.serialize(),
        },
        headers=headers,
    )
    assert wrong_revision.status_code == 400, wrong_revision.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunk_advances_behind_assistants_and_writes_one_atomic_audit_receipt(
    client,
    admin_token,
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

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.published_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["next_cursor"] is None
    assert payload["counts"] == {
        "advanced": 2,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert payload["outcomes"] == [
        {
            "assistant_id": str(assistant_id),
            "outcome": "advanced",
            "reason": None,
        }
        for assistant_id in sorted(seed.assistant_ids)
    ]

    async with db_container() as container:
        pins = list(
            await container.session().scalars(
                sa.select(AssistantSkillBindings.skill_revision_id)
                .where(
                    AssistantSkillBindings.assistant_id.in_(seed.assistant_ids),
                    AssistantSkillBindings.skill_id == seed.skill_id,
                )
                .order_by(AssistantSkillBindings.assistant_id)
            )
        )
        audit_metadata = list(
            await container.session().scalars(
                sa.select(AuditLog.log_metadata).where(
                    AuditLog.entity_id == seed.skill_id,
                    AuditLog.action == ActionType.SKILL_BINDINGS_ADVANCED.value,
                )
            )
        )
    assert pins == [seed.published_revision_id, seed.published_revision_id]
    assert len(audit_metadata) == 1
    metadata = audit_metadata[0]
    assert metadata["changes"] == {
        "advanced": 2,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert metadata["extra"]["surface"] == "assistant"
    assert metadata["extra"]["run_id"] == payload["run_id"]
    assert "instructions" not in str(metadata)


@pytest.mark.parametrize(
    ("terminal_state", "expected_code"),
    [
        ("unpublished", 9053),
        ("republished", 9043),
        ("blocked", 9054),
    ],
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_refusals_keep_the_pin_and_write_no_audit(
    terminal_state,
    expected_code,
    client,
    admin_token,
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
        repo = container.skill_repo()
        if terminal_state == "unpublished":
            await repo.unpublish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
            )
        elif terminal_state == "republished":
            change = await repo.create_revision(
                skill_id=seed.skill_id,
                display_name="Fleet HTTP",
                description="A third published revision",
                instructions="Use a third set of instructions.",
                content_digest="3" * 64,
                created_by_user_id=admin_user.id,
            )
            assert change is not None
            await repo.publish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                expected_revision_id=change.revision.id,
            )
        else:
            block = await repo.block_organization_skill(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                blocked_by_user_id=admin_user.id,
                reason="Confirmed unsafe instructions",
            )
            assert block is not None

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.published_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code in (400, 409), response.text
    assert response.json()["eneo_error_code"] == expected_code
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_ids[0],
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
        audit_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.entity_id == seed.skill_id,
                AuditLog.action == ActionType.SKILL_BINDINGS_ADVANCED.value,
            )
        )
    assert pin == seed.old_revision_id
    assert audit_count == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_policy_change_during_validation_returns_policy_conflict(
    monkeypatch,
    client,
    admin_token,
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
        await container.skill_repo().get_or_seed_runtime_policy(
            tenant_id=admin_user.tenant_id
        )

    validation_finished = asyncio.Event()
    policy_changed = asyncio.Event()
    original_apply = SkillRepoImpl.advance_assistant_skill_pins

    async def apply_after_policy_change(repo, **kwargs):
        validation_finished.set()
        await policy_changed.wait()
        return await original_apply(repo, **kwargs)

    monkeypatch.setattr(
        SkillRepoImpl,
        "advance_assistant_skill_pins",
        apply_after_policy_change,
    )
    request = asyncio.create_task(
        client.post(
            f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
            json={
                "expected_published_revision_id": str(seed.published_revision_id),
                "cursor": None,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )
    await asyncio.wait_for(validation_finished.wait(), timeout=5)
    async with db_container() as editor:
        await editor.session().execute(
            sa.update(SkillRuntimePolicies)
            .where(SkillRuntimePolicies.tenant_id == admin_user.tenant_id)
            .values(context_share_percent=1)
        )
    policy_changed.set()
    response = await request

    assert response.status_code == 409, response.text
    assert response.json()["eneo_error_code"] == 9055
    async with db_container() as verifier:
        pin = await verifier.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_ids[0],
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_oversized_candidate_skips_only_the_incompatible_assistant(
    client,
    admin_token,
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        small_model = await completion_model_factory(
            session,
            f"fleet-small-{uuid4().hex[:8]}",
            max_input_tokens=1_000,
        )
        large_model = await completion_model_factory(
            session,
            f"fleet-large-{uuid4().hex[:8]}",
            max_input_tokens=100_000,
        )
        space = await space_factory(
            session,
            f"Fleet fit {uuid4().hex[:8]}",
            [small_model.id, large_model.id],
        )
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        incompatible = await assistant_factory(
            session,
            "Fleet small context",
            small_model.id,
            space_id=space.id,
        )
        compatible = await assistant_factory(
            session,
            "Fleet large context",
            large_model.id,
            space_id=space.id,
        )
        organization = await session.scalar(
            sa.select(Spaces).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-fit-{uuid4().hex[:8]}",
            display_name="Fleet fit",
            description="Fleet candidate fit",
            instructions="Small original instructions.",
            content_digest="a" * 64,
            created_by_user_id=admin_user.id,
        )
        old_revision = skill.current_revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=old_revision.id,
        )
        for assistant in (incompatible, compatible):
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
        change = await repo.create_revision(
            skill_id=skill.id,
            display_name="Fleet fit",
            description="Fleet candidate fit",
            instructions="overflow " * 10_000,
            content_digest="b" * 64,
            created_by_user_id=admin_user.id,
        )
        assert change is not None
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=change.revision.id,
        )
        skill_id = skill.id
        published_revision_id = change.revision.id
        old_revision_id = old_revision.id
        incompatible_id = incompatible.id
        compatible_id = compatible.id

    response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(published_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    outcomes = {item["assistant_id"]: item for item in payload["outcomes"]}
    assert outcomes[str(incompatible_id)] == {
        "assistant_id": str(incompatible_id),
        "outcome": "incompatible",
        "reason": "context_window",
    }
    assert outcomes[str(compatible_id)]["outcome"] == "advanced"

    async with db_container() as container:
        pins = dict(
            (
                await container.session().execute(
                    sa.select(
                        AssistantSkillBindings.assistant_id,
                        AssistantSkillBindings.skill_revision_id,
                    ).where(AssistantSkillBindings.skill_id == skill_id)
                )
            ).all()
        )
    assert pins[incompatible_id] == old_revision_id
    assert pins[compatible_id] == published_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disabled_selective_activation_keeps_on_demand_pin_unchanged(
    client,
    admin_token,
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
        assistant_id = seed.assistant_ids[0]
        space_id = await container.session().scalar(
            sa.select(Assistants.space_id).where(Assistants.id == assistant_id)
        )
        assert space_id is not None
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
        await container.skill_service().replace_assistant_bindings(
            space_id=space_id,
            assistant_id=assistant_id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=seed.skill_id,
                        skill_revision_id=seed.old_revision_id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )
        await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=False,
                max_attached_skills=100,
                context_share_percent=100,
                max_activations_per_turn=10,
            ),
        )

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.published_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    assert response.json()["outcomes"] == [
        {
            "assistant_id": str(assistant_id),
            "outcome": "incompatible",
            "reason": "activation_unavailable",
        }
    ]
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == assistant_id,
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retained_deprecated_model_still_rejects_an_oversized_candidate(
    client,
    admin_token,
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
        model_id = await container.session().scalar(
            sa.select(Assistants.completion_model_id).where(
                Assistants.id == seed.assistant_ids[0]
            )
        )
        assert model_id is not None
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == model_id)
            .values(is_deprecated=True)
        )
        change = await container.skill_repo().create_revision(
            skill_id=seed.skill_id,
            display_name="Fleet deprecated model",
            description="Retained model fit contract",
            instructions="overflow " * 10_000,
            content_digest="d" * 64,
            created_by_user_id=admin_user.id,
        )
        assert change is not None
        await container.skill_repo().publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=seed.skill_id,
            expected_revision_id=change.revision.id,
        )
        candidate_revision_id = change.revision.id

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(candidate_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    assert response.json()["outcomes"][0]["reason"] == "context_window"
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_ids[0],
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_projected_mcp_tool_schema_matches_save_time_candidate_fit(
    client,
    admin_token,
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
            f"fleet-mcp-{uuid4().hex[:8]}",
            max_input_tokens=8_000,
        )
        model.supports_tool_calling = True
        space = await space_factory(
            session,
            f"Fleet MCP {uuid4().hex[:8]}",
            [model.id],
        )
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        assistant = await assistant_factory(
            session,
            "Fleet MCP Assistant",
            model.id,
            space_id=space.id,
        )
        organization = await session.scalar(
            sa.select(Spaces).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-mcp-{uuid4().hex[:8]}",
            display_name="Fleet MCP",
            description="Projected MCP fit contract",
            instructions="Original on-demand instructions.",
            content_digest="m" * 64,
            created_by_user_id=admin_user.id,
        )
        old_revision = skill.current_revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=old_revision.id,
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
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=old_revision.id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )
        mcp_server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Fleet large-schema MCP",
            description="Projected fleet tools",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=False,
            tool_definition_max_bytes=4 * 1024 * 1024,
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
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "warehouse field " * 100_000,
                    }
                },
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
        change = await repo.create_revision(
            skill_id=skill.id,
            display_name="Fleet MCP",
            description="Projected MCP fit contract",
            instructions="Candidate on-demand instructions.",
            content_digest="n" * 64,
            created_by_user_id=admin_user.id,
        )
        assert change is not None
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=change.revision.id,
        )
        skill_id = skill.id
        assistant_id = assistant.id
        space_id = space.id
        candidate_revision_id = change.revision.id

    response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(candidate_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["incompatible"] == 1
    assert response.json()["outcomes"][0]["reason"] == "context_window"

    async with db_container() as container:
        await container.skill_service().replace_assistant_bindings(
            space_id=space_id,
            assistant_id=assistant_id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill_id,
                        skill_revision_id=candidate_revision_id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )
        loaded_space = await container.space_repo().get_space_by_assistant(assistant_id)
        with pytest.raises(BadRequestException):
            await container.assistant_service()._validate_attachments_fit(
                loaded_space.get_assistant(assistant_id),
                space=loaded_space,
                validate_all_on_demand_candidates=True,
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_always_candidate_counts_mcp_baseline_and_fitting_control_can_ask(
    client,
    admin_token,
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
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
    monkeypatch.setattr(
        "eneo.assistants.assistant_service.measure_provider_input_tokens",
        lambda *_args, **_kwargs: TokenCount(
            tokens=8_000,
            source=TokenCountSource.LITELLM,
        ),
    )

    async with db_container() as container:
        session = container.session()
        constrained_model = await completion_model_factory(
            session,
            f"fleet-always-mcp-small-{uuid4().hex[:8]}",
            max_input_tokens=8_000,
        )
        fitting_model = await completion_model_factory(
            session,
            f"fleet-always-mcp-large-{uuid4().hex[:8]}",
            max_input_tokens=20_000,
        )
        constrained_model.supports_tool_calling = True
        fitting_model.supports_tool_calling = True
        space = await space_factory(
            session,
            f"Fleet always MCP {uuid4().hex[:8]}",
            [constrained_model.id, fitting_model.id],
        )
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        constrained_assistant = await assistant_factory(
            session,
            "Fleet constrained MCP Assistant",
            constrained_model.id,
            space_id=space.id,
        )
        fitting_assistant = await assistant_factory(
            session,
            "Fleet fitting MCP Assistant",
            fitting_model.id,
            space_id=space.id,
        )
        organization = await session.scalar(
            sa.select(Spaces).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"fleet-always-mcp-{uuid4().hex[:8]}",
            display_name="Fleet always MCP",
            description="Provider-visible MCP baseline contract",
            instructions="Original always instructions.",
            content_digest="a" * 64,
            created_by_user_id=admin_user.id,
        )
        old_revision = skill.current_revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=old_revision.id,
        )
        for assistant in (constrained_assistant, fitting_assistant):
            await container.skill_service().replace_assistant_bindings(
                space_id=space.id,
                assistant_id=assistant.id,
                intents=[
                    SkillBindingIntent(
                        reference=SkillBindingReference(
                            skill_id=skill.id,
                            skill_revision_id=old_revision.id,
                        ),
                        activation_mode=SkillActivationMode.ALWAYS,
                    )
                ],
            )
        mcp_server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Fleet always MCP baseline",
            description="Provider-visible fleet tools",
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
                "properties": {"query": {"type": "string"}},
            },
            is_enabled_by_default=True,
            requires_approval=False,
            removed_from_remote=False,
        )
        session.add(mcp_tool)
        await session.flush()
        session.add(SpacesMCPServers(space_id=space.id, mcp_server_id=mcp_server.id))
        for assistant in (constrained_assistant, fitting_assistant):
            session.add_all(
                [
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
        change = await repo.create_revision(
            skill_id=skill.id,
            display_name="Fleet always MCP",
            description="Provider-visible MCP baseline contract",
            instructions="Published always instructions.",
            content_digest="b" * 64,
            created_by_user_id=admin_user.id,
        )
        assert change is not None
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=change.revision.id,
        )
        skill_id = skill.id
        old_revision_id = old_revision.id
        candidate_revision_id = change.revision.id
        constrained_assistant_id = constrained_assistant.id
        fitting_assistant_id = fitting_assistant.id

    response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(candidate_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    assert {
        outcome["assistant_id"]: outcome["outcome"]
        for outcome in response.json()["outcomes"]
    } == {
        str(constrained_assistant_id): "incompatible",
        str(fitting_assistant_id): "advanced",
    }

    async with db_container() as container:
        pins = dict(
            (
                await container.session().execute(
                    sa.select(
                        AssistantSkillBindings.assistant_id,
                        AssistantSkillBindings.skill_revision_id,
                    ).where(AssistantSkillBindings.skill_id == skill_id)
                )
            ).all()
        )
        loaded_space = await container.space_repo().get_space_by_assistant(
            fitting_assistant_id
        )
        fitting = loaded_space.get_assistant(fitting_assistant_id)
        resolution = (
            await container.skill_service().resolve_assistant_bindings_for_runtime(
                assistant_id=fitting_assistant_id
            )
        )
        plan = await container.skill_service().create_turn_plan(
            base_instructions=fitting.get_prompt_text(),
            resolution=resolution,
        )
        assert fitting.completion_model is not None
        runtime = plan.to_activation_runtime(
            selected_model_route=fitting.completion_model.get_model_route(),
            max_input_tokens=fitting.completion_model.max_input_tokens,
            supports_tool_calling=fitting.completion_model.supports_tool_calling,
        )
        adapter = MagicMock()
        adapter.model = fitting.completion_model
        adapter.get_token_limit_of_model.return_value = (
            fitting.completion_model.max_input_tokens
        )
        adapter.get_model_route.return_value = (
            fitting.completion_model.get_model_route()
        )
        adapter.get_logging_details.return_value = None
        adapter.get_response = AsyncMock(
            return_value=Completion(text="The fitting Assistant answered.")
        )
        completion_service = container.completion_service()
        monkeypatch.setattr(
            completion_service,
            "_get_adapter",
            AsyncMock(return_value=adapter),
        )
        completion, _ = await fitting.ask(
            question="Can I query the warehouse?",
            completion_service=completion_service,
            references_service=container.references_service(),
            skill_runtime=runtime,
        )

    assert pins[constrained_assistant_id] == old_revision_id
    assert pins[fitting_assistant_id] == candidate_revision_id
    assert completion.completion.text == "The fitting Assistant answered."
    mcp_proxy = adapter.get_response.await_args.kwargs["mcp_proxy"]
    assert mcp_proxy is not None
    assert mcp_proxy.get_tool_count() == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cursor_drives_a_fleet_larger_than_one_chunk_to_completion(
    client,
    admin_token,
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
            size=101,
        )
    headers = {"Authorization": f"Bearer {admin_token}"}

    first = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.published_revision_id),
            "cursor": None,
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["counts"]["advanced"] == 100
    assert len(first_payload["outcomes"]) == 100
    assert first_payload["next_cursor"] is not None

    second = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.published_revision_id),
            "cursor": first_payload["next_cursor"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["run_id"] == first_payload["run_id"]
    assert second_payload["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert second_payload["next_cursor"] is None

    async with db_container() as container:
        advanced_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(AssistantSkillBindings)
            .where(
                AssistantSkillBindings.skill_id == seed.skill_id,
                AssistantSkillBindings.skill_revision_id == seed.published_revision_id,
            )
        )
    assert advanced_count == 101

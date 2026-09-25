import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from PIL import Image

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
    AssistantsFiles,
)
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.files_table import Files
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.skill_table import (
    AssistantSkillBindings,
    SkillRuntimePolicies,
)
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_repo import FileRepository
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.object_content.content import ContentFailureCode, ContentState, StorageKind
from eneo.object_content.content_service import ObjectContentService
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


async def _add_inline_file_content(
    session,
    *,
    file: Files,
    user_id: UUID,
    payload: bytes,
    variant: FileContentVariant,
    media_type: str,
) -> UUID:
    digest = sha256(payload).digest()
    content = ObjectContents(
        tenant_id=file.tenant_id,
        created_by_user_id=user_id,
        storage_kind=StorageKind.POSTGRES_INLINE.value,
        state="available",
        access_class="private_resource",
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type=media_type,
        verified_media_type=media_type,
        idempotency_key=f"fleet-derived-{uuid4().hex}",
        request_fingerprint=digest,
        available_at=datetime.now(UTC),
    )
    session.add(content)
    await session.flush()
    session.add_all(
        [
            InlineContentPayloads(
                content_id=content.id,
                storage_kind=StorageKind.POSTGRES_INLINE.value,
                payload=payload,
            ),
            FileContentReferences(
                file_id=file.id,
                content_id=content.id,
                variant=variant.value,
                ordinal=0,
            ),
        ]
    )
    await session.flush()
    return content.id


async def _add_pending_file_content(
    session,
    *,
    file: Files,
    user_id: UUID,
    payload: bytes,
    variant: FileContentVariant,
    media_type: str,
) -> UUID:
    digest = sha256(payload).digest()
    content = ObjectContents(
        tenant_id=file.tenant_id,
        created_by_user_id=user_id,
        storage_kind=StorageKind.OBJECT_STORE.value,
        state=ContentState.PENDING.value,
        access_class="private_resource",
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type=media_type,
        verified_media_type=media_type,
        idempotency_key=f"fleet-pending-{uuid4().hex}",
        request_fingerprint=digest,
    )
    session.add(content)
    await session.flush()
    session.add_all(
        [
            ObjectStoreObjects(
                content_id=content.id,
                storage_kind=StorageKind.OBJECT_STORE.value,
                object_key=f"fleet-pending/{uuid4().hex}",
                verification_chunk_size_bytes=len(payload),
                verification_chunk_sha256=digest,
            ),
            FileContentReferences(
                file_id=file.id,
                content_id=content.id,
                variant=variant.value,
                ordinal=0,
            ),
        ]
    )
    await session.flush()
    return content.id


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
async def test_missing_model_keeps_on_demand_pin_unchanged(
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
        await container.skill_repo().update_runtime_policy(
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
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(completion_model_id=None)
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
async def test_inactive_provider_does_not_block_always_only_fleet_targets(
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
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        inactive_model = await completion_model_factory(
            session,
            f"fleet-inactive-{uuid4().hex[:8]}",
            provider=f"fleet-inactive-{uuid4().hex[:8]}",
        )
        assert inactive_model.provider_id is not None
        await session.execute(
            sa.update(ModelProviders)
            .where(ModelProviders.id == inactive_model.provider_id)
            .values(is_active=False)
        )
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == seed.assistant_ids[0])
            .values(completion_model_id=inactive_model.id)
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
        "advanced": 2,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert {outcome["assistant_id"] for outcome in response.json()["outcomes"]} == {
        str(assistant_id) for assistant_id in seed.assistant_ids
    }
    assert all(
        outcome["outcome"] == "advanced" and outcome["reason"] is None
        for outcome in response.json()["outcomes"]
    )
    async with db_container() as container:
        pins = (
            await container.session().scalars(
                sa.select(AssistantSkillBindings.skill_revision_id).where(
                    AssistantSkillBindings.assistant_id.in_(seed.assistant_ids),
                    AssistantSkillBindings.skill_id == seed.skill_id,
                )
            )
        ).all()
    assert pins == [seed.published_revision_id, seed.published_revision_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inactive_on_demand_provider_only_excludes_its_assistant(
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
        seed = await _seed_behind_fleet(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        inactive_model = await completion_model_factory(
            session,
            f"fleet-inactive-on-demand-{uuid4().hex[:8]}",
            provider=f"fleet-inactive-on-demand-{uuid4().hex[:8]}",
        )
        assert inactive_model.provider_id is not None
        await session.execute(
            sa.update(ModelProviders)
            .where(ModelProviders.id == inactive_model.provider_id)
            .values(is_active=False)
        )
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == seed.assistant_ids[0])
            .values(completion_model_id=inactive_model.id)
        )
        active_model_id = await session.scalar(
            sa.select(Assistants.completion_model_id).where(
                Assistants.id == seed.assistant_ids[1]
            )
        )
        assert active_model_id is not None
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id.in_([inactive_model.id, active_model_id]))
            .values(supports_tool_calling=True)
        )
        space_id = await session.scalar(
            sa.select(Assistants.space_id).where(Assistants.id == seed.assistant_ids[0])
        )
        assert space_id is not None
        await container.skill_repo().update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=100,
                max_activations_per_turn=10,
            ),
        )
        for assistant_id in seed.assistant_ids:
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

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.published_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    outcomes = {
        UUID(outcome["assistant_id"]): outcome
        for outcome in response.json()["outcomes"]
    }
    assert response.json()["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    assert outcomes[seed.assistant_ids[0]] == {
        "assistant_id": str(seed.assistant_ids[0]),
        "outcome": "incompatible",
        "reason": "activation_unavailable",
    }
    assert outcomes[seed.assistant_ids[1]] == {
        "assistant_id": str(seed.assistant_ids[1]),
        "outcome": "advanced",
        "reason": None,
    }
    async with db_container() as container:
        pins = dict(
            (
                await container.session().execute(
                    sa.select(
                        AssistantSkillBindings.assistant_id,
                        AssistantSkillBindings.skill_revision_id,
                    ).where(
                        AssistantSkillBindings.assistant_id.in_(seed.assistant_ids),
                        AssistantSkillBindings.skill_id == seed.skill_id,
                    )
                )
            ).all()
        )
    assert pins == {
        seed.assistant_ids[0]: seed.old_revision_id,
        seed.assistant_ids[1]: seed.published_revision_id,
    }


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


@dataclass(frozen=True)
class _OwnerAttachmentFleetSeed:
    skill_id: UUID
    old_revision_id: UUID
    candidate_revision_id: UUID
    assistant_id: UUID
    assistant_ids: tuple[UUID, ...]
    owner_user_id: UUID
    root_file_id: UUID
    derived_content_id: UUID
    derived_content_ids: tuple[UUID, ...]
    derived_payload: bytes


async def _seed_owner_attachment_fleet(
    db_container,
    *,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
    derived_state: ContentState,
    vision: bool = True,
    assistant_count: int = 1,
) -> _OwnerAttachmentFleetSeed:
    if assistant_count < 1:
        raise ValueError("assistant_count must be positive")
    async with db_container() as container:
        session = container.session()
        owner = await user_factory(session, tenant_id=admin_user.tenant_id)
        model = await completion_model_factory(
            session,
            f"fleet-vision-{uuid4().hex[:8]}",
            max_input_tokens=4_000,
            vision=vision,
        )
        personal_space = await space_factory(
            session,
            f"Fleet owner {uuid4().hex[:8]}",
            [model.id],
            user_id=owner.id,
        )
        assistants = [
            Assistants(
                name=f"Owner vision Assistant {index + 1}",
                user_id=owner.id,
                completion_model_id=model.id,
                completion_model_kwargs={},
                logging_enabled=True,
                is_default=False,
                published=False,
                space_id=personal_space.id,
            )
            for index in range(assistant_count)
        ]
        session.add_all(assistants)
        await session.flush()

        derived_image = BytesIO()
        Image.new("RGB", (2_048, 1_024), color=(24, 95, 180)).save(
            derived_image,
            format="PNG",
        )
        derived_payload = derived_image.getvalue()
        add_derived_content = (
            _add_inline_file_content
            if derived_state is ContentState.AVAILABLE
            else _add_pending_file_content
        )
        roots: list[Files] = []
        derived_content_ids: list[UUID] = []
        for index, assistant in enumerate(assistants):
            root = Files(
                name=f"owner-document-{index + 1}.txt",
                mimetype="text/plain",
                file_type=FileType.TEXT.value,
                tenant_id=admin_user.tenant_id,
                user_id=owner.id,
            )
            session.add(root)
            await session.flush()
            roots.append(root)
            derived = Files(
                name=f"owner-page-{index + 1}.png",
                mimetype="image/png",
                file_type=FileType.IMAGE.value,
                tenant_id=admin_user.tenant_id,
                user_id=owner.id,
                parent_file_id=root.id,
            )
            session.add(derived)
            await session.flush()
            await _add_inline_file_content(
                session,
                file=root,
                user_id=owner.id,
                payload=b"short root attachment",
                variant=FileContentVariant.ORIGINAL,
                media_type="text/plain",
            )
            derived_content_ids.append(
                await add_derived_content(
                    session,
                    file=derived,
                    user_id=owner.id,
                    payload=derived_payload,
                    variant=FileContentVariant.DERIVED_PAGE,
                    media_type="image/png",
                )
            )
            session.add(AssistantsFiles(assistant_id=assistant.id, file_id=root.id))
        if derived_state is ContentState.FAILED:
            await session.execute(
                sa.update(ObjectContents)
                .where(ObjectContents.id.in_(derived_content_ids))
                .values(
                    state=ContentState.FAILED.value,
                    failure_code=ContentFailureCode.VERIFICATION_MISMATCH.value,
                    failure_detail="Terminal derivative failure for fleet validation",
                )
            )
        await session.flush()
        personal_space_id = personal_space.id
        assistant_ids = tuple(assistant.id for assistant in assistants)
        assistant_id = assistant_ids[0]
        owner_user_id = owner.id
        root_file_id = roots[0].id
        derived_content_id = derived_content_ids[0]

    async with db_container() as container:
        session = container.session()
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
            slug=f"fleet-owner-files-{uuid4().hex[:8]}",
            display_name="Fleet owner files",
            description="Owner-derived image fit contract",
            instructions="Short instructions.",
            content_digest="f" * 64,
            created_by_user_id=admin_user.id,
        )
        old_revision = skill.current_revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=old_revision.id,
        )
        session.add_all(
            AssistantSkillBindings(
                assistant_id=assistant_id,
                tenant_id=admin_user.tenant_id,
                space_id=personal_space_id,
                skill_space_id=organization.id,
                skill_id=skill.id,
                skill_revision_id=old_revision.id,
                position=0,
                activation_mode=SkillActivationMode.ALWAYS.value,
            )
            for assistant_id in assistant_ids
        )
        change = await repo.create_revision(
            skill_id=skill.id,
            display_name="Fleet owner files",
            description="Owner-derived image fit contract",
            instructions="overflow " * 1_500,
            content_digest="e" * 64,
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

    return _OwnerAttachmentFleetSeed(
        skill_id=skill_id,
        old_revision_id=old_revision_id,
        candidate_revision_id=candidate_revision_id,
        assistant_id=assistant_id,
        assistant_ids=assistant_ids,
        owner_user_id=owner_user_id,
        root_file_id=root_file_id,
        derived_content_id=derived_content_id,
        derived_content_ids=tuple(derived_content_ids),
        derived_payload=derived_payload,
    )


async def _advance_owner_attachment_fleet_with_query_counts(
    *,
    client,
    admin_token: str,
    db_container,
    seed: _OwnerAttachmentFleetSeed,
):
    async with db_container() as container:
        bind = container.session().get_bind()
        engine = getattr(bind, "engine", bind)
        derived_selects = 0
        content_reference_selects = 0

        def record_statement(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            nonlocal content_reference_selects, derived_selects
            normalized = statement.lower()
            if (
                normalized.lstrip().startswith("select")
                and "from file_content_references" in normalized
            ):
                content_reference_selects += 1
            if (
                normalized.lstrip().startswith("select")
                and "left outer join files as" in normalized
                and ".parent_file_id =" in normalized
                and "object_contents.state" in normalized
            ):
                derived_selects += 1

        sa.event.listen(engine, "before_cursor_execute", record_statement)
        try:
            response = await client.post(
                f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
                json={
                    "expected_published_revision_id": str(seed.candidate_revision_id),
                    "cursor": None,
                },
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        finally:
            sa.event.remove(engine, "before_cursor_execute", record_statement)
    return response, derived_selects, content_reference_selects


@pytest.mark.integration
@pytest.mark.asyncio
async def test_owner_derived_images_are_included_in_admin_fleet_validation(
    client,
    admin_token,
    db_container,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
):
    seed = await _seed_owner_attachment_fleet(
        db_container,
        admin_user=admin_user,
        user_factory=user_factory,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        derived_state=ContentState.AVAILABLE,
    )

    (
        response,
        derived_selects,
        _content_reference_selects,
    ) = await _advance_owner_attachment_fleet_with_query_counts(
        client=client,
        admin_token=admin_token,
        db_container=db_container,
        seed=seed,
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    assert response.json()["outcomes"] == [
        {
            "assistant_id": str(seed.assistant_id),
            "outcome": "incompatible",
            "reason": "context_window",
        }
    ]
    assert derived_selects == 1
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_id,
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_owner_derived_image_hydration_query_count_is_chunk_bounded(
    monkeypatch,
    client,
    admin_token,
    db_container,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
):
    seed = await _seed_owner_attachment_fleet(
        db_container,
        admin_user=admin_user,
        user_factory=user_factory,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        derived_state=ContentState.AVAILABLE,
        assistant_count=25,
    )
    derived_batch_limit = len(seed.derived_payload) * 4
    settings = get_settings().model_copy(
        update={"attachment_max_size_bytes": derived_batch_limit}
    )
    monkeypatch.setattr(
        "eneo.skills.application.organization_skill_service.get_settings",
        lambda: settings,
    )
    original_read_content_bytes = ObjectContentService.read_content_bytes
    derived_content_ids = frozenset(seed.derived_content_ids)
    derived_payload_batch_sizes: list[int] = []
    live_derived_payload_bytes = [0]
    peak_live_derived_payload_bytes = [0]

    class TrackedDerivedPayload(bytes):
        def __del__(self):
            live_derived_payload_bytes[0] -= len(self)

    async def record_derived_payload_batch(service, grants):
        derived_grant_ids = {
            grant.content_id
            for grant in grants
            if grant.content_id in derived_content_ids
        }
        if derived_grant_ids:
            assert live_derived_payload_bytes[0] == 0
        payloads = await original_read_content_bytes(service, grants)
        batch_size = 0
        for content_id in derived_grant_ids:
            tracked_payload = TrackedDerivedPayload(payloads[content_id])
            payloads[content_id] = tracked_payload
            batch_size += len(tracked_payload)
        live_derived_payload_bytes[0] += batch_size
        peak_live_derived_payload_bytes[0] = max(
            peak_live_derived_payload_bytes[0],
            live_derived_payload_bytes[0],
        )
        if batch_size:
            derived_payload_batch_sizes.append(batch_size)
        return payloads

    monkeypatch.setattr(
        ObjectContentService,
        "read_content_bytes",
        record_derived_payload_batch,
    )

    (
        response,
        derived_selects,
        content_reference_selects,
    ) = await _advance_owner_attachment_fleet_with_query_counts(
        client=client,
        admin_token=admin_token,
        db_container=db_container,
        seed=seed,
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 0,
        "incompatible": 25,
    }
    assert derived_selects == 1
    assert content_reference_selects == 3
    assert len(derived_payload_batch_sizes) == 7
    assert max(derived_payload_batch_sizes) <= derived_batch_limit
    assert sum(derived_payload_batch_sizes) == (
        len(seed.derived_payload) * len(seed.derived_content_ids)
    )
    assert peak_live_derived_payload_bytes[0] <= derived_batch_limit
    assert live_derived_payload_bytes[0] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_vision_fleet_skips_derived_image_projection(
    client,
    admin_token,
    db_container,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
):
    seed = await _seed_owner_attachment_fleet(
        db_container,
        admin_user=admin_user,
        user_factory=user_factory,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        derived_state=ContentState.AVAILABLE,
        vision=False,
    )

    (
        response,
        derived_selects,
        _content_reference_selects,
    ) = await _advance_owner_attachment_fleet_with_query_counts(
        client=client,
        admin_token=admin_token,
        db_container=db_container,
        seed=seed,
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert derived_selects == 0
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_id,
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.candidate_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unavailable_owner_derivative_matches_owner_time_fleet_validation(
    monkeypatch,
    client,
    admin_token,
    db_container,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
):
    seed = await _seed_owner_attachment_fleet(
        db_container,
        admin_user=admin_user,
        user_factory=user_factory,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        derived_state=ContentState.PENDING,
    )

    validation_finished = asyncio.Event()
    derivative_available = asyncio.Event()
    original_apply = SkillRepoImpl.advance_assistant_skill_pins
    original_read_content_bytes = ObjectContentService.read_content_bytes

    async def read_completed_derivative(service, grants):
        grants = tuple(grants)
        other_grants = tuple(
            grant for grant in grants if grant.content_id != seed.derived_content_id
        )
        payloads = (
            await original_read_content_bytes(service, other_grants)
            if other_grants
            else {}
        )
        if any(grant.content_id == seed.derived_content_id for grant in grants):
            payloads[seed.derived_content_id] = seed.derived_payload
        return payloads

    monkeypatch.setattr(
        ObjectContentService,
        "read_content_bytes",
        read_completed_derivative,
    )

    async def apply_after_derivative_becomes_available(repo, **kwargs):
        validation_finished.set()
        await derivative_available.wait()
        return await original_apply(repo, **kwargs)

    monkeypatch.setattr(
        SkillRepoImpl,
        "advance_assistant_skill_pins",
        apply_after_derivative_becomes_available,
    )
    request = asyncio.create_task(
        client.post(
            f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
            json={
                "expected_published_revision_id": str(seed.candidate_revision_id),
                "cursor": None,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )
    await asyncio.wait_for(validation_finished.wait(), timeout=5)
    async with db_container() as editor:
        await editor.session().execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id == seed.derived_content_id)
            .values(
                state=ContentState.AVAILABLE.value,
                available_at=datetime.now(UTC),
            )
        )
    derivative_available.set()
    response = await request

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 1,
        "incompatible": 0,
    }
    assert response.json()["outcomes"] == [
        {
            "assistant_id": str(seed.assistant_id),
            "outcome": "concurrent_change",
            "reason": None,
        }
    ]
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_id,
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id

    rerun = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.candidate_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    assert rerun.json()["outcomes"] == [
        {
            "assistant_id": str(seed.assistant_id),
            "outcome": "incompatible",
            "reason": "context_window",
        }
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_owner_derivative_is_a_stable_runtime_omission(
    client,
    admin_token,
    db_container,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
):
    seed = await _seed_owner_attachment_fleet(
        db_container,
        admin_user=admin_user,
        user_factory=user_factory,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        derived_state=ContentState.FAILED,
    )

    async with db_container() as container:
        runtime_derived = await FileRepository(container.session()).get_by_parent_ids(
            parent_ids=[seed.root_file_id],
            user_id=seed.owner_user_id,
        )
    assert runtime_derived == []

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/assistants/advance/",
        json={
            "expected_published_revision_id": str(seed.candidate_revision_id),
            "cursor": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert response.json()["outcomes"] == [
        {
            "assistant_id": str(seed.assistant_id),
            "outcome": "advanced",
            "reason": None,
        }
    ]
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AssistantSkillBindings.skill_revision_id).where(
                AssistantSkillBindings.assistant_id == seed.assistant_id,
                AssistantSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.candidate_revision_id


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

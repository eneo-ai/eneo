import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from PIL import Image

from eneo.apps.app_runs.app_run_repo import _serialize_skill_provenance
from eneo.apps.apps.app_repo import AppRepository
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.app_table import AppRuns, Apps, AppsFiles
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.skill_table import AppSkillBindings
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.files.file_models import FileContentVariant, FileType
from eneo.object_content.content import ContentState, StorageKind
from eneo.object_content.content_service import ObjectContentService
from eneo.skills.domain.skill import SkillBindingReference
from eneo.skills.infrastructure.skill_repo_impl import SkillRepoImpl


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


@dataclass(frozen=True)
class _AppFleetSeed:
    skill_id: UUID
    space_id: UUID
    old_revision_id: UUID
    published_revision_id: UUID
    app_ids: tuple[UUID, ...]


async def _add_file_content(
    session,
    *,
    file: Files,
    user_id: UUID,
    payload: bytes,
    variant: FileContentVariant,
    media_type: str,
    state: ContentState = ContentState.AVAILABLE,
) -> UUID:
    digest = sha256(payload).digest()
    storage_kind = (
        StorageKind.POSTGRES_INLINE
        if state is ContentState.AVAILABLE
        else StorageKind.OBJECT_STORE
    )
    content = ObjectContents(
        tenant_id=file.tenant_id,
        created_by_user_id=user_id,
        storage_kind=storage_kind.value,
        state=state.value,
        access_class="private_resource",
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type=media_type,
        verified_media_type=media_type,
        idempotency_key=f"app-fleet-file-{uuid4().hex}",
        request_fingerprint=digest,
        available_at=datetime.now(UTC) if state is ContentState.AVAILABLE else None,
    )
    session.add(content)
    await session.flush()
    stored_payload = (
        InlineContentPayloads(
            content_id=content.id,
            storage_kind=StorageKind.POSTGRES_INLINE.value,
            payload=payload,
        )
        if storage_kind is StorageKind.POSTGRES_INLINE
        else ObjectStoreObjects(
            content_id=content.id,
            storage_kind=StorageKind.OBJECT_STORE.value,
            object_key=f"app-fleet-pending/{uuid4().hex}",
            verification_chunk_size_bytes=len(payload),
            verification_chunk_sha256=digest,
        )
    )
    session.add_all(
        [
            stored_payload,
            FileContentReferences(
                content_id=content.id,
                file_id=file.id,
                variant=variant.value,
                ordinal=0,
            ),
        ]
    )
    await session.flush()
    return content.id


async def _seed_behind_apps(
    container,
    *,
    admin_user,
    completion_model_factory,
    space_factory,
    app_factory,
    size: int = 2,
    max_input_tokens: int = 8_000,
    reviewed_instructions: str = "Use the reviewed App instructions.",
    vision: bool = False,
) -> _AppFleetSeed:
    session = container.session()
    model = await completion_model_factory(
        session,
        f"app-fleet-{uuid4().hex[:8]}",
        max_input_tokens=max_input_tokens,
        vision=vision,
    )
    space = await space_factory(
        session,
        f"App fleet {uuid4().hex[:8]}",
        [model.id],
    )
    session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
    apps = [
        await app_factory(
            session,
            f"App fleet target {index}",
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
        slug=f"app-fleet-{uuid4().hex[:8]}",
        display_name="App fleet",
        description="App fleet advance HTTP contract",
        instructions="Use the original App instructions.",
        content_digest="1" * 64,
        created_by_user_id=admin_user.id,
    )
    old_revision = skill.current_revision
    await repo.publish_organization(
        tenant_id=admin_user.tenant_id,
        skill_id=skill.id,
        expected_revision_id=old_revision.id,
    )
    reference = SkillBindingReference(
        skill_id=skill.id,
        skill_revision_id=old_revision.id,
    )
    for app in apps:
        await container.skill_service().replace_app_bindings(
            space_id=space.id,
            app_id=app.id,
            references=[reference],
        )
    change = await repo.create_revision(
        skill_id=skill.id,
        display_name="App fleet",
        description="App fleet advance HTTP contract",
        instructions=reviewed_instructions,
        content_digest="2" * 64,
        created_by_user_id=admin_user.id,
    )
    assert change is not None
    await repo.publish_organization(
        tenant_id=admin_user.tenant_id,
        skill_id=skill.id,
        expected_revision_id=change.revision.id,
    )
    return _AppFleetSeed(
        skill_id=skill.id,
        space_id=space.id,
        old_revision_id=old_revision.id,
        published_revision_id=change.revision.id,
        app_ids=tuple(app.id for app in apps),
    )


async def _advance_with_statement_count(
    *,
    client,
    admin_token: str,
    db_container,
    skill_id: UUID,
    published_revision_id: UUID,
    cursor: str | None = None,
):
    async with db_container() as container:
        bind = container.session().get_bind()
        engine = getattr(bind, "engine", bind)
        statement_count = 0

        def count_statement(
            _connection: object,
            _cursor: object,
            _statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            nonlocal statement_count
            statement_count += 1

        sa.event.listen(engine, "before_cursor_execute", count_statement)
        try:
            response = await client.post(
                f"/api/v1/skills/organization/{skill_id}/apps/advance/",
                json={
                    "expected_published_revision_id": str(published_revision_id),
                    "cursor": cursor,
                },
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        finally:
            sa.event.remove(engine, "before_cursor_execute", count_statement)
    return response, statement_count


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunk_advances_apps_while_retained_run_provenance_stays_exact(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
        )
        queued_composition = await container.skill_service().compose_for_app(
            app_id=seed.app_ids[0],
            base_instructions="App prompt",
        )
        queued_provenance = queued_composition.provenance
        assert queued_provenance[0].skill_revision_id == seed.old_revision_id

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
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
        {"app_id": str(app_id), "outcome": "advanced", "reason": None}
        for app_id in sorted(seed.app_ids)
    ]

    async with db_container() as container:
        pinned_revisions = list(
            await container.session().scalars(
                sa.select(AppSkillBindings.skill_revision_id)
                .where(AppSkillBindings.app_id.in_(seed.app_ids))
                .order_by(AppSkillBindings.app_id)
            )
        )
        assert pinned_revisions == [seed.published_revision_id] * 2

        new_run = await container.skill_service().compose_for_app(
            app_id=seed.app_ids[0],
            base_instructions="App prompt",
        )
        retained_run = await container.skill_service().compose_for_execution_snapshot(
            tenant_id=admin_user.tenant_id,
            space_id=seed.space_id,
            provenance=queued_provenance,
            base_instructions="App prompt",
        )
        audit_metadata = list(
            await container.session().scalars(
                sa.select(AuditLog.log_metadata).where(
                    AuditLog.entity_id == seed.skill_id,
                    AuditLog.action == ActionType.SKILL_BINDINGS_ADVANCED.value,
                )
            )
        )

    assert new_run.provenance[0].skill_revision_id == seed.published_revision_id
    assert "reviewed App instructions" in new_run.prompt
    assert retained_run.provenance == queued_provenance
    assert "original App instructions" in retained_run.prompt
    assert len(audit_metadata) == 1
    assert audit_metadata[0]["changes"] == {
        "advanced": 2,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    assert audit_metadata[0]["extra"]["surface"] == "app"
    assert "instructions" not in str(audit_metadata[0])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queued_run_keeps_old_provenance_while_fleet_advance_waits(
    monkeypatch,
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
        )

    queue_composed = asyncio.Event()
    fleet_parent_locked = asyncio.Event()
    run_persisted = asyncio.Event()
    original_lock_skill = SkillRepoImpl._lock_organization_skill

    async def hold_fleet_after_parent_lock(repo, **kwargs):
        fleet_parent_locked.set()
        await run_persisted.wait()
        return await original_lock_skill(repo, **kwargs)

    monkeypatch.setattr(
        SkillRepoImpl,
        "_lock_organization_skill",
        hold_fleet_after_parent_lock,
    )

    async def queue_run():
        async with db_container() as container:
            completion_model_id = await container.session().scalar(
                sa.select(Apps.completion_model_id).where(Apps.id == seed.app_ids[0])
            )
            assert completion_model_id is not None
            composition = await container.skill_service().compose_for_app(
                app_id=seed.app_ids[0],
                base_instructions="App prompt",
            )
            assert composition.provenance[0].skill_revision_id == seed.old_revision_id
            queue_composed.set()
            await fleet_parent_locked.wait()

            app_run_id = uuid4()
            container.session().add(
                AppRuns(
                    id=app_run_id,
                    tenant_id=admin_user.tenant_id,
                    user_id=admin_user.id,
                    app_id=seed.app_ids[0],
                    completion_model_id=completion_model_id,
                    skill_provenance=_serialize_skill_provenance(
                        composition.provenance
                    ),
                )
            )
            await container.session().flush()
            run_persisted.set()
            return app_run_id, composition.provenance

    queue_task = asyncio.create_task(queue_run())
    await asyncio.wait_for(queue_composed.wait(), timeout=5)
    fleet_task = asyncio.create_task(
        client.post(
            f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
            json={"expected_published_revision_id": str(seed.published_revision_id)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )

    response, queued_run = await asyncio.wait_for(
        asyncio.gather(fleet_task, queue_task),
        timeout=10,
    )
    app_run_id, queued_provenance = queued_run

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    async with db_container() as container:
        persisted_provenance = await container.session().scalar(
            sa.select(AppRuns.skill_provenance).where(AppRuns.id == app_run_id)
        )
        pin = await container.session().scalar(
            sa.select(AppSkillBindings.skill_revision_id).where(
                AppSkillBindings.app_id == seed.app_ids[0],
                AppSkillBindings.skill_id == seed.skill_id,
            )
        )

    assert persisted_provenance == _serialize_skill_provenance(queued_provenance)
    assert pin == seed.published_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recovery_audit_uses_the_applied_revision_name(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
        )
        draft = await container.skill_repo().create_revision(
            skill_id=seed.skill_id,
            display_name="Renamed draft",
            description="A draft newer than the published App revision",
            instructions="Use the renamed draft instructions.",
            content_digest="3" * 64,
            created_by_user_id=admin_user.id,
        )
        assert draft is not None

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
        json={"expected_published_revision_id": str(seed.published_revision_id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    async with db_container() as container:
        description = await container.session().scalar(
            sa.select(AuditLog.description).where(
                AuditLog.entity_id == seed.skill_id,
                AuditLog.action == ActionType.SKILL_BINDINGS_ADVANCED.value,
            )
        )
    assert description == (
        "Moved App bindings of Skill 'App fleet' to published revision 2"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_app_fleet_is_admin_only(
    client,
    regular_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
        )

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
        json={"expected_published_revision_id": str(seed.published_revision_id)},
        headers={"Authorization": f"Bearer {regular_token}"},
    )

    assert response.status_code == 403, response.text
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AppSkillBindings.skill_revision_id).where(
                AppSkillBindings.app_id == seed.app_ids[0],
                AppSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_oversized_candidate_keeps_the_app_pin_unchanged(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
            max_input_tokens=32,
            reviewed_instructions="oversized " * 2_000,
        )

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
        json={"expected_published_revision_id": str(seed.published_revision_id)},
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
            "app_id": str(seed.app_ids[0]),
            "outcome": "incompatible",
            "reason": "context_window",
        }
    ]
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AppSkillBindings.skill_revision_id).where(
                AppSkillBindings.app_id == seed.app_ids[0],
                AppSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pending_derived_image_retries_before_context_validation(
    monkeypatch,
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
            max_input_tokens=2_000,
            reviewed_instructions="overflow " * 700,
            vision=True,
        )
        session = container.session()
        root = Files(
            name="app-document.txt",
            mimetype="text/plain",
            file_type=FileType.TEXT.value,
            tenant_id=admin_user.tenant_id,
            owner_type="user",
            owner_user_id=admin_user.id,
        )
        session.add(root)
        await session.flush()
        derived = Files(
            name="app-page.png",
            mimetype="image/png",
            file_type=FileType.IMAGE.value,
            tenant_id=admin_user.tenant_id,
            owner_type="user",
            owner_user_id=admin_user.id,
            parent_file_id=root.id,
        )
        session.add(derived)
        await session.flush()
        await _add_file_content(
            session,
            file=root,
            user_id=admin_user.id,
            payload=b"short App attachment",
            variant=FileContentVariant.ORIGINAL,
            media_type="text/plain",
        )
        image = BytesIO()
        Image.new("RGB", (2_048, 1_024), color=(24, 95, 180)).save(
            image,
            format="PNG",
        )
        derived_payload = image.getvalue()
        derived_content_id = await _add_file_content(
            session,
            file=derived,
            user_id=admin_user.id,
            payload=derived_payload,
            variant=FileContentVariant.DERIVED_PAGE,
            media_type="image/png",
            state=ContentState.PENDING,
        )
        session.add(AppsFiles(app_id=seed.app_ids[0], file_id=root.id))

    original_read_content_bytes = ObjectContentService.read_content_bytes

    async def read_completed_derivative(service, grants):
        grants = tuple(grants)
        other_grants = tuple(
            grant for grant in grants if grant.content_id != derived_content_id
        )
        payloads = (
            await original_read_content_bytes(service, other_grants)
            if other_grants
            else {}
        )
        if any(grant.content_id == derived_content_id for grant in grants):
            payloads[derived_content_id] = derived_payload
        return payloads

    monkeypatch.setattr(
        ObjectContentService,
        "read_content_bytes",
        read_completed_derivative,
    )

    headers = {"Authorization": f"Bearer {admin_token}"}
    request = {
        "expected_published_revision_id": str(seed.published_revision_id),
    }
    pending = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
        json=request,
        headers=headers,
    )

    assert pending.status_code == 200, pending.text
    assert pending.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 1,
        "incompatible": 0,
    }

    async with db_container() as container:
        await container.session().execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id == derived_content_id)
            .values(
                state=ContentState.AVAILABLE.value,
                available_at=datetime.now(UTC),
            )
        )

    available = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
        json=request,
        headers=headers,
    )

    assert available.status_code == 200, available.text
    assert available.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 0,
        "incompatible": 1,
    }
    assert available.json()["outcomes"] == [
        {
            "app_id": str(seed.app_ids[0]),
            "outcome": "incompatible",
            "reason": "context_window",
        }
    ]
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AppSkillBindings.skill_revision_id).where(
                AppSkillBindings.app_id == seed.app_ids[0],
                AppSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


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
async def test_terminal_skill_changes_refuse_the_app_chunk(
    terminal_state,
    expected_code,
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
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
                display_name="App fleet",
                description="A third published revision",
                instructions="Use a third set of App instructions.",
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
            await repo.block_organization_skill(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                blocked_by_user_id=admin_user.id,
                reason="Confirmed unsafe instructions",
            )

    response = await client.post(
        f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
        json={"expected_published_revision_id": str(seed.published_revision_id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code in (400, 409), response.text
    assert response.json()["eneo_error_code"] == expected_code
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AppSkillBindings.skill_revision_id).where(
                AppSkillBindings.app_id == seed.app_ids[0],
                AppSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_input_tokens", "reviewed_instructions"),
    [
        (8_000, "Use the reviewed App instructions."),
        (32, "oversized " * 2_000),
    ],
    ids=["compatible", "staged-context-window"],
)
async def test_concurrent_app_edit_supersedes_the_staged_validation_result(
    max_input_tokens,
    reviewed_instructions,
    monkeypatch,
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
            max_input_tokens=max_input_tokens,
            reviewed_instructions=reviewed_instructions,
        )

    validation_finished = asyncio.Event()
    app_changed = asyncio.Event()
    original_apply = SkillRepoImpl.advance_app_skill_pins

    async def apply_after_app_change(repo, **kwargs):
        validation_finished.set()
        await app_changed.wait()
        return await original_apply(repo, **kwargs)

    monkeypatch.setattr(
        SkillRepoImpl,
        "advance_app_skill_pins",
        apply_after_app_change,
    )
    request = asyncio.create_task(
        client.post(
            f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
            json={"expected_published_revision_id": str(seed.published_revision_id)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )
    await asyncio.wait_for(validation_finished.wait(), timeout=5)
    async with db_container() as editor:
        await editor.skill_service().replace_app_bindings(
            space_id=seed.space_id,
            app_id=seed.app_ids[0],
            references=[
                SkillBindingReference(
                    skill_id=seed.skill_id,
                    skill_revision_id=seed.old_revision_id,
                )
            ],
        )
    app_changed.set()
    response = await request

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 1,
        "incompatible": 0,
    }
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AppSkillBindings.skill_revision_id).where(
                AppSkillBindings.app_id == seed.app_ids[0],
                AppSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_editor_first_app_update_and_fleet_apply_do_not_deadlock(
    monkeypatch,
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
        )

    editor_locked = asyncio.Event()
    fleet_started = asyncio.Event()
    original_get_for_update = AppRepository.get_for_update
    original_apply = SkillRepoImpl.advance_app_skill_pins

    async def hold_editor_parent_lock(repo, app_id):
        locked_app = await original_get_for_update(repo, app_id)
        if app_id == seed.app_ids[0]:
            editor_locked.set()
            await fleet_started.wait()
        return locked_app

    async def note_fleet_start(repo, **kwargs):
        fleet_started.set()
        return await original_apply(repo, **kwargs)

    monkeypatch.setattr(AppRepository, "get_for_update", hold_editor_parent_lock)
    monkeypatch.setattr(SkillRepoImpl, "advance_app_skill_pins", note_fleet_start)

    async def edit_app():
        async with db_container() as editor:
            return await editor.app_service().update_app(
                app_id=seed.app_ids[0],
                prompt_text="Edited while the fleet update was staged.",
            )

    editor_request = asyncio.create_task(edit_app())
    await asyncio.wait_for(editor_locked.wait(), timeout=5)
    fleet_request = asyncio.create_task(
        client.post(
            f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
            json={"expected_published_revision_id": str(seed.published_revision_id)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )
    _, response = await asyncio.wait_for(
        asyncio.gather(editor_request, fleet_request),
        timeout=10,
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 0,
        "concurrent_change": 1,
        "incompatible": 0,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fleet_first_app_apply_and_publish_do_not_deadlock(
    monkeypatch,
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
        )

    fleet_applied = asyncio.Event()
    editor_started = asyncio.Event()
    original_get_for_update = AppRepository.get_for_update
    original_apply = SkillRepoImpl.advance_app_skill_pins

    async def hold_fleet_locks(repo, **kwargs):
        results = await original_apply(repo, **kwargs)
        fleet_applied.set()
        await editor_started.wait()
        return results

    async def note_editor_start(repo, app_id):
        if app_id == seed.app_ids[0]:
            editor_started.set()
        return await original_get_for_update(repo, app_id)

    monkeypatch.setattr(SkillRepoImpl, "advance_app_skill_pins", hold_fleet_locks)
    monkeypatch.setattr(AppRepository, "get_for_update", note_editor_start)

    fleet_request = asyncio.create_task(
        client.post(
            f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
            json={"expected_published_revision_id": str(seed.published_revision_id)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )
    await asyncio.wait_for(fleet_applied.wait(), timeout=5)

    async def publish_app():
        async with db_container() as editor:
            return await editor.app_service().publish_app(seed.app_ids[0], True)

    publish_request = asyncio.create_task(publish_app())
    response, _ = await asyncio.wait_for(
        asyncio.gather(fleet_request, publish_request),
        timeout=10,
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {
        "advanced": 1,
        "concurrent_change": 0,
        "incompatible": 0,
    }
    async with db_container() as container:
        pin, published = (
            await container.session().execute(
                sa.select(AppSkillBindings.skill_revision_id, Apps.published)
                .join(Apps, Apps.id == AppSkillBindings.app_id)
                .where(
                    AppSkillBindings.app_id == seed.app_ids[0],
                    AppSkillBindings.skill_id == seed.skill_id,
                )
            )
        ).one()
    assert pin == seed.published_revision_id
    assert published is True


@pytest.mark.parametrize(
    ("terminal_state", "expected_code"),
    [("unpublished", 9053), ("blocked", 9054)],
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_skill_lifecycle_change_after_validation_aborts_the_app_chunk(
    terminal_state,
    expected_code,
    monkeypatch,
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=1,
        )

    validation_finished = asyncio.Event()
    skill_changed = asyncio.Event()
    original_apply = SkillRepoImpl.advance_app_skill_pins

    async def apply_after_skill_change(repo, **kwargs):
        validation_finished.set()
        await skill_changed.wait()
        return await original_apply(repo, **kwargs)

    monkeypatch.setattr(
        SkillRepoImpl,
        "advance_app_skill_pins",
        apply_after_skill_change,
    )
    request = asyncio.create_task(
        client.post(
            f"/api/v1/skills/organization/{seed.skill_id}/apps/advance/",
            json={"expected_published_revision_id": str(seed.published_revision_id)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )
    await asyncio.wait_for(validation_finished.wait(), timeout=5)
    async with db_container() as editor:
        if terminal_state == "unpublished":
            await editor.skill_repo().unpublish_organization(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
            )
        else:
            await editor.skill_repo().block_organization_skill(
                tenant_id=admin_user.tenant_id,
                skill_id=seed.skill_id,
                blocked_by_user_id=admin_user.id,
                reason="Blocked during App rollout validation",
            )
    skill_changed.set()
    response = await request

    assert response.status_code in (400, 409), response.text
    assert response.json()["eneo_error_code"] == expected_code
    async with db_container() as container:
        pin = await container.session().scalar(
            sa.select(AppSkillBindings.skill_revision_id).where(
                AppSkillBindings.app_id == seed.app_ids[0],
                AppSkillBindings.skill_id == seed.skill_id,
            )
        )
    assert pin == seed.old_revision_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cursor_advances_more_than_one_app_chunk_with_chunk_bounded_queries(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        seed = await _seed_behind_apps(
            container,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            app_factory=app_factory,
            size=101,
        )
    first, first_statement_count = await _advance_with_statement_count(
        client=client,
        admin_token=admin_token,
        db_container=db_container,
        skill_id=seed.skill_id,
        published_revision_id=seed.published_revision_id,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["counts"]["advanced"] == 100
    assert len(first_payload["outcomes"]) == 100
    assert first_payload["next_cursor"] is not None

    second, second_statement_count = await _advance_with_statement_count(
        client=client,
        admin_token=admin_token,
        db_container=db_container,
        skill_id=seed.skill_id,
        published_revision_id=seed.published_revision_id,
        cursor=first_payload["next_cursor"],
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
    assert abs(first_statement_count - second_statement_count) <= 1

    async with db_container() as container:
        advanced_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(AppSkillBindings)
            .where(
                AppSkillBindings.skill_id == seed.skill_id,
                AppSkillBindings.skill_revision_id == seed.published_revision_id,
            )
        )
    assert advanced_count == 101

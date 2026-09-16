from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import FlowTemplateAssets
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.files.file_models import FileContentVariant
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from eneo.flows.infrastructure.flow_version_repo import (
    audit_flow_version_template_identity_readiness,
)
from eneo.flows.published_definition import (
    PublishedTemplateIdentityBlockerReason,
    build_published_definition_json,
    published_definition_checksum,
)
from eneo.object_content.content import (
    ContentAccessClass,
    ContentState,
    StorageKind,
)


def _flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Versioned Flow",
        description=None,
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=None,
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Persist version",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
        ],
    )


def _definition_json(
    *,
    flow: Flow,
    step: FlowStep,
    output_config: dict[str, str] | None = None,
    output_mode: str | None = None,
    output_type: str | None = None,
) -> FlowPersistedJsonObject:
    assert flow.id is not None
    assert step.id is not None
    return build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[
            {
                "step_id": str(step.id),
                "assistant_id": str(step.assistant_id),
                "step_order": step.step_order,
                "input_source": step.input_source,
                "input_type": step.input_type,
                "output_mode": output_mode or step.output_mode,
                "output_type": output_type or step.output_type,
                "output_config": output_config,
            }
        ],
    )


async def _create_template_asset(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    flow_id: UUID,
    space_id: UUID,
    user_id: UUID,
    template_bytes: bytes,
    asset_checksum: str,
    deleted: bool,
) -> tuple[UUID, UUID, str]:
    now = datetime.now(timezone.utc)
    content_checksum = sha256(template_bytes).digest()
    template_file = Files(
        name="template.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_type="document",
        owner_type="user",
        owner_user_id=user_id,
        owner_service_id=None,
        tenant_id=tenant_id,
        created_at=now,
        updated_at=now,
    )
    content = ObjectContents(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        storage_kind=StorageKind.POSTGRES_INLINE.value,
        state=ContentState.AVAILABLE.value,
        access_class=ContentAccessClass.PRIVATE_RESOURCE.value,
        sha256=content_checksum,
        size_bytes=len(template_bytes),
        declared_media_type=template_file.mimetype,
        verified_media_type=template_file.mimetype,
        idempotency_key=uuid4().hex,
        request_fingerprint=content_checksum,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add_all([template_file, content])
    await session.flush()
    session.add_all(
        [
            InlineContentPayloads(
                content_id=content.id,
                storage_kind=StorageKind.POSTGRES_INLINE.value,
                payload=template_bytes,
            ),
            FileContentReferences(
                file_id=template_file.id,
                content_id=content.id,
                variant=FileContentVariant.ORIGINAL.value,
                ordinal=0,
            ),
        ]
    )
    await session.flush()

    template_asset = FlowTemplateAssets(
        flow_id=flow_id,
        space_id=space_id,
        tenant_id=tenant_id,
        file_id=template_file.id,
        name=template_file.name,
        checksum=asset_checksum,
        mimetype=template_file.mimetype,
        placeholders=["Body"],
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
        status="ready",
        deleted_at=now if deleted else None,
        created_at=now,
        updated_at=now,
    )
    session.add(template_asset)
    await session.flush()
    return template_asset.id, template_file.id, content_checksum.hex()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("source_revision", [None, 7])
async def test_create_derives_definition_checksum_from_stored_definition(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    source_revision,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow version repository", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow Version Assistant",
            model.id,
            space_id=space.id,
        )
        flow_repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
        flow = await flow_repo.create(
            flow=_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        step = flow.steps[0]
        assert flow.id is not None
        assert step.id is not None
        definition_json = build_published_definition_json(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[
                {
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": step.step_order,
                    "input_source": step.input_source,
                    "input_type": step.input_type,
                    "output_mode": step.output_mode,
                    "output_type": step.output_type,
                }
            ],
        )

        published_at = datetime.now(timezone.utc)
        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json=definition_json,
            tenant_id=admin_user.tenant_id,
            first_published_at=published_at,
            source_draft_revision=source_revision,
        )

        stored_version = await version_repo.get(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
        )

        assert stored_version.first_published_at == published_at
        assert stored_version.source_draft_revision == source_revision
        assert (
            stored_version.model_validate(stored_version.model_dump()) == stored_version
        )
        assert stored_version.definition_checksum == published_definition_checksum(
            definition_json
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_template_asset_reference_check_scans_non_current_versions(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flow version template reference", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow Version Template Assistant",
            model.id,
            space_id=space.id,
        )
        flow_repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
        flow = await flow_repo.create(
            flow=_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        step = flow.steps[0]
        assert flow.id is not None
        template_asset_id = uuid4()
        template_file_id = uuid4()

        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json=_definition_json(
                flow=flow,
                step=step,
                output_config={
                    "template_asset_id": str(template_asset_id),
                    "template_file_id": str(template_file_id),
                },
            ),
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=flow.id,
            version=2,
            definition_json=_definition_json(flow=flow, step=step),
            tenant_id=admin_user.tenant_id,
        )

        assert await version_repo.has_template_asset_reference(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            template_asset_id=template_asset_id,
            template_file_id=template_file_id,
        )
        assert not await version_repo.has_template_asset_reference(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            template_asset_id=uuid4(),
            template_file_id=uuid4(),
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_template_identity_readiness_audit_scans_versions_and_active_assets(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flow version template identity audit", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow Version Template Identity Assistant",
            model.id,
            space_id=space.id,
        )
        flow_repo = FlowRepository(session=session)
        version_repo = FlowVersionRepository(session=session)
        flow = await flow_repo.create(
            flow=_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        step = flow.steps[0]
        assert flow.id is not None
        (
            active_asset_id,
            active_file_id,
            active_content_checksum,
        ) = await _create_template_asset(
            session,
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            space_id=space.id,
            user_id=admin_user.id,
            template_bytes=b"active durable template",
            asset_checksum=sha256(b"stale active checksum").hexdigest(),
            deleted=False,
        )
        (
            deleted_asset_id,
            deleted_file_id,
            deleted_content_checksum,
        ) = await _create_template_asset(
            session,
            tenant_id=admin_user.tenant_id,
            flow_id=flow.id,
            space_id=space.id,
            user_id=admin_user.id,
            template_bytes=b"deleted durable template",
            asset_checksum=sha256(b"stale deleted checksum").hexdigest(),
            deleted=True,
        )

        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json=_definition_json(
                flow=flow,
                step=step,
                output_mode="template_fill",
                output_type="docx",
                output_config={
                    "template_asset_id": str(active_asset_id),
                    "template_file_id": str(active_file_id),
                    "template_checksum": active_content_checksum,
                },
            ),
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=flow.id,
            version=2,
            definition_json=_definition_json(
                flow=flow,
                step=step,
                output_mode="template_fill",
                output_type="docx",
                output_config={
                    "template_asset_id": str(deleted_asset_id),
                    "template_file_id": str(deleted_file_id),
                    "template_checksum": deleted_content_checksum,
                },
            ),
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=flow.id,
            version=3,
            definition_json=_definition_json(flow=flow, step=step),
            tenant_id=admin_user.tenant_id,
        )

        result = await audit_flow_version_template_identity_readiness(session)

        blocker_counts = {item.reason: item.count for item in result.blocker_counts}
        assert result.total_versions == 3
        assert result.template_fill_steps == 2
        assert result.ready_template_fill_steps == 1
        assert result.blocked_template_fill_steps == 1
        assert (
            blocker_counts[PublishedTemplateIdentityBlockerReason.ASSET_NOT_LIVE] == 1
        )
        assert result.samples[0].version == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_snapshot_file_references_are_idempotent_and_protect_files(
    db_container, completion_model_factory, space_factory, admin_user
) -> None:
    import sqlalchemy as sa
    from sqlalchemy.exc import IntegrityError

    from eneo.database.tables.flow_tables import Flows, FlowVersions

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "snapshot-file-model")
        space = await space_factory(session, "Snapshot files", [model.id])
        flow = Flows(
            name="Snapshot files", tenant_id=admin_user.tenant_id, space_id=space.id
        )
        file = Files(
            name="frozen.txt",
            mimetype="text/plain",
            file_type="text",
            owner_type="user",
            owner_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
        )
        session.add_all([flow, file])
        await session.flush()
        repo = FlowVersionRepository(session)
        for version in (1, 2):
            candidate = await repo.create(
                flow_id=flow.id,
                version=version,
                tenant_id=admin_user.tenant_id,
                definition_json={"steps": []},
            )
            assert candidate.first_published_at is None
            assert candidate.source_draft_revision is None
        assert (
            await repo.file_ids_referenced_by_versions(flow.id, admin_user.tenant_id)
            == set()
        )
        for version in (1, 1, 2):
            await repo.add_file_references(
                flow.id, version, admin_user.tenant_id, [file.id, file.id]
            )
        await repo.add_file_references(flow.id, 1, admin_user.tenant_id, [])
        assert await repo.file_ids_referenced_by_versions(
            flow.id, admin_user.tenant_id
        ) == {file.id}
        assert await repo.file_ids_referenced_by_versions(flow.id, uuid4()) == set()
        count = await session.scalar(
            sa.text(
                "SELECT count(*) FROM flow_version_file_references WHERE flow_id = :flow_id"
            ),
            {"flow_id": flow.id},
        )
        assert count == 2
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(sa.delete(Files).where(Files.id == file.id))
        await session.execute(
            sa.delete(FlowVersions).where(
                FlowVersions.flow_id == flow.id, FlowVersions.version == 2
            )
        )
        assert await repo.file_ids_referenced_by_versions(
            flow.id, admin_user.tenant_id
        ) == {file.id}
        await session.execute(
            sa.delete(FlowVersions).where(FlowVersions.flow_id == flow.id)
        )
        assert (
            await repo.file_ids_referenced_by_versions(flow.id, admin_user.tenant_id)
            == set()
        )
        await session.execute(sa.delete(Files).where(Files.id == file.id))


@pytest.mark.asyncio
@pytest.mark.integration
async def test_snapshot_file_references_reject_cross_tenant_file(
    db_container,
    completion_model_factory,
    space_factory,
    tenant_factory,
    user_factory,
    admin_user,
) -> None:
    from sqlalchemy.exc import IntegrityError

    from eneo.database.tables.flow_tables import Flows

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "snapshot-file-tenant-model")
        space = await space_factory(
            session, "Snapshot file tenant isolation", [model.id]
        )
        flow = Flows(
            name="Snapshot file tenant isolation",
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
        )
        other_tenant = await tenant_factory(
            session, name=f"Snapshot file owner {uuid4().hex}"
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        other_file = Files(
            name="other-tenant.txt",
            mimetype="text/plain",
            file_type="text",
            owner_type="user",
            owner_user_id=other_user.id,
            tenant_id=other_tenant.id,
        )
        session.add_all([flow, other_file])
        await session.flush()
        repo = FlowVersionRepository(session)
        await repo.create(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
            definition_json={"steps": []},
        )

        with pytest.raises(
            IntegrityError, match="fk_flow_version_file_references_file_tenant"
        ):
            async with session.begin_nested():
                await repo.add_file_references(
                    flow.id, 1, admin_user.tenant_id, [other_file.id]
                )

        assert (
            await repo.file_ids_referenced_by_versions(flow.id, admin_user.tenant_id)
            == set()
        )

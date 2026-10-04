from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    Flows,
    FlowTemplateAssets,
    FlowVersionFileReferences,
    FlowVersions,
)
from eneo.flows import FlowVersionRepository
from eneo.flows.domain.flow import FlowStep
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeRepository,
)
from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    published_definition_checksum,
)
from tests.integration.flows.test_flow_template_attachment_persistence import (
    _create_flow_and_file,
)


def _definition(
    *,
    asset_id: UUID | None = None,
    template_file_id: UUID | None = None,
    attachment_ids: tuple[UUID, ...] = (),
) -> dict[str, object]:
    output_config: dict[str, str] = {}
    if asset_id is not None:
        output_config["template_asset_id"] = str(asset_id)
    if template_file_id is not None:
        output_config["template_file_id"] = str(template_file_id)
    return {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "steps": [
            {
                "output_config": output_config,
                "assistant_snapshot": {
                    "attachments": [
                        {"file_id": str(file_id), "checksum": "c"}
                        for file_id in attachment_ids
                    ]
                },
            }
        ],
    }


def _file(*, tenant_id: UUID, user_id: UUID, name: str) -> Files:
    return Files(
        name=name,
        mimetype="text/plain",
        file_type="text",
        owner_type="user",
        owner_user_id=user_id,
        tenant_id=tenant_id,
    )


async def _flow_with_files(session, space, admin_user, *, names: tuple[str, ...]):
    flow = Flows(name="Refs", tenant_id=admin_user.tenant_id, space_id=space.id)
    files = [
        _file(tenant_id=admin_user.tenant_id, user_id=admin_user.id, name=name)
        for name in names
    ]
    session.add_all([flow, *files])
    await session.flush()
    return flow, files


async def _references(session, flow_id: UUID) -> set[tuple[int, UUID]]:
    rows = await session.execute(
        sa.select(
            FlowVersionFileReferences.version, FlowVersionFileReferences.file_id
        ).where(FlowVersionFileReferences.flow_id == flow_id)
    )
    return {(version, file_id) for version, file_id in rows.all()}


def _asset(flow: Flows, file: Files, *, deleted: bool = False) -> FlowTemplateAssets:
    return FlowTemplateAssets(
        flow_id=flow.id,
        space_id=flow.space_id,
        tenant_id=flow.tenant_id,
        file_id=file.id,
        name=file.name,
        checksum="sum",
        placeholders=[],
        status="ready",
        deleted_at=sa.func.now() if deleted else None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_records_every_file_the_definition_names(
    db_container, completion_model_factory, space_factory, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "refs-create-model")
        space = await space_factory(session, "Refs create", [model.id])
        flow, (template, direct, attached, unused) = await _flow_with_files(
            session,
            space,
            admin_user,
            names=("t.docx", "d.docx", "a.txt", "unused.txt"),
        )
        asset = _asset(flow, template, deleted=True)
        session.add(asset)
        await session.flush()

        repo = FlowVersionRepository(session)
        await repo.create(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
            definition_json=_definition(
                asset_id=asset.id,
                template_file_id=direct.id,
                attachment_ids=(attached.id, uuid4()),
            ),
        )

        assert await _references(session, flow.id) == {
            (1, template.id),
            (1, direct.id),
            (1, attached.id),
        }
        assert unused.id not in await repo.file_ids_referenced_by_versions(
            flow.id, admin_user.tenant_id
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_without_file_references_writes_nothing(
    db_container, completion_model_factory, space_factory, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "refs-none-model")
        space = await space_factory(session, "Refs none", [model.id])
        flow, _ = await _flow_with_files(session, space, admin_user, names=())

        await FlowVersionRepository(session).create(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
            definition_json=_definition(),
        )

        assert await _references(session, flow.id) == set()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_references_skip_missing_foreign_tenant_and_other_flow_ids(
    db_container,
    completion_model_factory,
    space_factory,
    tenant_factory,
    user_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "refs-skip-model")
        space = await space_factory(session, "Refs skip", [model.id])
        flow, (own, other_flow_file) = await _flow_with_files(
            session, space, admin_user, names=("own.txt", "other-flow.docx")
        )
        other_flow = Flows(
            name="Other", tenant_id=admin_user.tenant_id, space_id=space.id
        )
        session.add(other_flow)
        await session.flush()
        other_flow_asset = _asset(other_flow, other_flow_file)
        session.add(other_flow_asset)
        other_tenant = await tenant_factory(session, name=f"refs-{uuid4().hex}")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        foreign = _file(tenant_id=other_tenant.id, user_id=other_user.id, name="f.txt")
        session.add(foreign)
        await session.flush()

        repo = FlowVersionRepository(session)
        await repo.create(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
            definition_json=_definition(
                asset_id=other_flow_asset.id,
                attachment_ids=(own.id, foreign.id, uuid4()),
            ),
        )

        assert await _references(session, flow.id) == {(1, own.id)}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_record_file_references_is_idempotent_and_counts_missing(
    db_container, completion_model_factory, space_factory, admin_user
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "refs-idem-model")
        space = await space_factory(session, "Refs idem", [model.id])
        flow, (file,) = await _flow_with_files(
            session, space, admin_user, names=("a.txt",)
        )
        repo = FlowVersionRepository(session)
        definition = _definition(attachment_ids=(file.id, uuid4(), uuid4()))
        await repo.create(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
            definition_json=definition,
        )

        for _ in range(2):
            skipped = await repo.record_file_references(
                flow_id=flow.id,
                version=1,
                tenant_id=admin_user.tenant_id,
                definition_json=definition,
            )
            assert skipped == 2

        assert await _references(session, flow.id) == {(1, file.id)}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_publish_records_the_template_file_and_purge_keeps_it_while_the_version_exists(
    db_container,
) -> None:
    async with db_container() as setup_container:
        user, _space, flow, file = await _create_flow_and_file(
            setup_container, placeholder="case_id"
        )

    async with db_container(user=user) as container:
        session = container.session()
        service = container.flow_service()
        asset = await container.flow_template_asset_service().create_from_existing_attached_file(
            flow_id=flow.id, file_id=file.id
        )
        assistant, _ = await service.create_flow_assistant(flow_id=flow.id, name="fill")
        updated = await service.update_flow(
            flow_id=flow.id,
            metadata_json={
                "form_schema": {"fields": [{"name": "case_id", "type": "text"}]}
            },
            steps=[
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="Fill",
                    input_source="flow_input",
                    input_type="text",
                    output_mode="template_fill",
                    output_type="docx",
                    output_config={
                        "template_asset_id": str(asset.id),
                        "bindings": {"case_id": "{{ flow_input.case_id }}"},
                    },
                )
            ],
        )

        await service.publish_flow(flow_id=updated.id)
        assert await _references(session, flow.id) == {(1, file.id)}

        # A second publish of the same definition adds its own version's row only.
        await service.publish_flow(flow_id=updated.id)
        assert await _references(session, flow.id) == {(1, file.id), (2, file.id)}

        # The asset row is gone, so only the version references still protect it.
        await session.execute(
            sa.delete(FlowTemplateAssets).where(FlowTemplateAssets.id == asset.id)
        )
        purge = FlowRunHistoryPurgeRepository(session)
        assert await purge._delete_unreferenced_files({file.id}) == set()

        await session.execute(
            sa.update(Flows).where(Flows.id == flow.id).values(published_version=None)
        )
        await session.execute(
            sa.delete(FlowVersions).where(FlowVersions.flow_id == flow.id)
        )
        assert await purge._delete_unreferenced_files({file.id}) == {file.id}


def _batches(connection, *, fail_on: int | None = None):
    """A savepoint per batch on the test connection, standing in for the
    committed transaction each batch gets in a real run."""
    batch = 0

    @contextmanager
    def begin() -> Iterator:
        nonlocal batch
        batch += 1
        with connection.begin_nested():
            yield connection
            if batch == fail_on:
                raise RuntimeError("interrupted")

    return begin


def _backfill_module():
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202610021015_backfill_flow_version_file_references.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_flow_version_refs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.integration
async def test_backfill_gives_existing_versions_the_references_the_writer_records(
    db_container,
    completion_model_factory,
    space_factory,
    tenant_factory,
    user_factory,
    admin_user,
) -> None:
    migration = _backfill_module()
    assert migration.down_revision == "202610021030"

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "refs-backfill-model")
        space = await space_factory(session, "Refs backfill", [model.id])
        flow, (template, attached) = await _flow_with_files(
            session, space, admin_user, names=("t.docx", "a.txt")
        )
        second = Flows(name="Second", tenant_id=admin_user.tenant_id, space_id=space.id)
        session.add(second)
        other_tenant = await tenant_factory(session, name=f"refs-{uuid4().hex}")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        foreign = _file(tenant_id=other_tenant.id, user_id=other_user.id, name="f.txt")
        second_file = _file(
            tenant_id=admin_user.tenant_id, user_id=admin_user.id, name="s.docx"
        )
        session.add_all([foreign, second_file])
        await session.flush()
        asset = _asset(flow, template)
        second_asset = _asset(second, second_file)
        session.add_all([asset, second_asset])
        await session.flush()
        flows = (flow, second)
        definitions = {
            (flow.id, 1): _definition(
                asset_id=asset.id, attachment_ids=(attached.id, uuid4())
            ),
            (flow.id, 2): _definition(),
            (flow.id, 3): {
                "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
                "steps": None,
            },
            (flow.id, 4): {"schema_version": 99, "steps": []},
            # Another flow's asset and a foreign-tenant file name nothing here.
            (flow.id, 5): _definition(
                asset_id=second_asset.id, attachment_ids=(foreign.id, attached.id)
            ),
            (second.id, 1): _definition(
                asset_id=second_asset.id, attachment_ids=(attached.id,)
            ),
            (second.id, 2): _definition(asset_id=asset.id),
        }
        for (flow_id, version), definition in definitions.items():
            session.add(
                FlowVersions(
                    flow_id=flow_id,
                    version=version,
                    tenant_id=admin_user.tenant_id,
                    definition_json=definition,
                    definition_checksum=published_definition_checksum(definition),
                )
            )
        await session.flush()

        # What the writer records for the same definitions is the reference.
        repo = FlowVersionRepository(session)
        for (flow_id, version), definition in definitions.items():
            await repo.record_file_references(
                flow_id=flow_id,
                version=version,
                tenant_id=admin_user.tenant_id,
                definition_json=definition,
            )
        by_writer = {
            (item.id, row)
            for item in flows
            for row in await _references(session, item.id)
        }
        assert by_writer == {
            (flow.id, (1, template.id)),
            (flow.id, (1, attached.id)),
            (flow.id, (5, attached.id)),
            (second.id, (1, second_file.id)),
            (second.id, (1, attached.id)),
        }
        await session.execute(
            sa.delete(FlowVersionFileReferences).where(
                FlowVersionFileReferences.flow_id.in_([flow.id, second.id])
            )
        )
        assert await _references(session, flow.id) == set()

        # A run interrupted in its last batch (one version per batch, in key
        # order) keeps exactly the references of every batch before it.
        connection = await session.connection()
        keys = (
            await session.execute(
                sa.select(FlowVersions.flow_id, FlowVersions.version).order_by(
                    FlowVersions.flow_id, FlowVersions.version
                )
            )
        ).all()
        last_flow_id, last_version = keys[-1]
        with pytest.raises(RuntimeError, match="interrupted"):
            await connection.run_sync(
                lambda sync: migration.backfill_flow_version_file_references(
                    _batches(sync, fail_on=len(keys)), batch_size=1
                )
            )
        partial = {
            (item.id, row)
            for item in flows
            for row in await _references(session, item.id)
        }
        assert partial == {
            (flow_id, row)
            for flow_id, row in by_writer
            if (flow_id, row[0]) != (last_flow_id, last_version)
        }

        first = await connection.run_sync(
            lambda sync: migration.backfill_flow_version_file_references(
                _batches(sync), batch_size=2
            )
        )
        by_migration = {
            (item.id, row)
            for item in flows
            for row in await _references(session, item.id)
        }
        assert by_migration == by_writer
        assert first.skipped_missing >= 3
        assert first.versions_scanned >= len(definitions)

        await connection.run_sync(
            lambda sync: migration.backfill_flow_version_file_references(
                _batches(sync), batch_size=2
            )
        )
        assert {
            (item.id, row)
            for item in flows
            for row in await _references(session, item.id)
        } == by_writer

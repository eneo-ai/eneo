"""Full SharePoint syncs over a local folder, end to end through the publish path.

The Graph client is replaced by a directory walk; everything after the bytes
arrive is production code: byte retention for tabular files, the per-source
tabular policy, versioning of originals, and the quota fallback.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from openpyxl import load_workbook

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.object_content_table import (
    InfoBlobContentReferences,
    ObjectContents,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.domain.tabular_policy import TabularPolicy
from eneo.object_content.content import ContentState
from tests.integration.fixtures.sharepoint_local_client import (
    FIXTURE_DRIVE_ID,
    FIXTURE_ROOT_ID,
    FIXTURE_WEB_ORIGIN,
    LocalFolderSharePointClient,
)

FIXTURE_FILES = Path(__file__).resolve().parent.parent / "fixtures" / "files"
CLIENT_PATH = (
    "eneo.integration.infrastructure.content_service."
    "sharepoint_content_service.SharePointContentClient"
)


def _embedding_result(*, model, chunks):
    result = ChunkEmbeddingList()
    result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
    return result


async def _seed_source(container, *, policy: TabularPolicy) -> UUID:
    session = container.session()
    user = container.user()
    space = await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == user.tenant_id, Spaces.user_id == user.id
        )
    )
    if space is None:
        space = Spaces(
            name=f"local sync {uuid4().hex}", tenant_id=user.tenant_id, user_id=user.id
        )
        session.add(space)
        await session.flush()
    model_row = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    embedding_model = await container.embedding_model_repo2().one(model_id=model_row.id)

    integration = await container.integration_repo().add(
        Integration(
            name="SharePoint", description="fixture", integration_type="sharepoint"
        )
    )
    tenant_integration = await container.tenant_integration_repo().add(
        TenantIntegration(tenant_id=user.tenant_id, integration=integration)
    )
    user_integration = await container.user_integration_repo().add(
        UserIntegration(
            tenant_integration=tenant_integration, user_id=user.id, authenticated=True
        )
    )
    knowledge = await container.integration_knowledge_repo().add(
        obj=IntegrationKnowledge(
            name="Local folder",
            user_integration=user_integration,
            embedding_model=embedding_model,
            tenant_id=user.tenant_id,
            space_id=space.id,
            url=FIXTURE_WEB_ORIGIN,
            drive_id=FIXTURE_DRIVE_ID,
            folder_id=FIXTURE_ROOT_ID,
            resource_type="onedrive",
            selected_item_type="folder",
            tabular_policy=policy,
        )
    )
    return knowledge.id


async def _sync(container, monkeypatch, *, knowledge_id: UUID, folder: Path):
    embeddings = AsyncMock()
    embeddings.get_embeddings.side_effect = _embedding_result
    container.create_embeddings_service.override(providers.Object(embeddings))
    monkeypatch.setattr(
        CLIENT_PATH, lambda **kwargs: LocalFolderSharePointClient(root=folder, **kwargs)
    )
    service = container.sharepoint_content_service()
    service.oauth_token_repo.one = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            id=uuid4(),
            access_token="fixture",
            base_url=FIXTURE_WEB_ORIGIN,
            is_sharepoint=True,
        )
    )
    await service.pull_content(
        token_id=uuid4(),
        integration_knowledge_id=knowledge_id,
        drive_id=FIXTURE_DRIVE_ID,
        folder_id=FIXTURE_ROOT_ID,
        resource_type="onedrive",
    )
    # What the sync recorded about itself: counts and per-file notes.
    (log,) = await container.sync_log_repo().get_by_integration_knowledge(
        knowledge_id, tenant_id=container.user().tenant_id, limit=1
    )
    return log.metadata or {}


async def _documents(session, knowledge_id: UUID) -> dict[str, list[InfoBlobs]]:
    rows = (
        await session.scalars(
            sa.select(InfoBlobs)
            .where(InfoBlobs.integration_knowledge_id == knowledge_id)
            .order_by(InfoBlobs.created_at, InfoBlobs.id)
        )
    ).all()
    by_title: dict[str, list[InfoBlobs]] = {}
    for row in rows:
        by_title.setdefault(row.title or "", []).append(row)
    return by_title


async def _active(session, knowledge_id: UUID, title: str) -> InfoBlobs:
    versions = (await _documents(session, knowledge_id))[title]
    (active,) = [
        v for v in versions if v.version_state == InfoBlobVersionState.ACTIVE.value
    ]
    return active


async def _chunk_count(session, blob_id: UUID) -> int:
    return (
        await session.scalar(
            sa.select(sa.func.count()).where(InfoBlobChunks.info_blob_id == blob_id)
        )
        or 0
    )


def _append_row(workbook_path: Path) -> None:
    workbook = load_workbook(workbook_path)
    workbook["Sales"].append(["2026-04", "North", 200])
    workbook.save(workbook_path)


@pytest.mark.integration
async def test_tabular_originals_follow_the_document_through_syncs(
    db_container, tmp_path, monkeypatch
):
    folder = tmp_path / "drive"
    folder.mkdir()
    shutil.copy(FIXTURE_FILES / "sales.xlsx", folder / "sales.xlsx")
    (folder / "notes.txt").write_text("Minutes from the budget meeting.\n")

    async with db_container() as container:
        knowledge_id = await _seed_source(
            container, policy=TabularPolicy.INDEX_AND_TOOL
        )

    # First sync: the spreadsheet is indexed and keeps its bytes; prose keeps none.
    async with db_container() as container:
        stats = await _sync(
            container, monkeypatch, knowledge_id=knowledge_id, folder=folder
        )
        assert stats["files_processed"] == 2, stats
        session = container.session()
        repo = InfoBlobRepository(session)
        sheet = await _active(session, knowledge_id, "sales.xlsx")
        notes = await _active(session, knowledge_id, "notes.txt")
        original = await repo.get_original(sheet.id)
        assert original is not None and original.usable
        assert original.original_filename == "sales.xlsx"
        assert original.media_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert await _chunk_count(session, sheet.id) > 0
        assert await repo.get_original(notes.id) is None
        first_sheet_id, first_content_id = sheet.id, original.content_id

    # Unchanged files: no new version, no new bytes.
    async with db_container() as container:
        await _sync(container, monkeypatch, knowledge_id=knowledge_id, folder=folder)
        session = container.session()
        assert len((await _documents(session, knowledge_id))["sales.xlsx"]) == 1
        original = await InfoBlobRepository(session).get_original(first_sheet_id)
        assert original is not None and original.content_id == first_content_id

    # A changed workbook: a new active version holds the new bytes, the
    # superseded version keeps its text but releases its bytes.
    _append_row(folder / "sales.xlsx")
    async with db_container() as container:
        await _sync(container, monkeypatch, knowledge_id=knowledge_id, folder=folder)
        session = container.session()
        repo = InfoBlobRepository(session)
        versions = (await _documents(session, knowledge_id))["sales.xlsx"]
        assert [v.version_state for v in versions] == ["superseded", "active"]
        assert versions[0].id == first_sheet_id
        assert await repo.get_original(first_sheet_id) is None
        current = await repo.get_original(versions[1].id)
        assert current is not None and current.content_id != first_content_id
        state, reference_count = (
            await session.execute(
                sa.select(ObjectContents.state, ObjectContents.reference_count).where(
                    ObjectContents.id == first_content_id
                )
            )
        ).one()
        assert (state, reference_count) == (ContentState.DELETE_PENDING.value, 0)
        assert versions[0].text  # text history stays
        second_content_id = current.content_id

    # Tools only: the next sync republishes the sheet as a schema stub without
    # chunks, sharing the unchanged bytes instead of storing a copy.
    async with db_container() as container:
        knowledge = await container.integration_knowledge_repo().one(id=knowledge_id)
        knowledge.tabular_policy = TabularPolicy.TOOL_ONLY
        await container.integration_knowledge_repo().update(knowledge)
    async with db_container() as container:
        await _sync(container, monkeypatch, knowledge_id=knowledge_id, folder=folder)
        session = container.session()
        sheet = await _active(session, knowledge_id, "sales.xlsx")
        assert 'Sheet "Sales": Month, Region, Amount' in (sheet.text or "")
        assert await _chunk_count(session, sheet.id) == 0
        original = await InfoBlobRepository(session).get_original(sheet.id)
        assert original is not None and original.content_id == second_content_id
        references = await session.scalar(
            sa.select(sa.func.count()).where(
                InfoBlobContentReferences.content_id == second_content_id
            )
        )
        assert references == 1


@pytest.mark.integration
async def test_original_is_dropped_not_the_document_when_quota_is_full(
    db_container, tmp_path, monkeypatch
):
    folder = tmp_path / "drive"
    folder.mkdir()
    shutil.copy(FIXTURE_FILES / "sales.xlsx", folder / "sales.xlsx")

    async with db_container() as container:
        knowledge_id = await _seed_source(container, policy=TabularPolicy.TOOL_ONLY)
        session = container.session()
        user = container.user()
        retained = await InfoBlobRepository(session).get_retained_size_of_tenant(
            user.tenant_id
        )
        # Room for the extracted text, not for the workbook's bytes.
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == user.tenant_id)
            .values(quota_limit=retained + 2_000)
        )

    async with db_container() as container:
        stats = await _sync(
            container, monkeypatch, knowledge_id=knowledge_id, folder=folder
        )
        assert stats["files_processed"] == 1, stats
        assert any(
            detail["file"] == "sales.xlsx"
            and detail["reason"].startswith("Original not kept: quota")
            for detail in stats["skipped_details"]
        ), stats["skipped_details"]
        session = container.session()
        sheet = await _active(session, knowledge_id, "sales.xlsx")
        # Tools-only degraded to indexed text: the rows are searchable and no
        # chunkless stub was left behind without a file.
        assert await InfoBlobRepository(session).get_original(sheet.id) is None
        assert await _chunk_count(session, sheet.id) > 0
        assert "North" in (sheet.text or "")

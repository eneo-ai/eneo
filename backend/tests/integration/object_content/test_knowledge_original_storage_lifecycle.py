from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blobs_table import (
    InfoBlobs,
    InfoBlobVersionState,
    active_info_blob_version,
)
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.object_content_table import (
    InfoBlobContentReferences,
    InlineContentPayloads,
    ObjectContentMoves,
    ObjectContentOrphanCandidates,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.info_blobs.info_blob_service import InfoBlobService
from eneo.jobs.job_models import JobFailureCode, Task
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import KnowledgeOriginalAdmission, UploadInfoBlob
from eneo.main.container.container import Container, SessionProxy
from eneo.main.exceptions import QuotaExceededException
from eneo.main.models import Status
from eneo.object_content import deployment_policy_router
from eneo.object_content.content import (
    ContentAccessClass,
    ContentReadGrant,
    ContentState,
    StorageKind,
)
from eneo.object_content.move_repository import ObjectContentMoveRepository
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.runtime import object_content_runtime
from eneo.object_content.s3_object_store import (
    ObjectStoreNotFoundError,
    S3ObjectStore,
)
from eneo.worker.upload_tasks import upload_info_blob_task
from tests.integration.object_content.conftest import RealObjectStore


class _Extractor:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract(
        self,
        filepath: Path,
        mimetype: str,
        filename: str | None = None,
    ) -> str:
        del filepath, mimetype, filename
        return self._text


def _embedding_result(*, model, chunks):
    del model
    result = ChunkEmbeddingList()
    result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
    return result


def _sessionless_container(*, user, tenant) -> Container:
    return Container(
        session=providers.Object(SessionProxy()),
        user=providers.Object(user),
        tenant=providers.Object(tenant),
    )


def _stage_job_file(tmp_path: Path, job_id: UUID, payload: bytes) -> Path:
    path = job_staging_path(job_id, upload_tmp_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


async def _seed_job(container, *, with_prior: bool):
    session = container.session()
    user = container.user()
    embedding_model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    space = Spaces(
        name=f"Object-store knowledge space {uuid4().hex[:8]}",
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    session.add(space)
    await session.flush()
    group = CollectionsTable(
        name=f"Object-store knowledge group {uuid4().hex[:8]}",
        size=0,
        user_id=user.id,
        tenant_id=user.tenant_id,
        embedding_model_id=embedding_model.id,
        space_id=space.id,
    )
    job = Jobs(
        id=uuid4(),
        user_id=user.id,
        task=Task.UPLOAD_FILE.value,
        name="knowledge.txt",
        status=Status.QUEUED.value,
    )
    session.add_all((group, job))
    await session.flush()

    prior_id = None
    if with_prior:
        prior_text = "Previously committed searchable knowledge"
        prior = InfoBlobs(
            title="knowledge.txt",
            text=prior_text,
            size=len(prior_text.encode()),
            content_hash=sha256(prior_text.encode()).digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=user.id,
            tenant_id=user.tenant_id,
            group_id=group.id,
            embedding_model_id=embedding_model.id,
        )
        session.add(prior)
        await session.flush()
        prior_id = prior.id

    return user, container.tenant(), group, job, prior_id


@asynccontextmanager
async def _configured_runtime(
    real_object_store: RealObjectStore,
) -> AsyncGenerator[S3ObjectStore]:
    assert not object_content_runtime.enabled
    store = S3ObjectStore(real_object_store.settings)
    object_content_runtime.start(
        core_settings=real_object_store.settings,
        settings=real_object_store.settings,
        store=store,
    )
    try:
        await object_content_runtime.validate_configuration()
        yield store
    finally:
        await object_content_runtime.stop()


def _params(*, user_id: UUID, group_id: UUID, space_id: UUID) -> UploadInfoBlob:
    return UploadInfoBlob(
        user_id=user_id,
        group_id=group_id,
        space_id=space_id,
        filename="knowledge.txt",
        mimetype="text/plain",
        original_storage=KnowledgeOriginalAdmission(
            policy_revision=7,
            storage_target=StorageKind.OBJECT_STORE,
            maximum_bytes=1_000_000,
        ),
    )


@pytest.mark.asyncio
async def test_knowledge_original_uses_generic_inventory_move_and_delete_lifecycle(
    db_container,
    real_object_store: RealObjectStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    payload = b"exact object-store knowledge original"
    searchable_text = "Searchable text extracted from object storage"

    async with _configured_runtime(real_object_store):
        async with db_container() as container:
            user, tenant, group, job, _ = await _seed_job(
                container,
                with_prior=False,
            )
            job_id = job.id
            group_id = group.id
            space_id = group.space_id

        staged_path = _stage_job_file(tmp_path, job_id, payload)
        task_container = _sessionless_container(user=user, tenant=tenant)
        task_container.text_extractor.override(
            providers.Object(_Extractor(searchable_text))
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        task_container.create_embeddings_service.override(providers.Object(embeddings))

        async with db_container():
            assert (
                await upload_info_blob_task(
                    job_id=job_id,
                    params=_params(
                        user_id=user.id,
                        group_id=group_id,
                        space_id=space_id,
                    ),
                    container=task_container,
                )
                is True
            )
        assert not staged_path.exists()

        async with sessionmanager.session() as session:
            inventory = await deployment_policy_router._read_inventory(session)
            async with session.begin():
                published = (
                    await session.scalars(
                        sa.select(InfoBlobs).where(
                            InfoBlobs.title == "knowledge.txt",
                            active_info_blob_version(),
                        )
                    )
                ).one()
                reference, content, descriptor = (
                    await session.execute(
                        sa.select(
                            InfoBlobContentReferences,
                            ObjectContents,
                            ObjectStoreObjects,
                        )
                        .join(
                            ObjectContents,
                            ObjectContents.id == InfoBlobContentReferences.content_id,
                        )
                        .join(
                            ObjectStoreObjects,
                            ObjectStoreObjects.content_id == ObjectContents.id,
                        )
                        .where(InfoBlobContentReferences.info_blob_id == published.id)
                    )
                ).one()
                job_state = await session.get(Jobs, job_id)
                assert job_state is not None
                assert job_state.status == Status.COMPLETE.value
                assert reference.original_filename == "knowledge.txt"
                assert content.storage_kind == StorageKind.OBJECT_STORE.value
                assert content.state == ContentState.AVAILABLE.value
                assert content.sha256 == sha256(payload).digest()
                assert content.size_bytes == len(payload)
                assert content.declared_media_type == "text/plain"
                assert content.verified_media_type == "text/plain"
                assert content.idempotency_key == f"knowledge-original-job:{job_id}"
                published_id = published.id
                content_id = content.id
                object_key = descriptor.object_key

        assert (await real_object_store.store.head(object_key)).size_bytes == len(
            payload
        )
        assert any(
            row.target is StorageKind.OBJECT_STORE
            and row.state is ContentState.AVAILABLE
            and row.count >= 1
            and row.bytes >= len(payload)
            for row in inventory.inventory
        )

        grant = ContentReadGrant(
            content_id=content_id,
            tenant_id=user.tenant_id,
            access_class=ContentAccessClass.PRIVATE_RESOURCE,
        )
        async with object_content_runtime.service.open_content(grant) as opened:
            assert b"".join([chunk async for chunk in opened.chunks]) == payload

        async with sessionmanager.session() as session, session.begin():
            queued = await ObjectContentMoveRepository(session).queue(
                target_kind=StorageKind.POSTGRES_INLINE,
                limit=1,
                requested_by_user_id=user.id,
                target_maximum_bytes=real_object_store.settings.inline_maximum_bytes,
            )
        assert queued.queued_count == 1

        reconciler = ObjectContentReconciler(
            real_object_store.settings,
            sessionmanager,
            object_store_settings=real_object_store.settings,
            object_store=real_object_store.store,
        )
        moved = await reconciler.run_once()
        assert moved.moves_processed == 1

        async with sessionmanager.session() as session:
            moved_inventory = await deployment_policy_router._read_inventory(session)
            async with session.begin():
                moved_content = await session.get(ObjectContents, content_id)
                inline = await session.get(InlineContentPayloads, content_id)
                moved_reference = await session.get(
                    InfoBlobContentReferences,
                    published_id,
                )
                move = await session.get(ObjectContentMoves, content_id)
                assert moved_content is not None
                assert inline is not None
                assert moved_reference is not None
                assert moved_content.storage_kind == StorageKind.POSTGRES_INLINE.value
                assert moved_content.sha256 == sha256(payload).digest()
                assert inline.payload == payload
                assert moved_reference.content_id == content_id
                assert move is None
        assert any(
            row.target is StorageKind.POSTGRES_INLINE
            and row.state is ContentState.AVAILABLE
            and row.count >= 1
            and row.bytes >= len(payload)
            for row in moved_inventory.inventory
        )

        async with object_content_runtime.service.open_content(grant) as opened:
            assert b"".join([chunk async for chunk in opened.chunks]) == payload

        async with sessionmanager.session() as session, session.begin():
            await InfoBlobRepository(session).delete(published_id)
            assert (
                await session.scalar(
                    sa.select(sa.func.count())
                    .select_from(InfoBlobContentReferences)
                    .where(InfoBlobContentReferences.info_blob_id == published_id)
                )
                == 0
            )
            detached = await session.get(ObjectContents, content_id)
            assert detached is not None
            await session.refresh(detached)
            assert detached.reference_count == 0
            assert detached.delete_requested_at is not None

        cleaned = await reconciler.run_once()
        assert cleaned.inline_deleted == 1
        async with sessionmanager.session() as session, session.begin():
            tombstoned = await session.get(ObjectContents, content_id)
            assert tombstoned is not None
            assert tombstoned.state == ContentState.TOMBSTONED.value
            assert await session.get(InlineContentPayloads, content_id) is None


@pytest.mark.asyncio
async def test_remote_upload_becomes_reconcilable_orphan_when_final_transaction_fails(
    db_container,
    real_object_store: RealObjectStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    payload = b"remote upload that must not become knowledge"
    original_publish = InfoBlobService.publish_info_blob_without_validation

    async def publish_then_reject_quota(
        self,
        info_blob,
        *,
        embedding_model,
        original=None,
    ):
        await original_publish(
            self,
            info_blob,
            embedding_model=embedding_model,
            original=original,
        )
        raise QuotaExceededException()

    monkeypatch.setattr(
        InfoBlobService,
        "publish_info_blob_without_validation",
        publish_then_reject_quota,
    )

    async with _configured_runtime(real_object_store):
        async with db_container() as container:
            user, tenant, group, job, prior_id = await _seed_job(
                container,
                with_prior=True,
            )
            job_id = job.id
            group_id = group.id
            space_id = group.space_id

        staged_path = _stage_job_file(tmp_path, job_id, payload)
        task_container = _sessionless_container(user=user, tenant=tenant)
        task_container.text_extractor.override(
            providers.Object(_Extractor("Replacement that must roll back"))
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        task_container.create_embeddings_service.override(providers.Object(embeddings))

        async with db_container():
            assert (
                await upload_info_blob_task(
                    job_id=job_id,
                    params=_params(
                        user_id=user.id,
                        group_id=group_id,
                        space_id=space_id,
                    ),
                    container=task_container,
                )
                is False
            )
        assert not staged_path.exists()

        async with sessionmanager.session() as session, session.begin():
            job_state = await session.get(Jobs, job_id)
            active_ids = set(
                await session.scalars(
                    sa.select(InfoBlobs.id).where(
                        InfoBlobs.group_id == group_id,
                        active_info_blob_version(),
                    )
                )
            )
            reference_count = await session.scalar(
                sa.select(sa.func.count()).select_from(InfoBlobContentReferences)
            )
            content_count = await session.scalar(
                sa.select(sa.func.count()).select_from(ObjectContents)
            )
            candidates = (
                await session.scalars(sa.select(ObjectContentOrphanCandidates))
            ).all()
            assert job_state is not None
            assert job_state.status == Status.FAILED.value
            assert job_state.failure_code == JobFailureCode.QUOTA_EXCEEDED.value
            assert len(candidates) == 1
            candidate_key = candidates[0].object_key
            candidate_size = candidates[0].size_bytes

        assert active_ids == {prior_id}
        assert reference_count == 0
        assert content_count == 0
        assert candidate_size == len(payload)
        assert (await real_object_store.store.head(candidate_key)).size_bytes == len(
            payload
        )

        async with sessionmanager.session() as session, session.begin():
            candidate = await session.get(
                ObjectContentOrphanCandidates,
                candidate_key,
                with_for_update=True,
            )
            assert candidate is not None
            now = await session.scalar(sa.select(sa.func.now()))
            assert now is not None
            candidate.eligible_after = now - timedelta(seconds=1)
            if candidate.lease_until is not None:
                candidate.lease_until = now - timedelta(seconds=1)

        reconciler = ObjectContentReconciler(
            real_object_store.settings,
            sessionmanager,
            object_store_settings=real_object_store.settings,
            object_store=real_object_store.store,
        )
        first = await reconciler.run_once()
        assert first.orphan_objects_deleted == 0
        second = await reconciler.run_once()
        assert second.orphan_objects_deleted == 1
        with pytest.raises(ObjectStoreNotFoundError):
            await real_object_store.store.head(candidate_key)

"""A renamed or moved SharePoint document: its active version follows the new
name and address without a new version."""

import sqlalchemy as sa

from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from tests.integration.info_blobs.test_integration_publication_locks import (
    _document,
    _seed_knowledge,
    _with_fake_embeddings,
)


async def test_only_the_active_version_follows_a_rename(
    db_container, user_integration_factory
) -> None:
    async with db_container() as container:
        _with_fake_embeddings(container)
        knowledge_id, model_id = await _seed_knowledge(
            container, user_integration_factory
        )
        model = await container.embedding_model_repo2().one(model_id)
        service = container.info_blob_service()
        for text in ("First version", "Second version"):
            await service.publish_info_blob_without_validation(
                _document(container, knowledge_id, "item-1", text),
                embedding_model=model,
            )
        repo = container.info_blob_repo()

        changed = await repo.refresh_sharepoint_citation(
            sharepoint_item_id="item-1",
            integration_knowledge_id=knowledge_id,
            title="Renamed.docx",
            url="https://example.test/sharepoint/Moved/Renamed.docx",
        )
        unchanged = await repo.refresh_sharepoint_citation(
            sharepoint_item_id="item-1",
            integration_knowledge_id=knowledge_id,
            title="Renamed.docx",
            url="https://example.test/sharepoint/Moved/Renamed.docx",
        )
        rows = (
            await container.session().execute(
                sa.select(InfoBlobs.version_state, InfoBlobs.title, InfoBlobs.url)
                .where(InfoBlobs.integration_knowledge_id == knowledge_id)
                .order_by(InfoBlobs.version_state)
            )
        ).all()

    assert (changed, unchanged) == (True, False)
    assert [tuple(row) for row in rows] == [
        (
            InfoBlobVersionState.ACTIVE.value,
            "Renamed.docx",
            "https://example.test/sharepoint/Moved/Renamed.docx",
        ),
        (
            InfoBlobVersionState.SUPERSEDED.value,
            "item-1.docx",
            "https://example.test/sharepoint/item-1.docx",
        ),
    ]

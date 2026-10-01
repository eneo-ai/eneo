"""Source metadata is embedded with each chunk but not stored in it."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.embedding_models.infrastructure.datastore import Datastore, settings
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobInDB, SourceMetadataEntry


def _info_blob(source_metadata) -> InfoBlobInDB:
    return InfoBlobInDB(
        id=uuid4(),
        text="First paragraph of the policy.\n\nSecond paragraph of the policy.",
        title="Policy.docx",
        embedding_model_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        size=10,
        source_id=uuid4(),
        version_state="active",
        source_metadata=source_metadata,
    )


def _datastore(captured: list):
    async def get_embeddings(model, chunks):
        captured.extend(chunks)
        embeddings = ChunkEmbeddingList()
        embeddings.add(chunks, [[0.1, 0.2] for _ in chunks])
        return embeddings

    user = MagicMock()
    user.tenant_id = uuid4()
    repo = MagicMock()
    repo.add = AsyncMock()
    return (
        Datastore(
            user=user,
            info_blob_chunk_repo=repo,
            create_embeddings_service=MagicMock(get_embeddings=get_embeddings),
        ),
        repo,
    )


def _stored_texts(repo) -> list[str]:
    return [chunk.text for call in repo.add.await_args_list for chunk in call.args[0]]


async def test_header_is_embedded_but_the_stored_text_stays_clean():
    embedded: list = []
    datastore, repo = _datastore(embedded)
    blob = _info_blob(
        [
            SourceMetadataEntry(
                name="t", label="Dokumenttyp", value="Policy", kind="choice"
            )
        ]
    )

    await datastore.add(info_blob=blob, embedding_model=MagicMock())

    assert embedded, "chunks were embedded"
    for chunk in embedded:
        assert chunk.text.startswith("Policy.docx\nDokumenttyp: Policy\n\n")
    stored = _stored_texts(repo)
    assert stored and all("Dokumenttyp" not in text for text in stored)
    assert [c.chunk_no for c in embedded] == list(range(len(stored)))


async def test_documents_without_metadata_embed_exactly_their_text():
    embedded: list = []
    datastore, repo = _datastore(embedded)

    await datastore.add(info_blob=_info_blob(None), embedding_model=MagicMock())

    assert [c.text for c in embedded] == _stored_texts(repo)


def test_header_is_capped_to_a_share_of_the_chunk_budget():
    datastore, _ = _datastore([])
    wide = [
        SourceMetadataEntry(name=f"c{i}", label=f"Column {i}", value="x" * 40)
        for i in range(30)
    ]
    header = datastore._source_header(_info_blob(wide))

    assert header.startswith("Policy.docx\nColumn 0: ")
    assert header.count("\n") < 30
    assert len(header.split()) <= settings.chunk_size

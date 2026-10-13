"""Source metadata is embedded with each chunk but not stored in it."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.embedding_models.domain import chunking
from eneo.embedding_models.domain.embedding_model import EmbeddingModel
from eneo.embedding_models.infrastructure.datastore import (
    SOURCE_HEADER_BUDGET_SHARE,
    Datastore,
)
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobChunk, InfoBlobInDB, SourceMetadataEntry
from eneo.tokens.token_utils import count_tokens


@pytest.fixture(autouse=True)
def configured_chunking(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chunking.settings, "chunk_size", 200)
    monkeypatch.setattr(chunking.settings, "chunk_overlap", 40)


def _model(max_input: int = 8191, family: str | None = None) -> EmbeddingModel:
    model = MagicMock(spec=EmbeddingModel)
    model.name = "test-model"
    model.max_input = max_input
    model.family = family
    return model


def _info_blob(source_metadata: list[SourceMetadataEntry] | None) -> InfoBlobInDB:
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


def _datastore(captured: list[InfoBlobChunk]):
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
    embedded: list[InfoBlobChunk] = []
    datastore, repo = _datastore(embedded)
    blob = _info_blob(
        [
            SourceMetadataEntry(
                name="t", label="Dokumenttyp", value="Policy", kind="choice"
            )
        ]
    )

    await datastore.add(info_blob=blob, embedding_model=_model())

    assert embedded, "chunks were embedded"
    for chunk in embedded:
        assert chunk.text.startswith("Policy.docx\nDokumenttyp: Policy\n\n")
    stored = _stored_texts(repo)
    assert stored and all("Dokumenttyp" not in text for text in stored)
    assert [c.chunk_no for c in embedded] == list(range(len(stored)))


async def test_documents_without_metadata_embed_exactly_their_text():
    embedded: list[InfoBlobChunk] = []
    datastore, repo = _datastore(embedded)

    await datastore.add(info_blob=_info_blob(None), embedding_model=_model())

    assert [c.text for c in embedded] == _stored_texts(repo)


def test_header_is_capped_to_a_share_of_the_chunk_budget():
    datastore, _ = _datastore([])
    wide = [
        SourceMetadataEntry(name=f"c{i}", label=f"Column {i}", value="x" * 40)
        for i in range(30)
    ]
    header = datastore._source_header(_info_blob(wide), _model())

    assert header.startswith("Policy.docx\nColumn 0: ")
    assert header.count("\n") < 30
    assert count_tokens(header) <= int(
        chunking.settings.chunk_size * SOURCE_HEADER_BUDGET_SHARE
    )


@pytest.mark.parametrize(
    ("configured_size", "max_input", "family"),
    [(200, 120, None), (200, 120, "e5"), (70, 200, "e5"), (200, 6, None)],
)
async def test_source_properties_fit_the_model_and_configured_embedding_budget(
    monkeypatch: pytest.MonkeyPatch,
    configured_size: int,
    max_input: int,
    family: str | None,
):
    monkeypatch.setattr(chunking.settings, "chunk_size", configured_size)
    embedded: list[InfoBlobChunk] = []
    datastore, repo = _datastore(embedded)
    model = _model(max_input, family)
    blob = _info_blob(
        [SourceMetadataEntry(name="t", label="Dokumenttyp", value="Policy")]
    ).model_copy(update={"text": " ".join(f"word{i}" for i in range(300))})

    await datastore.add(info_blob=blob, embedding_model=model)

    assert len(embedded) > 1
    prefix = "passage: " if family == "e5" else ""
    assert all(count_tokens(prefix + chunk.text) <= max_input for chunk in embedded)
    assert all(count_tokens(chunk.text) <= configured_size for chunk in embedded)
    assert all("Dokumenttyp" not in text for text in _stored_texts(repo))
    if max_input > 20:
        assert all("Dokumenttyp: Policy" in chunk.text for chunk in embedded)

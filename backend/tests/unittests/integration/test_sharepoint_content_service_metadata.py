"""Source metadata handling in the SharePoint content service."""

import hashlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.integration.infrastructure.content_service.sharepoint_content_service import (  # noqa: E501
    SharePointContentService,
    sanitize_text_for_db,
)
from eneo.integration.infrastructure.content_service.sharepoint_metadata import (
    SharePointColumnCatalog,
    source_metadata_fingerprint,
)

COLUMNS = [{"name": "Dokumenttyp", "displayName": "Dokumenttyp", "choice": {}}]
ITEM = {"id": "i1", "listItem": {"fields": {"Dokumenttyp": "Rutin"}}}
ENTRIES = [
    SourceMetadataEntry(
        name="Dokumenttyp", label="Dokumenttyp", value="Rutin", kind="choice"
    )
]


@pytest.fixture
def user():
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    return user


@pytest.fixture
def integration_knowledge():
    ik = MagicMock()
    ik.id = uuid4()
    ik.embedding_model = MagicMock()
    ik.size = 0
    return ik


@pytest.fixture
def deps(user):
    return {
        "job_service": AsyncMock(),
        "oauth_token_repo": AsyncMock(),
        "user_integration_repo": AsyncMock(),
        "user": user,
        "info_blob_service": AsyncMock(),
        "integration_knowledge_repo": AsyncMock(),
        "oauth_token_service": AsyncMock(),
        "session": AsyncMock(),
        "tenant_sharepoint_app_repo": AsyncMock(),
        "tenant_app_auth_service": AsyncMock(),
    }


@pytest.fixture
def service(deps):
    return SharePointContentService(**deps)


def _graph_client(columns=COLUMNS, *, enabled=True):
    client = MagicMock()
    client.list_item_fields_enabled = enabled
    client.get_list_columns = AsyncMock(return_value=columns)
    return client


class TestColumnCatalog:
    async def test_is_read_once_per_drive(self, service):
        client = _graph_client()

        first = await service._column_catalog(client, "d1")
        second = await service._column_catalog(client, "d1")
        await service._column_catalog(client, "d2")

        assert first is second
        assert list(first.columns) == ["Dokumenttyp"]
        assert client.get_list_columns.await_count == 2

    async def test_unreadable_columns_degrade_to_no_metadata(self, service):
        client = _graph_client()
        client.get_list_columns = AsyncMock(side_effect=RuntimeError("403"))

        catalog = await service._column_catalog(client, "d1")
        again = await service._column_catalog(client, "d1")

        assert catalog.is_empty and again.is_empty
        assert client.get_list_columns.await_count == 1

    async def test_skipped_without_drive_or_when_expansion_is_off(self, service):
        client = _graph_client(enabled=False)

        assert (await service._column_catalog(client, None)).is_empty
        assert (await service._column_catalog(client, "d1")).is_empty
        client.get_list_columns.assert_not_awaited()


class TestSourceMetadataFor:
    async def test_extracts_entries_from_the_item(self, service):
        entries = await service._source_metadata_for(_graph_client(), "d1", ITEM)
        assert entries == ENTRIES

    async def test_extraction_errors_give_nothing(self, service, monkeypatch):
        service._column_catalogs["d1"] = SharePointColumnCatalog.from_graph(COLUMNS)

        def explode(item, catalog):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "eneo.integration.infrastructure.content_service."
            "sharepoint_content_service.extract_source_metadata",
            explode,
        )

        assert await service._source_metadata_for(_graph_client(), "d1", ITEM) == []


class TestHashAndChangeKey:
    def test_hash_without_metadata_matches_the_legacy_digest(self):
        text = "Hello"
        assert (
            SharePointContentService._content_hash(text, [])
            == hashlib.sha256(text.encode("utf-8")).digest()
        )

    def test_hash_changes_with_metadata_values(self):
        text = "Hello"
        other = [
            SourceMetadataEntry(
                name="Dokumenttyp", label="Dokumenttyp", value="Policy", kind="choice"
            )
        ]
        plain = SharePointContentService._content_hash(text, [])
        with_meta = SharePointContentService._content_hash(text, ENTRIES)

        assert with_meta != plain
        assert with_meta == SharePointContentService._content_hash(text, list(ENTRIES))
        assert with_meta != SharePointContentService._content_hash(text, other)

    def test_change_key_folds_in_the_metadata_fingerprint(self):
        assert SharePointContentService._change_key_with_metadata("ctag", []) == "ctag"
        assert SharePointContentService._change_key_with_metadata(None, ENTRIES) is None
        assert SharePointContentService._change_key_with_metadata("ctag", ENTRIES) == (
            f"ctag#{source_metadata_fingerprint(ENTRIES)}"
        )


def _existing(content_hash: bytes, source_metadata):
    existing = MagicMock()
    existing.id = uuid4()
    existing.size = 10
    existing.title = "Doc"
    existing.url = "https://x"
    existing.source_metadata = source_metadata
    existing.content_hash = content_hash
    return existing


class TestProcessInfoBlob:
    async def test_new_document_is_published_with_its_metadata(
        self, service, deps, integration_knowledge
    ):
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=None
        )
        published = MagicMock()
        published.size = 10
        publish = AsyncMock(return_value=published)
        deps["info_blob_service"].publish_info_blob_without_validation = publish

        await service._process_info_blob(
            title="Doc",
            text="Body",
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=ENTRIES,
        )

        info_blob_add = publish.await_args.args[0]
        assert info_blob_add.source_metadata == ENTRIES
        assert info_blob_add.content_hash == SharePointContentService._content_hash(
            sanitize_text_for_db("Body"), ENTRIES
        )

    async def test_metadata_only_edit_re_publishes(
        self, service, deps, integration_knowledge
    ):
        legacy_hash = hashlib.sha256(
            sanitize_text_for_db("Body").encode("utf-8")
        ).digest()
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=_existing(legacy_hash, None)
        )
        published = MagicMock()
        published.size = 10
        publish = AsyncMock(return_value=published)
        deps["info_blob_service"].publish_info_blob_without_validation = publish

        await service._process_info_blob(
            title="Doc",
            text="Body",
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=ENTRIES,
        )

        publish.assert_awaited_once()

    async def test_unchanged_text_and_metadata_skip_republish(
        self, service, deps, integration_knowledge
    ):
        same_hash = SharePointContentService._content_hash(
            sanitize_text_for_db("Body"), ENTRIES
        )
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=_existing(same_hash, list(ENTRIES))
        )
        repo.update = AsyncMock()
        publish = AsyncMock()
        deps["info_blob_service"].publish_info_blob_without_validation = publish

        await service._process_info_blob(
            title="Doc",
            text="Body",
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=list(ENTRIES),
        )

        publish.assert_not_called()
        repo.update.assert_not_called()

"""Source metadata handling in the SharePoint content service."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
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

    async def test_unreadable_columns_are_distinct_from_an_empty_catalog(self, service):
        client = _graph_client()
        client.get_list_columns = AsyncMock(side_effect=RuntimeError("403"))

        catalog = await service._column_catalog(client, "d1")
        again = await service._column_catalog(client, "d1")

        assert catalog is None and again is None
        assert client.get_list_columns.await_count == 1

    async def test_skipped_without_drive_or_when_expansion_is_off(self, service):
        client = _graph_client(enabled=False)

        assert await service._column_catalog(client, None) is None
        assert await service._column_catalog(client, "d1") is None
        client.get_list_columns.assert_not_awaited()

    async def test_successfully_read_empty_catalog_is_not_unavailable(self, service):
        catalog = await service._column_catalog(_graph_client(columns=[]), "d1")
        assert catalog is not None and catalog.is_empty


class TestSourceMetadataFor:
    async def test_extracts_entries_from_the_item(self, service):
        entries = await service._source_metadata_for(_graph_client(), "d1", ITEM)
        assert entries == ENTRIES

    async def test_extraction_errors_leave_metadata_unread(self, service, monkeypatch):
        service._column_catalogs["d1"] = SharePointColumnCatalog.from_graph(COLUMNS)

        def explode(item, catalog):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "eneo.integration.infrastructure.content_service."
            "sharepoint_content_service.extract_source_metadata",
            explode,
        )

        assert await service._source_metadata_for(_graph_client(), "d1", ITEM) is None

    @pytest.mark.parametrize(
        "item", [{"id": "i1"}, {"listItem": {}}, {"listItem": {"fields": None}}]
    )
    async def test_missing_fields_leave_metadata_unread(self, service, item):
        assert await service._source_metadata_for(_graph_client(), "d1", item) is None

    async def test_successfully_read_empty_fields_clear_properties(self, service):
        item = {"id": "i1", "listItem": {"fields": {}}}
        assert await service._source_metadata_for(_graph_client(), "d1", item) == []

    async def test_successfully_read_no_admitted_columns_clears_properties(
        self, service
    ):
        assert (
            await service._source_metadata_for(_graph_client(columns=[]), "d1", ITEM)
            == []
        )


class TestHashAndChangeKey:
    def test_hash_without_metadata_matches_the_legacy_digest(self):
        text = "Hello"
        assert (
            SharePointContentService._content_hash(text, [], title="Doc")
            == hashlib.sha256(text.encode("utf-8")).digest()
        )

    def test_hash_changes_with_metadata_values(self):
        text = "Hello"
        other = [
            SourceMetadataEntry(
                name="Dokumenttyp", label="Dokumenttyp", value="Policy", kind="choice"
            )
        ]
        plain = SharePointContentService._content_hash(text, [], title="Doc")
        with_meta = SharePointContentService._content_hash(text, ENTRIES, title="Doc")

        assert with_meta != plain
        assert with_meta == SharePointContentService._content_hash(
            text, list(ENTRIES), title="Doc"
        )
        assert with_meta != SharePointContentService._content_hash(
            text, other, title="Doc"
        )

    def test_change_key_folds_in_the_metadata_fingerprint(self):
        assert (
            SharePointContentService._change_key_with_metadata("ctag", [], title="Doc")
            == "ctag"
        )
        assert (
            SharePointContentService._change_key_with_metadata(
                None, ENTRIES, title="Doc"
            )
            is None
        )
        assert SharePointContentService._change_key_with_metadata(
            "ctag", ENTRIES, title="Doc"
        ) == (f"ctag#{source_metadata_fingerprint(ENTRIES, title='Doc')}")

    def test_unread_metadata_does_not_skip_a_delta_as_a_duplicate(self):
        assert (
            SharePointContentService._change_key_with_metadata(
                "ctag", None, title="Doc"
            )
            is None
        )

    def test_rename_changes_both_the_hash_and_the_delta_key(self):
        assert SharePointContentService._content_hash(
            "Body", ENTRIES, title="Doc"
        ) != SharePointContentService._content_hash("Body", ENTRIES, title="Renamed")
        assert SharePointContentService._change_key_with_metadata(
            "ctag", ENTRIES, title="Doc"
        ) != SharePointContentService._change_key_with_metadata(
            "ctag", ENTRIES, title="Renamed"
        )

    def test_rename_without_properties_keeps_the_legacy_hash(self):
        assert SharePointContentService._content_hash(
            "Body", [], title="Doc"
        ) == SharePointContentService._content_hash("Body", [], title="Renamed")


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
            sanitize_text_for_db("Body"), ENTRIES, title="Doc"
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
            sanitize_text_for_db("Body"), ENTRIES, title="Doc"
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

    @pytest.mark.parametrize("body", ["Body", "Changed body"])
    @pytest.mark.parametrize("unavailable", ["columns", "expansion", "fields"])
    async def test_unread_metadata_preserves_existing_properties(
        self, service, deps, integration_knowledge, body, unavailable
    ):
        client = _graph_client(enabled=unavailable != "expansion")
        if unavailable == "columns":
            client.get_list_columns.side_effect = RuntimeError("403")
        item = {"id": "i1"} if unavailable == "fields" else ITEM
        metadata = await service._source_metadata_for(client, "d1", item)
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = _existing(
            SharePointContentService._content_hash("Body", ENTRIES, title="Doc"),
            ENTRIES,
        )
        publish = deps["info_blob_service"].publish_info_blob_without_validation

        await service._process_info_blob(
            title="Doc",
            text=body,
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=metadata,
        )

        if body == "Body":
            publish.assert_not_awaited()
            repo.update.assert_not_awaited()
        else:
            publish.assert_awaited_once()
            assert publish.await_args.args[0].source_metadata == ENTRIES

    async def test_successfully_removed_properties_are_cleared(
        self, service, deps, integration_knowledge
    ):
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = _existing(
            SharePointContentService._content_hash("Body", ENTRIES, title="Doc"),
            ENTRIES,
        )

        await service._process_info_blob(
            title="Doc",
            text="Body",
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=[],
        )

        publish = deps["info_blob_service"].publish_info_blob_without_validation
        assert publish.await_args.args[0].source_metadata is None
        assert (
            publish.await_args.args[0].content_hash == hashlib.sha256(b"Body").digest()
        )

    async def test_new_document_with_unread_metadata_still_imports(
        self, service, deps, integration_knowledge
    ):
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = None

        await service._process_info_blob(
            title="Doc",
            text="Body",
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=None,
        )

        publish = deps["info_blob_service"].publish_info_blob_without_validation
        assert publish.await_args.args[0].source_metadata is None
        assert (
            publish.await_args.args[0].content_hash == hashlib.sha256(b"Body").digest()
        )

    async def test_rename_reembeds_the_updated_source_header(
        self, service, deps, integration_knowledge
    ):
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = _existing(
            SharePointContentService._content_hash("Body", ENTRIES, title="Doc"),
            ENTRIES,
        )

        await service._process_info_blob(
            title="Renamed",
            text="Body",
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=ENTRIES,
        )

        publish = deps["info_blob_service"].publish_info_blob_without_validation
        publish.assert_awaited_once()
        assert publish.await_args.args[0].title == "Renamed"

    async def test_rename_without_properties_only_updates_the_title(
        self, service, deps, integration_knowledge
    ):
        repo = deps["info_blob_service"].repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = _existing(
            hashlib.sha256(b"Body").digest(), None
        )

        await service._process_info_blob(
            title="Renamed",
            text="Body",
            url="https://x",
            integration_knowledge=integration_knowledge,
            sharepoint_item_id="i1",
            source_metadata=[],
        )

        deps[
            "info_blob_service"
        ].publish_info_blob_without_validation.assert_not_awaited()
        assert repo.update.await_args.args[0].title == "Renamed"


class TestDeltaMetadata:
    @pytest.mark.parametrize("title", ["Doc.docx", "Renamed.docx"])
    @pytest.mark.parametrize("metadata_available", [True, False])
    async def test_unchanged_ctag_preserves_metadata_and_reindexes_a_rename(
        self, service, deps, integration_knowledge, title, metadata_available
    ):
        integration_knowledge.site_id = "s1"
        integration_knowledge.drive_id = "d1"
        integration_knowledge.folder_id = None
        integration_knowledge.selected_item_type = "site_root"
        integration_knowledge.delta_token = "old-token"
        deps["integration_knowledge_repo"].one.return_value = integration_knowledge
        token = MagicMock(
            id=uuid4(), base_url="https://graph.microsoft.com", access_token="token"
        )
        deps["oauth_token_repo"].one.return_value = token
        deps["session"].sync_session = None
        old_key = service._change_key_with_metadata(
            "same-ctag", ENTRIES, title="Doc.docx"
        )
        service.change_key_service = AsyncMock()
        service.change_key_service.should_process.side_effect = (
            lambda **kwargs: kwargs["change_key"] != old_key
        )
        existing = _existing(
            service._content_hash("Body", ENTRIES, title="Doc.docx"), ENTRIES
        )
        existing.title = "Doc.docx"
        deps[
            "info_blob_service"
        ].repo.get_by_sharepoint_item_and_integration_knowledge.return_value = existing
        deps[
            "info_blob_service"
        ].publish_info_blob_without_validation.return_value = MagicMock(size=10)
        client = _graph_client()
        if not metadata_available:
            client.get_list_columns.side_effect = RuntimeError("403")
        client.get_delta_changes = AsyncMock(
            return_value=(
                [
                    {
                        **ITEM,
                        "name": title,
                        "file": {},
                        "cTag": "same-ctag",
                        "webUrl": "https://x",
                    }
                ],
                "new-token",
            )
        )
        client.get_file_content_by_id = AsyncMock(return_value=("Body", None))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient",
            return_value=client,
        ):
            await service.process_delta_changes(
                token_id=token.id,
                integration_knowledge_id=integration_knowledge.id,
                drive_id="d1",
                site_id="s1",
            )

        publish = deps["info_blob_service"].publish_info_blob_without_validation
        if title == "Renamed.docx":
            publish.assert_awaited_once()
            assert publish.await_args.args[0].title == title
            assert publish.await_args.args[0].source_metadata == ENTRIES
        else:
            publish.assert_not_awaited()
        assert client.get_file_content_by_id.await_count == int(
            not metadata_available or title == "Renamed.docx"
        )
        assert integration_knowledge.delta_token == "new-token"

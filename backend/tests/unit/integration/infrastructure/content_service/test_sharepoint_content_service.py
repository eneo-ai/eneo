"""Publishing one downloaded SharePoint file: originals, quota and fallbacks.

The service is built with mocked collaborators; ``_publish_file`` is the one
path all four sync call sites go through, so its rules are tested here once.
"""

import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
    _AttachedOriginal,
    sanitize_text_for_db,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointFileContent,
)
from eneo.main.exceptions import TenantQuotaExceededException

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
UNEXTRACTABLE = "[Could not extract text from Excel spreadsheet]"
URL = "https://sharepoint.invalid/x"
SHA_A = b"\x01" * 32
SHA_B = b"\x02" * 32
BYTES = b"bytes"
BYTES_SHA = hashlib.sha256(BYTES).digest()


@pytest.fixture
def knowledge():
    return SimpleNamespace(
        id=uuid4(),
        size=500,
        embedding_model=MagicMock(),
    )


def _make_service():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    info_blob_service = AsyncMock()
    info_blob_service.quota_service = AsyncMock()
    repo = info_blob_service.repo
    repo.get_by_sharepoint_item_and_integration_knowledge = AsyncMock(return_value=None)
    repo.get_by_title_and_integration_knowledge = AsyncMock(return_value=None)
    repo.get_original = AsyncMock(return_value=None)
    repo.update = AsyncMock()
    info_blob_service.publish_info_blob_without_validation = AsyncMock(
        return_value=SimpleNamespace(size=100)
    )
    info_blob_service.release_original_without_validation = AsyncMock(
        return_value=SimpleNamespace(size=60)
    )
    return SharePointContentService(
        job_service=AsyncMock(),
        oauth_token_repo=AsyncMock(),
        user_integration_repo=AsyncMock(),
        user=user,
        info_blob_service=info_blob_service,
        integration_knowledge_repo=AsyncMock(),
        oauth_token_service=AsyncMock(),
        session=AsyncMock(),
        tenant_sharepoint_app_repo=AsyncMock(),
        tenant_app_auth_service=AsyncMock(),
        object_content=MagicMock(),
    )


@pytest.fixture
def service():
    """Publication stops at ``_process_info_blob``: tests see what it was handed."""
    svc = _make_service()
    svc._process_info_blob = AsyncMock()  # type: ignore[method-assign]
    return svc


@pytest.fixture
def publishing_service():
    """The real ``_process_info_blob`` over a mocked info-blob service."""
    return _make_service()


def _stats():
    return {
        "files_processed": 0,
        "files_deleted": 0,
        "out_of_scope_deleted": 0,
        "folders_processed": 0,
        "pages_processed": 0,
        "skipped_items": 0,
        "skipped_details": [],
    }


def _content(
    name="sales.xlsx",
    text="Excel sheet data: a|b",
    data=BYTES,
    content_type="xlsx",
    index_text=None,
):
    return SharePointFileContent(
        text=text,
        content_type=content_type,
        file_name=name,
        data=data,
        index_text=index_text,
    )


def _prepared(sha=SHA_A, size=5):
    return SimpleNamespace(captured=SimpleNamespace(sha256=sha, size_bytes=size))


def _attached(sha=SHA_A, size=5, usable=True):
    return SimpleNamespace(sha256=sha, size_bytes=size, usable=usable)


def _existing(service, text, *, title="sales.xlsx", size=100):
    """An active version whose indexed text is ``text`` (unchanged metadata)."""
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        url=URL,
        size=size,
        source_metadata=None,
        content_hash=service._content_hash(sanitize_text_for_db(text), [], title=title),
    )


def _patch_prepared(service, prepared):
    """Replace the capture context with one yielding ``prepared`` (or None)."""
    calls = []

    @asynccontextmanager
    async def fake(**kwargs):
        calls.append(kwargs)
        yield prepared

    service._prepared_original = fake  # type: ignore[method-assign]
    return calls


def _published(service):
    return service._process_info_blob.await_args.kwargs


async def _publish(service, knowledge, content, stats=None):
    return await service._publish_file(
        content=content,
        title=content.file_name,
        url=URL,
        integration_knowledge=knowledge,
        sharepoint_item_id="item-1",
        source_metadata=None,
        stats=stats if stats is not None else _stats(),
    )


class TestOriginalCapture:
    async def test_tabular_file_is_indexed_and_keeps_its_original(
        self, service, knowledge
    ):
        prepared = _prepared()
        calls = _patch_prepared(service, prepared)

        assert await _publish(service, knowledge, _content()) is True

        assert calls[0]["media_type"] == XLSX and calls[0]["data"] == BYTES
        published = _published(service)
        assert published["original"] is prepared
        assert published["text"] == "Excel sheet data: a|b"
        assert published["incoming_sha"] == BYTES_SHA

    async def test_non_tabular_file_carries_no_bytes_and_is_indexed_as_before(
        self, service, knowledge
    ):
        calls = _patch_prepared(service, None)

        assert await _publish(
            service,
            knowledge,
            _content("deck.pptx", "Slides", data=None, content_type="pptx"),
        )

        assert calls[0]["media_type"] is None
        published = _published(service)
        assert published["original"] is None
        assert published["incoming_sha"] is None
        # Only tabular files compare bytes with the active version up front.
        repo = service.info_blob_service.repo
        repo.get_by_sharepoint_item_and_integration_knowledge.assert_not_awaited()

    async def test_unextractable_file_without_bytes_is_not_published(
        self, service, knowledge
    ):
        _patch_prepared(service, None)

        published = await _publish(
            service, knowledge, _content("deck.pptx", UNEXTRACTABLE, data=None)
        )

        assert published is False
        service._process_info_blob.assert_not_awaited()

    async def test_unextractable_workbook_with_an_original_is_kept_as_a_stub(
        self, service, knowledge, monkeypatch
    ):
        _patch_prepared(service, _prepared())
        monkeypatch.setattr(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service."
            "build_tabular_placeholder_text",
            lambda name, data: f"stub for {name}",
        )

        assert await _publish(service, knowledge, _content(text=UNEXTRACTABLE))

        published = _published(service)
        assert published["text"] == "stub for sales.xlsx"


class TestIndexText:
    """A large table is indexed as its sample only while the original is kept."""

    async def test_sample_is_indexed_when_the_original_is_retained(
        self, service, knowledge
    ):
        _patch_prepared(service, _prepared(size=50_000))
        content = _content(text="every row", index_text="schema and sample")

        assert await _publish(service, knowledge, content)

        assert _published(service)["text"] == "schema and sample"
        service.info_blob_service.quota_service.ensure_capacity.assert_awaited_once_with(
            50_000 + len(b"schema and sample")
        )

    async def test_full_text_is_indexed_when_quota_drops_the_original(
        self, service, knowledge
    ):
        _patch_prepared(service, _prepared(size=50_000))
        service.info_blob_service.quota_service.ensure_capacity.side_effect = (
            TenantQuotaExceededException("full")
        )

        assert await _publish(
            service, knowledge, _content(text="every row", index_text="sample")
        )

        published = _published(service)
        assert published["original"] is None
        assert published["text"] == "every row"

    async def test_full_text_is_indexed_when_capture_fails(self, service, knowledge):
        _patch_prepared(service, None)

        assert await _publish(
            service, knowledge, _content(text="every row", index_text="sample")
        )

        assert _published(service)["text"] == "every row"


class TestQuota:
    async def test_quota_overflow_drops_the_bytes_and_keeps_the_text(
        self, service, knowledge
    ):
        _patch_prepared(service, _prepared(size=50_000))
        service.info_blob_service.quota_service.ensure_capacity.side_effect = (
            TenantQuotaExceededException("full")
        )
        stats = _stats()

        assert await _publish(service, knowledge, _content(), stats)

        published = _published(service)
        assert published["original"] is None
        assert stats["skipped_details"] == [
            {"file": "sales.xlsx", "reason": "Original not kept: quota"}
        ]
        assert stats["skipped_items"] == 0
        service.info_blob_service.quota_service.ensure_capacity.assert_awaited_once_with(
            50_000 + len(b"Excel sheet data: a|b")
        )

    async def test_a_replacement_is_charged_only_for_its_growth(
        self, service, knowledge
    ):
        repo = service.info_blob_service.repo
        existing = _existing(service, "older rows")
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = existing
        repo.get_original.return_value = _attached(SHA_B, size=40_000)
        _patch_prepared(service, _prepared(SHA_A, size=50_000))

        assert await _publish(service, knowledge, _content())

        repo.get_original.assert_awaited_once_with(existing.id)
        service.info_blob_service.quota_service.ensure_capacity.assert_awaited_once_with(
            10_000 + len(b"Excel sheet data: a|b")
        )
        published = _published(service)
        assert published["existing_blob"] is existing
        assert published["existing_original"] is repo.get_original.return_value

    async def test_unchanged_bytes_cost_no_storage(self, service, knowledge):
        repo = service.info_blob_service.repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = _existing(
            service, "same rows"
        )
        repo.get_original.return_value = _attached(SHA_A, size=50_000)
        _patch_prepared(service, _prepared(SHA_A, size=50_000))

        assert await _publish(service, knowledge, _content())

        service.info_blob_service.quota_service.ensure_capacity.assert_awaited_once_with(
            len(b"Excel sheet data: a|b")
        )

    async def test_a_smaller_replacement_is_not_credited_below_zero(
        self, service, knowledge
    ):
        repo = service.info_blob_service.repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = _existing(
            service, "older rows"
        )
        repo.get_original.return_value = _attached(SHA_B, size=80_000)
        _patch_prepared(service, _prepared(SHA_A, size=50_000))

        assert await _publish(service, knowledge, _content())

        service.info_blob_service.quota_service.ensure_capacity.assert_awaited_once_with(
            len(b"Excel sheet data: a|b")
        )


class TestAttachedOriginalState:
    """Pure comparison of the attached bytes with the downloaded file."""

    def test_nothing_to_compare_without_bytes(self):
        state = SharePointContentService._attached_original_state
        assert state(None, None, None) is _AttachedOriginal.CURRENT
        assert state(_attached(SHA_A), None, None) is _AttachedOriginal.CURRENT

    def test_retained_bytes_match_or_replace_the_attached_ones(self):
        state = SharePointContentService._attached_original_state
        assert state(_attached(SHA_A), _prepared(SHA_A), SHA_A) is (
            _AttachedOriginal.CURRENT
        )
        assert state(_attached(SHA_B), _prepared(SHA_A), SHA_A) is (
            _AttachedOriginal.REPLACE
        )
        assert state(None, _prepared(SHA_A), SHA_A) is _AttachedOriginal.REPLACE
        assert state(_attached(SHA_A, usable=False), _prepared(SHA_A), SHA_A) is (
            _AttachedOriginal.REPLACE
        )

    def test_dropped_bytes_are_stale_only_when_they_differ(self):
        state = SharePointContentService._attached_original_state
        assert state(_attached(SHA_A), None, SHA_A) is _AttachedOriginal.CURRENT
        assert state(None, None, SHA_A) is _AttachedOriginal.CURRENT
        assert state(_attached(SHA_A, usable=False), None, SHA_B) is (
            _AttachedOriginal.CURRENT
        )
        assert state(_attached(SHA_B), None, SHA_A) is _AttachedOriginal.STALE


class TestStaleOriginal:
    """Changed bytes whose new form could not be kept must not stay attached.

    A large table is indexed as a sample, so an edit beyond the sample leaves
    the indexed text unchanged while the original is replaced; with the
    original dropped, the complete text is indexed instead and publication
    supersedes the version that held the old bytes. When even the complete
    text is unchanged (a formatting-only save), there is nothing to publish
    and the attached original is released outright.
    """

    SAMPLE = "File: sales.xlsx\n\nLarge table: 5000 rows."

    def _existing_with(self, service, attached, *, text):
        repo = service.info_blob_service.repo
        existing = _existing(service, text, size=100)
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = existing
        repo.get_original.return_value = attached
        return existing

    async def test_dropped_bytes_behind_an_unchanged_sample_republish_the_full_text(
        self, publishing_service, knowledge
    ):
        service = publishing_service
        self._existing_with(service, _attached(SHA_B, size=40_000), text=self.SAMPLE)
        _patch_prepared(service, _prepared(SHA_A, size=50_000))
        service.info_blob_service.quota_service.ensure_capacity.side_effect = (
            TenantQuotaExceededException("full")
        )

        assert await _publish(
            service, knowledge, _content(text="every row", index_text=self.SAMPLE)
        )

        publish = service.info_blob_service.publish_info_blob_without_validation
        publish.assert_awaited_once()
        assert publish.await_args.args[0].text == "every row"
        assert publish.await_args.kwargs["original"] is None
        service.info_blob_service.release_original_without_validation.assert_not_awaited()

    async def test_dropped_bytes_behind_unchanged_text_release_the_attached_original(
        self, publishing_service, knowledge
    ):
        service = publishing_service
        existing = self._existing_with(
            service, _attached(SHA_B, size=40_000), text="every row"
        )
        _patch_prepared(service, _prepared(SHA_A, size=50_000))
        service.info_blob_service.quota_service.ensure_capacity.side_effect = (
            TenantQuotaExceededException("full")
        )
        stats = _stats()

        assert await _publish(service, knowledge, _content(text="every row"), stats)

        service.info_blob_service.release_original_without_validation.assert_awaited_once_with(
            existing.id
        )
        service.info_blob_service.publish_info_blob_without_validation.assert_not_awaited()
        assert knowledge.size == 460
        service.integration_knowledge_repo.update.assert_awaited_once_with(
            obj=knowledge
        )
        reasons = [detail["reason"] for detail in stats["skipped_details"]]
        assert reasons[0] == "Original not kept: quota"
        assert reasons[1].startswith("Previous original removed")

    async def test_unchanged_bytes_skip_without_touching_the_original(
        self, publishing_service, knowledge
    ):
        service = publishing_service
        self._existing_with(service, _attached(BYTES_SHA, size=5), text=self.SAMPLE)
        _patch_prepared(service, _prepared(BYTES_SHA, size=5))

        assert await _publish(
            service, knowledge, _content(text="every row", index_text=self.SAMPLE)
        )

        service.info_blob_service.release_original_without_validation.assert_not_awaited()
        service.info_blob_service.publish_info_blob_without_validation.assert_not_awaited()
        service.info_blob_service.repo.update.assert_not_awaited()

    async def test_retained_changed_bytes_republish_the_unchanged_text(
        self, publishing_service, knowledge
    ):
        service = publishing_service
        self._existing_with(service, _attached(SHA_B, size=5), text=self.SAMPLE)
        prepared = _prepared(SHA_A, size=5)
        _patch_prepared(service, prepared)

        assert await _publish(
            service, knowledge, _content(text="every row", index_text=self.SAMPLE)
        )

        service.info_blob_service.release_original_without_validation.assert_not_awaited()
        publish = service.info_blob_service.publish_info_blob_without_validation
        publish.assert_awaited_once()
        assert publish.await_args.kwargs["original"] is prepared
        assert publish.await_args.kwargs["attach_original_in_place"] is True

    async def test_a_non_tabular_file_keeps_the_plain_hash_skip(
        self, publishing_service, knowledge
    ):
        service = publishing_service
        repo = service.info_blob_service.repo
        repo.get_by_sharepoint_item_and_integration_knowledge.return_value = _existing(
            service, "Slides", title="deck.pptx"
        )
        _patch_prepared(service, None)

        assert await _publish(
            service,
            knowledge,
            _content("deck.pptx", "Slides", data=None, content_type="pptx"),
        )

        repo.get_original.assert_not_awaited()
        service.info_blob_service.release_original_without_validation.assert_not_awaited()
        service.info_blob_service.publish_info_blob_without_validation.assert_not_awaited()


class TestCaptureFailures:
    async def test_storage_trouble_yields_no_original_and_a_note(self, service):
        from eneo.object_content.content import ObjectContentUnavailableError

        service._upload_admission = AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                knowledge_file_maximum_bytes=10,
                new_write_storage_target="postgres_inline",
                object_store_revision=None,
                policy_revision=1,
            )
        )
        stats = _stats()
        async with service._prepared_original(
            filename="big.xlsx", media_type=XLSX, data=b"x" * 11, stats=stats
        ) as original:
            assert original is None
        assert stats["skipped_details"][-1]["reason"].startswith("Original not kept:")

        service.object_content.ensure_target_ready = AsyncMock(
            side_effect=ObjectContentUnavailableError("store down")
        )
        async with service._prepared_original(
            filename="ok.xlsx", media_type=XLSX, data=b"x", stats=stats
        ) as original:
            assert original is None
        assert "store down" in stats["skipped_details"][-1]["reason"]

    async def test_without_a_content_store_nothing_is_captured(self, service):
        service.object_content = None
        async with service._prepared_original(
            filename="ok.xlsx", media_type=XLSX, data=b"x", stats=_stats()
        ) as original:
            assert original is None

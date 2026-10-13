"""Publishing one downloaded SharePoint file: originals, policy, fallbacks.

The service is built with mocked collaborators; ``_publish_file`` is the one
path all four sync call sites go through, so its rules are tested here once.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.domain.tabular_policy import TabularPolicy
from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointFileContent,
)
from eneo.main.exceptions import TenantQuotaExceededException

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
UNEXTRACTABLE = "[Could not extract text from Excel spreadsheet]"


@pytest.fixture
def knowledge():
    return SimpleNamespace(
        id=uuid4(),
        size=0,
        embedding_model=MagicMock(),
        tabular_policy=TabularPolicy.INDEX_AND_TOOL,
    )


@pytest.fixture
def service():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    info_blob_service = AsyncMock()
    info_blob_service.quota_service = AsyncMock()
    svc = SharePointContentService(
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
    svc._process_info_blob = AsyncMock()  # type: ignore[method-assign]
    return svc


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
    name="sales.xlsx", text="Excel sheet data: a|b", data=b"bytes", content_type="xlsx"
):
    return SharePointFileContent(
        text=text, content_type=content_type, file_name=name, data=data
    )


def _prepared(sha=b"\x01" * 32, size=5):
    return SimpleNamespace(captured=SimpleNamespace(sha256=sha, size_bytes=size))


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
        url="https://sharepoint.invalid/x",
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

        assert calls[0]["media_type"] == XLSX and calls[0]["data"] == b"bytes"
        published = _published(service)
        assert published["original"] is prepared
        assert published["index_text"] is True
        assert published["text"] == "Excel sheet data: a|b"

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
        assert published["original"] is None and published["index_text"] is True

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
        assert published["index_text"] is False


class TestTabularPolicy:
    async def test_tool_only_publishes_a_schema_stub_without_chunks(
        self, service, knowledge, monkeypatch
    ):
        knowledge.tabular_policy = TabularPolicy.TOOL_ONLY
        _patch_prepared(service, _prepared())
        monkeypatch.setattr(
            "eneo.integration.infrastructure.content_service.sharepoint_content_service."
            "build_tabular_placeholder_text",
            lambda name, data: "schema only",
        )

        assert await _publish(service, knowledge, _content())

        published = _published(service)
        assert published["text"] == "schema only"
        assert published["index_text"] is False
        assert published["original"] is not None

    async def test_tool_only_falls_back_to_indexing_when_no_original_is_kept(
        self, service, knowledge
    ):
        knowledge.tabular_policy = TabularPolicy.TOOL_ONLY
        _patch_prepared(service, None)

        assert await _publish(service, knowledge, _content())

        published = _published(service)
        assert published["original"] is None
        assert published["index_text"] is True
        assert published["text"] == "Excel sheet data: a|b"

    async def test_policy_does_not_touch_other_sources_files(self, service, knowledge):
        knowledge.tabular_policy = TabularPolicy.TOOL_ONLY
        _patch_prepared(service, None)

        assert await _publish(
            service,
            knowledge,
            _content("policy.docx", "Prose", data=None, content_type="docx"),
        )

        assert _published(service)["index_text"] is True


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
        assert published["original"] is None and published["index_text"] is True
        assert stats["skipped_details"] == [
            {"file": "sales.xlsx", "reason": "Original not kept: quota"}
        ]
        assert stats["skipped_items"] == 0
        service.info_blob_service.quota_service.ensure_capacity.assert_awaited_once_with(
            50_000 + len(b"Excel sheet data: a|b")
        )

    async def test_quota_overflow_under_tool_only_still_indexes_the_text(
        self, service, knowledge
    ):
        knowledge.tabular_policy = TabularPolicy.TOOL_ONLY
        _patch_prepared(service, _prepared())
        service.info_blob_service.quota_service.ensure_capacity.side_effect = (
            TenantQuotaExceededException("full")
        )

        assert await _publish(service, knowledge, _content())

        published = _published(service)
        assert published["index_text"] is True
        assert published["text"] == "Excel sheet data: a|b"


class TestUnchangedDocuments:
    async def test_hash_skip_requires_the_same_original_to_be_attached(
        self, service, knowledge
    ):
        existing = SimpleNamespace(id=uuid4())
        attached = SimpleNamespace(usable=True, sha256=b"\x01" * 32)
        service.info_blob_service.repo.get_original = AsyncMock(return_value=attached)

        assert await service._original_already_attached(existing, None)
        assert await service._original_already_attached(
            existing, _prepared(b"\x01" * 32)
        )
        assert not await service._original_already_attached(
            existing, _prepared(b"\x02" * 32)
        )
        service.info_blob_service.repo.get_original = AsyncMock(return_value=None)
        assert not await service._original_already_attached(
            existing, _prepared(b"\x01" * 32)
        )


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

"""Unit tests for S3-backed original-byte storage + signed file references (#1).

Covers the object-storage wrapper, the signed-token tenant/variant binding, the
LLM-facing reference block, and FileService's graceful-degradation upload path.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.signed_urls import (
    build_signed_download_url,
    generate_signed_token,
    verify_signed_token,
)
from eneo.completion_models.infrastructure.context_builder import (
    ContextBuilder,
    build_file_references_string,
)
from eneo.files.file_models import ContentDisposition, FileBaseWithContent, FileType
from eneo.files.file_service import FileService
from eneo.files.object_storage import FileObjectStorage, ObjectStorageError


def _s3_settings(configured: bool = True):
    return SimpleNamespace(
        file_storage_s3_endpoint_url="http://minio:9000" if configured else None,
        file_storage_s3_bucket="eneo" if configured else None,
        file_storage_s3_access_key="key" if configured else None,
        file_storage_s3_secret_key="secret" if configured else None,
        file_storage_s3_region="us-east-1",
        file_storage_s3_use_path_style=True,
    )


class TestFileObjectStorage:
    def test_is_configured_false_when_unset(self):
        assert (
            FileObjectStorage(_s3_settings(configured=False)).is_configured() is False
        )

    def test_is_configured_true_when_all_set(self):
        assert FileObjectStorage(_s3_settings()).is_configured() is True

    @pytest.mark.asyncio
    async def test_upload_raises_when_unconfigured(self):
        storage = FileObjectStorage(_s3_settings(configured=False))
        with pytest.raises(ObjectStorageError):
            await storage.upload("k", b"data", "application/pdf")

    @pytest.mark.asyncio
    async def test_delete_is_noop_when_unconfigured(self):
        storage = FileObjectStorage(_s3_settings(configured=False))
        await storage.delete("k")  # must not raise

    @pytest.mark.asyncio
    async def test_upload_puts_object(self, monkeypatch):
        storage = FileObjectStorage(_s3_settings())
        client = AsyncMock()

        @asynccontextmanager
        async def fake_client():
            yield client

        monkeypatch.setattr(storage, "_client", fake_client)
        await storage.upload("tenant/uuid/doc.pdf", b"bytes", "application/pdf")

        client.put_object.assert_awaited_once()
        kwargs = client.put_object.await_args.kwargs
        assert kwargs["Bucket"] == "eneo"
        assert kwargs["Key"] == "tenant/uuid/doc.pdf"
        assert kwargs["Body"] == b"bytes"

    @pytest.mark.asyncio
    async def test_open_stream_yields_body_chunks(self, monkeypatch):
        # The aiobotocore streaming body is iterated via iter_chunks(size); its
        # read() does not accept a size arg, so the generator must use iter_chunks.
        class _FakeBody:
            def iter_chunks(self, size):
                async def gen():
                    yield b"abc"
                    yield b"def"

                return gen()

        storage = FileObjectStorage(_s3_settings())
        client = AsyncMock()
        client.get_object = AsyncMock(return_value={"Body": _FakeBody()})

        @asynccontextmanager
        async def fake_client():
            yield client

        monkeypatch.setattr(storage, "_client", fake_client)
        out = b"".join([chunk async for chunk in storage.open_stream("k")])
        assert out == b"abcdef"

    @pytest.mark.asyncio
    async def test_upload_wraps_sdk_error(self, monkeypatch):
        storage = FileObjectStorage(_s3_settings())
        client = AsyncMock()
        client.put_object.side_effect = RuntimeError("boom")

        @asynccontextmanager
        async def fake_client():
            yield client

        monkeypatch.setattr(storage, "_client", fake_client)
        with pytest.raises(ObjectStorageError):
            await storage.upload("k", b"x", None)


class TestSignedTokenTenantAndVariant:
    def test_roundtrip_carries_tenant_and_variant(self):
        file_id, tenant_id = uuid4(), uuid4()
        token = generate_signed_token(
            file_id=file_id,
            expires_at=2_000_000_000,
            content_disposition=ContentDisposition.ATTACHMENT,
            tenant_id=tenant_id,
            variant="original",
        )
        payload = verify_signed_token(token)
        assert payload is not None
        assert payload["tenant_id"] == str(tenant_id)
        assert payload["variant"] == "original"

    def test_tampered_variant_is_rejected(self):
        token = generate_signed_token(
            file_id=uuid4(),
            expires_at=2_000_000_000,
            content_disposition=ContentDisposition.ATTACHMENT,
            tenant_id=uuid4(),
            variant="text",
        )
        message, signature = token.split(".")
        import base64
        import json

        payload = json.loads(base64.urlsafe_b64decode(message))
        payload["variant"] = "original"
        forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        assert verify_signed_token(f"{forged}.{signature}") is None

    def test_build_signed_download_url_defaults_to_original(self):
        file_id, tenant_id = uuid4(), uuid4()
        url = build_signed_download_url(
            file_id=file_id,
            base_url="https://eneo.example.se/",
            expires_in=3600,
            tenant_id=tenant_id,
        )
        assert url.startswith(
            f"https://eneo.example.se/api/v1/files/{file_id}/download/"
        )
        payload = verify_signed_token(url.split("token=")[1])
        assert payload["variant"] == "original"
        assert payload["tenant_id"] == str(tenant_id)


class TestFileReferencesString:
    def _file(self, file_id):
        return SimpleNamespace(
            id=file_id, name="report.pdf", mimetype="application/pdf", size=1234
        )

    def test_emits_entry_only_for_files_in_map(self):
        with_url, without_url = uuid4(), uuid4()
        files = [self._file(with_url), self._file(without_url)]
        block = build_file_references_string(files, {with_url: "https://x/dl"})
        assert "https://x/dl" in block
        assert block.count('"url"') == 1

    def test_empty_when_no_file_in_map(self):
        assert build_file_references_string([self._file(uuid4())], {}) == ""


class TestInlineFileTextToggle:
    def _file(self, file_id, text):
        return SimpleNamespace(
            id=file_id,
            name="doc.csv",
            text=text,
            mimetype="text/csv",
            size=999,
        )

    def test_inline_on_keeps_text_and_adds_url(self):
        fid = uuid4()
        out = ContextBuilder()._build_input(
            input_str="question",
            files=[self._file(fid, "row1,row2")],
            file_reference_urls={fid: "https://x/dl"},
            inline_file_text=True,
        )
        assert "row1,row2" in out  # extracted text inlined
        assert "https://x/dl" in out  # plus the fetchable URL

    def test_inline_off_drops_text_for_referenced_file(self):
        fid = uuid4()
        out = ContextBuilder()._build_input(
            input_str="question",
            files=[self._file(fid, "huge-csv-body")],
            file_reference_urls={fid: "https://x/dl"},
            inline_file_text=False,
        )
        assert "huge-csv-body" not in out  # text kept out of the context window
        assert "https://x/dl" in out  # only the URL is surfaced

    def test_inline_off_still_inlines_file_without_url(self):
        with_url, without_url = uuid4(), uuid4()
        out = ContextBuilder()._build_input(
            input_str="question",
            files=[
                self._file(with_url, "ALPHACONTENT"),
                self._file(without_url, "BETACONTENT"),
            ],
            file_reference_urls={with_url: "https://x/dl"},
            inline_file_text=False,
        )
        assert "ALPHACONTENT" not in out
        assert "BETACONTENT" in out  # no URL -> still inlined so model sees it


class TestFileServiceStorageOffload:
    def _service(self, storage):
        user = MagicMock(id=uuid4(), tenant_id=uuid4())
        repo = AsyncMock()
        repo.session = MagicMock()
        repo.add = AsyncMock(side_effect=lambda create: create)
        protocol = AsyncMock()
        file = FileBaseWithContent(
            name="doc.pdf",
            checksum="abc",
            size=10,
            file_type=FileType.TEXT,
            text="extracted",
        )
        protocol.to_domain_with_derivatives.return_value = (file, [])
        return FileService(
            user=user, repo=repo, protocol=protocol, object_storage=storage
        ), protocol

    @pytest.mark.asyncio
    async def test_persists_storage_key_on_success(self):
        storage = MagicMock()
        storage.is_configured.return_value = True
        storage.upload = AsyncMock()
        service, _ = self._service(storage)

        upload = MagicMock()
        upload.read = AsyncMock(return_value=b"pdf-bytes")
        upload.seek = AsyncMock()

        saved = await service.save_file(upload)
        storage.upload.assert_awaited_once()
        assert saved.storage_key is not None

    @pytest.mark.asyncio
    async def test_degrades_to_null_key_on_upload_error(self):
        storage = MagicMock()
        storage.is_configured.return_value = True
        storage.upload = AsyncMock(side_effect=ObjectStorageError("down"))
        service, _ = self._service(storage)

        upload = MagicMock()
        upload.read = AsyncMock(return_value=b"pdf-bytes")
        upload.seek = AsyncMock()

        saved = await service.save_file(upload)
        assert saved.storage_key is None

    @pytest.mark.asyncio
    async def test_stream_untouched_when_storage_unconfigured(self):
        storage = MagicMock()
        storage.is_configured.return_value = False
        service, protocol = self._service(storage)

        upload = MagicMock()
        upload.read = AsyncMock()

        saved = await service.save_file(upload)
        upload.read.assert_not_awaited()
        protocol.to_domain_with_derivatives.assert_awaited_once_with(upload)
        assert saved.storage_key is None

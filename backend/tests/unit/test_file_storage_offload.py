"""Unit tests for S3-backed original-byte storage + signed file references (#1).

Covers the object-storage wrapper, the signed-token tenant/variant binding, the
LLM-facing reference block, FileService's graceful-degradation upload path, the
URL-only send-path filtering, and the completion-layer mint audit.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import eneo.files.file_reference as file_reference_mod
from eneo.assistants.assistant_service import AssistantService
from eneo.audit.domain.action_types import ActionType
from eneo.authentication.signed_urls import (
    build_signed_download_url,
    generate_signed_token,
    verify_signed_token,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import (
    ContextBuilder,
    build_file_references_string,
)
from eneo.files.file_models import (
    ContentDisposition,
    FileBaseWithContent,
    FileType,
    SignedURLRequest,
)
from eneo.files.file_reference import url_only_file_ids
from eneo.files.file_router import generate_signed_url
from eneo.files.file_service import FileService
from eneo.files.object_storage import FileObjectStorage, ObjectStorageError
from eneo.main.exceptions import FileTooLargeException, NotFoundException


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
    def _service(self, storage, tmp_path=None):
        """FileService with a fake protocol that mimics the real temp-file
        window: when the caller passes an on_disk_hook, it is invoked with a
        real on-disk copy of the upload, exactly once, after 'validation'."""
        user = MagicMock(id=uuid4(), tenant_id=uuid4())
        repo = AsyncMock()
        repo.session = MagicMock()
        repo.add = AsyncMock(side_effect=lambda create: create)
        file = FileBaseWithContent(
            name="doc.pdf",
            checksum="abc",
            size=10,
            file_type=FileType.TEXT,
            text="extracted",
        )

        async def fake_to_domain(upload, on_disk_hook=None):
            if on_disk_hook is not None:
                assert tmp_path is not None
                filepath = tmp_path / "upload.bin"
                filepath.write_bytes(b"pdf-bytes")
                on_disk_hook(filepath)
            return (file, [])

        protocol = AsyncMock()
        protocol.to_domain_with_derivatives = AsyncMock(side_effect=fake_to_domain)
        return FileService(
            user=user, repo=repo, protocol=protocol, object_storage=storage
        ), protocol

    def _upload(self):
        upload = MagicMock()
        upload.read = AsyncMock(return_value=b"pdf-bytes")
        upload.seek = AsyncMock()
        return upload

    @pytest.mark.asyncio
    async def test_persists_storage_key_on_success(self, tmp_path):
        storage = MagicMock()
        storage.is_configured.return_value = True
        storage.upload = AsyncMock()
        service, _ = self._service(storage, tmp_path)

        saved = await service.save_file(self._upload())
        storage.upload.assert_awaited_once()
        assert storage.upload.await_args.args[1] == b"pdf-bytes"
        assert saved.storage_key is not None

    @pytest.mark.asyncio
    async def test_degrades_to_null_key_on_upload_error(self, tmp_path):
        storage = MagicMock()
        storage.is_configured.return_value = True
        storage.upload = AsyncMock(side_effect=ObjectStorageError("down"))
        service, _ = self._service(storage, tmp_path)

        saved = await service.save_file(self._upload())
        assert saved.storage_key is None

    @pytest.mark.asyncio
    async def test_stream_untouched_when_storage_unconfigured(self):
        storage = MagicMock()
        storage.is_configured.return_value = False
        service, protocol = self._service(storage)

        upload = self._upload()
        saved = await service.save_file(upload)
        upload.read.assert_not_awaited()
        protocol.to_domain_with_derivatives.assert_awaited_once_with(
            upload, on_disk_hook=None
        )
        assert saved.storage_key is None

    @pytest.mark.asyncio
    async def test_never_buffers_upload_before_validation(self, tmp_path):
        # The offload bytes come from the protocol's temp file via the hook,
        # which only runs after the size guard: an oversized upload must be
        # rejected without the service ever allocating the raw bytes.
        storage = MagicMock()
        storage.is_configured.return_value = True
        storage.upload = AsyncMock()
        service, protocol = self._service(storage, tmp_path)
        protocol.to_domain_with_derivatives = AsyncMock(
            side_effect=FileTooLargeException(file_size=999, max_size=10)
        )

        upload = self._upload()
        with pytest.raises(FileTooLargeException):
            await service.save_file(upload)
        upload.read.assert_not_awaited()
        storage.upload.assert_not_awaited()


def _reference_settings(base_url: str | None = "http://host.docker.internal:8123"):
    return SimpleNamespace(file_reference_base_url=base_url, public_origin=None)


def _stub_file(
    file_type: FileType = FileType.TEXT,
    storage_key: str | None = "tenant/uuid/doc.csv",
    parent_file_id=None,
    name: str = "doc.csv",
):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        file_type=file_type,
        storage_key=storage_key,
        parent_file_id=parent_file_id,
    )


class TestUrlOnlyFileIds:
    def test_empty_when_inlining_enabled(self, monkeypatch):
        monkeypatch.setattr(
            file_reference_mod, "get_settings", lambda: _reference_settings()
        )
        assert url_only_file_ids([_stub_file()], inline_file_text=True) == set()

    def test_empty_without_base_url(self, monkeypatch):
        monkeypatch.setattr(
            file_reference_mod,
            "get_settings",
            lambda: _reference_settings(base_url=None),
        )
        assert url_only_file_ids([_stub_file()], inline_file_text=False) == set()

    def test_selects_only_stored_text_files(self, monkeypatch):
        monkeypatch.setattr(
            file_reference_mod, "get_settings", lambda: _reference_settings()
        )
        stored_text = _stub_file()
        unstored_text = _stub_file(storage_key=None)
        stored_image = _stub_file(file_type=FileType.IMAGE, storage_key="k")

        ids = url_only_file_ids(
            [stored_text, unstored_text, stored_image], inline_file_text=False
        )
        assert ids == {stored_text.id}


class TestSendPathUrlOnlyFiltering:
    """URL-only parents keep their text out of context (context_builder) — these
    tests pin that their derived vision images stay out of the request too."""

    @pytest.mark.asyncio
    async def test_message_derived_images_dropped_for_url_only_parent(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            file_reference_mod, "get_settings", lambda: _reference_settings()
        )
        stored_parent = _stub_file()
        plain_parent = _stub_file(storage_key=None, name="small.pdf")
        stored_derived = _stub_file(
            file_type=FileType.IMAGE,
            storage_key=None,
            parent_file_id=stored_parent.id,
        )
        plain_derived = _stub_file(
            file_type=FileType.IMAGE,
            storage_key=None,
            parent_file_id=plain_parent.id,
        )

        service = MagicMock()
        service._completion_prompt_files_for_model = AsyncMock(return_value=[])
        service._attach_history_derivatives = AsyncMock()
        service.file_service.with_derived_images = AsyncMock(
            return_value=[stored_parent, plain_parent, stored_derived, plain_derived]
        )

        result = await AssistantService._build_completion_file_inputs(
            service,
            files=[stored_parent, plain_parent],
            session=SimpleNamespace(questions=[]),
            assistant=SimpleNamespace(attachments=[], inline_file_text=False),
            completion_model=SimpleNamespace(vision=True),
        )

        # The stored parent stays (it becomes the URL reference block), but its
        # rendered images are dropped; the un-stored document keeps its images.
        assert stored_parent in result.completion_message_files
        assert stored_derived not in result.completion_message_files
        assert plain_derived in result.completion_message_files

    @pytest.mark.asyncio
    async def test_history_derivatives_skip_url_only_parents(self, monkeypatch):
        monkeypatch.setattr(
            file_reference_mod, "get_settings", lambda: _reference_settings()
        )
        stored_parent = _stub_file()
        plain_parent = _stub_file(storage_key=None, name="small.pdf")
        question = SimpleNamespace(files=[stored_parent, plain_parent])
        session = SimpleNamespace(questions=[question])

        plain_derived = _stub_file(
            file_type=FileType.IMAGE,
            storage_key=None,
            parent_file_id=plain_parent.id,
        )
        service = MagicMock()
        service.file_service.get_derived_images = AsyncMock(
            return_value=[plain_derived]
        )

        await AssistantService._attach_history_derivatives(
            service, session=session, inline_file_text=False
        )

        lookup = service.file_service.get_derived_images.await_args.kwargs
        assert lookup["parent_ids"] == [plain_parent.id]
        assert plain_derived in question.files

    @pytest.mark.asyncio
    async def test_fit_guard_ignores_url_only_uploads(self, monkeypatch):
        monkeypatch.setattr(
            file_reference_mod, "get_settings", lambda: _reference_settings()
        )
        stored = _stub_file(name="huge.csv")
        plain = _stub_file(storage_key=None, name="small.pdf")

        service = MagicMock()
        service._completion_prompt_files_for_model = AsyncMock(return_value=[])
        service.file_service.with_derived_images = AsyncMock(
            side_effect=lambda files: files
        )
        service._assert_files_fit_context = MagicMock()

        await AssistantService._assert_message_attachments_fit(
            service,
            assistant=SimpleNamespace(attachments=[], inline_file_text=False),
            model=SimpleNamespace(vision=True),
            prompt_text="prompt",
            files=[stored, plain],
        )

        counted = service._assert_files_fit_context.call_args.kwargs["files"]
        assert stored not in counted
        assert plain in counted


class TestCompletionMintAudit:
    def _user(self):
        return SimpleNamespace(
            id=uuid4(),
            username="anna",
            email="anna@kommun.se",
            active_api_key=None,
        )

    def _service(self, audit_service, user="default"):
        return CompletionService(
            context_builder=MagicMock(),
            tenant=SimpleNamespace(id=uuid4(), name="Kommun"),
            user=self._user() if user == "default" else user,
            config=SimpleNamespace(file_reference_url_expiry_seconds=3600),
            encryption_service=MagicMock(),
            audit_service=audit_service,
        )

    @pytest.mark.asyncio
    async def test_audits_only_current_turn_minted_files(self):
        audit_service = AsyncMock()
        service = self._service(audit_service)

        minted = _stub_file()
        unminted = _stub_file(storage_key=None)
        history_id = uuid4()
        urls = {minted.id: "https://x/dl", history_id: "https://x/dl2"}

        await service._audit_file_reference_mints(
            files=[minted, unminted],
            file_reference_urls=urls,
            session=SimpleNamespace(id=uuid4()),
        )

        audit_service.log_async.assert_awaited_once()
        kwargs = audit_service.log_async.await_args.kwargs
        assert kwargs["action"] == ActionType.FILE_SIGNED_URL_MINTED
        assert kwargs["entity_id"] == minted.id
        assert kwargs["metadata"]["extra"]["source"] == "completion"

    @pytest.mark.asyncio
    async def test_skipped_without_user(self):
        audit_service = AsyncMock()
        service = self._service(audit_service, user=None)
        minted = _stub_file()

        await service._audit_file_reference_mints(
            files=[minted],
            file_reference_urls={minted.id: "https://x/dl"},
            session=None,
        )

        audit_service.log_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noop_without_audit_service(self):
        service = self._service(audit_service=None)
        minted = _stub_file()

        await service._audit_file_reference_mints(
            files=[minted],
            file_reference_urls={minted.id: "https://x/dl"},
            session=None,
        )  # must not raise


class TestSignedUrlEndpointAudit:
    """The manual mint endpoint must write a FILE_SIGNED_URL_MINTED audit row
    using an owner-checked, metadata-only lookup (no text/blob columns)."""

    def _container(self, files):
        container = MagicMock()
        file_service = MagicMock()
        file_service.get_file_infos = AsyncMock(return_value=files)
        container.file_service.return_value = file_service
        container.user.return_value = SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            username="anna",
            email="anna@kommun.se",
        )
        audit_service = MagicMock()
        audit_service.log_async = AsyncMock()
        container.audit_service.return_value = audit_service
        return container, file_service, audit_service

    def _request(self):
        return SimpleNamespace(base_url="http://testserver/")

    @pytest.mark.asyncio
    async def test_minting_writes_audit_row(self):
        file_info = SimpleNamespace(id=uuid4(), name="doc.pdf")
        container, file_service, audit_service = self._container([file_info])

        response = await generate_signed_url(
            id=file_info.id,
            request=self._request(),
            signed_url_req=SignedURLRequest(),
            container=container,
        )

        file_service.get_file_infos.assert_awaited_once_with(file_ids=[file_info.id])
        audit_service.log_async.assert_awaited_once()
        kwargs = audit_service.log_async.await_args.kwargs
        assert kwargs["action"] == ActionType.FILE_SIGNED_URL_MINTED
        assert kwargs["entity_id"] == file_info.id
        assert kwargs["metadata"]["target"]["name"] == "doc.pdf"
        assert response.url.startswith(
            f"http://testserver/api/v1/files/{file_info.id}/download/"
        )

    @pytest.mark.asyncio
    async def test_missing_file_is_404_and_unaudited(self):
        container, _, audit_service = self._container([])

        with pytest.raises(NotFoundException):
            await generate_signed_url(
                id=uuid4(),
                request=self._request(),
                signed_url_req=SignedURLRequest(),
                container=container,
            )
        audit_service.log_async.assert_not_awaited()


class TestBuildFileReferenceUrlsTextOnly:
    @pytest.mark.asyncio
    async def test_mints_only_for_stored_text_files(self):
        service = CompletionService(
            context_builder=MagicMock(),
            tenant=SimpleNamespace(id=uuid4()),
            user=None,
            config=SimpleNamespace(
                file_reference_base_url="http://host.docker.internal:8123",
                public_origin=None,
                file_reference_url_expiry_seconds=3600,
            ),
            encryption_service=MagicMock(),
        )
        stored_text = _stub_file()
        stored_image = _stub_file(file_type=FileType.IMAGE, storage_key="k")

        urls = service._build_file_reference_urls([stored_text, stored_image])
        assert set(urls) == {stored_text.id}

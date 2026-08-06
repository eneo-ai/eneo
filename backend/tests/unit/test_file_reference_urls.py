"""Unit tests for signed file references surfaced to the LLM/MCP context.

Covers the tenant claim on signed download tokens, the original-download URL
builder, the LLM-facing reference block, the URL-only send-path filtering, and
the completion-layer mint audit. Original bytes themselves are stored by the
object-content subsystem; these tests only exercise the reference surface.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import eneo.files.file_reference as file_reference_mod
from eneo.assistants.assistant_service import AssistantService
from eneo.audit.domain.action_types import ActionType
from eneo.authentication.signed_urls import (
    build_signed_original_download_url,
    generate_file_original_download_token,
    generate_signed_token,
    verify_file_original_download_token,
    verify_signed_token,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import (
    ContextBuilder,
    build_file_references_string,
)
from eneo.files.file_models import (
    FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
    ContentDisposition,
    FileType,
)
from eneo.files.file_reference import url_only_file_ids
from eneo.files.file_service import FileService
from eneo.main.exceptions import UnauthorizedException


class TestSignedTokenTenantClaim:
    def test_legacy_roundtrip_carries_tenant(self):
        file_id, tenant_id = uuid4(), uuid4()
        token = generate_signed_token(
            file_id=file_id,
            expires_at=2_000_000_000,
            content_disposition=ContentDisposition.ATTACHMENT,
            tenant_id=tenant_id,
        )
        payload = verify_signed_token(token)
        assert payload is not None
        assert payload["tenant_id"] == str(tenant_id)

    def test_original_roundtrip_carries_tenant(self):
        file_id, tenant_id = uuid4(), uuid4()
        token = generate_file_original_download_token(
            file_id=file_id,
            expires_at=2_000_000_000,
            content_disposition=ContentDisposition.ATTACHMENT,
            tenant_id=tenant_id,
        )
        payload = verify_file_original_download_token(token)
        assert payload is not None
        assert payload["tenant_id"] == str(tenant_id)

    def test_tampered_tenant_is_rejected(self):
        token = generate_signed_token(
            file_id=uuid4(),
            expires_at=2_000_000_000,
            content_disposition=ContentDisposition.ATTACHMENT,
            tenant_id=uuid4(),
        )
        message, signature = token.split(".")
        import base64
        import json

        payload = json.loads(base64.urlsafe_b64decode(message))
        payload["tenant_id"] = str(uuid4())
        forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        assert verify_signed_token(f"{forged}.{signature}") is None

    def test_download_refuses_tenant_mismatch(self):
        metadata = SimpleNamespace(tenant_id=uuid4())
        with pytest.raises(UnauthorizedException):
            FileService._require_token_tenant(metadata, uuid4())

    def test_download_accepts_matching_or_absent_tenant(self):
        tenant_id = uuid4()
        metadata = SimpleNamespace(tenant_id=tenant_id)
        FileService._require_token_tenant(metadata, tenant_id)
        FileService._require_token_tenant(metadata, None)


class TestBuildSignedOriginalDownloadUrl:
    def test_url_targets_original_download_endpoint(self):
        file_id, tenant_id = uuid4(), uuid4()
        url = build_signed_original_download_url(
            file_id=file_id,
            base_url="https://eneo.example.se/",
            expires_in=3600,
            tenant_id=tenant_id,
        )
        assert url.startswith(
            f"https://eneo.example.se/api/v1/files/{file_id}/original/download/"
        )
        payload = verify_file_original_download_token(url.split("token=")[1])
        assert payload is not None
        assert payload["tenant_id"] == str(tenant_id)

    def test_expiry_is_clamped_to_token_maximum(self):
        url = build_signed_original_download_url(
            file_id=uuid4(),
            base_url="https://eneo.example.se",
            expires_in=10 * FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS,
        )
        payload = verify_file_original_download_token(url.split("token=")[1])
        assert payload is not None
        import time

        assert payload["expires_at"] <= (
            int(time.time()) + FILE_ORIGINAL_SIGNED_URL_MAXIMUM_EXPIRY_SECONDS + 5
        )


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


def _reference_settings(base_url: str | None = "http://host.docker.internal:8123"):
    return SimpleNamespace(file_reference_base_url=base_url, public_origin=None)


def _stub_file(
    file_type: FileType = FileType.TEXT,
    original_available: bool = True,
    parent_file_id: UUID | None = None,
    name: str = "doc.csv",
):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        file_type=file_type,
        original_available=original_available,
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

    def test_selects_only_text_files_with_original(self, monkeypatch):
        monkeypatch.setattr(
            file_reference_mod, "get_settings", lambda: _reference_settings()
        )
        text_with_original = _stub_file()
        text_without_original = _stub_file(original_available=False)
        image_with_original = _stub_file(file_type=FileType.IMAGE)

        ids = url_only_file_ids(
            [text_with_original, text_without_original, image_with_original],
            inline_file_text=False,
        )
        assert ids == {text_with_original.id}


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
        plain_parent = _stub_file(original_available=False, name="small.pdf")
        stored_derived = _stub_file(
            file_type=FileType.IMAGE,
            original_available=False,
            parent_file_id=stored_parent.id,
        )
        plain_derived = _stub_file(
            file_type=FileType.IMAGE,
            original_available=False,
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
        plain_parent = _stub_file(original_available=False, name="small.pdf")
        question = SimpleNamespace(files=[stored_parent, plain_parent])
        session = SimpleNamespace(questions=[question])

        plain_derived = _stub_file(
            file_type=FileType.IMAGE,
            original_available=False,
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
        import eneo.assistants.assistant_service as assistant_service_mod

        monkeypatch.setattr(
            file_reference_mod, "get_settings", lambda: _reference_settings()
        )
        fit_check = MagicMock()
        monkeypatch.setattr(
            assistant_service_mod,
            "assert_prompt_and_files_fit_context",
            fit_check,
        )
        stored = _stub_file(name="huge.csv")
        plain = _stub_file(original_available=False, name="small.pdf")

        service = MagicMock()
        service._completion_prompt_files_for_model = AsyncMock(return_value=[])
        service.file_service.with_derived_images = AsyncMock(
            side_effect=lambda files: files
        )

        await AssistantService._assert_message_attachments_fit(
            service,
            assistant=SimpleNamespace(attachments=[], inline_file_text=False),
            model=SimpleNamespace(vision=True, max_input_tokens=100_000, name="gpt-4o"),
            prompt_text="prompt",
            files=[stored, plain],
        )

        counted = fit_check.call_args.kwargs["files"]
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
        unminted = _stub_file(original_available=False)
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


class TestBuildFileReferenceUrls:
    def _service(self, base_url="http://host.docker.internal:8123", tenant="default"):
        return CompletionService(
            context_builder=MagicMock(),
            tenant=SimpleNamespace(id=uuid4()) if tenant == "default" else tenant,
            user=None,
            config=SimpleNamespace(
                file_reference_base_url=base_url,
                public_origin=None,
                file_reference_url_expiry_seconds=3600,
            ),
            encryption_service=MagicMock(),
        )

    def test_mints_only_for_text_files_with_original(self):
        service = self._service()
        text_with_original = _stub_file()
        image_with_original = _stub_file(file_type=FileType.IMAGE)
        text_without_original = _stub_file(original_available=False)

        urls = service._build_file_reference_urls(
            [text_with_original, image_with_original, text_without_original]
        )
        assert set(urls) == {text_with_original.id}
        assert "/original/download/" in urls[text_with_original.id]

    def test_empty_without_base_url(self):
        assert (
            self._service(base_url=None)._build_file_reference_urls([_stub_file()])
            == {}
        )

    def test_empty_without_tenant(self):
        assert (
            self._service(tenant=None)._build_file_reference_urls([_stub_file()]) == {}
        )

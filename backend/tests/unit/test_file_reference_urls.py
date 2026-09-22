"""Unit tests for signed file references surfaced to the LLM/MCP context.

Covers the tenant claim on signed download tokens, the original-download URL
builder, the LLM-facing reference block, the URL-only send-path filtering, and
the completion-layer mint audit. Original bytes themselves are stored by the
object-content subsystem; these tests only exercise the reference surface.
"""

import json
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
from eneo.files.file_reference import (
    image_reference_file_ids,
    reference_url_file_ids,
    referenced_file_ids,
    url_only_file_ids,
)
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
            id=file_id,
            name="report.pdf",
            mimetype="application/pdf",
            size=1234,
            file_type=FileType.TEXT,
        )

    def test_emits_entry_only_for_files_in_map(self):
        with_url, without_url = uuid4(), uuid4()
        files = [self._file(with_url), self._file(without_url)]
        block = build_file_references_string(files, {with_url: "https://x/dl"})
        assert "https://x/dl" in block
        assert block.count('"url":') == 1

    def test_empty_when_no_file_in_map(self):
        assert build_file_references_string([self._file(uuid4())], {}) == ""

    def test_preamble_carries_mechanics_only(self):
        # The block repeats per message with referenced files (history
        # included), so it states what the entries are and that the bytes are
        # absent; the tool-arbitration rules live in the system prompt
        # (ATTACHED_FILE_REFERENCES_INSTRUCTION), stated once per request.
        fid = uuid4()
        block = build_file_references_string([self._file(fid)], {fid: "https://x/dl"})
        assert "signed file reference" in block
        assert "raw bytes are NOT in this prompt" in block
        assert "read_file" not in block
        assert "re-upload" not in block


class TestInlineFileTextToggle:
    def _file(self, file_id, text):
        return SimpleNamespace(
            id=file_id,
            name="doc.csv",
            text=text,
            mimetype="text/csv",
            size=999,
            file_type=FileType.TEXT,
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


def _enable_file_references(
    monkeypatch,
    base_url: str | None = "http://host.docker.internal:8123",
):
    """Put the deployment in the state URL-only mode requires: a reference base
    URL to mint against. Storage is not part of it: which store holds a file's
    original is already folded into ``original_available``."""
    monkeypatch.setattr(
        file_reference_mod, "get_settings", lambda: _reference_settings(base_url)
    )


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
        _enable_file_references(monkeypatch)
        assert url_only_file_ids([_stub_file()], inline_file_text=True) == set()

    def test_empty_without_base_url(self, monkeypatch):
        _enable_file_references(monkeypatch, base_url=None)
        assert url_only_file_ids([_stub_file()], inline_file_text=False) == set()

    def test_needs_no_object_store(self, monkeypatch):
        """A PostgreSQL-backed original is URL-only exactly like an object-store
        one: the predicate reads the per-file flag and never asks the storage
        runtime, so the toggle works in deployments without any object store."""
        _enable_file_references(monkeypatch)
        stored = _stub_file()
        assert url_only_file_ids([stored], inline_file_text=False) == {stored.id}

    def test_selects_only_text_files_with_original(self, monkeypatch):
        _enable_file_references(monkeypatch)
        text_with_original = _stub_file()
        text_without_original = _stub_file(original_available=False)
        image_with_original = _stub_file(file_type=FileType.IMAGE)

        ids = url_only_file_ids(
            [text_with_original, text_without_original, image_with_original],
            inline_file_text=False,
        )
        assert ids == {text_with_original.id}


class TestReferencedFileIds:
    """Files a signed reference URL can serve, independent of inlining mode.

    ``url_only_file_ids`` must always be this set gated on inlining being off,
    so the two predicates cannot drift apart across the send path, preflight
    count, and fit guard.
    """

    def test_ignores_the_inlining_mode(self, monkeypatch):
        _enable_file_references(monkeypatch)
        stored = _stub_file()

        ids = referenced_file_ids([stored, _stub_file(original_available=False)])

        assert ids == {stored.id}
        assert url_only_file_ids([stored], inline_file_text=True) == set()
        assert url_only_file_ids([stored], inline_file_text=False) == ids

    def test_empty_without_base_url(self, monkeypatch):
        _enable_file_references(monkeypatch, base_url=None)
        assert referenced_file_ids([_stub_file()]) == set()

    def test_unreadable_original_is_never_referenced(self, monkeypatch):
        """``original_available`` is the loader's verdict that the bytes can be
        served (object-store rows without a connected store are not); a file
        it left unavailable inlines instead of getting a dead link."""
        _enable_file_references(monkeypatch)
        assert referenced_file_ids([_stub_file(original_available=False)]) == set()


class TestSendPathUrlOnlyFiltering:
    """URL-only parents keep their text out of context (context_builder) — these
    tests pin that their derived vision images stay out of the request too."""

    @pytest.mark.asyncio
    async def test_message_derived_images_dropped_for_url_only_parent(
        self, monkeypatch
    ):
        _enable_file_references(monkeypatch)
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
            assistant=SimpleNamespace(
                attachments=[],
                inline_file_text=False,
                url_only_attachment_ids=lambda model: set(),
            ),
            completion_model=SimpleNamespace(vision=True),
        )

        # The stored parent stays (it becomes the URL reference block), but its
        # rendered images are dropped; the un-stored document keeps its images.
        assert stored_parent in result.completion_message_files
        assert stored_derived not in result.completion_message_files
        assert plain_derived in result.completion_message_files

    @pytest.mark.asyncio
    async def test_history_derivatives_skip_url_only_parents(self, monkeypatch):
        _enable_file_references(monkeypatch)
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

        _enable_file_references(monkeypatch)
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
            assistant=SimpleNamespace(
                attachments=[],
                inline_file_text=False,
                url_only_attachment_ids=lambda model: set(),
            ),
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

    def test_mints_for_text_and_image_files_with_original(self, monkeypatch):
        _enable_file_references(monkeypatch)
        service = self._service()
        text_with_original = _stub_file()
        image_with_original = _stub_file(file_type=FileType.IMAGE)
        derived_page = _stub_file(file_type=FileType.IMAGE, parent_file_id=uuid4())
        text_without_original = _stub_file(original_available=False)

        urls = service._build_file_reference_urls(
            [
                text_with_original,
                image_with_original,
                derived_page,
                text_without_original,
            ]
        )
        assert set(urls) == {text_with_original.id, image_with_original.id}
        assert "/original/download/" in urls[text_with_original.id]
        assert "/original/download/" in urls[image_with_original.id]

    def test_empty_without_base_url(self):
        assert (
            self._service(base_url=None)._build_file_reference_urls([_stub_file()])
            == {}
        )

    def test_empty_without_tenant(self):
        assert (
            self._service(tenant=None)._build_file_reference_urls([_stub_file()]) == {}
        )


class TestImageReferenceFileIds:
    def test_attached_and_generated_images_are_referenced(self, monkeypatch):
        _enable_file_references(monkeypatch)
        uploaded = _stub_file(file_type=FileType.IMAGE, name="photo.png")
        generated = _stub_file(file_type=FileType.IMAGE, name="generated_image.png")
        derived_page = _stub_file(
            file_type=FileType.IMAGE, parent_file_id=uuid4(), name="page-1.png"
        )
        unavailable = _stub_file(file_type=FileType.IMAGE, original_available=False)
        text = _stub_file()

        ids = image_reference_file_ids(
            [uploaded, generated, derived_page, unavailable, text]
        )

        assert ids == {uploaded.id, generated.id}

    def test_empty_without_base_url(self, monkeypatch):
        _enable_file_references(monkeypatch, base_url=None)
        assert image_reference_file_ids([_stub_file(file_type=FileType.IMAGE)]) == set()

    def test_reference_url_ids_union_text_and_images(self, monkeypatch):
        _enable_file_references(monkeypatch)
        text, image = _stub_file(), _stub_file(file_type=FileType.IMAGE)
        assert reference_url_file_ids([text, image]) == {text.id, image.id}
        # The files-server gate stays TEXT-only.
        assert referenced_file_ids([text, image]) == {text.id}


class TestImageReferenceRendering:
    def _image(self, file_id):
        return SimpleNamespace(
            id=file_id,
            name="photo.png",
            mimetype="image/png",
            size=4321,
            file_type=FileType.IMAGE,
            text=None,
        )

    def test_entries_carry_their_kind(self):
        image_id, doc_id = uuid4(), uuid4()
        doc = SimpleNamespace(
            id=doc_id,
            name="report.pdf",
            mimetype="application/pdf",
            size=1,
            file_type=FileType.TEXT,
        )
        block = build_file_references_string(
            [self._image(image_id), doc],
            {image_id: "https://x/i", doc_id: "https://x/d"},
        )
        lines = [json.loads(line) for line in block.split("\n\n", 1)[1].splitlines()]
        assert [(entry["kind"], entry["url"]) for entry in lines] == [
            ("image", "https://x/i"),
            ("document", "https://x/d"),
        ]

    def test_image_gets_a_reference_entry_but_no_inline_text(self):
        image_id = uuid4()
        out = ContextBuilder()._build_input(
            input_str="make it blue",
            files=[self._image(image_id)],
            file_reference_urls={image_id: "https://x/i"},
        )
        assert '"kind": "image"' in out
        assert "https://x/i" in out
        assert out.endswith("make it blue")
        # Images carry no text to inline; the reference block is the only addition.
        assert out.count("photo.png") == 1


class TestGeneratedImageMintAudit:
    async def test_previous_turn_generated_images_are_audited_once(self, monkeypatch):
        _enable_file_references(monkeypatch)
        audit_service = AsyncMock()
        service = CompletionService(
            context_builder=MagicMock(),
            tenant=SimpleNamespace(id=uuid4(), name="Kommun"),
            user=SimpleNamespace(
                id=uuid4(), username="anna", email="anna@kommun.se", active_api_key=None
            ),
            config=SimpleNamespace(
                file_reference_base_url="http://host.docker.internal:8123",
                public_origin=None,
                file_reference_url_expiry_seconds=3600,
            ),
            encryption_service=MagicMock(),
            audit_service=audit_service,
        )
        older = _stub_file(file_type=FileType.IMAGE, name="generated_image.png")
        latest = _stub_file(file_type=FileType.IMAGE, name="generated_image.png")
        session = SimpleNamespace(
            id=uuid4(),
            questions=[
                SimpleNamespace(files=[], generated_files=[older]),
                SimpleNamespace(files=[], generated_files=[latest]),
            ],
        )
        history_files = [
            file
            for question in session.questions
            for file in [*question.files, *question.generated_files]
        ]
        urls = service._build_file_reference_urls(history_files)
        assert set(urls) == {older.id, latest.id}

        await service._audit_file_reference_mints(
            files=[*session.questions[-1].generated_files],
            file_reference_urls=urls,
            session=session,
        )

        audited = [
            c.kwargs["entity_id"] for c in audit_service.log_async.await_args_list
        ]
        assert audited == [latest.id]


def _content_file(
    *,
    file_type: FileType = FileType.TEXT,
    name: str = "kontoplan.xlsx",
    text: str = "konto 1910 kassa",
    parent_file_id: UUID | None = None,
    original_available: bool = True,
):
    from datetime import datetime, timezone

    from eneo.files.file_models import File

    now = datetime.now(timezone.utc)
    return File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name=name,
        checksum="0",
        size=len(text),
        mimetype="text/plain" if file_type == FileType.TEXT else "image/png",
        file_type=file_type,
        text=text if file_type == FileType.TEXT else None,
        blob=None if file_type == FileType.TEXT else b"",
        user_id=uuid4(),
        tenant_id=uuid4(),
        parent_file_id=parent_file_id,
        original_available=original_available,
    )


class TestUrlOnlyAttachmentIds:
    """Persistent attachments carry a per-file mode instead of the toggle."""

    def test_only_open_with_tool_attachments_with_original_are_url_only(
        self, monkeypatch
    ):
        _enable_file_references(monkeypatch)
        tool_file, prompt_file, legacy = (
            _stub_file(),
            _stub_file(),
            _stub_file(original_available=False),
        )
        model = SimpleNamespace(supports_tool_calling=True)

        result = file_reference_mod.url_only_attachment_ids(
            [tool_file, prompt_file, legacy],
            {tool_file.id: False, legacy.id: False},
            model,
        )

        assert result == {tool_file.id}

    def test_empty_for_model_without_tool_calling(self, monkeypatch):
        _enable_file_references(monkeypatch)
        tool_file = _stub_file()

        result = file_reference_mod.url_only_attachment_ids(
            [tool_file],
            {tool_file.id: False},
            SimpleNamespace(supports_tool_calling=False),
        )

        assert result == set()

    def test_empty_without_base_url(self, monkeypatch):
        _enable_file_references(monkeypatch, base_url=None)
        tool_file = _stub_file()

        result = file_reference_mod.url_only_attachment_ids(
            [tool_file],
            {tool_file.id: False},
            SimpleNamespace(supports_tool_calling=True),
        )

        assert result == set()

    def test_inlined_attachments_drop_url_only_files_and_their_pages(self):
        tool_file, prompt_file = _stub_file(), _stub_file()
        tool_page = _stub_file(file_type=FileType.IMAGE, parent_file_id=tool_file.id)
        prompt_page = _stub_file(
            file_type=FileType.IMAGE, parent_file_id=prompt_file.id
        )

        result = file_reference_mod.inlined_attachments(
            [tool_file, prompt_file, tool_page, prompt_page], {tool_file.id}
        )

        assert result == [prompt_file, prompt_page]

    def test_inlined_attachments_untouched_without_url_only_ids(self):
        files = [_stub_file(), _stub_file()]

        assert file_reference_mod.inlined_attachments(files, set()) == files


class TestAssistantAttachmentReferences:
    """URL-only attachments render on the current message, not in the prompt."""

    def _context(self, prompt_files, url_only_ids, urls):
        return ContextBuilder().build_context(
            input_str="vilket konto?",
            max_tokens=100_000,
            model_name="gpt-4o",
            prompt="Du är en ekonomiassistent.",
            prompt_files=prompt_files,
            file_reference_urls=urls,
            url_only_prompt_file_ids=url_only_ids,
        )

    def test_url_only_attachment_text_leaves_the_prompt_for_a_reference(self):
        kontoplan = _content_file(text="konto 1910 kassa")
        guide = _content_file(name="guide.md", text="skriv kortfattat")
        urls = {kontoplan.id: "https://x/dl/kontoplan"}

        context = self._context([kontoplan, guide], {kontoplan.id}, urls)

        assert "konto 1910 kassa" not in context.prompt
        assert "skriv kortfattat" in context.prompt
        assert "attached to this assistant by its author" in context.prompt
        assert "Files attached to this assistant by its author" in context.input
        assert urls[kontoplan.id] in context.input
        assert "vilket konto?" in context.input

    def test_no_reference_block_without_url_only_attachments(self):
        kontoplan = _content_file(text="konto 1910 kassa")

        context = self._context([kontoplan], set(), {})

        assert "konto 1910 kassa" in context.prompt
        assert "attached to this assistant" not in context.input

    def test_reference_block_is_counted_in_the_token_budget(self):
        kontoplan = _content_file(text="x")
        urls = {kontoplan.id: "https://x/dl/kontoplan"}

        with_block = self._context([kontoplan], {kontoplan.id}, urls)
        without_block = self._context([kontoplan], set(), {})

        assert with_block.token_count > without_block.token_count

    def test_pages_rendered_from_url_only_attachment_are_not_sent(self):
        kontoplan = _content_file()
        page = _content_file(file_type=FileType.IMAGE, parent_file_id=kontoplan.id)
        urls = {kontoplan.id: "https://x/dl/kontoplan"}

        context = self._context([kontoplan, page], {kontoplan.id}, urls)

        assert context.images == []

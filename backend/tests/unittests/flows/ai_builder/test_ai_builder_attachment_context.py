from __future__ import annotations

from uuid import uuid4

from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContextPolicy,
    AIBuilderAttachmentEvidence,
    build_ai_builder_attachment_context,
)


def _make_file(
    *,
    name: str,
    text: str | None,
    mimetype: str = "text/plain",
    file_type: FileType = FileType.TEXT,
    transcription: str | None = None,
) -> File:
    readable = text or transcription or ""
    return File(
        id=uuid4(),
        name=name,
        checksum="checksum",
        size=len(readable.encode("utf-8")) or 1,
        mimetype=mimetype,
        file_type=file_type,
        text=text,
        blob=b"x" if text is None else None,
        transcription=transcription,
        owner_type=None,
        owner_user_id=uuid4(),
        owner_api_key_id=None,
        user_id=uuid4(),
        tenant_id=uuid4(),
    )


def test_build_ai_builder_attachment_context_truncates_per_file_and_total_budget() -> (
    None
):
    files = [
        _make_file(name="one.txt", text="A" * 120),
        _make_file(name="two.txt", text="B" * 120),
    ]

    result = build_ai_builder_attachment_context(
        files,
        policy=AIBuilderAttachmentContextPolicy(
            max_chars_per_file=40,
            max_total_chars=70,
        ),
    )

    assert result is not None
    assert "one.txt" in result.context
    assert "two.txt" in result.context
    assert len(result.included_file_ids) == 2
    assert result.truncated is True
    assert result.total_chars <= 70


def test_build_ai_builder_attachment_context_includes_typed_file_evidence() -> None:
    files = [
        _make_file(
            name="beslutsmall.docx",
            text="Beslutspunkt: ...",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_type=FileType.DOCUMENT,
        ),
        _make_file(
            name="meeting.m4a",
            text=None,
            mimetype="audio/mp4",
            file_type=FileType.AUDIO,
            transcription="Vi beslutade att följa upp avtalet.",
        ),
    ]

    result = build_ai_builder_attachment_context(files)

    assert result is not None
    assert result.evidence == (
        AIBuilderAttachmentEvidence(
            file_id=files[0].id,
            filename="beslutsmall.docx",
            file_type=FileType.DOCUMENT,
            mimetype=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            has_readable_text=True,
            excerpt="Beslutspunkt: ...",
        ),
        AIBuilderAttachmentEvidence(
            file_id=files[1].id,
            filename="meeting.m4a",
            file_type=FileType.AUDIO,
            mimetype="audio/mp4",
            has_readable_text=True,
            excerpt="Vi beslutade att följa upp avtalet.",
        ),
    )
    assert result.discovery_context is not None
    assert "filename: beslutsmall.docx" in result.discovery_context
    assert "file_type: document" in result.discovery_context
    assert "filename: meeting.m4a" in result.discovery_context
    assert "file_type: audio" in result.discovery_context


def test_build_ai_builder_attachment_context_surfaces_unreadable_files_for_discovery() -> (
    None
):
    result = build_ai_builder_attachment_context(
        [
            _make_file(
                name="beslutsmall.docx",
                text=None,
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                file_type=FileType.DOCUMENT,
            )
        ]
    )

    assert result is not None
    assert result.context is None
    assert result.discovery_context is not None
    assert "filename: beslutsmall.docx" in result.discovery_context
    assert "has_readable_text: false" in result.discovery_context
    assert result.evidence[0].has_readable_text is False
    assert result.evidence[0].excerpt is None

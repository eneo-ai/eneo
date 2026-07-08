from __future__ import annotations

from typing import get_args
from uuid import uuid4

from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    _FILE_ROLE_PRIORITY,
    AIBuilderAttachmentContextPolicy,
    build_ai_builder_attachment_context,
)
from eneo.flows.ai_builder.planning_state import FileRole


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


def test_file_role_priority_covers_all_declared_file_roles() -> None:
    assert set(_FILE_ROLE_PRIORITY) == set(get_args(FileRole))


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
    assert result.evidence[0].file_id == files[0].id
    assert result.evidence[0].filename == "beslutsmall.docx"
    assert result.evidence[0].file_type == FileType.DOCUMENT
    assert result.evidence[0].inferred_role == "context_only"
    assert result.evidence[0].role_confidence == "low"
    assert result.evidence[1].file_id == files[1].id
    assert result.evidence[1].filename == "meeting.m4a"
    assert result.evidence[1].file_type == FileType.AUDIO
    assert result.evidence[1].inferred_role == "runtime_input_sample"
    assert result.evidence[1].role_confidence == "high"
    assert result.discovery_context is not None
    assert f"file_id: {files[0].id}" in result.discovery_context
    assert "filename: beslutsmall.docx" in result.discovery_context
    assert "file_type: document" in result.discovery_context
    assert "inferred_role: context_only" in result.discovery_context
    assert "filename: meeting.m4a" in result.discovery_context
    assert "file_type: audio" in result.discovery_context
    assert "inferred_role: runtime_input_sample" in result.discovery_context


def test_build_ai_builder_attachment_context_detects_structural_template_placeholders() -> (
    None
):
    files = [
        _make_file(
            name="avtalsmall.docx",
            text="Fyll i {{ kundnamn }} och {{ datum }}.",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_type=FileType.DOCUMENT,
        ),
        _make_file(
            name="lagstod.pdf",
            text="Lagstöd och föreskrifter som ska användas vid bedömning.",
            mimetype="application/pdf",
            file_type=FileType.DOCUMENT,
        ),
    ]

    result = build_ai_builder_attachment_context(files)

    assert result is not None
    assert [item.inferred_role for item in result.evidence] == [
        "template",
        "context_only",
    ]
    assert "content:template_placeholder:kundnamn" in result.evidence[0].role_evidence
    assert "content:template_placeholder:datum" in result.evidence[0].role_evidence
    assert result.context is not None
    assert "File role: template" in result.context
    assert "File role: context_only" in result.context


def test_build_ai_builder_attachment_context_does_not_infer_semantic_roles() -> None:
    result = build_ai_builder_attachment_context(
        [
            _make_file(
                name="exempel-lagmall.docx",
                text="Lagstöd och föreskrifter som ska användas vid bedömning.",
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml."
                    "document"
                ),
                file_type=FileType.DOCUMENT,
            ),
        ]
    )

    assert result is not None
    evidence = result.evidence[0]
    assert evidence.inferred_role == "context_only"
    assert evidence.role_confidence == "low"
    assert evidence.candidate_roles == ("context_only",)
    assert evidence.role_evidence == ("fallback:unclassified_file",)
    assert result.discovery_context is not None
    assert "inferred_role: context_only" in result.discovery_context


def test_build_ai_builder_attachment_context_avoids_substring_role_false_positives() -> (
    None
):
    result = build_ai_builder_attachment_context(
        [
            _make_file(
                name="underlag.pdf",
                text="Allmänt underlag utan rättskälla.",
                mimetype="application/pdf",
                file_type=FileType.DOCUMENT,
            ),
            _make_file(
                name="bilaga.pdf",
                text="Bilaga till ärendet.",
                mimetype="application/pdf",
                file_type=FileType.DOCUMENT,
            ),
            _make_file(
                name="small.pdf",
                text="Short document.",
                mimetype="application/pdf",
                file_type=FileType.DOCUMENT,
            ),
        ]
    )

    assert result is not None
    assert [item.inferred_role for item in result.evidence] == [
        "context_only",
        "context_only",
        "context_only",
    ]


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

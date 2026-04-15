from __future__ import annotations

from uuid import uuid4

from intric.files.file_models import File, FileType
from intric.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContextPolicy,
    build_ai_builder_attachment_context,
)


def _make_file(
    *,
    name: str,
    text: str | None,
    mimetype: str = "text/plain",
) -> File:
    return File(
        id=uuid4(),
        name=name,
        checksum="checksum",
        size=len((text or "").encode("utf-8")) or 1,
        mimetype=mimetype,
        file_type=FileType.TEXT,
        text=text,
        blob=b"x" if text is None else None,
        transcription=None,
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


def test_build_ai_builder_attachment_context_skips_files_without_readable_text() -> (
    None
):
    result = build_ai_builder_attachment_context(
        [_make_file(name="empty.txt", text=None)]
    )

    assert result is None

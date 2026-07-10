from __future__ import annotations

from typing import get_args
from uuid import uuid4

from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    _FILE_ROLE_PRIORITY,
    AIBuilderAttachmentContextPolicy,
    build_ai_builder_attachment_context,
    render_ai_builder_attachment_evidence,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_slot_classification_input,
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
    assert result.evidence[0].coverage == "fully_seen"
    assert result.evidence[1].file_id == files[1].id
    assert result.evidence[1].filename == "meeting.m4a"
    assert result.evidence[1].file_type == FileType.AUDIO
    assert result.evidence[1].inferred_role == "runtime_input_sample"
    assert result.evidence[1].role_confidence == "high"
    assert result.evidence[1].coverage == "fully_seen"


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
    assert result.evidence[0].filename == "beslutsmall.docx"
    assert result.evidence[0].has_readable_text is False
    assert result.evidence[0].excerpt is None
    assert result.evidence[0].coverage == "inventory_only"


def test_discovery_excerpts_cover_every_file_fairly() -> None:
    files = [
        _make_file(name=f"{index}.txt", text=character * 100)
        for index, character in enumerate(("A", "B", "C"), start=1)
    ]

    result = build_ai_builder_attachment_context(
        files,
        policy=AIBuilderAttachmentContextPolicy(
            max_discovery_excerpt_chars=100,
            max_discovery_excerpt_chars_total=30,
        ),
    )

    assert result is not None
    assert {item.file_id for item in result.evidence} == {file.id for file in files}
    assert [len(item.excerpt or "") for item in result.evidence] == [10, 10, 10]
    assert {item.coverage for item in result.evidence} == {"excerpt_truncated"}


def test_discovery_excerpts_redistribute_unused_short_file_capacity() -> None:
    short_file = _make_file(name="short.txt", text="S")
    long_file = _make_file(name="long.txt", text="L" * 100)

    result = build_ai_builder_attachment_context(
        [short_file, long_file],
        policy=AIBuilderAttachmentContextPolicy(
            max_discovery_excerpt_chars=100,
            max_discovery_excerpt_chars_total=30,
        ),
    )

    assert result is not None
    excerpts_by_id = {item.file_id: item.excerpt or "" for item in result.evidence}
    assert len(excerpts_by_id[short_file.id]) == 1
    assert len(excerpts_by_id[long_file.id]) == 29
    assert sum(len(excerpt) for excerpt in excerpts_by_id.values()) == 30


def test_discovery_excerpts_mark_exactly_consumed_capacity_fully_seen() -> None:
    files = [
        _make_file(name="short.txt", text="S" * 10),
        _make_file(name="long.txt", text="L" * 20),
    ]

    result = build_ai_builder_attachment_context(
        files,
        policy=AIBuilderAttachmentContextPolicy(
            max_discovery_excerpt_chars=20,
            max_discovery_excerpt_chars_total=30,
        ),
    )

    assert result is not None
    assert sum(len(item.excerpt or "") for item in result.evidence) == 30
    assert {item.coverage for item in result.evidence} == {"fully_seen"}


def test_discovery_excerpts_respect_per_file_limits_with_total_room_remaining() -> None:
    files = [
        _make_file(name="first.txt", text="A" * 100),
        _make_file(name="second.txt", text="B" * 100),
    ]

    result = build_ai_builder_attachment_context(
        files,
        policy=AIBuilderAttachmentContextPolicy(
            max_discovery_excerpt_chars=20,
            max_discovery_excerpt_chars_total=100,
        ),
    )

    assert result is not None
    assert [len(item.excerpt or "") for item in result.evidence] == [20, 20]
    assert {item.coverage for item in result.evidence} == {"excerpt_truncated"}


def test_large_file_inventory_keeps_the_last_stable_id_beyond_legacy_prefix_budget() -> (
    None
):
    files = [
        _make_file(
            name=f"source-{index:02d}-{'x' * 60}.txt",
            text=f"Source {index} " + "evidence " * 200,
        )
        for index in range(30)
    ]

    result = build_ai_builder_attachment_context(files)

    assert result is not None
    stable_evidence = sorted(result.evidence, key=lambda item: str(item.file_id))
    rendered_inventory = "\n".join(
        render_ai_builder_attachment_evidence(item) for item in stable_evidence
    )
    assert len(rendered_inventory) > 4_000
    last_file_id = max((file.id for file in files), key=str)
    classification_input = build_slot_classification_input([], result)
    last_source = classification_input.sources[-1]
    assert last_source.source_id == f"uploaded_file:{last_file_id}"
    assert last_source.file_id == last_file_id
    assert last_source.coverage == "excerpt_truncated"


def test_discovery_file_inventory_is_permutation_stable() -> None:
    files = [
        _make_file(name=f"{index}.txt", text=character * 100)
        for index, character in enumerate(("A", "B", "C"), start=1)
    ]
    policy = AIBuilderAttachmentContextPolicy(
        max_discovery_excerpt_chars=100,
        max_discovery_excerpt_chars_total=31,
    )

    forward = build_ai_builder_attachment_context(files, policy=policy)
    reverse = build_ai_builder_attachment_context(list(reversed(files)), policy=policy)

    assert forward is not None
    assert reverse is not None
    assert {
        item.file_id: (item.excerpt, item.coverage) for item in forward.evidence
    } == {item.file_id: (item.excerpt, item.coverage) for item in reverse.evidence}
    assert sum(len(item.excerpt or "") for item in forward.evidence) == 31


def test_zero_excerpt_budget_keeps_inventory_and_marks_context_truncated() -> None:
    file = _make_file(name="source.txt", text="Readable source content")

    result = build_ai_builder_attachment_context(
        [file],
        policy=AIBuilderAttachmentContextPolicy(
            max_discovery_excerpt_chars=100,
            max_discovery_excerpt_chars_total=0,
        ),
    )

    assert result is not None
    assert result.truncated is True
    assert result.evidence[0].coverage == "inventory_only"
    assert result.evidence[0].excerpt is None

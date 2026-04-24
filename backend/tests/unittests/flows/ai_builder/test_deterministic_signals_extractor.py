"""Contract tests for `extract_deterministic_signals`.

Pins the dispatcher surface callers rely on:

- every call populates file-level signals (mime_type, extension,
  size_bytes) regardless of mime family,
- extension is inferred from the filename suffix first and falls back
  to the `MIMETYPE_EXTENSIONS_MAPPER` registry when the filename
  carries no informative suffix,
- the text extractor populates `bullet_density` from bytes it can
  decode as UTF-8 (with replacement on invalid sequences),
- unsupported mimes still return a valid `DeterministicSignals` with
  the default empty / None per-mime fields, so upstream callers never
  need a None check on the top-level return.
"""

from __future__ import annotations

from io import BytesIO

from docx import Document

from intric.flows.ai_builder.attachment_observation import DeterministicSignals
from intric.flows.ai_builder.deterministic_signals_extractor import (
    extract_deterministic_signals,
)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _build_docx(
    *,
    headings: list[tuple[int, str]] | None = None,
    paragraphs: list[str] | None = None,
    tables: list[tuple[int, int]] | None = None,
) -> bytes:
    """Build a minimal in-memory DOCX containing the declared structure.

    Used by tests so the extractor's DOCX branch is exercised against
    real openxml bytes, not a hand-rolled fake; anything python-docx
    itself might change (namespace URIs, relationship IDs) is therefore
    covered by round-trip from the upstream writer to the extractor's
    reader.
    """
    document = Document()
    for level, text in headings or []:
        document.add_heading(text, level=level)
    for paragraph in paragraphs or []:
        document.add_paragraph(paragraph)
    for rows, cols in tables or []:
        document.add_table(rows=rows, cols=cols)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class TestFileLevelSignals:
    def test_dispatcher_sets_mime_extension_size_for_text(self):
        signals = extract_deterministic_signals(
            raw_bytes=_bytes("hello"),
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.mime_type == "text/plain"
        assert signals.extension == "txt"
        assert signals.size_bytes == 5

    def test_size_bytes_reflects_actual_byte_length(self):
        payload = b"\xef\xbb\xbfhello"
        signals = extract_deterministic_signals(
            raw_bytes=payload,
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.size_bytes == len(payload)

    def test_returns_deterministic_signals_instance(self):
        signals = extract_deterministic_signals(
            raw_bytes=b"",
            mime="application/pdf",
            filename="empty.pdf",
        )

        assert isinstance(signals, DeterministicSignals)


class TestExtensionInference:
    def test_uses_filename_suffix_lowercased_without_dot(self):
        signals = extract_deterministic_signals(
            raw_bytes=b"",
            mime="text/plain",
            filename="Report.TXT",
        )

        assert signals.extension == "txt"

    def test_falls_back_to_mime_mapping_when_filename_has_no_suffix(self):
        signals = extract_deterministic_signals(
            raw_bytes=b"",
            mime="application/pdf",
            filename="no-extension",
        )

        assert signals.extension == "pdf"

    def test_empty_extension_when_mime_and_filename_yield_nothing(self):
        signals = extract_deterministic_signals(
            raw_bytes=b"",
            mime="application/x-unknown",
            filename="blob",
        )

        assert signals.extension == ""

    def test_hidden_file_with_no_suffix_still_falls_back_to_mime(self):
        signals = extract_deterministic_signals(
            raw_bytes=b"",
            mime="text/plain",
            filename=".gitignore",
        )

        assert signals.extension == "txt"


class TestTextBulletDensity:
    def test_plain_text_without_bullets_has_zero_density(self):
        signals = extract_deterministic_signals(
            raw_bytes=_bytes("line one\nline two\nline three"),
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.bullet_density == 0.0

    def test_all_bullet_lines_has_density_one(self):
        signals = extract_deterministic_signals(
            raw_bytes=_bytes("- a\n- b\n- c"),
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.bullet_density == 1.0

    def test_mixed_bullet_and_prose_has_expected_ratio(self):
        signals = extract_deterministic_signals(
            raw_bytes=_bytes("intro\n* bullet one\n* bullet two\noutro"),
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.bullet_density is not None
        assert 0.49 <= signals.bullet_density <= 0.51

    def test_recognises_asterisk_dash_plus_and_typographic_bullets(self):
        content = "* a\n- b\n+ c\n• d\n· e"
        signals = extract_deterministic_signals(
            raw_bytes=_bytes(content),
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.bullet_density == 1.0

    def test_blank_lines_ignored_when_computing_density(self):
        signals = extract_deterministic_signals(
            raw_bytes=_bytes("\n- a\n\n- b\n\n"),
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.bullet_density == 1.0

    def test_empty_text_leaves_bullet_density_none(self):
        signals = extract_deterministic_signals(
            raw_bytes=b"",
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.bullet_density is None

    def test_indented_bullet_lines_still_count(self):
        signals = extract_deterministic_signals(
            raw_bytes=_bytes("  - indented\n    * also indented"),
            mime="text/plain",
            filename="notes.md",
        )

        assert signals.bullet_density == 1.0

    def test_invalid_utf8_bytes_do_not_crash(self):
        payload = b"valid line\n\xff\xfeinvalid\n- bullet"
        signals = extract_deterministic_signals(
            raw_bytes=payload,
            mime="text/plain",
            filename="notes.txt",
        )

        assert signals.bullet_density is not None


class TestMarkdownIsTreatedAsText:
    def test_markdown_mime_populates_bullet_density(self):
        signals = extract_deterministic_signals(
            raw_bytes=_bytes("- one\n- two"),
            mime="text/markdown",
            filename="README.md",
        )

        assert signals.mime_type == "text/markdown"
        assert signals.extension == "md"
        assert signals.bullet_density == 1.0


class TestUnsupportedMimeFallback:
    def test_unknown_mime_returns_file_level_signals_without_per_mime_fields(self):
        signals = extract_deterministic_signals(
            raw_bytes=b"%PDF-1.4 minimal",
            mime="application/pdf",
            filename="doc.pdf",
        )

        assert signals.mime_type == "application/pdf"
        assert signals.extension == "pdf"
        assert signals.size_bytes == len(b"%PDF-1.4 minimal")
        assert signals.page_count is None
        assert signals.table_count is None
        assert signals.form_fields == []
        assert signals.placeholder_tokens == []
        assert signals.bullet_density is None


class TestDocxExtractor:
    """DOCX attachments carry the highest-signal structure for AI Builder
    flow-archetype selection: a document with `{{placeholder}}` tokens
    is a `document_to_docx_template` candidate; one with rich heading
    structure and tables is a `document_to_structured_report` candidate.
    The extractor surfaces those signals mechanically before any LLM
    pass sees the file.
    """

    def test_headings_are_extracted_with_levels_and_text(self) -> None:
        raw = _build_docx(
            headings=[
                (1, "Contract"),
                (2, "Scope"),
                (2, "Deliverables"),
            ],
        )
        signals = extract_deterministic_signals(
            raw_bytes=raw,
            mime=_DOCX_MIME,
            filename="contract.docx",
        )

        assert signals.heading_tree is not None
        headings = [(h.level, h.text) for h in signals.heading_tree]
        assert headings == [
            (1, "Contract"),
            (2, "Scope"),
            (2, "Deliverables"),
        ]

    def test_placeholder_tokens_are_extracted_from_body_text(self) -> None:
        """Jinja-style `{{ var }}` placeholders are the dominant signal
        for `document_to_docx_template` — the planner uses the set
        of tokens to score whether the attachment is a fill-in
        template versus a generated output sample.
        """
        raw = _build_docx(
            paragraphs=[
                "Hello {{ customer_name }}, welcome to {{ company }}.",
                "Your order number is {{order_id}}.",
                "Regular prose with no tokens.",
                "{{customer_name}} again — duplicates collapse to a single token.",
            ],
        )
        signals = extract_deterministic_signals(
            raw_bytes=raw,
            mime=_DOCX_MIME,
            filename="template.docx",
        )

        assert set(signals.placeholder_tokens) == {
            "customer_name",
            "company",
            "order_id",
        }

    def test_table_count_and_dimensions_match_document(self) -> None:
        raw = _build_docx(tables=[(2, 3), (4, 5)])
        signals = extract_deterministic_signals(
            raw_bytes=raw,
            mime=_DOCX_MIME,
            filename="report.docx",
        )

        assert signals.table_count == 2
        dims = [(t.rows, t.cols) for t in signals.table_dimensions]
        assert dims == [(2, 3), (4, 5)]

    def test_docx_without_placeholders_returns_empty_token_list(self) -> None:
        raw = _build_docx(paragraphs=["Plain prose.", "No tokens here."])
        signals = extract_deterministic_signals(
            raw_bytes=raw,
            mime=_DOCX_MIME,
            filename="prose.docx",
        )
        assert signals.placeholder_tokens == []

    def test_empty_docx_returns_empty_structural_fields(self) -> None:
        raw = _build_docx()
        signals = extract_deterministic_signals(
            raw_bytes=raw,
            mime=_DOCX_MIME,
            filename="empty.docx",
        )

        assert signals.mime_type == _DOCX_MIME
        assert signals.extension == "docx"
        assert signals.heading_tree == []
        assert signals.placeholder_tokens == []
        assert signals.table_count == 0
        assert signals.table_dimensions == []

    def test_malformed_docx_bytes_fall_back_to_file_level_signals(self) -> None:
        """DOCX is a ZIP; non-ZIP bytes must not crash the extractor.
        Upstream MIME classification is permissive (cache key derives
        from every byte stream reaching the pipeline), so a malformed
        payload should still produce a valid DeterministicSignals.
        """
        signals = extract_deterministic_signals(
            raw_bytes=b"not a real docx file",
            mime=_DOCX_MIME,
            filename="broken.docx",
        )

        assert signals.mime_type == _DOCX_MIME
        assert signals.extension == "docx"
        assert signals.heading_tree is None
        assert signals.table_count is None
        assert signals.placeholder_tokens == []

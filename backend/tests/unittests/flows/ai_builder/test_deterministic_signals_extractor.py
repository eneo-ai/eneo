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

from intric.flows.ai_builder.attachment_observation import DeterministicSignals
from intric.flows.ai_builder.deterministic_signals_extractor import (
    extract_deterministic_signals,
)


def _bytes(text: str) -> bytes:
    return text.encode("utf-8")


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

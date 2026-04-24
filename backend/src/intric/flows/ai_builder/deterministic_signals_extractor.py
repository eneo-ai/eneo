"""Deterministic signal extractor for AI Builder attachment observations.

The observation pipeline asks this module, before any LLM call, what
the raw bytes alone can tell us: the canonical MIME, a filename
extension, the size in bytes, and — for text-like payloads — a
bullet-line density that hints at whether the content is dense prose
or a list. Per-mime extractors for DOCX / PDF / XLSX / CSV / media
plug into the dispatcher below; text and markdown are handled here.

Unsupported or legacy MIMEs still produce a ``DeterministicSignals``
with the file-level fields populated and per-mime fields at their
defaults, so upstream callers never need a ``None`` check on the
top-level return. Rejection of legacy uploads happens at the upload
boundary via ``files.mime_support.classify_mime``; here we stay
permissive so the cache key remains derivable for every byte stream
that reaches the pipeline.
"""

from __future__ import annotations

import re

from intric.files.extensions import MIMETYPE_EXTENSIONS_MAPPER
from intric.files.mime_support import canonicalize_mime
from intric.flows.ai_builder.attachment_observation import DeterministicSignals

_TEXT_MIMES: frozenset[str] = frozenset({"text/plain", "text/markdown"})
_BULLET_LINE = re.compile(r"^\s*[-*+•·]\s+\S")


def extract_deterministic_signals(
    *,
    raw_bytes: bytes,
    mime: str,
    filename: str,
) -> DeterministicSignals:
    canonical_mime = canonicalize_mime(mime) or (mime or "")
    extension = _infer_extension(filename=filename, mime=canonical_mime)
    size_bytes = len(raw_bytes)

    if canonical_mime in _TEXT_MIMES:
        return DeterministicSignals(
            mime_type=canonical_mime,
            extension=extension,
            size_bytes=size_bytes,
            bullet_density=_bullet_density(raw_bytes),
        )

    return DeterministicSignals(
        mime_type=canonical_mime,
        extension=extension,
        size_bytes=size_bytes,
    )


def _infer_extension(*, filename: str, mime: str) -> str:
    suffix = _filename_suffix(filename)
    if suffix:
        return suffix
    extensions = MIMETYPE_EXTENSIONS_MAPPER.get(mime, [])
    if extensions:
        return extensions[0].lstrip(".")
    return ""


def _filename_suffix(filename: str) -> str:
    if "." not in filename:
        return ""
    # A hidden filename like ".gitignore" has no informative suffix —
    # the leading dot is a visibility marker, not an extension.
    if filename.startswith(".") and filename.count(".") == 1:
        return ""
    _, _, suffix = filename.rpartition(".")
    return suffix.lower()


def _bullet_density(raw_bytes: bytes) -> float | None:
    if not raw_bytes:
        return None
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    bullet_count = sum(1 for line in lines if _BULLET_LINE.match(line))
    return bullet_count / len(lines)

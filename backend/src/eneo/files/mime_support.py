"""Single source of truth for MIME-type classification.

Every upload-boundary validator, advertised-formats endpoint, and
content-extractor dispatcher consults this module. The goal is that a
user cannot upload a file whose MIME the backend will later reject at
worker-time — the rejection decision lives here, before the file is
queued.

Three classification states:

- ``SUPPORTED`` — the MIME belongs to one of the registered families
  (text, audio, image) and is not on the legacy-advice list.
- ``LEGACY_REJECTED`` — the MIME is known but deprecated (e.g. the
  pre-OOXML ``.doc``/``.ppt`` formats). Callers surface the paired
  advice string so end users know which modern equivalent to export.
- ``UNKNOWN`` — the MIME is not in any registered family. Callers
  reject with a generic "not supported" message.

``classify_mime`` also owns canonicalisation so every caller sees the
same comparison contract: strip the ``;charset=…`` suffix, lowercase,
and collapse the small set of container aliases (e.g. ``audio/mp3`` →
``audio/mpeg``, ``video/mp4`` → ``audio/mp4``) that arrive from
different browsers for the same codec.
"""

from __future__ import annotations

from enum import Enum

from eneo.files.audio import AudioMimeTypes
from eneo.files.image import ImageMimeTypes
from eneo.files.text import TextMimeTypes


class MimeSupport(str, Enum):
    SUPPORTED = "supported"
    LEGACY_REJECTED = "legacy_rejected"
    UNKNOWN = "unknown"


_LEGACY_ADVICE: dict[str, str] = {
    TextMimeTypes.DOC.value: ".doc (Legacy Word) - please save as .docx",
    TextMimeTypes.PPT.value: ".ppt (Legacy PowerPoint) - please save as .pptx",
}

_MIMETYPE_CANONICAL_ALIASES: dict[str, str] = {
    "audio/mp3": "audio/mpeg",
    "audio/x-m4a": "audio/mp4",
    "video/mp4": "audio/mp4",
    "video/webm": "audio/webm",
}


def canonicalize_mime(mimetype: str | None) -> str:
    """Return a canonical form suitable for comparison, or ``""``."""

    if not mimetype:
        return ""
    base = mimetype.split(";", 1)[0].strip().lower()
    if not base:
        return ""
    return _MIMETYPE_CANONICAL_ALIASES.get(base, base)


def classify_mime(mimetype: str | None) -> tuple[MimeSupport, str | None]:
    """Classify *mimetype* into one of the three support states.

    Returns ``(state, rejection_reason)``. ``rejection_reason`` is the
    user-facing advice string for ``LEGACY_REJECTED`` and ``None`` for
    the other two states.
    """

    canonical = canonicalize_mime(mimetype)
    if not canonical:
        return MimeSupport.UNKNOWN, None
    if canonical in _LEGACY_ADVICE:
        return MimeSupport.LEGACY_REJECTED, _LEGACY_ADVICE[canonical]
    if (
        TextMimeTypes.has_value(canonical)
        or AudioMimeTypes.has_value(canonical)
        or ImageMimeTypes.has_value(canonical)
    ):
        return MimeSupport.SUPPORTED, None
    return MimeSupport.UNKNOWN, None


def is_supported(mimetype: str | None) -> bool:
    """Shorthand — returns ``True`` only for ``SUPPORTED``."""

    state, _ = classify_mime(mimetype)
    return state is MimeSupport.SUPPORTED


def supported_text_mimes() -> list[str]:
    """Text MIMEs advertised to clients, legacy filtered out."""

    return [value for value in TextMimeTypes.values() if value not in _LEGACY_ADVICE]


def supported_audio_mimes() -> list[str]:
    return AudioMimeTypes.values()


def supported_image_mimes() -> list[str]:
    return ImageMimeTypes.values()


def supported_mimes() -> list[str]:
    """Union of all supported MIMEs across families, legacy excluded."""

    return supported_text_mimes() + supported_audio_mimes() + supported_image_mimes()

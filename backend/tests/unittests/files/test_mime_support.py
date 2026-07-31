"""Contract tests for the MIME classification module.

Every upload-boundary validator and advertised-formats endpoint now
consults ``classify_mime``. These tests pin the shape callers rely on:

- canonicalisation strips the ``;charset=…`` suffix, lowercases, and
  collapses the handful of container aliases so call sites see one
  comparison contract,
- DOC and PPT are rejected at classify time with the user-facing advice
  string that worker-time paths used to surface,
- every enum member of ``TextMimeTypes`` / ``AudioMimeTypes`` /
  ``ImageMimeTypes`` (except the legacy list) classifies as supported,
- the ``supported_*`` helpers back advertised-formats APIs and never
  leak legacy mimes to clients.
"""

from __future__ import annotations

import pytest

from eneo.files.audio import AudioMimeTypes
from eneo.files.image import ImageMimeTypes
from eneo.files.mime_support import (
    MimeSupport,
    canonicalize_mime,
    classify_mime,
    is_supported,
    supported_audio_mimes,
    supported_image_mimes,
    supported_mimes,
    supported_text_mimes,
)
from eneo.files.text import TextMimeTypes


class TestCanonicalize:
    def test_none_returns_empty_string(self):
        assert canonicalize_mime(None) == ""

    def test_empty_returns_empty_string(self):
        assert canonicalize_mime("") == ""
        assert canonicalize_mime("   ") == ""

    def test_strips_charset_suffix(self):
        assert canonicalize_mime("text/plain; charset=utf-8") == "text/plain"

    def test_lowercases(self):
        assert canonicalize_mime("Application/PDF") == "application/pdf"

    def test_trims_whitespace(self):
        assert canonicalize_mime("  text/markdown  ") == "text/markdown"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("audio/mp3", "audio/mpeg"),
            ("audio/x-m4a", "audio/mp4"),
            ("video/mp4", "audio/mp4"),
            ("video/webm", "audio/webm"),
        ],
    )
    def test_collapses_container_aliases(self, raw: str, expected: str):
        assert canonicalize_mime(raw) == expected


class TestClassifyMime:
    def test_none_is_unknown(self):
        state, reason = classify_mime(None)
        assert state is MimeSupport.UNKNOWN
        assert reason is None

    def test_empty_is_unknown(self):
        assert classify_mime("")[0] is MimeSupport.UNKNOWN

    @pytest.mark.parametrize(
        "mime",
        [
            m.value
            for m in TextMimeTypes
            if m.value
            not in {
                TextMimeTypes.DOC.value,
                TextMimeTypes.PPT.value,
            }
        ],
    )
    def test_every_non_legacy_text_mime_is_supported(self, mime: str):
        state, reason = classify_mime(mime)
        assert state is MimeSupport.SUPPORTED
        assert reason is None

    @pytest.mark.parametrize("mime", [m.value for m in AudioMimeTypes])
    def test_every_audio_mime_is_supported(self, mime: str):
        assert classify_mime(mime)[0] is MimeSupport.SUPPORTED

    @pytest.mark.parametrize("mime", [m.value for m in ImageMimeTypes])
    def test_every_image_mime_is_supported(self, mime: str):
        assert classify_mime(mime)[0] is MimeSupport.SUPPORTED

    def test_legacy_doc_rejected_with_advice(self):
        state, reason = classify_mime("application/msword")
        assert state is MimeSupport.LEGACY_REJECTED
        assert reason is not None
        assert ".doc" in reason and ".docx" in reason

    def test_legacy_ppt_rejected_with_advice(self):
        state, reason = classify_mime("application/vnd.ms-powerpoint")
        assert state is MimeSupport.LEGACY_REJECTED
        assert reason is not None
        assert ".ppt" in reason and ".pptx" in reason

    def test_unknown_mime_classified_unknown(self):
        assert classify_mime("application/x-novel")[0] is MimeSupport.UNKNOWN

    def test_json_is_supported_text(self):
        assert classify_mime("application/json")[0] is MimeSupport.SUPPORTED

    def test_legacy_rejection_honours_canonicalisation(self):
        state, reason = classify_mime("Application/msword; charset=utf-8")
        assert state is MimeSupport.LEGACY_REJECTED
        assert reason is not None

    def test_alias_audio_mp3_classified_supported(self):
        assert classify_mime("audio/mp3")[0] is MimeSupport.SUPPORTED


class TestIsSupported:
    def test_true_for_supported(self):
        assert is_supported("text/plain") is True

    def test_false_for_legacy(self):
        assert is_supported("application/msword") is False

    def test_false_for_unknown(self):
        assert is_supported("application/x-novel") is False

    def test_false_for_none(self):
        assert is_supported(None) is False


class TestSupportedHelpers:
    def test_supported_text_excludes_legacy(self):
        mimes = supported_text_mimes()
        assert "application/msword" not in mimes
        assert "application/vnd.ms-powerpoint" not in mimes

    def test_supported_text_includes_modern(self):
        mimes = supported_text_mimes()
        assert "application/pdf" in mimes
        assert (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            in mimes
        )

    def test_supported_audio_matches_enum(self):
        assert set(supported_audio_mimes()) == set(AudioMimeTypes.values())

    def test_supported_image_matches_enum(self):
        assert set(supported_image_mimes()) == set(ImageMimeTypes.values())

    def test_supported_mimes_union_excludes_legacy(self):
        union = supported_mimes()
        assert "application/msword" not in union
        assert "application/vnd.ms-powerpoint" not in union
        assert "text/plain" in union
        assert "audio/wav" in union
        assert "image/png" in union

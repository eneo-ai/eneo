"""normalize_free_text and AuditedReason: one plain line, bounded after
normalisation."""

import pytest
from pydantic import BaseModel, ValidationError

from eneo.audit.application.free_text import (
    REASON_MAX_LENGTH,
    REASON_MIN_LENGTH,
    AuditedReason,
    normalize_free_text,
)


class _Reasoned(BaseModel):
    reason: AuditedReason


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ärende\r\nKS 2026/123", "Ärende KS 2026/123"),
        ("Ärende\n\n\nKS", "Ärende KS"),
        ("Ärende\tKS", "Ärende KS"),
        ("Ärende\u2028KS\u2029123", "Ärende KS 123"),
        ("Ärende\x85KS", "Ärende KS"),
        ("Ärende \xa0 \u3000 KS", "Ärende KS"),
        ("  Ärende   KS  ", "Ärende KS"),
    ],
)
def test_every_whitespace_run_becomes_one_space(raw, expected):
    assert normalize_free_text(raw) == expected


@pytest.mark.parametrize(
    "control",
    [
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\u061c",
        "\u200b",
        "\u200c",
        "\u200d",
        "\u200e",
        "\u200f",
    ],
)
def test_bidi_and_zero_width_controls_are_removed(control):
    assert normalize_free_text(f"KS{control}2026") == "KS2026"


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b", "\x7f", "\x9b"])
def test_other_control_characters_are_removed(control):
    assert normalize_free_text(f"KS{control}2026") == "KS2026"


def test_text_is_composed_to_nfc():
    decomposed = "Ärende".replace("Ä", "A\u0308")
    assert len(decomposed) == 7
    assert normalize_free_text(decomposed) == "Ärende"


def test_a_reason_is_stored_normalised():
    assert (
        _Reasoned(reason="Ärende\r\nKS\u202e 2026/123 ").reason == "Ärende KS 2026/123"
    )


def test_the_bounds_apply_after_normalisation():
    shortest = "x" * REASON_MIN_LENGTH
    longest = "x" * REASON_MAX_LENGTH
    assert _Reasoned(reason=shortest).reason == shortest
    assert _Reasoned(reason=longest).reason == longest

    # Long enough only because of whitespace and hidden characters.
    for padded in (
        f"   {'x' * (REASON_MIN_LENGTH - 1)}   ",
        "x" * (REASON_MIN_LENGTH - 1) + "\u200b" * 5,
        "\n\t\r " * 10,
    ):
        with pytest.raises(ValidationError):
            _Reasoned(reason=padded)

    with pytest.raises(ValidationError):
        _Reasoned(reason="x" * (REASON_MAX_LENGTH + 1))

    # Too long as typed, within bounds once whitespace runs are collapsed.
    collapsible = "x  " * 200
    assert len(collapsible) > REASON_MAX_LENGTH
    assert len(_Reasoned(reason=collapsible).reason) == 399

    # Composition shortens it: ten decomposed letters are twenty code points.
    assert (
        _Reasoned(reason="A\u0308" * REASON_MIN_LENGTH).reason
        == "Ä" * REASON_MIN_LENGTH
    )
    with pytest.raises(ValidationError):
        _Reasoned(reason="A\u0308" * (REASON_MIN_LENGTH - 1))

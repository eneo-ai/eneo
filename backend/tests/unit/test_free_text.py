import random
import unicodedata

import pytest
from pydantic import BaseModel, ValidationError

from eneo.audit.application.free_text import (
    REASON_MAX_LENGTH,
    REASON_MIN_LENGTH,
    AuditedReason,
    normalize_free_text,
    visible_length,
)


class _Reasoned(BaseModel):
    reason: AuditedReason


# Characters that stay but interact with the rule: letters that compose,
# combining marks, whitespace of every kind, astral characters and jamo.
_KEPT = [
    "a",
    "e",
    "A",
    "Ä",
    "ö",
    "1",
    "/",
    "-",
    "€",
    "😀",
    "👍",
    "\U0001f3fd",
    "漢",
    "\u1100",
    "\u1161",
    "\u11a8",
    "\uac00",
    "\u0301",
    "\u0308",
    "\u0323",
    "\u0340",
    "\u2126",
    "\u212b",
    "\ue000",
    " ",
    "\t",
    "\n",
    "\r",
    "\x0b",
    "\x0c",
    "\x85",
    "\xa0",
    "\u1680",
    "\u2000",
    "\u2003",
    "\u200a",
    "\u2028",
    "\u2029",
    "\u202f",
    "\u205f",
    "\u3000",
]
# Characters the rule removes.
_REMOVED = [
    "\x00",
    "\x07",
    "\x1b",
    "\x1c",
    "\x1f",
    "\x7f",
    "\x9b",
    "\xad",
    "\u034f",
    "\u061c",
    "\u115f",
    "\u1160",
    "\u17b4",
    "\u180b",
    "\u180e",
    "\u200b",
    "\u200c",
    "\u200d",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202e",
    "\u2060",
    "\u2064",
    "\u2066",
    "\u2069",
    "\u2800",
    "\u3164",
    "\ufe0f",
    "\ufeff",
    "\uffa0",
    "\ud800",
    "\udfff",
    "\U0001d173",
    "\U000e0001",
    "\U000e0041",
    "\U000e007f",
    "\U000e0100",
]
_WHITESPACE = {
    "\t",
    "\n",
    "\x0b",
    "\x0c",
    "\r",
    " ",
    "\x85",
    "\xa0",
    "\u1680",
    *(chr(code) for code in range(0x2000, 0x200B)),
    "\u2028",
    "\u2029",
    "\u202f",
    "\u205f",
    "\u3000",
}


def _samples(count: int) -> list[str]:
    rng = random.Random(20260925)
    alphabet = _KEPT + _REMOVED
    samples = []
    for _ in range(count):
        length = rng.randint(0, 24)
        text = "".join(rng.choice(alphabet) for _ in range(length))
        # Now and then an arbitrary code point, surrogates included.
        if rng.random() < 0.3:
            text += chr(rng.randint(0, 0x10FFFF))
        samples.append(text)
    return samples


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


@pytest.mark.parametrize("removed", _REMOVED, ids=[hex(ord(c)) for c in _REMOVED])
def test_invisible_format_and_control_characters_are_removed(removed):
    assert normalize_free_text(f"KS{removed}2026") == "KS2026"


def test_file_separators_are_removed_not_turned_into_spaces():
    # Python's str.isspace() counts U+001C-U+001F; Unicode White_Space does not.
    assert normalize_free_text("abcd\x1cefghij") == "abcdefghij"


def test_text_is_composed_to_nfc():
    decomposed = "Ärende".replace("Ä", "A\u0308")
    assert len(decomposed) == 7
    assert normalize_free_text(decomposed) == "Ärende"


def test_nothing_composes_across_a_removed_character():
    # Removed before NFC, so the mark composes once and a second pass keeps it.
    assert normalize_free_text("abcdefgh" + "e\u200b\u0301") == "abcdefghé"


def test_normalising_is_idempotent():
    for text in _samples(5000):
        once = normalize_free_text(text)
        assert normalize_free_text(once) == once, ascii(text)


def test_normalised_text_is_one_plain_nfc_line():
    for text in _samples(5000):
        result = normalize_free_text(text)
        assert unicodedata.is_normalized("NFC", result), ascii(text)
        assert not any(char in _REMOVED for char in result), ascii(text)
        assert not any(unicodedata.category(char) == "Cs" for char in result)
        assert result == result.strip(" ")
        assert "  " not in result
        assert not any(char in _WHITESPACE - {" "} for char in result), ascii(text)


def test_visible_characters_are_neither_whitespace_nor_marks():
    assert visible_length("Ä Ö") == 2
    assert visible_length("A\u0308") == 1
    assert visible_length("😀👍") == 2
    assert visible_length("\u0301" * 20) == 0


def test_a_reason_is_stored_normalised():
    assert (
        _Reasoned(reason="Ärende\r\nKS\u202e 2026/123 ").reason == "Ärende KS 2026/123"
    )


def test_a_validated_reason_is_already_normalised():
    for text in _samples(2000):
        try:
            reason = _Reasoned(reason=text).reason
        except ValidationError:
            continue
        assert normalize_free_text(reason) == reason
        assert REASON_MIN_LENGTH <= len(reason) <= REASON_MAX_LENGTH


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
        "abcdefgh" + "e\u200b\u0301",
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


@pytest.mark.parametrize(
    "invisible",
    [
        "\u2060",
        "\u2061",
        "\ufeff",
        "\xad",
        "\u180e",
        "\u034f",
        "\u115f",
        "\u1160",
        "\u3164",
        "\uffa0",
        "\u2800",
        "\U000e0041",
        "\ufe0f",
        "\u0301",
    ],
    ids=lambda char: hex(ord(char)),
)
def test_invisible_characters_never_make_up_the_minimum(invisible):
    with pytest.raises(ValidationError):
        _Reasoned(reason=invisible * REASON_MIN_LENGTH)
    with pytest.raises(ValidationError):
        _Reasoned(reason="x" * (REASON_MIN_LENGTH - 1) + invisible * 20)


def test_characters_are_code_points_not_utf16_units():
    # Astral characters count once, as the stored CHECK counts them.
    with pytest.raises(ValidationError):
        _Reasoned(reason="😀" * (REASON_MIN_LENGTH // 2))
    assert _Reasoned(reason="😀" * REASON_MIN_LENGTH).reason == "😀" * 10
    assert len(_Reasoned(reason="😀" * REASON_MAX_LENGTH).reason) == REASON_MAX_LENGTH
    with pytest.raises(ValidationError):
        _Reasoned(reason="😀" * (REASON_MAX_LENGTH + 1))


def test_hidden_payloads_are_dropped():
    tags = "".join(chr(0xE0000 + ord(char)) for char in "secret")
    selectors = "".join(chr(0xE0100 + byte) for byte in b"payload")
    assert normalize_free_text(f"Ärende KS 2026{tags}") == "Ärende KS 2026"
    assert normalize_free_text(f"Ärende 😀{selectors} KS") == "Ärende 😀 KS"

from __future__ import annotations

from hashlib import sha256

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from eneo.flows.domain.text_processing import SectionManifest


def _manifest() -> dict:
    return {
        "content_sha256": sha256("Å \n猫\tend  ".encode()).hexdigest(),
        "utf8_length": 13,
        "character_length": 10,
        "sources": [],
        "sections": [
            {"core": {"start_char": 0, "end_char": 3}, "output_index": 0},
            {"core": {"start_char": 3, "end_char": 10}, "output_index": 1},
        ],
    }


@st.composite
def _manifest_cases(draw):
    parts = tuple(
        draw(st.lists(st.text(min_size=1, max_size=64), min_size=1, max_size=8))
    )
    text = "".join(parts)
    index = draw(st.integers(min_value=0, max_value=len(text) - 1))
    changed = text[:index] + chr(ord(text[index]) ^ 1) + text[index + 1 :]
    return parts, changed


@given(case=_manifest_cases())
@example(case=(("Å \n", "猫\tend  "), "Å \n猫\tEND  "))
def test_manifest_round_trip_and_rejects_same_length_mutation(case):
    parts, changed = case
    text = "".join(parts)
    sections = []
    start = 0
    for index, part in enumerate(parts):
        end = start + len(part)
        sections.append(
            {"core": {"start_char": start, "end_char": end}, "output_index": index}
        )
        start = end
    manifest = SectionManifest.model_validate(
        {
            "content_sha256": sha256(text.encode()).hexdigest(),
            "utf8_length": len(text.encode()),
            "character_length": len(text),
            "sections": sections,
        }
    )

    assert manifest.resplit(text) == parts
    assert "".join(manifest.resplit(text)) == text
    assert "".join(manifest.resplit(text)).encode() == text.encode()
    assert changed != text
    assert len(changed) == len(text)
    assert len(changed.encode()) == len(text.encode())
    with pytest.raises(ValueError, match="hash"):
        manifest.resplit(changed)


@pytest.mark.parametrize("start", [2, 4])
def test_manifest_rejects_overlapping_or_missing_core_characters(start):
    payload = _manifest()
    payload["sections"][1]["core"]["start_char"] = start

    with pytest.raises(ValidationError, match="coverage"):
        SectionManifest.model_validate(payload)


def test_manifest_rejects_byte_length_used_as_character_length():
    payload = _manifest()
    payload["character_length"] = 13
    payload["sections"][1]["core"]["end_char"] = 13
    manifest = SectionManifest.model_validate(payload)

    with pytest.raises(ValueError, match="character length"):
        manifest.resplit("Å \n猫\tend  ")


def test_manifest_refuses_record_association_drift():
    payload = _manifest()
    payload["sections"][1]["output_index"] = 0

    with pytest.raises(ValidationError, match="output_index"):
        SectionManifest.model_validate(payload)


def test_context_is_readable_but_does_not_own_core_characters():
    payload = _manifest()
    payload["sections"][1]["context"] = [{"start_char": 0, "end_char": 3}]
    manifest = SectionManifest.model_validate(payload)

    assert manifest.resplit("Å \n猫\tend  ") == ("Å \n", "猫\tend  ")

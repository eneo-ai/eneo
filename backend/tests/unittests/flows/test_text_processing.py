from __future__ import annotations

from hashlib import sha256

import pytest
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


def test_manifest_resplits_exact_unicode_text_and_preserves_whitespace():
    manifest = SectionManifest.model_validate(_manifest())

    assert manifest.resplit("Å \n猫\tend  ") == ("Å \n", "猫\tend  ")
    assert "".join(manifest.resplit("Å \n猫\tend  ")) == "Å \n猫\tend  "


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


def test_manifest_refuses_changed_content_with_the_same_length():
    manifest = SectionManifest.model_validate(_manifest())

    with pytest.raises(ValueError, match="hash"):
        manifest.resplit("Å \n猫\tEND  ")


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

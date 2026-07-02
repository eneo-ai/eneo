import pytest

from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    normalize_discovery_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("worddokument", "word dokument"),
        ("Word-dokument", "word dokument"),
        ("word dokument", "word dokument"),
        ("worddokumentet", "word dokument"),
        ("wordfilen", "word fil"),
        ("docxdokument", "docx dokument"),
        ("docxfilen", "docx fil"),
        ("pdfdokument", "pdf dokument"),
        ("pdffilen", "pdf fil"),
        ("pdfrapporten", "pdf rapport"),
        ("jsonfilen", "json fil"),
        ("wordmallen", "word mall"),
    ],
)
def test_normalize_discovery_text_splits_swedish_artifact_compounds(
    text: str,
    expected: str,
) -> None:
    assert normalize_discovery_text(text) == expected


def test_normalize_discovery_text_keeps_unrelated_swedish_words_intact() -> None:
    assert normalize_discovery_text("dokumentation och rapportering") == (
        "dokumentation och rapportering"
    )

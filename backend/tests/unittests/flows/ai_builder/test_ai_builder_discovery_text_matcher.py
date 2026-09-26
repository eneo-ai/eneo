import pytest

from eneo.flows.ai_builder import ai_builder_discovery_text_matcher as text_matcher
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_phrase,
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


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("Create a REPORT, please.", "report"),
        ("Ladda upp WORDDOKUMENTET.", "word dokument"),
        ("Skapa PDFRAPPORTERNA!", "pdf rapport"),
    ],
)
def test_contains_phrase_normalizes_text_and_supported_swedish_compounds(
    text: str,
    phrase: str,
) -> None:
    assert contains_phrase(text, phrase)


@pytest.mark.parametrize(
    ("text", "phrases"),
    [
        ("This is reporting metadata.", ("report",)),
        ("Dokumentation krävs.", ("dokument",)),
        ("Jämförelsevis enkelt.", ("jämförelse", "jämför")),
    ],
)
def test_contains_any_phrase_rejects_substring_false_positives(
    text: str,
    phrases: tuple[str, ...],
) -> None:
    assert not contains_any_phrase(text, phrases)


@pytest.mark.parametrize(
    "text",
    [
        "Ladda upp WORDDOKUMENTET.",
        "Skapa PDFRAPPORTERNA!",
        "dokumentation och rapportering",
        # Past the short-text cache: request text has its own bounded cache.
        "Vi spelar in våra nämndmöten och vill ha protokollet som worddokument. " * 20,
    ],
    ids=["compound", "plural-compound", "unrelated", "long-request-text"],
)
def test_the_cached_normaliser_returns_what_the_normaliser_computes(text: str) -> None:
    uncached = text_matcher._normalize(text)  # noqa: SLF001

    assert normalize_discovery_text(text) == uncached
    # A repeat is served from the cache and is still the same text.
    assert normalize_discovery_text(text) == uncached


def test_the_normaliser_caches_are_bounded() -> None:
    short_cache = text_matcher._normalize_short_text  # noqa: SLF001
    long_cache = text_matcher._normalize_long_text  # noqa: SLF001

    assert short_cache.cache_info().maxsize is not None
    assert long_cache.cache_info().maxsize is not None
    before = short_cache.cache_info().hits
    normalize_discovery_text("wordmallen")
    normalize_discovery_text("wordmallen")
    assert short_cache.cache_info().hits > before

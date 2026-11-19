"""Not-knowing phrases: catch admissions, leave ordinary answers alone."""

import re

import pytest

from eneo.analysis.gap_patterns import (
    NOT_KNOWING_PATTERNS,
    NOT_KNOWING_REGEX,
    not_knowing_fragment,
)


@pytest.mark.parametrize(
    "answer,fragment",
    [
        (
            "Jag hittar tyvärr inte den informationen i mina källor.",
            "hittar tyvärr inte",
        ),
        ("Det framgår inte av underlaget vad avgiften är.", "framgår inte"),
        (
            "Jag kan tyvärr inte hjälpa till med deklarationen.",
            "kan tyvärr inte hjälpa",
        ),
        ("Jag har ingen information om öppettiderna.", "har ingen information"),
        ("Det finns tyvärr ingen uppgift om detta.", "finns tyvärr ingen uppgift"),
        ("Den frågan ligger utanför mina källor.", "utanför mina källor"),
        ("I couldn't find anything about that in the documents.", "couldn't find"),
        ("There is no information about parking permits here.", "no information about"),
        ("I'm unable to answer that from the sources.", "i'm unable to"),
        ("The sources do not cover school transport.", "sources do not cover"),
    ],
)
def test_admissions_are_matched(answer, fragment):
    matched = not_knowing_fragment(answer)

    assert matched is not None
    assert matched.lower() == fragment


@pytest.mark.parametrize(
    "answer",
    [
        "Jag hittar tre alternativ för dig: A, B och C.",
        "Du hittar blanketten på kommunens webbplats.",
        "Ansökan finns i e-tjänsten och tar en vecka att handlägga.",
        "Det framgår av detaljplanen att tomten får bebyggas.",
        "You can find the form on the website.",
        "The sources mention three options.",
    ],
)
def test_ordinary_answers_are_not_matched(answer):
    assert not_knowing_fragment(answer) is None


def test_matching_is_case_insensitive():
    assert not_knowing_fragment("JAG VET TYVÄRR INTE.") is not None


def test_patterns_use_only_the_dialect_neutral_subset():
    """The same source runs as a Postgres ARE and a Python re: no
    look-around, word boundaries or named groups."""
    for pattern in NOT_KNOWING_PATTERNS:
        assert "(?" not in pattern
        assert "\\b" not in pattern
        re.compile(pattern)
    assert NOT_KNOWING_REGEX.count("|") >= len(NOT_KNOWING_PATTERNS) - 1

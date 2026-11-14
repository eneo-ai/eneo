"""The Python port of the frontends' quote convention.

The first cases are the ones the TypeScript originals are tested with
(`questionQuote.test.ts` in the SvelteKit app, `question-quote.test.ts` in
web-next), so the two sides cannot drift apart unnoticed.
"""

import pytest

from eneo.conversations.question_quote import (
    QuestionContext,
    QuestionQuote,
    compose_question_with_context,
    compose_quoted_question,
    parse_quoted_question,
)

FILE_ID = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
QUOTE = QuestionQuote(
    text="Första stycket\n\nAndra stycket", file_name="Skrivelse (v2).docx"
)


def test_puts_the_quote_and_its_file_before_the_question():
    assert (
        compose_quoted_question(QUOTE, "Korta ner det här")
        == "> Första stycket\n>\n> Andra stycket\n> (Skrivelse (v2).docx)\n\n"
        "Korta ner det här"
    )
    assert (
        compose_quoted_question(
            QuestionQuote(text="One\n\nTwo", file_name="a.md"), "Why?"
        )
        == "> One\n>\n> Two\n> (a.md)\n\nWhy?"
    )
    assert compose_quoted_question(None, "Hej") == "Hej"


def test_reads_back_what_it_composed():
    assert parse_quoted_question(
        compose_quoted_question(QUOTE, "Korta ner\ndet här")
    ) == (QUOTE, "Korta ner\ndet här")
    assert parse_quoted_question(compose_quoted_question(QUOTE, "")) == (QUOTE, "")


def test_reads_back_the_exact_file_and_where_the_passage_stands():
    quote = QuestionQuote(
        text="Same line",
        file_name="notes, v2.md",
        file_id=FILE_ID,
        locator="occurrence 2 of 5",
    )
    assert parse_quoted_question(compose_quoted_question(quote, "Shorter?")) == (
        quote,
        "Shorter?",
    )


@pytest.mark.parametrize(
    "located",
    [
        QuestionQuote(
            text="Personal",
            file_name="Budget, utfall.xlsx",
            locator="occurrence 2 of 5",
        ),
        QuestionQuote(
            text="Personal",
            file_name="utfall.xlsx",
            locator="row 3 (data row 2), cells: Vård (norr), Augusti | Personal | 19072",
        ),
        QuestionQuote(
            text="Personal",
            file_name="utfall.xlsx",
            locator='sheet "Utfall, 2025", rows 8-12 (data rows 7-11)',
        ),
    ],
)
def test_carries_where_a_repeated_passage_stands_after_the_file_name(located):
    question = compose_quoted_question(located, "Ändra")
    assert f"> ({located.file_name}, {located.locator})" in question
    assert parse_quoted_question(question) == (located, "Ändra")


@pytest.mark.parametrize(
    "quote",
    [
        QuestionQuote(
            file_id="11111111-2222-3333-4444-555555555555",
            file_name="Budget, 2025.xlsx",
            text="D · Budget: 21 245",
            locator='sheet "Utfall 2025", row 2 (data row 1), column D',
        ),
        QuestionQuote(
            file_id="11111111-2222-3333-4444-555555555555",
            file_name="Report.docx",
            text="Paragraph",
        ),
        QuestionQuote(
            file_id="12345678-1234-4234-8234-123456789012",
            file_name="budget.xlsx",
            text="Selected rows: 3",
            locator='sheet "Budget", source rows [2,4,8]',
        ),
    ],
)
def test_retains_the_exact_file_and_location(quote):
    assert parse_quoted_question(compose_quoted_question(quote, "Explain")) == (
        quote,
        "Explain",
    )


def test_reads_a_quote_typed_by_hand_without_a_file():
    assert parse_quoted_question("> citat\n\nfråga") == (
        QuestionQuote(text="citat"),
        "fråga",
    )


@pytest.mark.parametrize(
    "question",
    [
        "> 5 är större\nän 3",
        ">inget mellanslag\n\nfråga",
        "Vanlig fråga",
        "> not a paragraph\nnext line",
    ],
)
def test_leaves_text_that_only_starts_with_a_quote_mark_alone(question):
    assert parse_quoted_question(question) == (None, question)


# Context sent with a question.


def test_no_context_leaves_the_question_untouched():
    assert compose_question_with_context([], "Hej") == "Hej"


def test_one_context_item_is_one_quote_named_by_its_label():
    composed = compose_question_with_context(
        [QuestionContext(label="Ärende 2026-104", text="Rad ett\n\nRad tre")],
        "Vad gäller?",
    )

    assert composed == "> Rad ett\n>\n> Rad tre\n> (Ärende 2026-104)\n\nVad gäller?"
    assert parse_quoted_question(composed) == (
        QuestionQuote(text="Rad ett\n\nRad tre", file_name="Ärende 2026-104"),
        "Vad gäller?",
    )


def test_several_items_share_the_one_block_the_frontends_read():
    composed = compose_question_with_context(
        [
            QuestionContext(label="Kalender", text="Möte 10.00"),
            QuestionContext(label="Ärende", text="Väntar på svar"),
        ],
        "Hinner jag?",
    )

    assert composed == (
        "> Möte 10.00\n> (Kalender)\n>\n> Väntar på svar\n> (Ärende)\n\nHinner jag?"
    )
    # The whole block is the quote and nothing of it leaks into the question;
    # the last label is its source, the earlier one stays under its text.
    assert parse_quoted_question(composed) == (
        QuestionQuote(
            text="Möte 10.00\n(Kalender)\n\nVäntar på svar", file_name="Ärende"
        ),
        "Hinner jag?",
    )


def test_text_that_looks_like_a_quote_or_a_source_survives_the_round_trip():
    text = "> redan citerat\n(inte en källa)\n\n>utan mellanslag"
    composed = compose_question_with_context(
        [QuestionContext(label="Anteckning", text=text)], "Sammanfatta"
    )

    assert parse_quoted_question(composed) == (
        QuestionQuote(text=text, file_name="Anteckning"),
        "Sammanfatta",
    )


def test_a_label_stays_on_one_line_and_line_endings_are_normalised():
    composed = compose_question_with_context(
        [QuestionContext(label="  Två\nrader \t här ", text="\r\nEtt\r\nTvå\n\n")],
        "Fråga",
    )

    assert composed == "> Ett\n> Två\n> (Två rader här)\n\nFråga"


def test_context_without_a_question_is_only_the_quote():
    assert (
        compose_question_with_context([QuestionContext(label="Källa", text="Text")], "")
        == "> Text\n> (Källa)"
    )

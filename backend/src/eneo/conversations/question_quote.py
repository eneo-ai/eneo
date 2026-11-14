"""A quote carried in the text of a question.

A Python port of the convention the frontends own
(`frontend/apps/web/src/lib/features/chat/questionQuote.ts` and
`frontend/apps/web-next/src/features/chat/side-panel/question-quote.ts`). The
quote travels as the opening lines of the question, in a form both the model
and the question bubble read:

    > the quoted text,
    > line by line
    > (name of the source[, locator])

    what the person asks about it

`compose_question_with_context` uses it to put the context another client
sends with a question in front of that question, so both frontends draw it as
a quote. Keep this module pure and in step with the TypeScript originals.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

_SOURCE_LINE = re.compile(r"\((.+)\)")
_FILE_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_FILE_LOCATOR = re.compile(r"file ([0-9a-f-]{36})(?:; (.*))?", re.IGNORECASE)

# The locator grammar of the previews (`passage-locator.ts`, `table-reference.ts`).
_ROWS_LOCATOR = re.compile(
    r'(?:sheet "(.*?)", )?rows? ([0-9]+)(?:-[0-9]+)? '
    r"\((?:the header(?: and data rows? [0-9]+(?:-[0-9]+)?)?"
    r"|data rows? [0-9]+(?:-[0-9]+)?)\)(?:, cells: .*)?"
)
_OCCURRENCE_LOCATOR = re.compile(r"occurrence ([0-9]+) of [0-9]+")
_TABLE_CELLS_LOCATOR = re.compile(
    r"table ([0-9]+), rows? ([0-9]+)(?:-([0-9]+))?, columns? ([0-9]+)(?:-([0-9]+))?"
)
_SHEET_ROW_LOCATOR = re.compile(
    r'sheet ("(?:[^"\\]|\\.)*"), row ([0-9]+) \(data row ([0-9]+)\)'
    r"(?:, column ([A-Z]{1,5}))?"
)
_SHEET_ROWS_LOCATOR = re.compile(
    r'sheet ("(?:[^"\\]|\\.)*"), source rows (\[[0-9,]+\])'
)
_MAX_SHEET_ROW = 1_048_576
_MAX_SAFE_INTEGER = 2**53 - 1


@dataclass(frozen=True, slots=True)
class QuestionQuote:
    text: str
    # The source the text was taken from, when the quote names one.
    file_name: str | None = None
    # Which of several identical passages in the source is meant.
    locator: str | None = None
    # Exact immutable file, when the quote names one.
    file_id: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionContext:
    """Text another client sends with a question, and what to call it."""

    label: str
    text: str


def _json_string(source: str) -> bool:
    try:
        return isinstance(json.loads(source), str)
    except ValueError:
        return False


def _is_sheet_locator(text: str) -> bool:
    multiple = _SHEET_ROWS_LOCATOR.fullmatch(text)
    if multiple:
        # A JSON array of row numbers: no empty item, no leading zero.
        rows = multiple[2][1:-1].split(",")
        return (
            _json_string(multiple[1])
            and len(rows) <= 500
            and all(
                row != "" and not row.startswith("0") and int(row) <= _MAX_SHEET_ROW
                for row in rows
            )
            and all(int(row) >= 2 for row in rows)
        )
    match = _SHEET_ROW_LOCATOR.fullmatch(text)
    if not match:
        return False
    row = int(match[2])
    return (
        2 <= row <= _MAX_SAFE_INTEGER
        and int(match[3]) == row - 1
        and _json_string(match[1])
    )


def is_locator(text: str) -> bool:
    """Whether `text` is a locator, as opposed to the tail of a source name."""
    return (
        _is_sheet_locator(text)
        or _ROWS_LOCATOR.fullmatch(text) is not None
        or _OCCURRENCE_LOCATOR.fullmatch(text) is not None
        or _TABLE_CELLS_LOCATOR.fullmatch(text) is not None
    )


def _quote_lines(quote: QuestionQuote) -> list[str]:
    """The quoted text and its source line, before the quote marks."""
    identity = (
        f"file {quote.file_id.lower()}"
        if quote.file_id and _FILE_ID.fullmatch(quote.file_id)
        else ""
    )
    locator = "; ".join(part for part in (identity, quote.locator) if part)
    source = f"{quote.file_name}, {locator}" if locator else quote.file_name
    return [*quote.text.split("\n"), f"({source})"]


def _quoted(lines: Sequence[str], question: str) -> str:
    quoted = "\n".join(">" if line == "" else f"> {line}" for line in lines)
    return quoted if question == "" else f"{quoted}\n\n{question}"


def compose_quoted_question(quote: QuestionQuote | None, question: str) -> str:
    """The text to send for a question that quotes a source."""
    if quote is None:
        return question
    return _quoted(_quote_lines(quote), question)


def parse_quoted_question(question: str) -> tuple[QuestionQuote | None, str]:
    """Split a question into the quote it opens with, if any, and the rest."""
    lines = question.split("\n")
    end = 0
    while end < len(lines) and (lines[end] == ">" or lines[end].startswith("> ")):
        end += 1
    # A quote is its own paragraph: text that merely starts with ">" is not one.
    if end == 0 or (end < len(lines) and lines[end] != ""):
        return None, question
    quoted = [line[2:] for line in lines[:end]]
    source_match = _SOURCE_LINE.fullmatch(quoted[-1]) if len(quoted) > 1 else None
    source = source_match[1] if source_match else None
    if source is not None:
        quoted.pop()
    # The locator follows the source name's ", "; a name may hold commas too.
    file_name = source
    locator: str | None = None
    file_id: str | None = None
    at = source.find(", ") if source is not None else -1
    while source is not None and at != -1:
        suffix = source[at + 2 :]
        identity = _FILE_LOCATOR.fullmatch(suffix)
        if (
            identity
            and _FILE_ID.fullmatch(identity[1])
            and (not identity[2] or is_locator(identity[2]))
        ):
            file_name = source[:at]
            file_id = identity[1].lower()
            locator = identity[2] or None
            break
        if is_locator(suffix):
            file_name = source[:at]
            locator = suffix
            break
        at = source.find(", ", at + 1)
    return (
        QuestionQuote(
            text="\n".join(quoted),
            file_name=file_name,
            locator=locator,
            file_id=file_id,
        ),
        "\n".join(lines[end + 1 :]),
    )


def compose_question_with_context(
    context: Sequence[QuestionContext], question: str
) -> str:
    """The text to store and send for a question that came with context.

    Each item is written as a quote: its text, then its label as the source
    line. The frontends read ONE quote block per question (the opening run of
    quote lines, closed by a blank line), so several items share one block,
    separated by an empty quote line. The parser then shows the whole block as
    the quote and the last item's label as its source; the earlier labels stay
    readable inside the quote, each on the line under its text.

    A label is put on one line, since a source line cannot span two; line
    endings in a text are normalised and blank lines around it dropped.
    """
    lines: list[str] = []
    for item in context:
        if lines:
            lines.append("")
        text = item.text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        lines.extend(
            _quote_lines(
                QuestionQuote(text=text, file_name=" ".join(item.label.split()))
            )
        )
    return _quoted(lines, question) if lines else question

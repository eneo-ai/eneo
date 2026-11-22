"""Download names for the documents a flow run generates."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import cached_property
from typing import cast

from eneo.flows.domain.flow import flow_run_day
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.domain.step_deliverable import (
    file_name_expressions,
    form_field_read_by,
)
from eneo.flows.domain.step_output import utf8_prefix
from eneo.flows.flow_run_redaction import redact_string
from eneo.flows.variable_resolver import TEMPLATE_VARIABLE_PATTERN

# NTFS allows 255 UTF-16 units in a name, ext4 and APFS 255 bytes; no
# character takes more UTF-16 units than UTF-8 bytes, so 255 UTF-8 bytes fits
# them all.
MAX_FILE_NAME_BYTES = 255
_DOCUMENT_TYPES = frozenset({"pdf", "docx"})
# For a flow name that holds nothing a file name can keep.
_FALLBACK_FLOW_NAME = "Dokument"
# Only a name's first 255 bytes are kept, but a credential starting in them can
# end after them, so masking judges the whole filled-in name. The masking
# patterns take time quadratic in a long run of word characters, and a form
# value has no length limit of its own, so a value or a filled-in name longer
# than this is never judged: cut, it could lose what makes it a credential (the
# `@` after a URL's user information), so it is treated as one.
_MASKED_PREFIX_CHARS = 1000
# What publishing puts in place of each expression to judge the fixed text.
_PLAIN_VALUE = "x"
# Refused by Windows in names; "/" also separates directories everywhere else.
_RESERVED_CHARACTERS = frozenset('\\/:*?"<>|')
# Controls, invisible format characters (bidirectional overrides, zero-width
# spaces), lone surrogates and unassigned code points (U+FFFE, which XML and
# so a DOCX title refuses): a name shows what it holds, and encodes.
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Cn"})
# Windows opens the device instead of the file when the part of a name before
# its first dot is one of these, whatever case and trailing spaces it has.
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{port}{digit}" for port in ("COM", "LPT") for digit in "123456789¹²³"}
)


@dataclass(frozen=True)
class GeneratedFileNames:
    """Names every document of one run from the definition the run is pinned to.

    ``<flow name> <YYYY-MM-DD>.<ext>``, or for a run with a name and a day (a
    meeting's, from its form) that name and that day. When the definition has more than one
    step producing a document type, each such document also carries its
    step's name before the date, and when two of them would still share a name,
    every document of that type carries ``Steg <n>`` too. Both are decided from
    the whole definition, so a document's name does not depend on which steps
    have rendered so far.

    A step whose deliverable has a file name of its own is named by it, filled
    in from the run's form, instead of by the flow's and the step's names; the
    day and the numbering apply as to any other document. When a form value
    or the filled-in name reads as a credential or is longer than masking
    judges, or the name holds nothing, the deliverable's label names the
    document: it is fixed text, while the run's own name can be the very form
    value masking refused.
    """

    flow_name: str
    run_day: date
    step_names: Mapping[int, str]
    # The step orders producing each document type.
    documents: Mapping[str, tuple[int, ...]]
    # Each step's own file name, filled in and cleaned, or its label in its
    # place; a step without a file name of its own is not listed.
    own_names: Mapping[int, str]

    @classmethod
    def for_run(
        cls,
        *,
        flow_name: str,
        steps: Sequence[RuntimeStep],
        run_created_at: datetime,
        form_values: Mapping[str, object],
        run_label: str | None = None,
        run_date: date | None = None,
    ) -> GeneratedFileNames:
        return cls(
            # A run's own name, when a file name can keep any of it.
            flow_name=run_label if run_label and _clean(run_label) else flow_name,
            run_day=flow_run_day(run_date=run_date, created_at=run_created_at),
            step_names={step.step_order: step.user_description or "" for step in steps},
            documents={
                output_type: tuple(
                    step.step_order for step in steps if step.output_type == output_type
                )
                for output_type in _DOCUMENT_TYPES
            },
            own_names={
                step.step_order: _own_name(step.deliverable.file_name, form_values)
                or _clean(step.deliverable.label)
                or _FALLBACK_FLOW_NAME
                for step in steps
                if step.deliverable is not None
                and step.deliverable.file_name is not None
            },
        )

    def name(self, *, step_order: int, output_type: str) -> str:
        stem = self.stem(step_order=step_order, output_type=output_type)
        return f"{stem}.{output_type}"

    def stem(self, *, step_order: int, output_type: str) -> str:
        """The name without its extension, which is also the document's title."""
        numbered = output_type in self._numbered_types
        return self._stem(step_order, output_type, numbered=numbered)

    @cached_property
    def _numbered_types(self) -> frozenset[str]:
        # Numbering only the clashing ones could meet a third name ("Beslut
        # Steg 1"); numbered all, the names end in distinct numbers. Names
        # differing only in case are one file on Windows and macOS.
        numbered: set[str] = set()
        for output_type, orders in self.documents.items():
            stems = {
                self._stem(order, output_type, numbered=False).casefold()
                for order in orders
            }
            if len(stems) < len(orders):
                numbered.add(output_type)
        return frozenset(numbered)

    def _stem(self, step_order: int, output_type: str, *, numbered: bool) -> str:
        own_name = self.own_names.get(step_order)
        words = [own_name or _clean(self.flow_name) or _FALLBACK_FLOW_NAME]
        if own_name is None and len(self.documents.get(output_type, ())) > 1:
            words.append(
                _clean(self.step_names.get(step_order, "")) or f"Steg {step_order}"
            )
        number = f" Steg {step_order}" if numbered else ""
        tail = f"{number} {self.run_day.isoformat()}"
        head = utf8_prefix(
            " ".join(words),
            max_bytes=MAX_FILE_NAME_BYTES
            - len(f"{tail}.{output_type}".encode("utf-8")),
        )
        stem = head.rstrip(" .") + tail
        # The dot after a device name becomes a space: "CON.rapport" downloads
        # as "CON rapport <day>".
        while stem.partition(".")[0].rstrip(" ").upper() in _WINDOWS_DEVICE_NAMES:
            stem = " ".join(stem.replace(".", " ", 1).split())
        return stem


def file_name_reads_as_credential(file_name: str) -> bool:
    """Whether masking changes ``file_name``'s fixed text, each expression
    standing for a plain word: no run could then be named by it."""
    sample = TEMPLATE_VARIABLE_PATTERN.sub(_PLAIN_VALUE, file_name)
    return _masked(sample) or _masked(_clean(sample))


def _masked(text: str) -> bool:
    return redact_string(text, key=None) != text


def _own_name(file_name: str, form_values: Mapping[str, object]) -> str:
    """``file_name`` with each `{{ flow_input.<field> }}` filled in from the
    run's form, cleaned and cut to a file name's length; empty when nothing is
    left, or when a value or the filled-in name is longer than masking judges
    or masking would change it, as written or cleaned. Anything else
    between `{{ }}`, and a name with a stray brace, fill in nothing: publish
    refuses them, and a run must never fail on its name.

    A name missing one value is never built: the value left out can hold what
    makes the rest a credential (the `@` after a URL's user information), so
    only the whole filled-in name is judged, never a part of it."""
    expressions = file_name_expressions(file_name)
    if expressions is None:
        return ""
    values: list[str] = []
    for expression in expressions:
        field = form_field_read_by(expression)
        value = _form_value_text(form_values.get(field), field=field) if field else ""
        if value is None:
            return ""
        values.append(value)

    filled_values = iter(values)
    filled = TEMPLATE_VARIABLE_PATTERN.sub(lambda _: next(filled_values), file_name)
    if len(filled) > _MASKED_PREFIX_CHARS:
        return ""
    # A value clean on its own can complete a credential with the fixed text
    # around it (`token={{ flow_input.x }}`), and cleaning can make one
    # (`Bearer/<token>` becomes `Bearer <token>`); a separator cleaning turns
    # into a space (`password:<value>`) is judged as written. The name is cut
    # only after it is judged, so a credential running past the cut counts.
    cleaned = _clean(filled)
    if _masked(filled) or _masked(cleaned):
        return ""
    return _clean(utf8_prefix(cleaned, max_bytes=MAX_FILE_NAME_BYTES))


def _form_value_text(value: object, *, field: str) -> str | None:
    """A form value as it is written into a file name, empty when the field
    holds nothing a name can show; None, leaving the value out, when masking
    would change it or it is longer than masking judges, so a credential typed
    into the form never names a file."""
    try:
        text = _scalar_text(value)
        if text is None and isinstance(value, (list, tuple)):
            items = (_scalar_text(item) for item in cast(Sequence[object], value))
            text = ", ".join(item for item in items if item)
    except ValueError:
        # An integer past Python's digit limit for int-to-text conversion,
        # far longer than masking judges.
        return None
    if not text:
        return ""
    if len(text) > _MASKED_PREFIX_CHARS or redact_string(text, key=field) != text:
        return None
    return text


def _scalar_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return ""
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else ""
    if isinstance(value, int):
        return str(value)
    return None


def _clean(text: str) -> str:
    """``text`` as part of a file name on Windows, macOS and Linux."""
    kept = "".join(
        " "
        if char in _RESERVED_CHARACTERS
        or unicodedata.category(char) in _REFUSED_CATEGORIES
        else char
        for char in unicodedata.normalize("NFC", text)
    )
    return " ".join(kept.split()).strip(" .")

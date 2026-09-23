"""Download names for the documents a flow run generates."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import cached_property

from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.domain.step_output import utf8_prefix

# NTFS allows 255 UTF-16 units in a name, ext4 and APFS 255 bytes; no
# character takes more UTF-16 units than UTF-8 bytes, so 255 UTF-8 bytes fits
# them all.
MAX_FILE_NAME_BYTES = 255
_DOCUMENT_TYPES = frozenset({"pdf", "docx"})
# For a flow name that holds nothing a file name can keep.
_FALLBACK_FLOW_NAME = "Dokument"
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

    ``<flow name> <YYYY-MM-DD>.<ext>``. When the definition has more than one
    step producing a document type, each such document also carries its
    step's name before the date, and when two of them would still share a name,
    every document of that type carries ``Steg <n>`` too. Both are decided from
    the whole definition, so a document's name does not depend on which steps
    have rendered so far.
    """

    flow_name: str
    run_day: date
    step_names: Mapping[int, str]
    # The step orders producing each document type.
    documents: Mapping[str, tuple[int, ...]]

    @classmethod
    def for_run(
        cls,
        *,
        flow_name: str,
        steps: Sequence[RuntimeStep],
        run_created_at: datetime,
    ) -> GeneratedFileNames:
        if run_created_at.tzinfo is None:
            run_created_at = run_created_at.replace(tzinfo=timezone.utc)
        return cls(
            flow_name=flow_name,
            # Eneo has no user or tenant time zone: a run is dated by its UTC day.
            run_day=run_created_at.astimezone(timezone.utc).date(),
            step_names={step.step_order: step.user_description or "" for step in steps},
            documents={
                output_type: tuple(
                    step.step_order for step in steps if step.output_type == output_type
                )
                for output_type in _DOCUMENT_TYPES
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
        words = [_clean(self.flow_name) or _FALLBACK_FLOW_NAME]
        if len(self.documents.get(output_type, ())) > 1:
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

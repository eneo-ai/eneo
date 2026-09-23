"""Download names for the documents a flow run generates."""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone

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
# spaces) and lone surrogates: a name shows what it holds, and encodes.
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


@dataclass(frozen=True)
class GeneratedFileNames:
    """Names every document of one run from the definition the run is pinned to.

    ``<flow name> <YYYY-MM-DD>.<ext>``. When the definition has more than one
    step producing a document type, each such document also carries its
    step's name before the date; that is decided from the whole definition, so
    a document's name does not depend on which steps have rendered so far.
    """

    flow_name: str
    run_day: date
    step_names: Mapping[int, str]
    shared_types: frozenset[str]

    @classmethod
    def for_run(
        cls,
        *,
        flow_name: str,
        steps: Sequence[RuntimeStep],
        run_created_at: datetime,
    ) -> GeneratedFileNames:
        documents = Counter(
            step.output_type for step in steps if step.output_type in _DOCUMENT_TYPES
        )
        if run_created_at.tzinfo is None:
            run_created_at = run_created_at.replace(tzinfo=timezone.utc)
        return cls(
            flow_name=flow_name,
            # Eneo has no user or tenant time zone: a run is dated by its UTC day.
            run_day=run_created_at.astimezone(timezone.utc).date(),
            step_names={step.step_order: step.user_description or "" for step in steps},
            shared_types=frozenset(
                output_type for output_type, count in documents.items() if count > 1
            ),
        )

    def name(self, *, step_order: int, output_type: str) -> str:
        stem = self.stem(step_order=step_order, output_type=output_type)
        return f"{stem}.{output_type}"

    def stem(self, *, step_order: int, output_type: str) -> str:
        """The name without its extension, which is also the document's title."""
        words = [_clean(self.flow_name) or _FALLBACK_FLOW_NAME]
        if output_type in self.shared_types:
            words.append(
                _clean(self.step_names.get(step_order, "")) or f"Steg {step_order}"
            )
        day = f" {self.run_day.isoformat()}"
        suffix = f"{day}.{output_type}"
        # ponytail: two steps with one name, or a flow name long enough to cut
        # the step name away, give two documents one name; add the step number
        # if that happens.
        head = utf8_prefix(
            " ".join(words), max_bytes=MAX_FILE_NAME_BYTES - len(suffix.encode("utf-8"))
        )
        return head.rstrip(" .") + day


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

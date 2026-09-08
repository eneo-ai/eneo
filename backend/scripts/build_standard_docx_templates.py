"""Build the neutral runtime DOCX template and developer example templates.

Run from ``backend/``::

    uv run --no-sync python scripts/build_standard_docx_templates.py

The templates land in ``src/eneo/flows/runtime/templates/standard/`` and are
committed, so a build here is a reviewable change. Every fill target is a Word
content control (see ``eneo.flows.runtime.document_rendering.docx_content_controls``) with a tag
the flow binds to, a label, and placeholder text that doubles as the authoring
hint the AI Builder reads. The template owns everything visual: sv-SE
language, the built-in heading styles with a house look, list styles, a table
style with a marked header row, page numbers and core properties. The report
and meeting templates are examples, not runtime defaults. Authors copy these
files, add their organisation's branding, and
add or rename controls from Word's Developer tab; no code is needed.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eneo.flows.runtime.document_rendering.docx_content_controls import (  # noqa: E402
    append_rich_control,
    append_text_control,
)

LANGUAGE = "sv-SE"
OUTPUT_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "eneo"
    / "flows"
    / "runtime"
    / "templates"
    / "standard"
)
_ACCENT_BLUE = RGBColor(0x00, 0x5B, 0x8C)
_ACCENT_GREEN = RGBColor(0x2E, 0x6B, 0x3A)
_INK = RGBColor(0x1F, 0x1F, 0x1F)


def build_dokument() -> bytes:
    """Body template for verbatim rendering: house look, one document control."""

    document = _base(title="Dokument", accent=_ACCENT_BLUE)
    append_rich_control(
        document,
        tag="dokument",
        label="Dokument",
        hint="Hela dokumentet: börja med dokumentets titel som rubrik.",
    )
    return _bytes(document)


def build_rapport() -> bytes:
    document = _base(title="Rapport", accent=_ACCENT_BLUE)
    title = document.add_paragraph(style="Title")
    append_text_control(
        title, tag="titel", label="Rapportens titel", hint="Rapportens titel"
    )
    _metadata_line(document, "Datum: ", tag="datum", label="Datum", hint="ÅÅÅÅ-MM-DD")
    _metadata_line(
        document,
        "Författare: ",
        tag="forfattare",
        label="Författare",
        hint="Namn och funktion",
    )
    for tag, label, hint in (
        (
            "sammanfattning",
            "Sammanfattning",
            "Sammanfatta rapportens viktigaste innehåll i två till fyra stycken "
            "löpande text, utan egna rubriker.",
        ),
        (
            "bakgrund",
            "Bakgrund",
            "Beskriv bakgrund och syfte. Underrubriker och punktlistor får användas.",
        ),
        (
            "analys",
            "Analys",
            "Redovisa analysen med en underrubrik per delområde. Använd tabeller "
            "med rubrikrad för siffror.",
        ),
        (
            "slutsatser",
            "Slutsatser och rekommendationer",
            "Ange slutsatserna som löpande text och rekommendationerna som en "
            "numrerad lista.",
        ),
    ):
        document.add_heading(label, level=1)
        append_rich_control(document, tag=tag, label=label, hint=hint)
    return _bytes(document)


def build_motesprotokoll() -> bytes:
    document = _base(title="Mötesprotokoll", accent=_ACCENT_GREEN)
    title = document.add_paragraph(style="Title")
    append_text_control(
        title, tag="titel", label="Mötets titel", hint="Mötets namn eller ärende"
    )
    _metadata_line(document, "Datum: ", tag="datum", label="Datum", hint="ÅÅÅÅ-MM-DD")
    _metadata_line(
        document,
        "Plats: ",
        tag="plats",
        label="Plats",
        hint="Lokal eller digitalt möte",
    )
    for tag, label, hint in (
        (
            "narvarande",
            "Närvarande",
            "Lista deltagarna som en punktlista med namn och roll.",
        ),
        (
            "dagordning",
            "Dagordning",
            "Numrerad lista över de punkter som behandlades.",
        ),
        (
            "diskussion",
            "Diskussion",
            "Sammanfatta diskussionen med en underrubrik per dagordningspunkt.",
        ),
        (
            "beslut",
            "Beslut",
            "Varje beslut som en punkt i en punktlista, formulerat som ett fattat "
            "beslut.",
        ),
        (
            "atgarder",
            "Åtgärder",
            "Tabell med kolumnerna Åtgärd, Ansvarig och Klart senast, en rad per "
            "åtgärd.",
        ),
    ):
        document.add_heading(label, level=1)
        append_rich_control(document, tag=tag, label=label, hint=hint)
    return _bytes(document)


def _base(*, title: str, accent: RGBColor):
    document = Document()
    _set_language(document)
    _house_styles(document, accent=accent)
    _page_layout(document)
    document.core_properties.title = title
    document.core_properties.language = LANGUAGE
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    return document


def _metadata_line(document, prefix: str, *, tag: str, label: str, hint: str) -> None:
    paragraph = document.add_paragraph(prefix)
    append_text_control(paragraph, tag=tag, label=label, hint=hint)


def _set_language(document) -> None:
    for lang in document.styles.element.iter(qn("w:lang")):
        lang.set(qn("w:val"), LANGUAGE)
        lang.set(qn("w:eastAsia"), LANGUAGE)


def _house_styles(document, *, accent: RGBColor) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for level, size in ((1, 18), (2, 14), (3, 12), (4, 11), (5, 11), (6, 11)):
        heading = document.styles[f"Heading {level}"]
        heading.font.name = "Arial"
        heading.font.size = Pt(size)
        heading.font.bold = True
        heading.font.italic = False
        heading.font.color.rgb = accent if level == 1 else _INK
        heading.paragraph_format.space_before = Pt(18 if level == 1 else 12)
        heading.paragraph_format.space_after = Pt(6)
        heading.paragraph_format.keep_with_next = True
    title = document.styles["Title"]
    title.font.name = "Arial"
    title.font.size = Pt(26)
    title.font.color.rgb = accent
    for name in (
        "List Bullet",
        "List Bullet 2",
        "List Bullet 3",
        "List Number",
        "List Number 2",
        "List Number 3",
    ):
        document.styles[name].font.name = "Arial"
        document.styles[name].font.size = Pt(11)
    table_grid = document.styles["Table Grid"]
    table_grid.font.name = "Arial"
    table_grid.font.size = Pt(10)


def _page_layout(document) -> None:
    section = document.sections[0]
    for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, side, Cm(2.5))
    footer_paragraph = section.footer.paragraphs[0]
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    run_element = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run_element.append(text)
    field.append(run_element)
    footer_paragraph._p.append(field)


def _bytes(document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, build in (
        ("dokument.docx", build_dokument),
        ("rapport.docx", build_rapport),
        ("motesprotokoll.docx", build_motesprotokoll),
    ):
        (OUTPUT_DIR / name).write_bytes(build())
        print(f"wrote {OUTPUT_DIR / name}")


if __name__ == "__main__":
    main()

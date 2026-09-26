#!/usr/bin/env python3
"""Generate deterministic local fixtures for the AI Builder battle corpus.

The script never calls a live API. Run it from ``backend/`` in the backend virtual environment (it reads the
harness's rules, and the harness reads the backend settings):

    PYTHONPATH=src .venv/bin/python scripts/generate_battle_fixtures.py [--check]

It writes the fixture files and ``manifest.json`` below
``scripts/fixtures/ai_builder_battle``. The manifest pins each fixture's content
SHA-256; a battle case attaches a fixture by name and the harness uploads it
itself, so a fresh environment can run the suite without hand-provisioned file
IDs. Nothing here is environment-specific and nothing needs post-upload capture.

Two kinds of fixture live there. The legacy ones are built by the functions
below. Every other document is rendered from its content spec in ``specs/``
(see ``ai_builder_fixture_render.py``), and a spec may not claim an existing
fixture's name.

The checked-in ``01_protokoll_bun_2026_02_25.pdf`` is the canonical authentic
§17 protokollsutdrag (three pages) from the source and its SHA-256 is pinned
below. ``--source`` may initialize or replace that file only when the supplied
bytes match the pinned hash.

``--check`` changes nothing in the repository. It prints one line per problem and exits 1 when the committed bytes,
the manifest and the specs disagree: a manifest the harness would refuse, a pinned file that is missing or has other
bytes, a pinned file with neither a spec nor a legacy generator, an entry of the fixture directory the manifest does
not pin (other than ``UNPINNED_FIXTURE_ENTRIES``), a spec that is invalid or whose file is not pinned, a committed
file whose text, read through the product's own extractor, either lacks a piece of its spec's content or reads
differently from the spec rendered now, or a DOCX template whose content controls (every field the product's
template inspector returns, in order, with each control's XML) differ from the spec rendered now, or that the
product refuses as a template (every read failure normalized as the runtime does). Byte equality after re-rendering
is NOT required: PDF bytes and page layout depend on the rendering machine's fonts, so a PDF is compared by its
layout-free readings and every other format by its exact text.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import importlib
import io
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Collection, Mapping, Sequence
from itertools import zip_longest
from pathlib import Path
from types import ModuleType

import docx
from docx.document import Document as DocxDocument
from lxml import etree

from eneo.files.docx_template_validation import (
    normalize_template_extraction_error,
    validate_docx_template_archive,
)
from eneo.files.text import ExtractionError, TextExtractor, TextMimeTypes
from eneo.flows.runtime.document_rendering.docx_content_controls import (
    inspect_content_controls,
)

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ai_builder_corpus_coverage import (  # noqa: E402
    parse_sources,
    pinned_source_problem,
)
from ai_builder_fixture_render import (  # noqa: E402
    BulletList,
    Cell,
    Control,
    DocumentContent,
    FixtureSpec,
    Heading,
    JsonData,
    Letterhead,
    Paragraph,
    Sheet,
    Signature,
    Table,
    add_metadata_table,
    cell_text,
    configure_document,
    document_bytes,
    parse_spec,
    render,
)

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "ai_builder_battle"
SPEC_DIR = FIXTURE_DIR / "specs"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
SOURCES_PATH = Path(__file__).with_name("ai_builder_municipal_sources.json")
MANIFEST_VERSION = 1
AUTHENTIC_PROTOCOL_SHA256 = (
    "cdab0e4471ca518fa5c7334a185a0c77da1c5743a49468e54d3ff094f824c6d8"
)
_LEGACY_LETTERHEAD = Letterhead(
    "Sundsvalls kommun", "Barn- och utbildningsförvaltningen"
)


MATTER_FIXTURE_NAMES = (
    "01_protokoll_bun_2026_02_25.pdf",
    "02_tjansteskrivelse_underlag.docx",
    "03_barnkonsekvensanalys.docx",
    "04_remissvar.docx",
    "05_lokalkalkyl.csv",
    "06_tidigare_beslut.pdf",
)

# What a fixture directory may hold without a manifest entry: the manifest, the seed flows and edit chains (the
# harness hashes those itself), the prompts and the specs.
UNPINNED_FIXTURE_ENTRIES = frozenset(
    {
        "manifest.json",
        "edit_chain_10.json",
        "edit_chain_30.json",
        "edit_seed_a.json",
        "edit_seed_g.json",
        "edit_seed_s_speaker.json",
        "prompts",
        "specs",
    }
)

GENERATED_FIXTURE_NAMES = (
    *MATTER_FIXTURE_NAMES,
    "decision_letter_template.docx",
    "example_report.docx",
    "generic_case_template.docx",
    "tjansteskrivelse_template.docx",
)


def _write_docx(path: Path, build: object) -> None:
    if not callable(build):
        raise TypeError("DOCX builder must be callable")
    document = docx.Document()
    configure_document(document, _LEGACY_LETTERHEAD, "Kommunalt ärendeunderlag")
    build(document)
    path.write_bytes(document_bytes(document))


def _build_decision_letter(document: DocxDocument) -> None:
    document.add_paragraph("BESLUTSBREV", style="Municipal Title")
    add_metadata_table(
        document,
        (
            ("Diarienummer", "{{ diarienummer }}"),
            ("Beslutsdatum", "{{ beslutsdatum }}"),
            ("Handläggare", "{{ handlaggare }}"),
        ),
    )
    for heading, placeholder in (
        ("Beslut", "{{ beslut }}"),
        ("Motivering", "{{ motivering }}"),
        ("Villkor", "{{ villkor }}"),
        ("Så överklagar du", "{{ overklagandehanvisning }}"),
    ):
        document.add_paragraph(heading, style="Municipal Heading")
        document.add_paragraph(placeholder)


def _build_generic_template(document: DocxDocument) -> None:
    document.add_paragraph("ÄRENDERAPPORT", style="Municipal Title")
    add_metadata_table(
        document,
        (("Kundnamn", "{{ kundnamn }}"), ("Ärende-ID", "{{ case_id }}")),
    )
    document.add_paragraph("Sammanfattning", style="Municipal Heading")
    document.add_paragraph("{{ mallinnehall }}")


def _build_tjansteskrivelse_template(document: DocxDocument) -> None:
    document.add_paragraph("TJÄNSTESKRIVELSE", style="Municipal Title")
    add_metadata_table(
        document,
        (
            ("Diarienummer", "{{ diarienummer }}"),
            ("Handläggare", "{{ handlaggare }}"),
            ("Förvaltning", "{{ forvaltning }}"),
            ("Nämnd", "{{ namnd }}"),
            ("Beslutsdatum", "{{ beslutsdatum }}"),
        ),
    )
    for heading, placeholder in (
        ("Ärendet", "{{ sections.ärendet.text }}"),
        ("Bakgrund", "{{ sections.bakgrund.text }}"),
        ("Bedömning", "{{ sections.bedömning.text }}"),
        ("Konsekvenser", "{{ sections.konsekvenser.text }}"),
        (
            "Förslag till beslut",
            "{{ sections.förslag_till_beslut.text }}",
        ),
    ):
        document.add_paragraph(heading, style="Municipal Heading")
        document.add_paragraph(placeholder)


def _build_example_report(document: DocxDocument) -> None:
    document.add_paragraph("EXEMPELRAPPORT — KÄLLGENOMGÅNG", style="Municipal Title")
    add_metadata_table(
        document,
        (("Rapportdatum", "2026-01-15"), ("Status", "Exempel, anonymiserat")),
    )
    for heading, body in (
        (
            "Källa 1 — Ärendeunderlag",
            "Redovisa dokumenttyp, datum, avsändare, relevanta fakta och osäkerheter.",
        ),
        (
            "Källa 2 — Tidigare beslut",
            "Återge beslutet separat och behåll den synliga källhänvisningen.",
        ),
        (
            "Samlad bedömning",
            "Syntetisera endast belagda uppgifter och visa motsägelser och luckor.",
        ),
    ):
        document.add_paragraph(heading, style="Municipal Heading")
        document.add_paragraph(body)


def _build_underlag(document: DocxDocument) -> None:
    document.add_paragraph(
        "Underlag till tjänsteskrivelse — Ny förskolestruktur i Njurunda",
        style="Municipal Title",
    )
    add_metadata_table(
        document,
        (
            ("Diarienummer", "BUN-2026-00037-1"),
            ("Dokumentdatum", "2026-02-04"),
            ("Dokumenttyp", "Tjänsteskrivelseunderlag"),
        ),
    )
    document.add_paragraph("Ärende", style="Municipal Heading")
    document.add_paragraph(
        "Barnantalet i Njurunda har minskat. Förvaltningen föreslår att "
        "verksamheten vid Klockarbergets förskola i Kvissleby avvecklas."
    )
    document.add_paragraph("Bedömningspunkter", style="Municipal Heading")
    document.add_paragraph(
        "Barn och pedagoger ska erbjudas en planerad övergång. Personaltätheten "
        "ska efter förflyttningen i genomsnitt vara högst 5,0 barn per anställd. "
        "Lämpliga barngruppsstorlekar och en mångfald av förskolor ska bevaras."
    )


def _build_child_impact(document: DocxDocument) -> None:
    document.add_paragraph(
        "Barnkonsekvensanalys — Klockarbergets förskola",
        style="Municipal Title",
    )
    add_metadata_table(
        document,
        (
            ("Diarienummer", "BUN-2026-00037-1"),
            ("Dokumentdatum", "2026-01-28"),
            ("Dokumenttyp", "Barnkonsekvensanalys"),
        ),
    )
    document.add_paragraph("Belagda konsekvenser", style="Municipal Heading")
    document.add_paragraph(
        "Avvecklingen innebär byte av förskola för berörda barn. Kontinuitet "
        "stärks om personal kan följa med barnen när lag, avtal och kommunens "
        "rutiner för personalförflyttning medger det. Närhet, trygghet och "
        "lämpliga barngrupper behöver följas upp under övergången."
    )
    document.add_paragraph("Uppföljning", style="Municipal Heading")
    document.add_paragraph(
        "Förvaltningen följer personaltäthet, barngruppsstorlek och trygghet före, "
        "under och efter övergången samt återrapporterar avvikelser till nämnden."
    )


def _build_consultation_response(document: DocxDocument) -> None:
    document.add_paragraph(
        "Sammanställt remissvar — Förskolestruktur Njurunda",
        style="Municipal Title",
    )
    add_metadata_table(
        document,
        (
            ("Diarienummer", "BUN-2026-00037-1"),
            ("Dokumentdatum", "2026-02-18"),
            ("Dokumenttyp", "Remissvar"),
        ),
    )
    document.add_paragraph("Synpunkter", style="Municipal Heading")
    document.add_paragraph(
        "Synpunkterna betonar trygg övergång, information till vårdnadshavare "
        "och fortsatt variation mellan mindre och större förskolor."
    )
    document.add_paragraph("Datumuppgift att kontrollera", style="Municipal Heading")
    document.add_paragraph(
        "Remissammanställningen anger nämndens beslutsdatum som 2026-02-24."
    )


def _pdf_bytes(lines: Sequence[str]) -> bytes:
    def pdf_string(value: str) -> bytes:
        encoded = value.encode("cp1252")
        return (
            encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        )

    commands = [b"BT", b"/F1 10 Tf", b"50 790 Td", b"13 TL"]
    for line in lines:
        commands.extend((b"(" + pdf_string(line) + b") Tj", b"T*"))
    commands.append(b"ET")
    stream = b"\n".join(commands) + b"\n"
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"endstream",
    )
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_authentic_protocol(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Authentic protocol fixture is missing: {path}")
    actual_sha256 = _sha256(path)
    if actual_sha256 != AUTHENTIC_PROTOCOL_SHA256:
        raise ValueError(
            "Authentic protocol SHA-256 mismatch: "
            f"expected {AUTHENTIC_PROTOCOL_SHA256}, got {actual_sha256} for {path}"
        )


def _harness() -> ModuleType:
    return importlib.import_module("ai_builder_api_battle_test")


def _pinned_sources() -> dict[str, frozenset[str]]:
    return parse_sources(json.loads(SOURCES_PATH.read_text(encoding="utf-8")))


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen.add(key)
    return dict(pairs)


def _read_spec(
    path: Path, pinned_sources: Mapping[str, frozenset[str]], reserved: Collection[str]
) -> FixtureSpec:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_keys,
        )
    except ValueError as error:
        raise ValueError(f"{path.name}: {error}") from error
    spec = parse_spec(raw, spec_name=path.name)
    # A spec names its source as a case does: by the harness's rules, and only as pinned evidence.
    harness = _harness()
    if not harness._CATALOGUE_ID.fullmatch(spec.source.catalogue_id):
        raise ValueError(f"{path.name}: source catalogue_id must look like BYG-01")
    if not harness._is_https_url(spec.source.url):
        raise ValueError(f"{path.name}: source url must be an https URL")
    problem = pinned_source_problem(
        path.name, spec.source.catalogue_id, spec.source.url, pinned_sources
    )
    if problem is not None:
        raise ValueError(problem)
    if spec.file in reserved:
        raise ValueError(f"{path.name}: {spec.file} collides with an existing fixture")
    return spec


def _write_fixtures(*, source_path: Path | None = None) -> dict[str, str]:
    # Every spec is validated and rendered before anything is written. A file the manifest does not pin (a seed
    # flow, the manifest itself) is not a fixture, and a spec may not replace it.
    pinned: Mapping[str, str] = (
        _harness()._fixture_manifest(MANIFEST_PATH) if MANIFEST_PATH.is_file() else {}
    )
    unpinned = {
        path.name
        for path in FIXTURE_DIR.glob("*")
        if path.is_file() and path.name not in pinned
    }
    sources = _pinned_sources()
    reserved = {*GENERATED_FIXTURE_NAMES, *unpinned}
    rendered = {
        spec.file: render(spec)
        for spec in (
            _read_spec(path, sources, reserved)
            for path in sorted(SPEC_DIR.glob("*.json"))
        )
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    canonical_protocol = FIXTURE_DIR / MATTER_FIXTURE_NAMES[0]
    if source_path is not None:
        _verify_authentic_protocol(source_path)
        if source_path.resolve() != canonical_protocol.resolve():
            shutil.copyfile(source_path, canonical_protocol)
    _verify_authentic_protocol(canonical_protocol)
    _write_docx(FIXTURE_DIR / "decision_letter_template.docx", _build_decision_letter)
    _write_docx(FIXTURE_DIR / "example_report.docx", _build_example_report)
    _write_docx(FIXTURE_DIR / "generic_case_template.docx", _build_generic_template)
    _write_docx(
        FIXTURE_DIR / "tjansteskrivelse_template.docx",
        _build_tjansteskrivelse_template,
    )
    _write_docx(FIXTURE_DIR / MATTER_FIXTURE_NAMES[1], _build_underlag)
    _write_docx(FIXTURE_DIR / MATTER_FIXTURE_NAMES[2], _build_child_impact)
    _write_docx(FIXTURE_DIR / MATTER_FIXTURE_NAMES[3], _build_consultation_response)
    (FIXTURE_DIR / MATTER_FIXTURE_NAMES[4]).write_text(
        "diarienummer,dokumentdatum,dokumenttyp,post,belopp_sek,kalla,status\n"
        "BUN-2026-00037-1,2026-02-03,Lokalkalkyl,avvecklingsarbete,180000,"
        "preliminar_kalkyl,beraknat\n"
        "BUN-2026-00037-1,2026-02-03,Lokalkalkyl,anpassning_mottagande_lokaler,"
        "420000,preliminar_kalkyl,beraknat\n"
        "BUN-2026-00037-1,2026-02-03,Lokalkalkyl,overgangsstod,,saknas,"
        "finansieringskalla_ej_faststalld\n",
        encoding="utf-8",
        newline="\n",
    )
    (FIXTURE_DIR / MATTER_FIXTURE_NAMES[5]).write_bytes(
        _pdf_bytes(
            (
                "Protokollsutdrag - Barn- och utbildningsnamndens arbetsutskott",
                "Diarienummer: BUN-2026-00037-1",
                "Sammantradesdatum: 2026-02-11",
                "Paragraf 11: Ny forskolestruktur i Njurunda",
                "Arbetsutskottet foreslar avveckling av Klockarbergets forskola.",
                "Forslaget motiveras av minskat barnantal i Njurunda.",
                "Beslutet ska forenas med trygg overgangen for barn och personal.",
                "Personaltatheten ska i genomsnitt vara hogst 5,0 barn per anstalld.",
                "Arkiveringsstampel:",
                "B",
                "E",
                "S",
                "L",
                "U",
                "T",
                "A",
                "D",
            )
        )
    )
    for name, data in rendered.items():
        (FIXTURE_DIR / name).write_bytes(data)
    return {
        fixture_name: _sha256(FIXTURE_DIR / fixture_name)
        for fixture_name in sorted((*GENERATED_FIXTURE_NAMES, *rendered))
    }


def _write_manifest(content_sha256s: Mapping[str, str]) -> None:
    """Pin every fixture's bytes so a case can name one and mean exactly it.

    File IDs are deliberately absent: they are per-environment and per-upload,
    and hand-carrying them is what let the flagship runtime sentinel skip
    itself for six full suite runs. The harness uploads these bytes and derives
    the IDs it needs.
    """

    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "version": MANIFEST_VERSION,
                "description": (
                    "Deterministic AI Builder battle fixtures. Regenerate with "
                    "backend/scripts/generate_battle_fixtures.py."
                ),
                "fixtures": dict(sorted(content_sha256s.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


_MIMETYPES: dict[str, str] = {
    "pdf": TextMimeTypes.PDF.value,
    "docx": TextMimeTypes.DOCX.value,
    "xlsx": TextMimeTypes.XLSX.value,
    "csv": TextMimeTypes.TEXT_CSV.value,
    "json": TextMimeTypes.JSON.value,
    "txt": TextMimeTypes.TXT.value,
}
_PAGE_MARKER = re.compile(r"\[PAGE \d+\]")
_PAGE_HEADER = re.compile(r".*Sida \d+ av \d+")


def _extract(path: Path, fmt: str) -> str:
    return TextExtractor().extract(path, _MIMETYPES[fmt], path.name)


def _flat(text: str) -> str:
    return "".join(text.split())


def _pdf_readings(text: str) -> tuple[str, str]:
    """A PDF's running text and its table rows as the Builder reads them, free of layout.

    Fonts move line and page breaks, and the extractor frames every page and puts its tables after its text: page
    markers and the page header line are dropped, a table that continues on the next page is read once (its
    repeated header row goes), tables are read apart from the running text, and whitespace is removed.
    """

    running: list[str] = []
    rows: list[str] = []
    header: str | None = None
    for block in text.split("\n\n"):
        lines = [
            line for line in block.splitlines() if not _PAGE_MARKER.fullmatch(line)
        ]
        if lines and lines[0].startswith("|"):
            if lines[0] != header:
                rows.append(lines[0])
            header = lines[0]
            rows.extend(lines[2:])
        else:
            running.extend(line for line in lines if not _PAGE_HEADER.fullmatch(line))
    return _flat("".join(running)), _flat("".join(rows))


def _document_problem(
    document: DocumentContent, running: str, tables: str
) -> str | None:
    texts = [value for _, value in document.metadata()] + [document.title]
    cells: list[str] = []
    for block in document.blocks:
        match block:
            case Heading(text=value) | Paragraph(text=value):
                texts.append(value)
            case BulletList(items=items):
                texts.extend(items)
            case Signature(name=name, role=role):
                texts.extend((name, role))
            case Control(hint=hint):
                texts.append(hint)
            case Table(columns=columns, rows=rows):
                cells.extend((*columns, *(cell for row in rows for cell in row)))
            case _:
                pass
    for fragments, flat in ((texts, running), (cells, tables)):
        cursor = 0
        for fragment in fragments:
            found = flat.find(_flat(fragment), cursor)
            if found < 0:
                return f"{fragment!r} is not in the extracted text in spec order"
            cursor = found + len(_flat(fragment))
    return None


def _json_problem(value: object, text: str) -> str | None:
    try:
        same = json.loads(text) == value
    except json.JSONDecodeError:
        same = False
    return None if same else "extracted JSON differs from the spec data"


def _csv_problem(sheet: Sheet, text: str) -> str | None:
    expected = [
        list(sheet.columns),
        *([cell_text(value) for value in row] for row in sheet.rows),
    ]
    actual = list(csv.reader(io.StringIO(text)))
    for number, (want, got) in enumerate(zip_longest(expected, actual), start=1):
        if want != got:
            return f"row {number} reads {got!r}, the spec has {want!r}"
    return None


def _same_cell(value: str | int | float, text: str) -> bool:
    if isinstance(value, str):
        return text == value
    try:
        return float(text) == value
    except ValueError:
        return False


def _xlsx_row_matches(sheet: Sheet, row: Sequence[Cell], line: str) -> bool:
    # The extractor writes "Sheet: <name> | <column>: <value> | ..." and leaves out an empty cell unless it
    # forward-fills it from the row above.
    cells = [
        (column, value)
        for column, value in zip(sheet.columns, row, strict=True)
        if value is not None
    ]
    pattern = re.escape(f"Sheet: {sheet.name} | ") + re.escape(" | ").join(
        re.escape(f"{column}: ") + "(.*)" for column, _ in cells
    )
    match = re.fullmatch(pattern, line)
    return match is not None and all(
        _same_cell(value, text)
        for (_, value), text in zip(cells, match.groups(), strict=True)
    )


def _xlsx_problem(sheets: Sequence[Sheet], text: str) -> str | None:
    lines = [line for line in text.splitlines() if line.startswith("Sheet: ")]
    rows = [(sheet, row) for sheet in sheets for row in sheet.rows]
    if len(lines) != len(rows):
        return f"the extractor reads {len(lines)} rows, the spec has {len(rows)}"
    for (sheet, row), line in zip(rows, lines, strict=True):
        if not _xlsx_row_matches(sheet, row, line):
            return f"sheet {sheet.name!r} row {list(row)!r} reads {line!r} through the extractor"
    return None


def _spec_problem(spec: FixtureSpec, text: str) -> str | None:
    """Whether the text the Builder reads carries every piece of the spec's content."""

    match spec.content:
        case DocumentContent() as document:
            if spec.format == "pdf":
                return _document_problem(document, *_pdf_readings(text))
            return _document_problem(document, _flat(text), _flat(text))
        case JsonData(value=value):
            return _json_problem(value, text)
        case sheets:
            if spec.format == "csv":
                return _csv_problem(sheets[0], text)
            return _xlsx_problem(sheets, text)


def _rendered_problem(spec: FixtureSpec, text: str) -> str | None:
    """Whether the file reads exactly as the spec renders now, so nothing beyond the spec is left in it.

    Only a PDF depends on the rendering machine (its fonts); it is compared by its layout-free readings.
    """

    with tempfile.TemporaryDirectory() as scratch:
        current = Path(scratch) / spec.file
        current.write_bytes(render(spec))
        expected = _extract(current, spec.format)
    if spec.format == "pdf":
        readings, wanted = _pdf_readings(text), _pdf_readings(expected)
    else:
        readings, wanted = (text,), (expected,)
    for reading, want in zip(readings, wanted, strict=True):
        if reading != want:
            index = next(
                index
                for index, (have, need) in enumerate(zip_longest(reading, want))
                if have != need
            )
            return (
                f"reads {reading[index : index + 40]!r} where the spec now renders "
                f"{want[index : index + 40]!r}"
            )
    return None


def _control_readings(data: bytes, name: str) -> list[dict[str, object]]:
    """Every field the product's template inspector returns per control, in order, as the runtime reads a template.

    The control's own XML stands in for its element, so a property the inspector does not project (today or
    later) still counts.
    """

    validate_docx_template_archive(data, filename=name)
    readings: list[dict[str, object]] = []
    for control in inspect_content_controls(docx.Document(io.BytesIO(data))):
        reading = {
            field.name: getattr(control, field.name)
            for field in dataclasses.fields(control)
        }
        reading["element"] = etree.tostring(control.element)
        readings.append(reading)
    return readings


def _controls_problem(spec: FixtureSpec, path: Path) -> str | None:
    """Whether a DOCX template's controls read, through the product's template inspector, as the spec renders them.

    A control's tag, label, kind and properties are not text, so the text comparison cannot see them change.
    """

    if not isinstance(spec.content, DocumentContent) or not any(
        isinstance(block, Control) for block in spec.content.blocks
    ):
        return None
    try:
        controls = _control_readings(path.read_bytes(), spec.file)
    except Exception as error:
        # As the template runtime does: every read failure becomes the product's typed rejection.
        rejection = normalize_template_extraction_error(error)
        return f"is not a template the product accepts: {rejection}"
    wanted = _control_readings(render(spec), spec.file)
    if len(controls) != len(wanted):
        return f"has {len(controls)} controls where the spec now renders {len(wanted)}"
    for number, (control, want) in enumerate(zip(controls, wanted), start=1):
        differing = sorted(key for key in want if control[key] != want[key])
        if differing:
            return (
                f"control {number} ({want['name']}) differs from the spec rendered now in "
                + ", ".join(differing)
            )
    return None


def _content_problem(spec: FixtureSpec, path: Path) -> str | None:
    try:
        text = _extract(path, spec.format)
    except ExtractionError as error:
        return f"cannot be read through the extractor: {error.message}"
    return (
        _spec_problem(spec, text)
        or _rendered_problem(spec, text)
        or _controls_problem(spec, path)
    )


def check(
    fixture_dir: Path,
    spec_dir: Path,
    manifest_path: Path,
    pinned_sources: Mapping[str, frozenset[str]],
) -> list[str]:
    """Every disagreement between committed fixtures, their specs and the manifest, one line each; reads only."""

    try:
        pinned: Mapping[str, str] = _harness()._fixture_manifest(manifest_path)
    except (OSError, ValueError) as error:
        return [f"{manifest_path.name}: cannot be read: {error!r}"]
    spec_paths = sorted(spec_dir.glob("*.json"))
    problems: list[str] = []
    specs: list[FixtureSpec] = []
    for path in spec_paths:
        try:
            spec = _read_spec(path, pinned_sources, GENERATED_FIXTURE_NAMES)
        except ValueError as error:
            problems.append(str(error))
            continue
        specs.append(spec)
        if spec.file not in pinned:
            problems.append(f"{spec.file}: not pinned in {manifest_path.name}")
    specified = {path.name.removesuffix(".json") for path in spec_paths}
    for name, expected in pinned.items():
        path = fixture_dir / name
        if name not in specified and name not in GENERATED_FIXTURE_NAMES:
            problems.append(
                f"{name}: pinned in {manifest_path.name} without a spec or a legacy generator"
            )
        if not path.is_file():
            problems.append(f"{name}: missing from the fixture directory")
        elif (actual := _sha256(path)) != expected:
            problems.append(
                f"{name}: sha256 {actual} does not match {manifest_path.name}"
            )
    problems += [
        f"{path.name}: in the fixture directory but not pinned in {manifest_path.name}"
        for path in sorted(fixture_dir.iterdir())
        if path.name not in {*pinned, *specified, *UNPINNED_FIXTURE_ENTRIES}
    ]
    for spec in specs:
        path = fixture_dir / spec.file
        if path.is_file() and (problem := _content_problem(spec, path)) is not None:
            problems.append(f"{spec.file}: {problem}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--source",
        type=Path,
        help=(
            "Initialize the canonical protocol from a local file whose SHA-256 "
            "matches the pinned authentic source."
        ),
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; print one line per problem and exit 1 if there is any.",
    )
    args = parser.parse_args()
    # The table registry first: the flows packages import each other through it, and the harness imports them.
    importlib.import_module("eneo.database.tables")
    if args.check:
        problems = check(FIXTURE_DIR, SPEC_DIR, MANIFEST_PATH, _pinned_sources())
        for problem in problems:
            print(problem)
        return 1 if problems else 0

    content_sha256s = _write_fixtures(source_path=args.source)
    _write_manifest(content_sha256s)

    print(f"fixture_directory={FIXTURE_DIR.resolve()}")
    for fixture_name, sha256 in sorted(content_sha256s.items()):
        print(f"{sha256}  {fixture_name}")
    print(f"manifest={MANIFEST_PATH.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

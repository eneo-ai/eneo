from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from types import ModuleType
from typing import Any

import docx
import openpyxl
import pdfplumber
from openpyxl.utils.exceptions import IllegalCharacterError
from pytest import CaptureFixture, MonkeyPatch, mark, raises

from eneo.flows.runtime import docx_template_runtime

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
FIXTURE_DIR = SCRIPTS / "fixtures" / "ai_builder_battle"
SOURCE = {
    "catalogue_id": "UTB-10",
    "url": "https://e-tjanster.sundsvall.se/oversikt/overview/285",
}
PINNED = {"UTB-10": frozenset({SOURCE["url"]})}


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The renderer first, under its own name, so the generator imports this same module.
render = _load("ai_builder_fixture_render")
generator = _load("generate_battle_fixtures")

DOCUMENT: dict[str, Any] = {
    "letterhead": {
        "organisation": "Sundsvalls kommun",
        "unit": "Vuxenutbildningen",
        "address": "851 85 Sundsvall",
    },
    "date": "2026-08-12",
    "diarienummer": "VUX-2026-00873",
    "title": "Beslut om antagning",
    "blocks": [
        {"heading": "Beslut"},
        {"paragraph": "Du antas inte till kursen Matematik 2c."},
        {"list": ["Sökt kurs: Matematik 2c", "Sökt period: hösten 2026"]},
        {
            "table": {
                "columns": ["Kurs", "Poäng", "Beslut"],
                "rows": [
                    ["Matematik 2c", "100", "Ej antagen"],
                    ["Svenska 3", "100", ""],
                ],
            }
        },
        {"page_break": True},
        {"heading": "Så överklagar du"},
        {"signature": {"name": "Eva Berg", "role": "Rektor"}},
    ],
}
SHEET: dict[str, Any] = {
    "name": "Utbetalningar",
    "columns": ["Månad", "Belopp", "Kommentar"],
    "rows": [["2026-07", 5220, None], ["2026-08", 5220.5, "Återbetald ränta"]],
}


def _spec(file: str, **content: Any) -> dict[str, Any]:
    return {
        "file": file,
        "format": file.rsplit(".", 1)[1],
        "source": dict(SOURCE),
        "description": "Testdokument.",
        **copy.deepcopy(content),
    }


def _specs() -> dict[str, dict[str, Any]]:
    without_break = [block for block in DOCUMENT["blocks"] if "page_break" not in block]
    specs = (
        _spec("beslut.pdf", **DOCUMENT),
        _spec("beslut.docx", **DOCUMENT),
        _spec("beslut.txt", **{**DOCUMENT, "blocks": without_break}),
        _spec(
            "register.xlsx",
            sheets=[SHEET, {"name": "Summering", "columns": ["Antal"], "rows": [[2]]}],
        ),
        _spec("export.csv", sheets=[SHEET]),
        _spec(
            "ansokan.json",
            data={"ärende": {"id": "A-1", "barn": [{"namn": "Åsa"}]}, "belopp": 12.5},
        ),
    )
    return {spec["file"]: spec for spec in specs}


def _parse(raw: dict[str, Any]) -> Any:
    return render.parse_spec(raw, spec_name=f"{raw['file']}.json")


def _tree(
    tmp_path: Path, specs: dict[str, dict[str, Any]] | None = None
) -> tuple[Path, Path, Path]:
    """A fixture directory rendered from its specs (one per format by default), pinned in its own manifest."""

    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    pinned: dict[str, str] = {}
    for name, raw in (specs or _specs()).items():
        (spec_dir / f"{name}.json").write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )
        data = render.render(_parse(raw))
        (tmp_path / name).write_bytes(data)
        pinned[name] = hashlib.sha256(data).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"version": 1, "fixtures": pinned}), encoding="utf-8"
    )
    return tmp_path, spec_dir, manifest


def _check(tree: tuple[Path, Path, Path]) -> list[str]:
    return generator.check(*tree, PINNED)


def _edit_spec(
    spec_dir: Path, name: str, edit: Callable[[dict[str, Any]], object]
) -> None:
    path = spec_dir / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    edit(raw)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def test_the_tracked_fixtures_match_their_specs_and_the_manifest(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    before = {
        path.name: path.read_bytes() for path in FIXTURE_DIR.iterdir() if path.is_file()
    }
    monkeypatch.setattr(sys, "argv", ["generate_battle_fixtures.py", "--check"])

    assert generator.main() == 0
    assert capsys.readouterr().out == ""
    assert {
        path.name: path.read_bytes() for path in FIXTURE_DIR.iterdir() if path.is_file()
    } == before


def test_a_tree_rendered_from_its_specs_passes_for_every_format(tmp_path: Path) -> None:
    assert _check(_tree(tmp_path)) == []


@mark.parametrize("name", sorted(_specs()))
def test_every_format_renders_the_same_bytes_twice(name: str) -> None:
    spec = _parse(_specs()[name])

    assert render.render(spec) == render.render(spec)


def test_metadata_dates_are_pinned() -> None:
    specs = _specs()
    pdf = render.render(_parse(specs["beslut.pdf"]))
    workbook = openpyxl.load_workbook(
        io.BytesIO(render.render(_parse(specs["register.xlsx"])))
    )
    document = docx.Document(io.BytesIO(render.render(_parse(specs["beslut.docx"]))))

    with pdfplumber.open(io.BytesIO(pdf)) as pages:
        assert pages.metadata["CreationDate"] == "D:20260101"
        assert pages.metadata["ModDate"] == "D:20260101"
        # The page break splits the document, and every page carries its number.
        assert len(pages.pages) == 2
        assert "Sida 2 av 2" in (pages.pages[1].extract_text() or "")
    assert (
        workbook.properties.created
        == workbook.properties.modified
        == render.FIXED_TIMESTAMP
    )
    # python-docx reads the stored UTC time back as an aware datetime.
    assert document.core_properties.modified == render.FIXED_TIMESTAMP.replace(
        tzinfo=UTC
    )


TEMPLATE_BLOCKS: list[dict[str, Any]] = [
    {"heading": "Beslut om markupplåtelse"},
    {"paragraph": "Diarienummer:"},
    {
        "control": {
            "kind": "text",
            "tag": "diarienummer",
            "label": "Diarienummer",
            "hint": "MK-ÅÅÅÅ-NNNN",
        }
    },
    {"heading": "Beslut"},
    {
        "control": {
            "kind": "rich",
            "tag": "beslut",
            "label": "Beslut",
            "hint": "Skriv beslutet och villkoren.",
        }
    },
]


def test_a_template_control_is_a_word_content_control_the_product_accepts(
    tmp_path: Path,
) -> None:
    template = _spec("mall.docx", **{**DOCUMENT, "blocks": TEMPLATE_BLOCKS})
    spec = _parse(template)

    controls = docx_template_runtime.inspect_docx_template_bytes(
        render.render(spec), filename="mall.docx"
    )

    assert [
        (control["name"], control["kind"], control["label"], control["hint"])
        for control in controls
    ] == [
        ("diarienummer", "text", "Diarienummer", "MK-ÅÅÅÅ-NNNN"),
        ("beslut", "rich", "Beslut", "Skriv beslutet och villkoren."),
    ]
    assert render.render(spec) == render.render(spec)
    assert _check(_tree(tmp_path, {"mall.docx": template})) == []


@mark.parametrize(
    ("change", "field"),
    [
        ({"tag": "dnr"}, "name"),
        ({"label": "Ärendenummer"}, "label"),
        ({"kind": "rich"}, "kind"),
    ],
    ids=["tag", "label", "kind"],
)
def test_a_template_control_that_no_longer_matches_its_spec_is_reported(
    tmp_path: Path, change: dict[str, str], field: str
) -> None:
    # A control's tag, label and kind are not text: only the template inspector sees them change.
    template = _spec("mall.docx", **{**DOCUMENT, "blocks": TEMPLATE_BLOCKS})
    fixture_dir, spec_dir, manifest = _tree(tmp_path, {"mall.docx": template})
    _edit_spec(
        spec_dir, "mall.docx", lambda raw: raw["blocks"][2]["control"].update(change)
    )

    problems = _check((fixture_dir, spec_dir, manifest))

    assert len(problems) == 1
    assert problems[0].startswith("mall.docx: control 1 (")
    assert field in problems[0].split(" differs from the spec rendered now in ")[
        1
    ].split(", ")


def _tamper_template(path: Path, old: str, new: str, extra: str | None = None) -> None:
    with zipfile.ZipFile(path) as source:
        members = {name: source.read(name) for name in source.namelist()}
    body = members["word/document.xml"].decode()
    assert body.count(old) == 1
    members["word/document.xml"] = body.replace(old, new).encode()
    if extra is not None:
        members[extra] = b"\x00"
    with zipfile.ZipFile(path, "w") as target:
        for name, data in members.items():
            target.writestr(name, data)


@mark.parametrize(
    ("old", "new", "extra", "problem"),
    [
        # Only the multiline flag of the text control changes; its text stays the same.
        (
            "<w:text/>",
            '<w:text w:multiLine="1"/>',
            None,
            "mall.docx: control 1 (diarienummer) differs from the spec rendered now in element, multiline",
        ),
        (
            '<w:tag w:val="beslut"/>',
            "",
            None,
            "mall.docx: is not a template the product accepts: A content control ('Beslut') has no tag. Give every "
            "control a tag in Word (Developer > Properties) so the flow can address it.",
        ),
        (
            "<w:text/>",
            "<w:text/>",
            "word/vbaProject.bin",
            "mall.docx: is not a template the product accepts: Macro-enabled Word files are not allowed as flow "
            "templates.",
        ),
        (
            "<w:text/>",
            "<w:text/>",
            "word/styles.xml",
            "mall.docx: is not a template the product accepts: The DOCX template could not be read.",
        ),
    ],
    ids=["multiline", "untagged", "macro", "malformed styles"],
)
def test_a_committed_template_that_differs_from_its_spec_or_is_refused_is_reported(
    tmp_path: Path, old: str, new: str, extra: str | None, problem: str
) -> None:
    template = _spec("mall.docx", **{**DOCUMENT, "blocks": TEMPLATE_BLOCKS})
    fixture_dir, spec_dir, manifest = _tree(tmp_path, {"mall.docx": template})
    _tamper_template(fixture_dir / "mall.docx", old, new, extra)

    problems = _check((fixture_dir, spec_dir, manifest))

    assert problems[0].startswith("mall.docx: sha256 ")
    assert problems[1:] == [problem]


def test_json_never_writes_a_non_finite_number() -> None:
    spec = _parse(_specs()["ansokan.json"])

    with raises(ValueError, match="Out of range float values are not JSON compliant"):
        render.render(
            dataclasses.replace(spec, content=render.JsonData({"belopp": float("inf")}))
        )


def test_json_keeps_the_spec_key_order_and_writes_swedish_characters() -> None:
    data = render.render(_parse(_specs()["ansokan.json"]))

    assert list(json.loads(data)) == ["ärende", "belopp"]
    assert "Åsa".encode() in data


def test_text_and_tables_that_cross_page_breaks_still_read_as_their_spec(
    tmp_path: Path,
) -> None:
    # The extractor puts a page marker and the page header inside a split paragraph, and a page's tables after its
    # text; a continued table repeats its header row on the next page.
    blocks = [
        {
            "paragraph": "Planförslaget prövas mot översiktsplanen och SSBTEK-svaret. "
            * 120
        },
        {
            "table": {
                "columns": ["Datum", "Text"],
                "rows": [
                    [f"2026-08-{day:02d}", f"Kortköp {day}"] for day in range(1, 32)
                ],
            }
        },
        {"paragraph": "Efter tabellen."},
    ]
    long = _spec("lang.pdf", **{**DOCUMENT, "blocks": blocks})
    fixture_dir, spec_dir, manifest = _tree(tmp_path, {"lang.pdf": long})

    with pdfplumber.open(fixture_dir / "lang.pdf") as document:
        assert len(document.pages) >= 3
        assert [row[:2] for row in document.pages[-1].extract_table() or []][:1] == [
            ["Datum", "Text"]
        ]
    assert _check((fixture_dir, spec_dir, manifest)) == []


def test_pdf_readings_do_not_depend_on_where_pages_break() -> None:
    # Another machine's fonts break the same document into pages elsewhere.
    two_pages = (
        "[PAGE 1]\nSida 1 av 2\nBeslut\nFörsta stycket som\n\n| Kurs | Poäng |\n| --- | --- |\n"
        "| Fysik 1a | 150 |\n\n[PAGE 2]\nSundsvalls kommun · Vuxenutbildningen Sida 2 av 2\n"
        "fortsätter här.\n\n| Kurs | Poäng |\n| --- | --- |\n| Kemi 1 | 100 |"
    )
    one_page = (
        "[PAGE 1]\nSida 1 av 1\nBeslut\nFörsta stycket som fortsätter\nhär.\n\n"
        "| Kurs | Poäng |\n| --- | --- |\n| Fysik 1a | 150 |\n| Kemi 1 | 100 |"
    )

    assert generator._pdf_readings(two_pages) == generator._pdf_readings(one_page)


def test_bytes_that_no_longer_match_the_manifest_are_reported(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    (tmp_path / "beslut.docx").write_bytes(b"inte en docx")
    with (tmp_path / "ansokan.json").open("a", encoding="utf-8") as handle:
        handle.write("}")
    (tmp_path / "export.csv").unlink()

    problems = _check(tree)

    assert "export.csv: missing from the fixture directory" in problems
    assert any(
        problem.startswith("beslut.docx: sha256 ")
        and problem.endswith(" does not match manifest.json")
        for problem in problems
    )
    assert any(
        problem.startswith("beslut.docx: cannot be read through the extractor: ")
        for problem in problems
    )
    assert "ansokan.json: extracted JSON differs from the spec data" in problems
    assert len(problems) == 5


def test_a_manifest_entry_without_a_spec_or_a_legacy_generator_is_an_orphan(
    tmp_path: Path,
) -> None:
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    (spec_dir / "ansokan.json.json").unlink()

    assert _check((fixture_dir, spec_dir, manifest)) == [
        "ansokan.json: pinned in manifest.json without a spec or a legacy generator"
    ]


@mark.parametrize("stray", ["va_felrapport.pdf", "gammalt"])
def test_a_file_the_manifest_does_not_pin_is_reported(
    tmp_path: Path, stray: str
) -> None:
    # Deleting a spec and its manifest entry must not leave bytes nobody sees; the seed flows, the prompts and the
    # specs are the only unpinned entries a fixture directory may hold.
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    for allowed in generator.UNPINNED_FIXTURE_ENTRIES:
        (fixture_dir / allowed).touch(exist_ok=True)
    (fixture_dir / stray).mkdir() if "." not in stray else (
        fixture_dir / stray
    ).write_bytes(b"%PDF")

    assert _check((fixture_dir, spec_dir, manifest)) == [
        f"{stray}: in the fixture directory but not pinned in manifest.json"
    ]


def test_a_spec_whose_file_is_not_pinned_is_reported(tmp_path: Path) -> None:
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    pinned = json.loads(manifest.read_text(encoding="utf-8"))
    del pinned["fixtures"]["beslut.pdf"]
    manifest.write_text(json.dumps(pinned), encoding="utf-8")

    assert _check((fixture_dir, spec_dir, manifest)) == [
        "beslut.pdf: not pinned in manifest.json"
    ]


def _swap_headings(raw: dict[str, Any]) -> None:
    blocks = raw["blocks"]
    blocks[0], blocks[5] = blocks[5], blocks[0]


@mark.parametrize(
    ("name", "edit", "problem"),
    [
        (
            "beslut.pdf",
            lambda raw: raw["blocks"][1].update(paragraph="Du antas till kursen."),
            "beslut.pdf: 'Du antas till kursen.' is not in the extracted text in spec order",
        ),
        (
            "beslut.pdf",
            _swap_headings,
            "beslut.pdf: 'Du antas inte till kursen Matematik 2c.' is not in the extracted text in spec order",
        ),
        (
            "beslut.docx",
            lambda raw: raw.update(title="Beslut om avslag"),
            "beslut.docx: 'Beslut om avslag' is not in the extracted text in spec order",
        ),
        (
            "beslut.docx",
            lambda raw: raw["blocks"][3]["table"]["rows"][0].__setitem__(2, "Antagen"),
            "beslut.docx: 'Antagen' is not in the extracted text in spec order",
        ),
        (
            "beslut.txt",
            lambda raw: raw["blocks"][2]["list"].append("Sökt ort: Sundsvall"),
            "beslut.txt: 'Sökt ort: Sundsvall' is not in the extracted text in spec order",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][1]["rows"][0].__setitem__(0, 3),
            "register.xlsx: sheet 'Summering' row [3] reads 'Sheet: Summering | Antal: 2' through the extractor",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][1]["rows"].append([4]),
            "register.xlsx: the extractor reads 3 rows, the spec has 4",
        ),
        (
            "export.csv",
            lambda raw: raw["sheets"][0]["rows"][1].__setitem__(2, "Avgift"),
            "export.csv: row 3 reads ['2026-08', '5220.5', 'Återbetald ränta'], the spec has ['2026-08', '5220.5', 'Avgift']",
        ),
        (
            "ansokan.json",
            lambda raw: raw["data"]["ärende"].update(id="A-2"),
            "ansokan.json: extracted JSON differs from the spec data",
        ),
        (
            "beslut.docx",
            lambda raw: raw["blocks"][6]["signature"].update(name="Eva Bergström"),
            "beslut.docx: 'Eva Bergström' is not in the extracted text in spec order",
        ),
        (
            "beslut.txt",
            lambda raw: raw.update(date="2026-08-13"),
            "beslut.txt: '2026-08-13' is not in the extracted text in spec order",
        ),
        (
            "export.csv",
            lambda raw: raw["sheets"][0]["rows"].pop(),
            "export.csv: row 3 reads ['2026-08', '5220.5', 'Återbetald ränta'], the spec has None",
        ),
    ],
)
def test_content_that_no_longer_matches_its_spec_is_reported(
    tmp_path: Path,
    name: str,
    edit: Callable[[dict[str, Any]], object],
    problem: str,
) -> None:
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    _edit_spec(spec_dir, name, edit)

    assert _check((fixture_dir, spec_dir, manifest)) == [problem]


def _drop_second_row(raw: dict[str, Any]) -> None:
    raw["blocks"][3]["table"]["rows"].pop()


def _reverse_keys(raw: dict[str, Any]) -> None:
    raw["data"] = dict(reversed(raw["data"].items()))


@mark.parametrize(
    ("name", "edit"),
    [
        ("beslut.pdf", _drop_second_row),
        (
            "beslut.pdf",
            lambda raw: raw["letterhead"].update(organisation="Region Västernorrland"),
        ),
        ("beslut.docx", _drop_second_row),
        ("ansokan.json", _reverse_keys),
    ],
)
def test_a_file_that_says_more_than_its_spec_is_reported(
    tmp_path: Path, name: str, edit: Callable[[dict[str, Any]], object]
) -> None:
    # Everything the spec still says is in the file, but the file no longer reads as the spec renders.
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    _edit_spec(spec_dir, name, edit)

    problems = _check((fixture_dir, spec_dir, manifest))

    assert len(problems) == 1
    assert problems[0].startswith(f"{name}: reads ")
    assert " where the spec now renders " in problems[0]


def test_an_invalid_spec_is_one_problem_line_and_the_check_goes_on(
    tmp_path: Path,
) -> None:
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    _edit_spec(spec_dir, "beslut.txt", lambda raw: raw.update(styling="fet"))
    _edit_spec(
        spec_dir,
        "export.csv",
        lambda raw: raw.update(
            source={
                "catalogue_id": "UTB-01",
                "url": "https://e-tjanster.sundsvall.se/x",
            }
        ),
    )
    _edit_spec(
        spec_dir, "beslut.pdf", lambda raw: raw["source"].update(catalogue_id="utb-10")
    )
    _edit_spec(
        spec_dir,
        "register.xlsx",
        lambda raw: raw["source"].update(
            url="http://e-tjanster.sundsvall.se/oversikt/overview/285"
        ),
    )
    (spec_dir / "ansokan.json.json").write_text(
        '{"file": "ansokan.json",', encoding="utf-8"
    )
    (spec_dir / "beslut.docx.json").write_text(
        '{"file": "beslut.docx", "file": "beslut.docx"}', encoding="utf-8"
    )
    # 1e400 parses to infinity, which JSON cannot carry.
    (spec_dir / "extra.json.json").write_text(
        json.dumps(
            {**_specs()["ansokan.json"], "file": "extra.json", "data": {"belopp": 0}}
        ).replace('"belopp": 0', '"belopp": 1e400'),
        encoding="utf-8",
    )

    problems = _check((fixture_dir, spec_dir, manifest))

    assert problems[0].startswith("ansokan.json.json: Expecting property name")
    assert problems[1:] == [
        "beslut.docx.json: duplicate key 'file'",
        "beslut.pdf.json: source catalogue_id must look like BYG-01",
        "beslut.txt.json: unknown keys: styling",
        "export.csv.json: source 'UTB-01' is not in the pinned sources",
        "extra.json.json: data holds a number that is not finite",
        "register.xlsx.json: source url must be an https URL",
    ]


def test_a_manifest_the_harness_would_refuse_is_one_problem_line(
    tmp_path: Path,
) -> None:
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    pinned = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps({**pinned, "version": 2}), encoding="utf-8")

    problems = _check((fixture_dir, spec_dir, manifest))

    assert len(problems) == 1
    assert problems[0].startswith("manifest.json: cannot be read: ValueError(")
    manifest.unlink()
    assert _check((fixture_dir, spec_dir, manifest)) == [
        "manifest.json: cannot be read: FileNotFoundError(2, 'No such file or directory')"
    ]


def test_a_spec_may_not_claim_a_legacy_fixture_name(tmp_path: Path) -> None:
    fixture_dir, spec_dir, manifest = _tree(tmp_path)
    legacy = _spec("04_remissvar.docx", **DOCUMENT)
    (spec_dir / "04_remissvar.docx.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )

    assert _check((fixture_dir, spec_dir, manifest)) == [
        "04_remissvar.docx.json: 04_remissvar.docx collides with an existing fixture"
    ]


def _generate_into(
    tmp_path: Path, monkeypatch: MonkeyPatch, *specs: dict[str, Any]
) -> None:
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    for raw in specs:
        (spec_dir / f"{raw['file']}.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(generator, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(generator, "SPEC_DIR", spec_dir)
    monkeypatch.setattr(generator, "MANIFEST_PATH", tmp_path / "manifest.json")
    generator._write_fixtures()


@mark.parametrize(
    "raw",
    [
        _spec("edit_seed_a.json", data={"name": "ersätter fröet"}),
        _spec("04_remissvar.docx", **DOCUMENT),
    ],
    ids=["unpinned file", "legacy name"],
)
def test_the_generator_refuses_a_spec_that_takes_a_fixture_name(
    tmp_path: Path, monkeypatch: MonkeyPatch, raw: dict[str, Any]
) -> None:
    seed = tmp_path / "edit_seed_a.json"
    seed.write_text("{}", encoding="utf-8")

    with raises(ValueError, match=f"{raw['file']} collides with an existing fixture"):
        _generate_into(tmp_path, monkeypatch, raw)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "edit_seed_a.json",
        "specs",
    ]
    assert seed.read_text(encoding="utf-8") == "{}"


def test_the_generator_writes_nothing_when_a_spec_cannot_be_rendered(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    unrenderable = {"name": "Blad", "columns": ["Text"], "rows": [["styrtecken \x01"]]}

    with raises(IllegalCharacterError):
        _generate_into(
            tmp_path,
            monkeypatch,
            _spec("a_export.csv", sheets=[SHEET]),
            _spec("b_register.xlsx", sheets=[unrenderable]),
        )
    assert sorted(path.name for path in tmp_path.iterdir()) == ["specs"]


def _drop(key: str) -> Callable[[dict[str, Any]], object]:
    return lambda raw: raw.pop(key)


@mark.parametrize(
    ("name", "edit", "message"),
    [
        ("beslut.pdf", lambda raw: raw.update(styling="fet"), "unknown keys: styling"),
        ("beslut.pdf", _drop("letterhead"), "missing keys: letterhead"),
        ("beslut.pdf", _drop("title"), "missing keys: title"),
        (
            "beslut.pdf",
            lambda raw: raw.update(file="annat.pdf"),
            "must be named annat.pdf.json",
        ),
        ("beslut.pdf", lambda raw: raw.update(format="odt"), "format must be one of"),
        (
            "beslut.pdf",
            lambda raw: raw.update(format="docx"),
            "file suffix must be .docx",
        ),
        (
            "beslut.pdf",
            lambda raw: raw.update(date="12 augusti 2026"),
            "date must be YYYY-MM-DD",
        ),
        (
            "beslut.pdf",
            lambda raw: raw.update(date="20260812"),
            "date must be YYYY-MM-DD",
        ),
        (
            "beslut.pdf",
            lambda raw: raw.update(description=""),
            "description must be a non-empty string",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["source"].update(kommun="Sundsvall"),
            "source: unknown keys: kommun",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["letterhead"].pop("unit"),
            "letterhead: missing keys: unit",
        ),
        (
            "beslut.pdf",
            lambda raw: raw.update(blocks=[]),
            "blocks must be a non-empty list",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"].append({"heading": "A", "paragraph": "B"}),
            "blocks\\[7\\] must have exactly one of",
        ),
        (
            "beslut.pdf",
            lambda raw: raw.update(letterhead="Sundsvalls kommun"),
            "letterhead must be an object",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"].append("Beslut"),
            "blocks\\[7\\] must have exactly one of",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"].append({"citat": "A"}),
            "blocks\\[7\\] must have exactly one of",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"].append({"page_break": False}),
            "page_break must be true",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"].append({"signature": {"name": "Eva Berg"}}),
            "signature: missing keys: role",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"][3]["table"]["rows"].append(["en cell"]),
            "table row 3 has 1 cells for 3 columns",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"][3]["table"]["rows"][0].__setitem__(1, 100),
            "table cells must be strings",
        ),
        (
            "beslut.txt",
            lambda raw: raw["blocks"].append({"page_break": True}),
            "a txt document has no page_break",
        ),
        (
            "export.csv",
            lambda raw: raw["sheets"].append(SHEET),
            "a csv has exactly one sheet",
        ),
        ("export.csv", lambda raw: raw.update(blocks=[]), "unknown keys: blocks"),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][0]["rows"].append(["2026-09", True, None]),
            "cell must be a string, a number or null",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][1].update(name="Summering: kvartal 1/2"),
            "a sheet name has at most 31 characters",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][1].update(
                name="Summering av utbetalningar per månad"
            ),
            "a sheet name has at most 31 characters",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][0]["columns"].__setitem__(2, "Månad"),
            "columns must be unique non-empty strings",
        ),
        (
            "beslut.pdf",
            lambda raw: raw["blocks"].append(TEMPLATE_BLOCKS[2]),
            "only a docx has content controls",
        ),
        (
            "beslut.docx",
            lambda raw: raw["blocks"].extend([TEMPLATE_BLOCKS[2], TEMPLATE_BLOCKS[2]]),
            "control tags must be unique",
        ),
        (
            "beslut.docx",
            lambda raw: raw["blocks"].append(
                {"control": {**TEMPLATE_BLOCKS[2]["control"], "kind": "date"}}
            ),
            "control kind must be rich or text",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][0]["rows"].append(
                ["2026-09", float("inf"), None]
            ),
            "cell must be a finite number",
        ),
        (
            "ansokan.json",
            lambda raw: raw["data"].update(belopp=float("nan")),
            "data holds a number that is not finite",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][1].update(name="utbetalningar"),
            "sheet names must differ in more than case",
        ),
        (
            "register.xlsx",
            lambda raw: raw["sheets"][0]["rows"][0].pop(),
            "row 1 has 2 cells for 3 columns",
        ),
        ("ansokan.json", _drop("data"), "missing keys: data"),
    ],
)
def test_a_spec_is_validated_on_load(
    name: str, edit: Callable[[dict[str, Any]], object], message: str
) -> None:
    raw = _specs()[name]
    edit(raw)

    with raises(ValueError, match=message):
        render.parse_spec(raw, spec_name=f"{name}.json")


def test_a_spec_must_be_a_json_object() -> None:
    with raises(ValueError, match="beslut.pdf.json must be an object"):
        render.parse_spec([_specs()["beslut.pdf"]], spec_name="beslut.pdf.json")

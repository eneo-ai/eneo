from __future__ import annotations

import io
import zipfile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from eneo.flows.runtime.document_rendering.blocks import DocumentStructureError
from eneo.flows.runtime.document_rendering.docx_content_controls import (
    DocxTemplateContractError,
    append_rich_control,
    append_text_control,
)
from eneo.flows.runtime.document_rendering.limits import DocumentRenderLimits
from eneo.flows.runtime.docx_template_runtime import (
    extract_docx_template_text_preview,
    extract_docx_text,
    inspect_docx_template_bytes,
    inspect_docx_template_placeholders,
    render_docx_template,
)
from eneo.main.exceptions import (
    BadRequestException,
    FileNotSupportedException,
    TypedIOValidationException,
)
from tests.docx_template_fixtures import (
    control_template_bytes,
    docx_paragraph_texts,
    docx_paragraphs,
    docx_styled_paragraphs,
    docx_tables,
)

_RAPPORT_TEXT = [
    ("titel", "Titel", "Rapportens titel"),
    ("datum", "Datum", "ÅÅÅÅ-MM-DD"),
]
_RAPPORT_RICH = [
    ("sammanfattning", "Sammanfattning", "Två till fyra stycken."),
    ("analys", "Analys", "Underrubriker och tabeller."),
]


def _rapport() -> bytes:
    return control_template_bytes(text=_RAPPORT_TEXT, rich=_RAPPORT_RICH)


def _document_xml(blob: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(blob)).read("word/document.xml").decode()


def _bytes(document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# --- discovery ------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Ordinary source document", "Case: {{ case_id }}"])
def test_empty_control_discovery_is_allowed_but_template_use_is_rejected(
    text: str,
) -> None:
    document = Document()
    document.add_paragraph(text)
    blob = _bytes(document)

    assert inspect_docx_template_placeholders(blob, filename="source.docx") == ()
    with pytest.raises(DocxTemplateContractError, match="at least one") as info:
        inspect_docx_template_bytes(blob, filename="template.docx")
    assert info.value.code == "flow_template_no_controls"
    with pytest.raises(TypedIOValidationException, match="at least one"):
        render_docx_template(template_bytes=blob, context={}, step_order=1)


def test_corrupt_pinned_template_has_typed_runtime_failure() -> None:
    with pytest.raises(TypedIOValidationException) as info:
        render_docx_template(template_bytes=b"not a docx", context={}, step_order=1)
    assert info.value.code == "typed_io_template_render_failed"


def test_inspect_lists_controls_with_kind_label_and_hint_in_document_order() -> None:
    placeholders = inspect_docx_template_bytes(_rapport(), filename="rapport.docx")

    assert placeholders == [
        {
            "name": "titel",
            "label": "Titel",
            "kind": "text",
            "hint": "Rapportens titel",
            "location": "body",
        },
        {
            "name": "datum",
            "label": "Datum",
            "kind": "text",
            "hint": "ÅÅÅÅ-MM-DD",
            "location": "body",
        },
        {
            "name": "sammanfattning",
            "label": "Sammanfattning",
            "kind": "rich",
            "hint": "Två till fyra stycken.",
            "location": "body",
        },
        {
            "name": "analys",
            "label": "Analys",
            "kind": "rich",
            "hint": "Underrubriker och tabeller.",
            "location": "body",
        },
    ]


def test_inspect_rejects_macro_enabled_filenames_before_reading() -> None:
    with pytest.raises(FileNotSupportedException):
        inspect_docx_template_bytes(_rapport(), filename="rapport.docm")


def test_inspect_rejects_a_control_without_a_tag() -> None:
    document = Document()
    sdt = append_rich_control(document, tag="tmp", label="Avsnitt", hint="x")
    properties = sdt.find(qn("w:sdtPr"))
    properties.remove(properties.find(qn("w:tag")))

    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(document), filename="t.docx")
    assert info.value.code == "flow_template_control_untagged"


def test_inspect_rejects_duplicate_tags() -> None:
    document = Document()
    append_rich_control(document, tag="avsnitt", label="A", hint="a")
    append_rich_control(document, tag="avsnitt", label="B", hint="b")

    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(document), filename="t.docx")
    assert info.value.code == "flow_template_control_duplicate"


def test_inspect_rejects_nested_controls() -> None:
    document = Document()
    outer = append_rich_control(document, tag="outer", label="Outer", hint="o")
    inner = OxmlElement("w:sdt")
    inner_properties = OxmlElement("w:sdtPr")
    tag = OxmlElement("w:tag")
    tag.set(qn("w:val"), "inner")
    inner_properties.append(tag)
    inner.append(inner_properties)
    inner.append(OxmlElement("w:sdtContent"))
    outer.find(qn("w:sdtContent")).append(inner)

    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(document), filename="t.docx")
    assert info.value.code == "flow_template_control_nested"


def test_inspect_rejects_controls_mapped_to_custom_xml() -> None:
    document = Document()
    sdt = append_rich_control(document, tag="mapped", label="Mapped", hint="m")
    binding = OxmlElement("w:dataBinding")
    binding.set(qn("w:xpath"), "/root/value")
    binding.set(qn("w:storeItemID"), "{00000000-0000-0000-0000-000000000000}")
    sdt.find(qn("w:sdtPr")).append(binding)

    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(document), filename="t.docx")
    assert info.value.code == "flow_template_control_mapped"


def test_inspect_rejects_unsupported_control_kinds() -> None:
    document = Document()
    paragraph = document.add_paragraph("Datum: ")
    sdt = append_text_control(paragraph, tag="datum", label="Datum", hint="d")
    properties = sdt.find(qn("w:sdtPr"))
    properties.remove(properties.find(qn("w:text")))
    properties.append(OxmlElement("w:date"))

    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(document), filename="t.docx")
    assert info.value.code == "flow_template_control_unsupported"
    assert "date control" in str(info.value)


@pytest.mark.parametrize("shape", ["body_text", "custom_xml_parent"])
def test_inspect_rejects_controls_outside_the_structural_profile(shape: str) -> None:
    document = Document()
    sdt = append_rich_control(document, tag="value", label="Value", hint="v")
    if shape == "body_text":
        sdt.find(qn("w:sdtPr")).append(OxmlElement("w:text"))
    else:
        wrapper = OxmlElement("w:customXml")
        document.element.body.insert(0, wrapper)
        wrapper.append(sdt)

    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(document), filename="t.docx")
    assert info.value.code == "flow_template_control_placement"


def test_inspect_rejects_controls_in_table_cells_and_headers() -> None:
    in_cell = Document()
    cell_paragraph = in_cell.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0]
    append_text_control(cell_paragraph, tag="cell", label="Cell", hint="c")
    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(in_cell), filename="t.docx")
    assert info.value.code == "flow_template_control_placement"

    in_header = Document()
    header_paragraph = in_header.sections[0].header.paragraphs[0]
    append_text_control(header_paragraph, tag="header", label="Header", hint="h")
    with pytest.raises(DocxTemplateContractError) as info:
        inspect_docx_template_bytes(_bytes(in_header), filename="t.docx")
    assert info.value.code == "flow_template_control_placement"


def test_inspect_normalizes_corrupt_archives() -> None:
    with pytest.raises(BadRequestException):
        inspect_docx_template_bytes(b"not a docx", filename="t.docx")


# --- fill -------------------------------------------------------------------------


def test_render_writes_markdown_sections_with_the_template_styles() -> None:
    blob, mimetype, filename = render_docx_template(
        template_bytes=_rapport(),
        context={
            "titel": "Översyn 2026",
            "datum": "2026-09-08",
            "sammanfattning": "Första stycket.\n\nAndra stycket med **fetstil**.",
            "analys": (
                "## Kostnader\n\n| Förvaltning | 2025 |\n|---|---|\n| Skola | 131 |\n\n"
                "## Orsaker\n\n- Hyra\n  - Index\n- Nya lokaler\n\n1. Ett\n2. Två"
            ),
        },
        step_order=4,
    )

    assert mimetype.endswith("wordprocessingml.document")
    assert filename == "step_4_output.docx"
    styled = docx_styled_paragraphs(blob)
    assert ("Normal", "Titel: Översyn 2026") in styled
    assert ("Heading 1", "Sammanfattning") in styled
    assert ("Normal", "Första stycket.") in styled
    assert ("Heading 2", "Kostnader") in styled
    assert ("Heading 2", "Orsaker") in styled
    assert ("List Bullet", "Hyra") in styled
    assert ("List Bullet 2", "Index") in styled
    assert ("List Number", "Ett") in styled
    bold_runs = [
        run.text
        for paragraph in docx_paragraphs(blob)
        for run in paragraph.runs
        if run.bold
    ]
    assert bold_runs == ["fetstil"]
    tables = docx_tables(blob)
    assert len(tables) == 1
    header_row = tables[0].rows[0]
    assert header_row._tr.trPr.find(qn("w:tblHeader")) is not None
    assert [cell.paragraphs[0].runs[0].bold for cell in header_row.cells] == [
        True,
        True,
    ]
    assert tables[0].rows[1].cells[0].paragraphs[0].runs[0].bold is None
    xml = _document_xml(blob)
    assert "showingPlcHdr" not in xml
    assert "PlaceholderText" not in xml


def test_render_keeps_relative_heading_levels_under_the_section_heading() -> None:
    template = control_template_bytes(
        rich=[("avsnitt", "Avsnitt", "x")], heading_level=2
    )

    blob, _, _ = render_docx_template(
        template_bytes=template,
        context={"avsnitt": "# Delrubrik\n\nText\n\n## Underrubrik"},
        step_order=1,
    )

    styles = docx_styled_paragraphs(blob)
    assert ("Heading 2", "Avsnitt") in styles
    assert ("Heading 3", "Delrubrik") in styles
    assert ("Heading 4", "Underrubrik") in styles


def test_render_rejects_skipped_heading_levels_by_section() -> None:
    with pytest.raises(DocumentStructureError, match="section 'Analys'"):
        render_docx_template(
            template_bytes=_rapport(),
            context={
                "titel": "T",
                "datum": "D",
                "sammanfattning": "S",
                "analys": "## A\n\n#### Hoppar över en nivå",
            },
            step_order=1,
        )


def test_render_text_controls_take_one_line_unless_multiline() -> None:
    document = Document()
    single = document.add_paragraph("En rad: ")
    append_text_control(single, tag="en", label="En", hint="e")
    multi = document.add_paragraph("Flera: ")
    append_text_control(multi, tag="flera", label="Flera", hint="f", multiline=True)

    blob, _, _ = render_docx_template(
        template_bytes=_bytes(document),
        context={"en": "första\nandra", "flera": "första\nandra"},
        step_order=1,
    )

    texts = docx_paragraph_texts(blob)
    assert texts[0] == "En rad: första andra"
    assert _document_xml(blob).count("<w:br/>") == 1
    assert "Flera: första" in texts[1]


def test_render_removes_a_control_bound_to_empty_and_keeps_static_content() -> None:
    blob, _, _ = render_docx_template(
        template_bytes=_rapport(),
        context={"titel": "T", "datum": "", "sammanfattning": "S", "analys": ""},
        step_order=1,
    )

    texts = docx_paragraph_texts(blob)
    assert "Datum: " in texts
    assert "Analys" in texts
    assert _document_xml(blob).count("<w:sdt>") == 2
    assert "Underrubriker" not in extract_docx_text(blob)


def test_render_rejects_missing_and_valueless_bindings_before_writing() -> None:
    with pytest.raises(
        TypedIOValidationException, match="Unresolved template placeholders: analys"
    ):
        render_docx_template(
            template_bytes=_rapport(),
            context={"titel": "T", "datum": "D", "sammanfattning": "S"},
            step_order=1,
        )
    with pytest.raises(TypedIOValidationException, match="without a value: datum"):
        render_docx_template(
            template_bytes=_rapport(),
            context={"titel": "T", "datum": None, "sammanfattning": "S", "analys": "A"},
            step_order=1,
        )


def test_render_holds_the_whole_document_to_the_render_limits() -> None:
    with pytest.raises(TypedIOValidationException):
        render_docx_template(
            template_bytes=_rapport(),
            context={
                "titel": "T",
                "datum": "D",
                "sammanfattning": "Ett\n\nTvå",
                "analys": "Tre\n\nFyra",
            },
            step_order=1,
            limits=DocumentRenderLimits(max_blocks=3),
        )


@pytest.mark.parametrize("second_kind", ["text", "rich"])
@pytest.mark.parametrize(
    ("limits", "metric"),
    [
        (DocumentRenderLimits(max_source_chars=7), "source_chars"),
        (DocumentRenderLimits(max_text_chars=7), "text_chars"),
    ],
)
def test_render_counts_inline_values_in_aggregate_limits(
    second_kind: str, limits: DocumentRenderLimits, metric: str
) -> None:
    second = ("second", "Second", "s")
    template = control_template_bytes(
        text=[("first", "First", "f"), *([second] if second_kind == "text" else [])],
        rich=[second] if second_kind == "rich" else [],
    )
    with pytest.raises(TypedIOValidationException) as info:
        render_docx_template(
            template_bytes=template,
            context={"first": "abcd", "second": "efgh"},
            step_order=1,
            limits=limits,
        )
    assert info.value.context is not None
    assert info.value.context["metric"] == metric


def test_render_refuses_a_template_that_left_the_supported_profile() -> None:
    document = Document()
    append_rich_control(document, tag="a", label="A", hint="a")
    append_rich_control(document, tag="a", label="B", hint="b")

    with pytest.raises(TypedIOValidationException, match="no longer fillable"):
        render_docx_template(
            template_bytes=_bytes(document), context={"a": "x"}, step_order=1
        )


# --- extraction ---------------------------------------------------------------------


def test_extract_docx_text_reads_control_content_and_skips_page_furniture() -> None:
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Sidhuvud"
    document.add_paragraph("Före")
    append_rich_control(document, tag="mitt", label="Mitt", hint="Placeholder")
    document.add_paragraph("Efter")
    blob, _, _ = render_docx_template(
        template_bytes=_bytes(document),
        context={"mitt": "Inuti kontrollen\n\n| A | B |\n|---|---|\n| 1 | 2 |"},
        step_order=1,
    )

    text = extract_docx_text(blob)

    assert text.index("Före") < text.index("Inuti kontrollen") < text.index("Efter")
    assert "1" in text and "B" in text
    assert "Sidhuvud" not in text
    assert "Placeholder" not in text


def test_extract_docx_template_text_preview_returns_readable_text() -> None:
    assert "Sammanfattning" in extract_docx_template_text_preview(_rapport())

from intric.flows.ai_builder.ai_builder_clause_segmenter import (
    build_role_scoped_text,
)


def test_role_scoped_text_separates_uploaded_pdf_input_from_docx_output() -> None:
    scoped = build_role_scoped_text(
        "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
    )

    assert "uppladdat pdf dokument" in scoped.input_text
    assert "genererar en docx rapport" in scoped.output_text


def test_role_scoped_text_separates_pdf_output_from_text_summary_content() -> None:
    scoped = build_role_scoped_text(
        "Bygg ett flöde som skapar en PDF-rapport som innehåller en kort textsammanfattning på svenska."
    )

    assert "skapar en pdf rapport" in scoped.output_text
    assert scoped.input_text == ""


def test_role_scoped_text_tracks_replacement_target_and_source() -> None:
    scoped = build_role_scoped_text(
        "Ändra så att jag får ut en DOCX-rapport istället för en PDF."
    )

    assert "docx rapport" in scoped.replacement_target_text
    assert "pdf" in scoped.replacement_source_text


def test_role_scoped_text_handles_empty_text() -> None:
    scoped = build_role_scoped_text("   ")

    assert scoped.clauses == ()


def test_role_scoped_text_handles_bare_replacement_phrase_without_crashing() -> None:
    scoped = build_role_scoped_text("istället för")

    assert scoped.replacement_target_text == ""
    assert scoped.replacement_source_text == ""

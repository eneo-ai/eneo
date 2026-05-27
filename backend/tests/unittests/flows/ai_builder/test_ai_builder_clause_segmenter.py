from intric.flows.ai_builder.ai_builder_clause_segmenter import (
    build_role_scoped_text,
)


def test_role_scoped_text_separates_uploaded_pdf_input_from_docx_output() -> None:
    scoped = build_role_scoped_text(
        "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
    )

    assert "uppladdat pdf dokument" in scoped.input_text
    assert "genererar en docx rapport" in scoped.output_text


def test_role_scoped_text_splits_terminal_word_file_after_audio_input() -> None:
    scoped = build_role_scoped_text(
        (
            "Jag vill bygga ett flöde där jag ska skicka in en ljudfil som ska "
            "transkriberas. Jag vill ha en Word-fil i slutet."
        )
    )

    assert "skicka in en ljudfil" in scoped.input_text
    assert "word fil i slutet" in scoped.output_text
    assert "word fil" not in scoped.input_text


def test_role_scoped_text_splits_inflected_swedish_final_docx_output() -> None:
    scoped = build_role_scoped_text(
        (
            "Bygg ett Flow för en extern webbapp där användaren laddar upp ljud, "
            "får transkribering, kan granska och korrigera texten, och sedan får "
            "en slutlig DOCX-rapport. Använd strukturerad JSON där det hjälper "
            "API-konsumenten, men håll slutresultatet som dokument."
        )
    )

    assert "laddar upp ljud" in scoped.input_text
    assert "får en slutlig docx rapport" in scoped.output_text
    assert "docx rapport" not in scoped.input_text


def test_role_scoped_text_does_not_promote_uploaded_pdf_before_terminal_connector() -> (
    None
):
    scoped = build_role_scoped_text(
        (
            "Bygg ett flöde där användaren ska skicka in en PDF och i slutet "
            "vill jag ha en sammanfattning."
        )
    )

    assert "skicka in en pdf och i slutet vill jag ha en sammanfattning" in (
        scoped.input_text
    )
    assert "pdf" not in scoped.output_text


def test_role_scoped_text_keeps_terse_terminal_docx_upload_as_input() -> None:
    scoped = build_role_scoped_text("Skicka in en DOCX i slutet.")

    assert "skicka in en docx i slutet" in scoped.input_text
    assert scoped.output_text == ""


def test_role_scoped_text_keeps_explicit_output_anchor_with_terminal_artifact() -> None:
    scoped = build_role_scoped_text("Bygg ett flöde som skapar en DOCX i slutet.")

    assert scoped.input_text == ""
    assert "skapar en docx i slutet" in scoped.output_text


def test_role_scoped_text_keeps_compact_word_upload_as_input() -> None:
    scoped = build_role_scoped_text(
        "Skapa ett flöde som ska få ett worddokument uppladdat som input."
    )

    assert scoped.output_text == ""
    assert "word dokument" in scoped.neutral_text
    assert "uppladdat som input" in scoped.input_text


def test_role_scoped_text_splits_compact_word_terminal_output_after_input() -> None:
    scoped = build_role_scoped_text(
        (
            "Skapa ett flöde som ska få ett worddokument uppladdat som input. "
            "När alla steg är klara så ska det i slutändan skapas ett "
            "worddokument som output."
        )
    )

    assert "uppladdat som input" in scoped.input_text
    assert "i slutändan skapas ett word dokument som output" in scoped.output_text


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

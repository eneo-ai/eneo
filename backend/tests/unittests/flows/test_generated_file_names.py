from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.runtime.generated_file_names import GeneratedFileNames

# 22:30 UTC on 23 September is already the 24th in Stockholm; Eneo has no
# time zone to name that day by, so a run is dated by its UTC day.
RUN_CREATED_AT = datetime(2026, 9, 23, 22, 30, tzinfo=timezone.utc)


def _step(step_order: int, output_type: str, name: str | None = None) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=name,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_type=output_type,
    )


def _names(flow_name: str, *steps: RuntimeStep) -> GeneratedFileNames:
    return GeneratedFileNames.for_run(
        flow_name=flow_name, steps=steps, run_created_at=RUN_CREATED_AT
    )


def test_one_document_is_named_after_the_flow_and_the_run_day() -> None:
    names = _names(
        "Nämndmöte", _step(1, "text", "Transkribera"), _step(2, "pdf", "Protokoll")
    )

    assert names.name(step_order=2, output_type="pdf") == "Nämndmöte 2026-09-23.pdf"


def test_steps_sharing_a_document_type_add_their_names() -> None:
    names = _names(
        "Nämndmöte",
        _step(1, "pdf", "Protokoll"),
        _step(2, "pdf", "Beslut"),
        _step(3, "docx", "Kallelse"),
    )

    assert (
        names.name(step_order=1, output_type="pdf")
        == "Nämndmöte Protokoll 2026-09-23.pdf"
    )
    assert (
        names.name(step_order=2, output_type="pdf") == "Nämndmöte Beslut 2026-09-23.pdf"
    )
    assert names.name(step_order=3, output_type="docx") == "Nämndmöte 2026-09-23.docx"


def test_characters_file_systems_refuse_become_spaces() -> None:
    names = _names(
        '.Nämnd/Styrelse: "protokoll" <v2>?*|\\ \t\u202e\x07 ..', _step(1, "pdf")
    )

    assert (
        names.name(step_order=1, output_type="pdf")
        == "Nämnd Styrelse protokoll v2 2026-09-23.pdf"
    )


def test_names_that_clean_to_nothing_fall_back_to_neutral_words() -> None:
    names = _names(" ?? ", _step(1, "pdf", "***"), _step(2, "pdf"))

    assert (
        names.name(step_order=1, output_type="pdf") == "Dokument Steg 1 2026-09-23.pdf"
    )
    assert (
        names.name(step_order=2, output_type="pdf") == "Dokument Steg 2 2026-09-23.pdf"
    )


def test_a_long_flow_name_is_cut_to_255_bytes_between_whole_characters() -> None:
    names = _names("ö" * 200, _step(1, "docx"))

    name = names.name(step_order=1, output_type="docx")

    # 255 bytes less " 2026-09-23.docx" leaves 239: 119 two-byte characters.
    assert name == "ö" * 119 + " 2026-09-23.docx"
    assert len(name.encode("utf-8")) <= 255

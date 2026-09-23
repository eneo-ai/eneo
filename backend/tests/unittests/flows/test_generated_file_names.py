from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from uuid import uuid4

import pytest
from docx import Document

from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.runtime.document_rendering.service import (
    default_document_render_service,
)
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


def _pdf_names(names: GeneratedFileNames, *step_orders: int) -> list[str]:
    return [names.name(step_order=order, output_type="pdf") for order in step_orders]


def test_documents_that_would_share_a_name_all_carry_their_step_number() -> None:
    names = _names(
        "Nämndmöte",
        _step(1, "pdf", "Beslut"),
        _step(2, "pdf", "Beslut"),
        _step(3, "pdf", "Beslut Steg 1"),
        _step(4, "docx", "Kallelse"),
    )

    assert _pdf_names(names, 1, 2, 3) == [
        "Nämndmöte Beslut Steg 1 2026-09-23.pdf",
        "Nämndmöte Beslut Steg 2 2026-09-23.pdf",
        "Nämndmöte Beslut Steg 1 Steg 3 2026-09-23.pdf",
    ]
    assert names.name(step_order=4, output_type="docx") == "Nämndmöte 2026-09-23.docx"


def test_step_names_that_clean_to_one_name_carry_their_step_number() -> None:
    names = _names("Nämndmöte", _step(1, "pdf", "A/B"), _step(2, "pdf", "A:B"))

    assert _pdf_names(names, 1, 2) == [
        "Nämndmöte A B Steg 1 2026-09-23.pdf",
        "Nämndmöte A B Steg 2 2026-09-23.pdf",
    ]


def test_a_flow_name_that_cuts_the_step_names_away_keeps_the_step_number() -> None:
    names = _names("ö" * 128, _step(1, "pdf", "Protokoll"), _step(2, "pdf", "Beslut"))

    # 255 bytes less " Steg 1 2026-09-23.pdf" leaves 233: 116 two-byte characters.
    assert _pdf_names(names, 1, 2) == [
        "ö" * 116 + " Steg 1 2026-09-23.pdf",
        "ö" * 116 + " Steg 2 2026-09-23.pdf",
    ]


_WINDOWS_DEVICES = [
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"{port}{digit}" for port in ("COM", "LPT") for digit in "123456789¹²³"),
]


@pytest.mark.parametrize(
    "device", [*_WINDOWS_DEVICES, *(device.lower() for device in _WINDOWS_DEVICES)]
)
@pytest.mark.parametrize("flow_name", ["{}.rapport", "{} ..rapport"])
def test_a_flow_named_after_a_windows_device_downloads_under_a_usable_name(
    device: str, flow_name: str
) -> None:
    names = _names(flow_name.format(device), _step(1, "docx"))

    name = names.name(step_order=1, output_type="docx")

    assert not PureWindowsPath(name).is_reserved()
    assert name == f"{device} rapport 2026-09-23.docx"


@pytest.mark.parametrize("noncharacter", ["\ufffe", "\uffff", "\ufdd0"])
def test_a_noncharacter_leaves_a_title_a_docx_can_carry(noncharacter: str) -> None:
    names = _names(f"Möte{noncharacter}", _step(1, "docx"))
    title = names.stem(step_order=1, output_type="docx")

    blob, _ = default_document_render_service().render_document(
        "Text", "docx", step_order=1, title=title
    )

    assert Document(io.BytesIO(blob)).core_properties.title == "Möte 2026-09-23"

from __future__ import annotations

import io
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import PureWindowsPath
from unittest.mock import patch
from uuid import uuid4

import pytest
from docx import Document

from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.domain.step_deliverable import FlowStepDeliverable
from eneo.flows.flow_run_redaction import redact_string
from eneo.flows.runtime.document_rendering.service import (
    default_document_render_service,
)
from eneo.flows.runtime.generated_file_names import (
    MAX_FILE_NAME_BYTES,
    GeneratedFileNames,
)

# Templates are read and documents rendered in the shared tool runtime.
pytestmark = pytest.mark.usefixtures("shared_document_runtime")

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
        flow_name=flow_name, steps=steps, run_created_at=RUN_CREATED_AT, form_values={}
    )


def test_one_document_is_named_after_the_flow_and_the_run_day() -> None:
    names = _names(
        "Nämndmöte", _step(1, "text", "Transkribera"), _step(2, "pdf", "Protokoll")
    )

    assert names.name(step_order=2, output_type="pdf") == "Nämndmöte 2026-09-23.pdf"


def test_a_named_and_dated_run_names_its_documents_after_itself() -> None:
    steps = (_step(1, "text", "Transkribera"), _step(2, "docx", "Protokoll"))
    names = GeneratedFileNames.for_run(
        flow_name="Generell mötesantecknare med talare",
        steps=steps,
        run_created_at=RUN_CREATED_AT,
        form_values={},
        run_label="Testmöte 2",
        run_date=date(2026, 10, 1),
    )

    assert names.name(step_order=2, output_type="docx") == "Testmöte 2 2026-10-01.docx"
    assert names.stem(step_order=2, output_type="docx") == "Testmöte 2 2026-10-01"


@pytest.mark.parametrize(
    ("run_label", "run_date", "expected"),
    [
        ("Testmöte 2", None, "Testmöte 2 2026-09-23.pdf"),
        (None, date(2026, 10, 1), "Nämndmöte 2026-10-01.pdf"),
        (None, None, "Nämndmöte 2026-09-23.pdf"),
        ("Möte: 3/4", None, "Möte 3 4 2026-09-23.pdf"),
        ("../..", None, "Nämndmöte 2026-09-23.pdf"),
    ],
)
def test_a_runs_name_and_day_each_stand_in_for_the_flows_and_the_run_day(
    run_label: str | None, run_date: date | None, expected: str
) -> None:
    names = GeneratedFileNames.for_run(
        flow_name="Nämndmöte",
        steps=(_step(1, "pdf", "Protokoll"),),
        run_created_at=RUN_CREATED_AT,
        form_values={},
        run_label=run_label,
        run_date=run_date,
    )

    assert names.name(step_order=1, output_type="pdf") == expected


def test_a_named_runs_documents_of_one_type_still_carry_their_steps() -> None:
    names = GeneratedFileNames.for_run(
        flow_name="Nämndmöte",
        steps=(_step(1, "pdf", "Protokoll"), _step(2, "pdf", "Beslut")),
        run_created_at=RUN_CREATED_AT,
        form_values={},
        run_label="Testmöte 2",
        run_date=date(2026, 10, 1),
    )

    assert (
        names.name(step_order=1, output_type="pdf")
        == "Testmöte 2 Protokoll 2026-10-01.pdf"
    )
    assert (
        names.name(step_order=2, output_type="pdf")
        == "Testmöte 2 Beslut 2026-10-01.pdf"
    )


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


@pytest.mark.parametrize(
    ("first", "second", "first_shown", "second_shown"),
    [
        ("A/B", "A:B", "A B", "A B"),
        # One file on case-insensitive file systems (Windows, macOS).
        ("Beslut", "beslut", "Beslut", "beslut"),
        ("Åtgärd", "åtgärd", "Åtgärd", "åtgärd"),
    ],
)
def test_step_names_that_clean_to_one_name_carry_their_step_number(
    first: str, second: str, first_shown: str, second_shown: str
) -> None:
    names = _names("Nämndmöte", _step(1, "pdf", first), _step(2, "pdf", second))

    assert _pdf_names(names, 1, 2) == [
        f"Nämndmöte {first_shown} Steg 1 2026-09-23.pdf",
        f"Nämndmöte {second_shown} Steg 2 2026-09-23.pdf",
    ]


def test_the_numbering_is_decided_once_per_run() -> None:
    names = _names(
        "Nämndmöte", *(_step(order, "pdf", "Beslut") for order in range(1, 31))
    )

    with patch.object(
        GeneratedFileNames,
        "_stem",
        autospec=True,
        side_effect=GeneratedFileNames._stem,
    ) as built:
        for order in range(1, 31):
            names.name(step_order=order, output_type="pdf")

    # 30 stems to decide the numbering, then one for each name.
    assert built.call_count == 60


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
async def test_a_noncharacter_leaves_a_title_a_docx_can_carry(
    noncharacter: str,
) -> None:
    names = _names(f"Möte{noncharacter}", _step(1, "docx"))
    title = names.stem(step_order=1, output_type="docx")

    blob, _ = await default_document_render_service().render_document(
        "Text", "docx", step_order=1, title=title
    )

    assert Document(io.BytesIO(blob)).core_properties.title == "Möte 2026-09-23"


def _own(
    step_order: int, output_type: str, file_name: str, name: str | None = None
) -> RuntimeStep:
    return replace(
        _step(step_order, output_type, name),
        deliverable=FlowStepDeliverable(label=name or "Dokument", file_name=file_name),
    )


def _own_names(
    *steps: RuntimeStep, form_values: dict[str, object] | None = None
) -> GeneratedFileNames:
    return GeneratedFileNames.for_run(
        flow_name="Möte",
        steps=steps,
        run_created_at=RUN_CREATED_AT,
        form_values=form_values or {},
    )


def test_an_own_file_name_takes_the_place_of_the_flows() -> None:
    names = _own_names(
        _own(1, "docx", "Standup {{ flow_input.Team }}"),
        form_values={"Team": "Eneo"},
    )

    assert names.name(step_order=1, output_type="docx") == (
        "Standup Eneo 2026-09-23.docx"
    )


def test_an_own_name_replaces_the_step_name_beside_other_documents() -> None:
    names = _own_names(
        _own(1, "pdf", "Brukarversion", "Skapa PDF"), _step(2, "pdf", "Slutversion")
    )

    assert names.name(step_order=1, output_type="pdf") == (
        "Brukarversion 2026-09-23.pdf"
    )
    assert names.name(step_order=2, output_type="pdf") == (
        "Möte Slutversion 2026-09-23.pdf"
    )


def test_two_equal_own_names_are_numbered() -> None:
    names = _own_names(_own(1, "pdf", "Protokoll"), _own(2, "pdf", "protokoll"))

    assert names.name(step_order=1, output_type="pdf") == (
        "Protokoll Steg 1 2026-09-23.pdf"
    )
    assert names.name(step_order=2, output_type="pdf") == (
        "protokoll Steg 2 2026-09-23.pdf"
    )


def test_an_own_name_equal_to_a_default_name_is_numbered() -> None:
    names = _own_names(_own(1, "docx", "Möte Beslut"), _step(2, "docx", "Beslut"))

    assert names.name(step_order=1, output_type="docx") == (
        "Möte Beslut Steg 1 2026-09-23.docx"
    )
    assert names.name(step_order=2, output_type="docx") == (
        "Möte Beslut Steg 2 2026-09-23.docx"
    )


def test_a_long_own_name_is_cut_to_255_bytes() -> None:
    names = _own_names(
        _own(1, "pdf", "ö{{ flow_input.Text }}"), form_values={"Text": "å" * 400}
    )

    name = names.name(step_order=1, output_type="pdf")

    assert len(name.encode("utf-8")) <= MAX_FILE_NAME_BYTES
    assert name.endswith(" 2026-09-23.pdf")
    assert name.startswith("öåå")


@pytest.mark.parametrize(
    ("file_name", "form_values"),
    [
        ("{{ flow_input.Team }}", {}),
        ("{{ flow_input.Team }}", {"Team": ""}),
        ("{{ flow_input.Team }}", {"Team": "  "}),
        ("{{ flow_input.Team }}", {"Team": None}),
        ("{{ flow_input.Team }}", {"Team": {"name": "Eneo"}}),
        ("{{ flow_input.Team }}", {"Team": "///"}),
        ("{{ step_1.output }}", {}),
        ("{{ datum }}", {}),
        ("{{ flow_input.Team", {"Team": "Eneo"}),
    ],
)
def test_an_own_name_that_holds_nothing_falls_back_to_its_label(
    file_name: str, form_values: dict[str, object]
) -> None:
    names = _own_names(_own(1, "pdf", file_name, "Protokoll"), form_values=form_values)

    assert names.name(step_order=1, output_type="pdf") == "Protokoll 2026-09-23.pdf"


def test_a_label_that_holds_nothing_falls_back_to_neutral_words() -> None:
    names = _own_names(_own(1, "pdf", "{{ flow_input.Team }}", "///"))

    assert names.name(step_order=1, output_type="pdf") == "Dokument 2026-09-23.pdf"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "Möte 0"),
        (2.5, "Möte 2.5"),
        (True, "Möte"),
        (False, "Möte"),
        (float("nan"), "Möte"),
        (float("inf"), "Möte"),
        (["Anna", "", "Bo"], "Möte Anna, Bo"),
        (("Anna", 3), "Möte Anna, 3"),
        (["Anna", True, None, {"a": 1}, ["x"]], "Möte Anna"),
        ([], "Möte"),
    ],
)
def test_a_form_value_is_written_as_text(value: object, expected: str) -> None:
    names = _own_names(
        _own(1, "pdf", "Möte {{ flow_input.Val }}"), form_values={"Val": value}
    )

    assert names.name(step_order=1, output_type="pdf") == f"{expected} 2026-09-23.pdf"


def test_a_number_too_long_to_write_leaves_the_name_as_before() -> None:
    names = _own_names(
        _own(1, "pdf", "Möte {{ flow_input.Val }}"), form_values={"Val": 10**5000}
    )

    assert names.name(step_order=1, output_type="pdf") == "Möte 2026-09-23.pdf"


def test_a_field_name_with_spaces_and_swedish_letters_is_read() -> None:
    names = _own_names(
        _own(1, "pdf", "{{ flow_input.Mötets namn }}"),
        form_values={"Mötets namn": "Årsmöte"},
    )

    assert names.name(step_order=1, output_type="pdf") == "Årsmöte 2026-09-23.pdf"


def test_characters_a_file_cannot_hold_leave_a_form_value() -> None:
    names = _own_names(
        _own(1, "pdf", "Möte {{ flow_input.Val }}"),
        form_values={"Val": 'a\r\nb "c"/d {{ e }}\u0000‮f'},
    )

    assert names.name(step_order=1, output_type="pdf") == (
        "Möte a b c d {{ e }} f 2026-09-23.pdf"
    )


def test_names_do_not_depend_on_the_order_they_are_asked_in() -> None:
    steps = (
        _own(1, "pdf", "Protokoll {{ flow_input.Team }}"),
        _own(2, "pdf", "Protokoll {{ flow_input.Team }}"),
        _step(3, "pdf", "Slut"),
    )
    form_values: dict[str, object] = {"Team": "Eneo"}
    first = _own_names(*steps, form_values=form_values)
    second = _own_names(*steps, form_values=form_values)

    forward = [first.name(step_order=order, output_type="pdf") for order in (1, 2, 3)]
    backward = [second.name(step_order=order, output_type="pdf") for order in (3, 2, 1)]

    assert forward == backward[::-1]
    assert forward[0] == "Protokoll Eneo Steg 1 2026-09-23.pdf"


def test_a_retry_in_the_run_gets_the_same_name() -> None:
    steps = (_own(1, "docx", "Standup {{ flow_input.Team }}"),)

    first = _own_names(*steps, form_values={"Team": "Eneo"})
    retried = _own_names(*steps, form_values={"Team": "Eneo"})

    assert first.name(step_order=1, output_type="docx") == retried.name(
        step_order=1, output_type="docx"
    )


SECRET_MARKER = "MARKER7f3a"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_token", SECRET_MARKER),
        ("Team", f"token={SECRET_MARKER}"),
        ("Team", f"Bearer {SECRET_MARKER}{SECRET_MARKER}{SECRET_MARKER}"),
        ("Team", f"https://user:{SECRET_MARKER}@example.com/"),
    ],
)
def test_a_value_masking_would_change_never_reaches_a_name(
    field: str, value: str
) -> None:
    names = _own_names(
        _own(1, "pdf", "Möte {{ flow_input.%s }}" % field),
        form_values={field: value},
    )

    assert redact_string(value, key=field) != value
    assert SECRET_MARKER not in names.name(step_order=1, output_type="pdf")
    assert SECRET_MARKER not in names.stem(step_order=1, output_type="pdf")


def test_a_clean_value_that_completes_a_credential_never_reaches_a_name() -> None:
    # Each value is clean on its own; with the fixed text around it, the name
    # reads as a credential.
    names = _own_names(
        _own(1, "pdf", "token={{ flow_input.Team }}", "Protokoll"),
        form_values={"Team": SECRET_MARKER},
    )

    assert redact_string(SECRET_MARKER, key="Team") == SECRET_MARKER
    assert names.name(step_order=1, output_type="pdf") == "Protokoll 2026-09-23.pdf"


@pytest.mark.parametrize(
    ("file_name", "value"),
    [
        # Masked as written; cleaning would turn the separator into a space.
        ("password:{{ flow_input.Team }}", SECRET_MARKER),
        # Clean as written; cleaning makes them a credential.
        ("{{ flow_input.Team }}", f"Bearer/{SECRET_MARKER}"),
        ("{{ flow_input.Team }}", f"password\u200b={SECRET_MARKER}"),
    ],
)
def test_a_name_masking_would_change_before_or_after_cleaning_takes_the_label(
    file_name: str, value: str
) -> None:
    # The run's own name can be the same form value; the label is fixed text.
    names = GeneratedFileNames.for_run(
        flow_name="Möte",
        steps=(_own(1, "pdf", file_name, "Protokoll"),),
        run_created_at=RUN_CREATED_AT,
        form_values={"Team": value},
        run_label=value,
    )

    assert names.name(step_order=1, output_type="pdf") == "Protokoll 2026-09-23.pdf"
    assert names.stem(step_order=1, output_type="pdf") == "Protokoll 2026-09-23"


def test_a_credential_starting_before_the_length_limit_takes_the_label() -> None:
    # Each value is clean on its own; the cut at 255 bytes would keep only
    # "toke" of the credential they make, which masking leaves alone.
    form_values: dict[str, object] = {"A": "x" * 250, "B": SECRET_MARKER}
    names = _own_names(
        _own(1, "pdf", "{{ flow_input.A }} token={{ flow_input.B }}", "Protokoll"),
        form_values=form_values,
    )

    for field, value in form_values.items():
        assert redact_string(str(value), key=field) == value
    assert len(" ".join(["x" * 250, "toke"]).encode("utf-8")) == MAX_FILE_NAME_BYTES
    assert names.name(step_order=1, output_type="pdf") == "Protokoll 2026-09-23.pdf"


def test_a_megabyte_form_value_is_named_in_well_under_a_second() -> None:
    # The masking patterns take time quadratic in a long run of word
    # characters; only the start of a value can reach a name.
    value = "token" * 200_000
    steps = (_own(1, "pdf", "Möte {{ flow_input.Team }} {{ flow_input.Team }}"),)

    started = time.perf_counter()
    names = _own_names(*steps, form_values={"Team": value})
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    name = names.name(step_order=1, output_type="pdf")
    assert name.startswith("Möte tokentoken")
    assert len(name.encode("utf-8")) <= MAX_FILE_NAME_BYTES

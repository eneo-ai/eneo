from __future__ import annotations

import pytest

from eneo.flows.domain.one_line_text import one_line
from eneo.flows.domain.step_deliverable import (
    FlowStepDeliverable,
    file_name_expressions,
    form_field_read_by,
    parse_flow_step_deliverable,
)
from eneo.flows.enums import (
    FlowOutputDelivery,
    FlowOutputMode,
    FlowOutputType,
    final_output_delivery,
    step_delivers_artifact,
)


@pytest.mark.parametrize("output_mode", list(FlowOutputMode))
@pytest.mark.parametrize("output_type", list(FlowOutputType))
def test_a_step_delivers_an_artifact_exactly_when_its_output_is_a_file(
    output_mode: FlowOutputMode, output_type: FlowOutputType
) -> None:
    expected = (
        final_output_delivery(output_type=output_type, output_mode=output_mode)
        is FlowOutputDelivery.ARTIFACT
    )

    assert (
        step_delivers_artifact(output_type=output_type, output_mode=output_mode)
        is expected
    )
    assert (
        step_delivers_artifact(
            output_type=output_type.value, output_mode=output_mode.value
        )
        is expected
    )


def test_a_pass_through_document_and_an_http_post_document_differ() -> None:
    assert step_delivers_artifact(
        output_type=FlowOutputType.DOCX, output_mode=FlowOutputMode.PASS_THROUGH
    )
    assert not step_delivers_artifact(
        output_type=FlowOutputType.DOCX, output_mode=FlowOutputMode.HTTP_POST
    )
    assert not step_delivers_artifact(
        output_type=FlowOutputType.TEXT, output_mode=FlowOutputMode.COMPOSE_TEXT
    )


def test_one_line_takes_its_bound() -> None:
    assert one_line("a" * 121) is None
    assert one_line("a" * 121, max_chars=200) == "a" * 121
    assert one_line("a" * 201, max_chars=200) is None


def test_a_deliverable_reads_its_label_and_file_name() -> None:
    deliverable = parse_flow_step_deliverable(
        {
            "deliverable": {
                "label": "Standup Eneo",
                "file_name": "Standup {{ flow_input.Team }}",
            },
            "citation_mode": "off",
        }
    )

    assert deliverable == FlowStepDeliverable(
        label="Standup Eneo", file_name="Standup {{ flow_input.Team }}"
    )


@pytest.mark.parametrize("output_config", [None, {}, {"citation_mode": "off"}, []])
def test_a_config_without_the_key_has_no_deliverable(output_config: object) -> None:
    assert parse_flow_step_deliverable(output_config) is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "Standup",
        {},
        {"file_name": "Standup"},
        {"label": ""},
        {"label": " Standup"},
        {"label": "Standup "},
        {"label": "Standup  Eneo"},
        {"label": "Standup\nEneo"},
        {"label": "Standup\u0000"},
        {"label": "a" * 121},
        {"label": 5},
        {"label": "Standup", "file_name": 5},
        {"label": "Standup", "file_name": ""},
        {"label": "Standup", "file_name": "Standup\r\n"},
        {"label": "Standup", "file_name": "a" * 201},
        {"label": "Standup", "kind": "artifact"},
    ],
)
def test_a_malformed_deliverable_is_refused(raw: object) -> None:
    with pytest.raises(ValueError, match="output_config.deliverable"):
        parse_flow_step_deliverable({"deliverable": raw})


def test_a_file_name_may_be_200_characters() -> None:
    deliverable = parse_flow_step_deliverable(
        {"deliverable": {"label": "Standup", "file_name": "a" * 200}}
    )

    assert deliverable is not None
    assert deliverable.file_name == "a" * 200


@pytest.mark.parametrize(
    ("expression", "field"),
    [
        ("flow_input.Team", "Team"),
        ("flow_input.Mötets namn", "Mötets namn"),
        (" flow_input . Team ", "Team"),
        ("step_2.output.text", None),
        ("datum", None),
        ("flow.input.x", None),
        ("flow_input", None),
        ("flow_input.", None),
        ("flow_input.a.b", None),
    ],
)
def test_a_file_name_expression_reads_one_form_field_at_most(
    expression: str, field: str | None
) -> None:
    assert form_field_read_by(expression) == field


def test_a_file_name_lists_each_expression_it_reads() -> None:
    assert file_name_expressions(
        "{{ flow_input.Team }} {{datum}} {{ flow_input.Mötets namn }}"
    ) == ["flow_input.Team", "datum", "flow_input.Mötets namn"]
    assert file_name_expressions("Standup") == []


@pytest.mark.parametrize(
    "file_name",
    ["Standup {{ flow_input.Team", "Standup }}", "{{ {{ flow_input.Team }}"],
)
def test_a_file_name_with_a_stray_brace_reads_nothing(file_name: str) -> None:
    assert file_name_expressions(file_name) is None

from __future__ import annotations

import pytest

from eneo.flows.flow_run_input_envelope import FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
from eneo.flows.flow_variable_definitions import (
    FLOW_INPUT_ALIASES,
    RESERVED_FORM_FIELD_INPUT_KEYS,
    RESERVED_RUNTIME_VARIABLES,
    RUNTIME_VARIABLE_SHAPES,
    STEP_INPUT_KEY_SHAPES,
    FlowRunInput,
    VariableShape,
    flow_input_alias_source,
    is_reserved_form_field_input_key,
    reads_unreceived_run_input,
    unreceived_flow_input_aliases,
    variable_path_segments,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import TypedIOValidationException


def test_runtime_variables_include_datum() -> None:
    assert "datum" in RESERVED_RUNTIME_VARIABLES
    assert RUNTIME_VARIABLE_SHAPES["datum"] is VariableShape.SCALAR


def test_step_input_key_shapes_are_explicit() -> None:
    assert STEP_INPUT_KEY_SHAPES["text"] is VariableShape.SCALAR
    assert STEP_INPUT_KEY_SHAPES["file_ids"] is VariableShape.SEQUENCE
    assert STEP_INPUT_KEY_SHAPES["input_format"] is VariableShape.SCALAR


def test_reserved_form_field_input_keys_include_run_envelope_keys() -> None:
    assert FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS <= RESERVED_FORM_FIELD_INPUT_KEYS
    assert is_reserved_form_field_input_key("expected_flow_version") is True
    assert is_reserved_form_field_input_key("step_inputs") is True
    assert is_reserved_form_field_input_key("case_id") is False


# The alias names are the resolver's: a run of each shape defines exactly the
# aliases the variable owner says that shape receives, so publish and the
# Builder refuse the reads the run would fail on and no others.
@pytest.mark.parametrize(
    ("run_input", "payload", "defined"),
    [
        pytest.param(
            FlowRunInput(form_fields=True),
            {"diarienummer": "2026-1", "namn": "Ada"},
            set(),
            id="form-fields",
        ),
        pytest.param(FlowRunInput(runtime_files=True), {}, set(), id="uploaded-files"),
        pytest.param(
            FlowRunInput(form_fields=True, runtime_files=True),
            {"diarienummer": "2026-1"},
            set(),
            id="form-fields-and-files",
        ),
        pytest.param(
            FlowRunInput(),
            {"text": "Hej", "json": {"a": 1}},
            {"indata_text", "indata_json"},
            id="free-text",
        ),
        pytest.param(
            FlowRunInput(),
            {"text": "Hej", "structured": [1]},
            {"indata_text", "indata_json"},
            id="free-text-structured",
        ),
    ],
)
def test_the_resolver_defines_exactly_the_aliases_the_run_input_receives(
    run_input: FlowRunInput, payload: dict[str, object], defined: set[str]
) -> None:
    context = FlowVariableResolver().build_context(payload, [])

    assert FLOW_INPUT_ALIASES & set(context) == defined
    assert FLOW_INPUT_ALIASES - unreceived_flow_input_aliases(run_input) == defined


def test_every_run_input_alias_is_a_reserved_runtime_variable() -> None:
    assert FLOW_INPUT_ALIASES == {"indata_text", "indata_json"}
    assert FLOW_INPUT_ALIASES <= RESERVED_RUNTIME_VARIABLES


@pytest.mark.parametrize(
    ("alias", "payload", "source"),
    [
        ("indata_text", {"text": "Hej"}, ("text", "Hej")),
        ("indata_text", {"text": "  "}, None),
        ("indata_text", {"text": 5}, None),
        ("indata_text", {"json": {"a": 1}}, None),
        ("indata_json", {"json": {"a": 1}}, ("json", {"a": 1})),
        ("indata_json", {"json": None, "structured": [1]}, ("structured", [1])),
        ("indata_json", {"json": {"a": 1}, "structured": [1]}, ("json", {"a": 1})),
        # A present but unusable json value does not fall back to structured.
        ("indata_json", {"json": "x", "structured": {"a": 1}}, None),
        ("indata_json", {"text": "Hej"}, None),
    ],
)
def test_a_run_defines_an_alias_only_from_a_usable_payload_value(
    alias: str, payload: dict[str, object], source: tuple[str, object] | None
) -> None:
    assert flow_input_alias_source(alias, payload) == source


@pytest.mark.parametrize(
    ("expression", "reads_unreceived"),
    [
        ("indata_text", True),
        ("indata_json.rader", True),
        ("flow_input.text", True),
        ("flow_input.json.rader", True),
        (" flow_input . structured ", True),
        ("flow.input.text", True),
        ("flow . input . text", True),
        ("flow.input . json . 0", True),
        ("flow_input. text", True),
        ("flow_input", False),
        ("flow.input", False),
        ("flow . input . diarienummer", False),
        ("flow_input.diarienummer", False),
        ("flow.input.diarienummer", False),
        ("flow_input.texten", False),
        ("step_input.text", False),
        ("datum", False),
    ],
)
def test_a_form_run_carries_no_run_text_whichever_way_it_is_read(
    expression: str, reads_unreceived: bool
) -> None:
    assert reads_unreceived_run_input(expression, FlowRunInput(form_fields=True)) is (
        reads_unreceived
    )
    assert reads_unreceived_run_input(expression, FlowRunInput(runtime_files=True)) is (
        reads_unreceived
    )
    assert not reads_unreceived_run_input(expression, FlowRunInput())


def test_the_resolver_and_the_owner_walk_a_path_by_the_same_segments() -> None:
    assert variable_path_segments("flow . input.x") == ["flow", "input", "x"]
    assert variable_path_segments("a..b") == ["a", "", "b"]
    context = FlowVariableResolver().build_context({"text": "hej", "namn": "Ada"}, [])
    assert FlowVariableResolver().resolve_path(context, "flow . input . text") == "hej"


@pytest.mark.parametrize(
    "expression",
    [
        "indata_text",
        "indata_json.a",
        "flow_input.text",
        "flow_input . json . a",
        "flow_input.structured",
        "flow.input.text",
        "flow . input . json",
        "flow.input . structured",
        "flow_input",
        "flow_input.namn",
        "flow . input . namn",
        "flow.input",
        "datum",
        "step_input.text",
    ],
)
def test_a_form_run_refuses_exactly_the_reads_only_a_text_payload_resolves(
    expression: str,
) -> None:
    """The owner's refusal agrees with what the resolver resolves: a read is
    refused for a form run iff it resolves only when the payload carries the
    free-text keys."""

    resolver = FlowVariableResolver()

    def resolves(payload: dict[str, object]) -> bool:
        context = resolver.build_context(payload, [])
        try:
            resolver.resolve_path(context, expression)
        except TypedIOValidationException:
            return False
        return True

    form_payload = {"namn": "Ada"}
    text_payload = {**form_payload, "text": "hej", "json": {"a": 1}, "structured": [1]}
    only_text_resolves = resolves(text_payload) and not resolves(form_payload)

    assert reads_unreceived_run_input(expression, FlowRunInput(form_fields=True)) is (
        only_text_resolves
    )

"""A step whose input source is ``tool``: what save, publish, the stored
definition, cleaning and the graph accept and refuse."""

from __future__ import annotations

import importlib.util
import io
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.flows.api.flow_graph import build_graph_from_steps
from eneo.flows.application.flow_run_export_json import _build_input_lineage
from eneo.flows.domain.flow import FlowStep, FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.flow_step_validation import FlowStepValidationError
from eneo.flows.domain.step_config import clean_inactive_step_config
from eneo.flows.enums import FLOW_INPUT_SOURCE_VALUES
from eneo.flows.flow_validators import validate_steps
from eneo.flows.runtime.step_definition_parser import parse_runtime_steps
from eneo.flows.step_lineage import build_step_ref_mapping
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import BadRequestException, TypedIOValidationException
from tests.unittests.flows.test_step_definition_parser import (
    _definition,
    _step_snapshot,
)

_INVALID_CONFIG = "typed_io_tool_invalid_config"
_NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)
_IDS = {"mcp_server_id": str(uuid4()), "tool_id": str(uuid4())}
_BOUND = {**_IDS, "arguments": {"days": "{{step_1.output.structured.days}}"}}
# What publish adds to the configuration of a published step.
_PIN = {"tool_name": "lookup_case", "input_schema_sha256": "0" * 64}
# What the first step declares as its result, and the run form of the flow.
_DAYS_CONTRACT: dict[str, object] = {
    "type": "object",
    "properties": {"days": {"type": "array", "items": {"type": "string"}}},
}
_CASE_FORM: dict[str, object] = {
    "form_schema": {"fields": [{"name": "case_id", "type": "text"}]}
}

# Every shape of input_config that is not a tool configuration, with the
# field the refusal names.
_MALFORMED = [
    pytest.param(None, "input_config.tool", id="config-absent"),
    pytest.param({}, "input_config.tool", id="tool-absent"),
    pytest.param({"tool": None}, "input_config.tool", id="tool-null"),
    pytest.param({"tool": [_IDS]}, "input_config.tool", id="tool-list"),
    pytest.param({"tool": "search"}, "input_config.tool", id="tool-string"),
    pytest.param(
        {"tool": {**_IDS, "url": "https://example.org"}},
        "input_config.tool.url",
        id="unknown-key",
    ),
    pytest.param(
        {"tool": {**_IDS, "mcp_server_id": "not-a-uuid"}},
        "input_config.tool.mcp_server_id",
        id="bad-server-id",
    ),
    pytest.param(
        {"tool": {"mcp_server_id": _IDS["mcp_server_id"]}},
        "input_config.tool.tool_id",
        id="tool-id-absent",
    ),
    pytest.param(
        {"tool": {**_IDS, "tool_id": 7}}, "input_config.tool.tool_id", id="bad-tool-id"
    ),
    pytest.param(
        {"tool": {**_IDS, "arguments": ["positional"]}},
        "input_config.tool.arguments",
        id="arguments-list",
    ),
    pytest.param(
        {"tool": {**_IDS, "arguments": None}},
        "input_config.tool.arguments",
        id="arguments-null",
    ),
]


def _pinned(input_config: object) -> object:
    """The configuration with the pin beside whatever its tool object holds."""
    tool = input_config.get("tool") if isinstance(input_config, dict) else None
    if not isinstance(tool, dict):
        return input_config
    return {"tool": {**tool, **_PIN}}


def _step(step_order: int = 1, **updates: object) -> FlowStep:
    return FlowStep.model_validate(
        {
            "id": uuid4(),
            "assistant_id": uuid4(),
            "step_order": step_order,
            "user_description": f"Step {step_order}",
            "input_source": "flow_input" if step_order == 1 else "previous_step",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "json",
            **updates,
        }
    )


def _tool_step(step_order: int = 1, **updates: object) -> FlowStep:
    return _step(
        step_order,
        **{"input_source": "tool", "input_config": {"tool": _IDS}, **updates},
    )


def _refusal(
    steps: list[FlowStep],
    *,
    metadata_json: dict[str, object] | None = None,
    publish: bool = False,
) -> FlowStepValidationError:
    with pytest.raises(FlowStepValidationError) as refused:
        validate_steps(
            steps,
            metadata_json=metadata_json,
            require_complete_template_fill_config=publish,
        )
    return refused.value


@pytest.mark.parametrize("input_type", ["text", "json"])
def test_a_tool_step_with_fixed_and_bound_arguments_is_accepted(
    input_type: str,
) -> None:
    # Kills the mutants that refuse the source itself, a fixed argument of any
    # JSON type, or one whole reference as an argument.
    arguments = {"view": "daily", "limit": 10, "tags": ["a"], **_BOUND["arguments"]}
    steps = [
        _step(1, output_contract=_DAYS_CONTRACT),
        _tool_step(
            2,
            input_type=input_type,
            input_config={"tool": {**_IDS, "arguments": arguments}},
        ),
    ]

    validate_steps(steps)
    validate_steps(steps, require_complete_template_fill_config=True)


@pytest.mark.parametrize(("input_config", "field"), _MALFORMED)
def test_save_refuses_an_input_config_that_is_not_a_tool_configuration(
    input_config: dict[str, object] | None, field: str
) -> None:
    # Kills the mutant that saves a tool step without checking its
    # configuration (the validator not called, or a missing/unknown key let by).
    refused = _refusal([_tool_step(input_config=input_config)])

    assert (refused.code, refused.step_order) == (_INVALID_CONFIG, 1)
    assert (refused.context or {})["field"] == field


@pytest.mark.parametrize(
    ("argument", "problem"),
    [
        ("select * from t where day = '{{step_1.output.text}}'", "composed_text"),
        ("{{step_1.output.text}} {{flow_input.to}}", "composed_text"),
        ({"day": "{{step_1.output.text}}"}, "nested_reference"),
        ([["x {{step_1.output.text}}"]], "nested_reference"),
    ],
)
def test_save_refuses_an_argument_that_composes_run_data(
    argument: object, problem: str
) -> None:
    # Kills the mutant that parses the configuration but never applies the
    # argument rule: text built from run data would reach the tool.
    config = {"tool": {**_IDS, "arguments": {"query": argument}}}

    refused = _refusal([_step(1), _tool_step(2, input_config=config)])

    assert (refused.code, refused.step_order) == (_INVALID_CONFIG, 2)
    assert refused.context is not None
    assert {key: refused.context[key] for key in ("field", "argument", "problem")} == {
        "field": "input_config.tool.arguments.query",
        "argument": "query",
        "problem": problem,
    }
    assert "select" not in str(refused)


def test_save_refuses_the_keys_only_publish_writes() -> None:
    # Kills the mutant that lets an author store the pin (the pin fields on
    # the editable model): a saved name or fingerprint would stand in for
    # what publish reads from the server's own tool row.
    refused = _refusal([_tool_step(input_config={"tool": {**_IDS, **_PIN}})])

    assert (refused.code, refused.step_order) == (_INVALID_CONFIG, 1)
    assert (refused.context or {})["field"] == "input_config.tool.tool_name"


def _flow_reading(reference: str, tool_step_order: int = 3) -> list[FlowStep]:
    """Three steps, the first with a declared result; the step at
    ``tool_step_order`` is a tool step whose argument ``q`` is the reference."""
    steps = [_step(1, output_contract=_DAYS_CONTRACT), _step(2), _step(3)]
    config = {"tool": {**_IDS, "arguments": {"q": f"{{{{ {reference} }}}}"}}}
    steps[tool_step_order - 1] = _tool_step(tool_step_order, input_config=config)
    return steps


@pytest.mark.parametrize(
    ("step_order", "reference"),
    [
        pytest.param(2, "step_4.output.text", id="no-such-step"),
        pytest.param(2, "step_2.output.text", id="own-step"),
        pytest.param(2, "step_3.output.structured.days", id="later-step"),
        pytest.param(2, "Step 3", id="later-step-by-name"),
        pytest.param(1, "föregående_steg", id="previous-of-the-first-step"),
    ],
)
def test_publish_refuses_an_argument_that_reads_a_step_that_has_not_run(
    step_order: int, reference: str
) -> None:
    # Kills the mutants that judge an argument's form but not which step it
    # names, or that leave ``föregående_steg`` on the first step to the rule
    # for runtime variables: every run would fail on a value no earlier step
    # produced.
    refused = _refusal(
        _flow_reading(reference, step_order), metadata_json=_CASE_FORM, publish=True
    )

    assert (refused.code, refused.step_order) == (_INVALID_CONFIG, step_order)
    assert refused.context == {
        "field": "input_config.tool.arguments.q",
        "argument": "q",
        "problem": "step_not_earlier",
        "reference": reference,
        "issue_code": "flow_step_invalid",
        "step_order": step_order,
    }


@pytest.mark.parametrize(
    "reference",
    [
        # No name, a name the flow does not declare, an alias no step has.
        "",
        "nonsense",
        "step_01.output",
        "flow_input.nope",
        # A path the named value does not declare.
        "step_1.output.structured.nope.deeper",
        "step_2.output.structured.days",
        "step_1.output.nope",
        "step_1.input.text",
        "flow_input.case_id.deeper",
        "case_id.deeper",
        "flow.nope",
        "datum.year",
        # The result envelope of a step, which no contract declares.
        "step_1",
        "step_1.output",
        # The step's own input does not exist when its arguments are read.
        "step_input",
        "step_input.text",
    ],
)
def test_publish_refuses_an_argument_that_names_no_value_of_the_run(
    reference: str,
) -> None:
    # Kills the mutant that publishes a tool argument without asking the rule
    # for one whole reference (``whole_reference_value``): the version would
    # be pinned and every run would fail on the reference at the step.
    steps = _flow_reading(reference)

    refused = _refusal(steps, metadata_json=_CASE_FORM, publish=True)

    assert (refused.code, refused.step_order) == (_INVALID_CONFIG, 3)
    assert refused.context == {
        "field": "input_config.tool.arguments.q",
        "argument": "q",
        "problem": "unknown_reference",
        "reference": reference,
        "issue_code": "flow_step_invalid",
        "step_order": 3,
    }
    # A save does not know the run form, so it judges no reference.
    validate_steps(steps, metadata_json=_CASE_FORM)


@pytest.mark.parametrize(
    ("reference", "resolves"),
    [
        ("Step 1", True),
        ("Step 1.output.text", False),
        ("Step 1.status", False),
        ("Step 1.output.structured.days", False),
    ],
)
def test_publish_judges_a_reference_by_step_name_as_the_run_resolves_it(
    reference: str, resolves: bool
) -> None:
    # Kills the mutant that judges a step's name like its ``step_N`` alias:
    # the run binds the name to the step's text and to nothing below it, so
    # publish would pin a path every run fails on and refuse the bare name.
    steps = _flow_reading(reference)
    results = [
        FlowStepResult(
            id=uuid4(),
            flow_run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            step_id=uuid4(),
            step_order=order,
            status=FlowStepResultStatus.COMPLETED,
            current_attempt_no=1,
            output_payload_json={"text": f"text {order}", "structured": {"days": []}},
            created_at=_NOW,
            updated_at=_NOW,
        )
        for order in (1, 2)
    ]
    names = {step.step_order: step.user_description or "" for step in steps}
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence(
        {"case_id": "A-1"},
        results,
        current_step_order=3,
        step_names_by_order=names,
        step_ref_mapping=build_step_ref_mapping(
            {"step_order": order, "user_description": name}
            for order, name in names.items()
        ),
    )

    def publish() -> None:
        validate_steps(
            steps, metadata_json=_CASE_FORM, require_complete_template_fill_config=True
        )

    def run() -> object:
        return resolver.resolve_reference_with_evidence(
            reference, context, binding_ref="tool.arguments.q"
        )[0]

    if resolves:
        publish()
        assert run() == "text 1"
    else:
        with pytest.raises(FlowStepValidationError) as refused:
            publish()
        assert (refused.value.context or {})["problem"] == "unknown_reference"
        with pytest.raises(TypedIOValidationException):
            run()


@pytest.mark.parametrize(
    "reference",
    [
        "flow_input.case_id",
        "case_id",
        "flow_input",
        "datum",
        "step_1.output.structured.days",
        "step_1.output.structured",
        "step_1.status",
        "step_2.output.text",
        "föregående_steg",
    ],
)
def test_a_bound_argument_reads_the_run_form_or_an_earlier_step(
    reference: str,
) -> None:
    # Kills the mutants that refuse every reference to a step, a read of the
    # run form, a whole declared result, or a value that is not a scalar (the
    # DOCX rule's own requirement) together with the unreadable ones.
    steps = _flow_reading(reference)

    validate_steps(steps, metadata_json=_CASE_FORM)
    validate_steps(
        steps, metadata_json=_CASE_FORM, require_complete_template_fill_config=True
    )


def test_a_tool_step_reads_text_or_json_only() -> None:
    # Kills the mutant that copies the HTTP rule (which bans the four file
    # types and lets ``any`` through): no other rule refuses this step.
    refused = _refusal([_tool_step(input_type="any")])

    assert refused.code == _INVALID_CONFIG
    assert (refused.context or {})["field"] == "input_type"


def test_a_tool_step_cannot_use_a_mode_that_never_reads_its_input() -> None:
    # Kills the mutant that lets a tool step fill a DOCX template: that mode
    # builds its result from its bindings, so the step would complete without
    # the tool ever being called.
    refused = _refusal(
        [
            _step(1),
            _tool_step(2, output_mode="template_fill", output_type="docx"),
        ]
    )

    assert (refused.code, refused.step_order) == (_INVALID_CONFIG, 2)
    assert (refused.context or {})["field"] == "output_mode"
    assert str(refused) == (
        "Step 2: output_mode 'template_fill' does not read the step's input, so "
        "it cannot be used with input_source 'tool'."
    )


def test_a_tool_step_cannot_also_take_uploaded_files() -> None:
    # Kills the mutant that lets a tool step ask the run for files: a JSON
    # step would drop the upload's text and still record it as read.
    config = {"tool": _IDS, "runtime_input": {"enabled": True}}

    refused = _refusal([_tool_step(input_config=config)])

    assert (refused.code, refused.step_order) == (_INVALID_CONFIG, 1)
    assert (refused.context or {})["field"] == "input_config.runtime_input"
    validate_steps(
        [_tool_step(input_config={"tool": _IDS, "runtime_input": {"enabled": False}})]
    )


def test_a_tool_step_cannot_also_have_underlag() -> None:
    # Kills the mutant that leaves the combination rule on http_get alone:
    # underlag would silently replace the tool's answer.
    refused = _refusal(
        [
            _step(1),
            _tool_step(2, input_bindings={"question": "{{ step_1.output.text }}"}),
        ]
    )

    assert refused.code == "typed_io_invalid_input_source_combination"
    assert "'tool'" in str(refused)


def test_publish_refuses_a_tool_argument_that_reads_run_text_of_a_form_run() -> None:
    # Kills the mutant that does not show the tool's bound arguments to the
    # run-form check: the argument would read a value no run supplies.
    config = {"tool": {**_IDS, "arguments": {"q": "{{ flow_input.text }}"}}}
    form: dict[str, object] = {
        "form_schema": {"fields": [{"name": "case_id", "type": "text"}]}
    }

    refused = _refusal(
        [_tool_step(input_config=config)], metadata_json=form, publish=True
    )

    assert refused.code == "flow_input_alias_not_received"
    assert refused.context == {
        "field": "input_config.tool.arguments.q",
        "reference": "flow_input.text",
        "issue_code": "flow_input_alias_not_received",
        "step_order": 1,
    }
    validate_steps(
        [_tool_step(input_config=config)], require_complete_template_fill_config=True
    )


def test_a_stored_definition_with_a_tool_step_parses_with_its_configuration() -> None:
    # Kills the mutant that drops or rewrites the configuration on the way
    # into the runtime step (the read at run time would have nothing to call).
    config = {"tool": {**_BOUND, **_PIN}, "runtime_input": {"enabled": False}}

    step = parse_runtime_steps(
        _definition(_step_snapshot(input_source="tool", input_config=config))
    )[0]

    assert (step.input_source, step.input_config) == ("tool", config)


@pytest.mark.parametrize(
    "input_config",
    [
        "not-an-object",
        *(_pinned(case.values[0]) for case in _MALFORMED),
        pytest.param({"tool": _BOUND}, id="no-pin"),
        pytest.param({"tool": {**_BOUND, "tool_name": "lookup_case"}}, id="no-hash"),
        pytest.param(
            {"tool": {**_BOUND, "input_schema_sha256": "0" * 64}}, id="no-name"
        ),
        # A pin only publish writes: a name, and a SHA-256 as publish spells it.
        pytest.param({"tool": {**_BOUND, **_PIN, "tool_name": ""}}, id="empty-name"),
        pytest.param(
            {"tool": {**_BOUND, **_PIN, "input_schema_sha256": "ZZ"}}, id="no-sha256"
        ),
    ],
)
def test_a_stored_definition_whose_tool_configuration_is_unreadable_is_refused(
    input_config: object,
) -> None:
    # Kills the mutants that treat ``tool`` like the sources without a
    # configuration (a published definition would name no tool) or accept the
    # editable shape: a run would call a tool nothing pinned.
    with pytest.raises(BadRequestException) as refused:
        parse_runtime_steps(
            _definition(_step_snapshot(input_source="tool", input_config=input_config))
        )

    assert refused.value.code == _INVALID_CONFIG
    assert "not-a-uuid" not in str(refused.value)


@pytest.mark.parametrize(
    ("input_source", "kept"),
    [("tool", True), ("flow_input", False), ("http_get", False)],
)
def test_cleaning_keeps_the_tool_configuration_only_on_a_tool_step(
    input_source: str, kept: bool
) -> None:
    # Kills the mutants that strip the configuration of a tool step (it could
    # never be saved) or leave it on a step that changed source (a later
    # switch back would revive a call nobody reviewed).
    other = {"runtime_input": {"enabled": False}}
    step = _step(input_source=input_source, input_config={"tool": _BOUND, **other})

    cleaned = clean_inactive_step_config(step)

    assert cleaned.input_config == ({"tool": _BOUND, **other} if kept else other)


def test_the_graph_draws_a_tool_step_as_fed_from_outside_the_flow() -> None:
    # Kills the mutant that gives a tool step no incoming edge: the graph
    # would show a step that reads nothing.
    step = {
        "step_id": str(uuid4()),
        "step_order": 2,
        "input_source": "tool",
        "input_type": "json",
        "output_type": "text",
        "output_mode": "pass_through",
    }

    _, edges = build_graph_from_steps([step])

    incoming = [edge for edge in edges if edge.target == step["step_id"]]
    assert [(edge.source, edge.kind, edge.style) for edge in incoming] == [
        ("input", "tool", "dashed")
    ]


def _reading_tool_step(step_order: int) -> dict[str, object]:
    """A stored tool step whose arguments read the first step and a form field."""
    arguments = {"days": "{{step_1.output.structured.days}}", "case": "{{case_id}}"}
    return {
        "step_id": str(uuid4()),
        "step_order": step_order,
        "input_source": "tool",
        "input_type": "json",
        "output_type": "text",
        "output_mode": "pass_through",
        "input_config": {"tool": {**_IDS, **_PIN, "arguments": arguments}},
    }


def test_the_graph_draws_the_steps_a_tool_steps_arguments_read() -> None:
    # Kills the mutant that draws a tool step from the run's input alone: what
    # an earlier step produced is sent to the tool's server, and the graph
    # would not show it.
    first, second = (
        {"step_id": str(uuid4()), "step_order": order, "input_source": "flow_input"}
        for order in (1, 2)
    )
    tool = _reading_tool_step(3)

    _, edges = build_graph_from_steps([first, second, tool])

    incoming = [edge for edge in edges if edge.target == tool["step_id"]]
    assert [(edge.source, edge.kind, edge.source_step_order) for edge in incoming] == [
        ("input", "tool", 0),
        (first["step_id"], "tool_arguments", 1),
    ]


def test_the_run_export_reports_the_steps_a_tool_steps_arguments_read() -> None:
    # Kills the mutant that reports a tool step's upstream steps from its
    # input source alone: the export would say the step read no earlier step.
    lineage = _build_input_lineage(
        step=_reading_tool_step(3),
        step_order=3,
        step_ref_mapping={},
        step_labels_by_order={1: "Mätvärden", 2: "Annat", 3: "Hämta"},
        result={},
        max_prior_step_order=3,
    )

    assert lineage["upstream_step_orders"] == [1]
    assert lineage["upstream_step_labels"] == ["Mätvärden"]


def _migration_sql(direction: str) -> str:
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202610121300_allow_tool_input_source.py"
    )
    spec = importlib.util.spec_from_file_location("allow_tool_input_source", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration, direction)()
    return output.getvalue()


def _allowed_sources(sql: str) -> list[str]:
    values = sql.rsplit("input_source IN (", 1)[1].split(")", 1)[0]
    return [value.strip().strip("'") for value in values.split(",")]


def test_the_migration_allows_exactly_the_sources_the_model_allows() -> None:
    # Kills the mutants where the database CHECK and the enum drift apart: a
    # tool step the API accepts would fail on insert, or the downgrade would
    # keep a value the older code cannot read.
    upgrade, downgrade = _migration_sql("upgrade"), _migration_sql("downgrade")

    assert _allowed_sources(upgrade) == list(FLOW_INPUT_SOURCE_VALUES)
    assert _allowed_sources(downgrade) == [
        value for value in FLOW_INPUT_SOURCE_VALUES if value != "tool"
    ]
    # Also the mutants that wait for the table lock without a bound, scan
    # flow_steps under the exclusive lock (a check added without NOT VALID,
    # or validated inside the DDL transaction), or read the database when
    # only the SQL is asked for.
    for sql in (upgrade, downgrade):
        statements = [
            "SET LOCAL lock_timeout = '5s'",
            "DROP CONSTRAINT ck_flow_steps_input_source",
            ") NOT VALID",
            "COMMIT",
            "SET lock_timeout = '5s'",
            "VALIDATE CONSTRAINT ck_flow_steps_input_source",
            "RESET lock_timeout",
        ]
        positions = [sql.index(statement) for statement in statements]
        assert positions == sorted(positions), sql
        assert "count(" not in sql

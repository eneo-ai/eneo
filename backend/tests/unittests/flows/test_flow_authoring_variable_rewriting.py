"""Which saved steps a text reads by alias, and where a saved row is renumbered.

One reader decides both: the head of a `{{ }}` expression is an alias when the
runtime resolver would find a step's result under it. The configuration
columns are read and renumbered only at the strings the runtime interpolates
for the modes the step runs.
"""

from __future__ import annotations

from typing import Any

import pytest

from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_authoring_variable_rewriting import (
    config_alias_reads,
    input_binding_alias_reads,
    renumber_config_aliases,
    rewrite_step_alias_heads,
)
from eneo.flows.step_lineage import ConfigColumn, config_channel


def _reads(text: str) -> list[int]:
    orders: list[int] = []
    rewrite_step_alias_heads(text, lambda order, _: orders.append(order))
    return orders


@pytest.mark.parametrize(
    ("text", "orders"),
    [
        ("{{step_1.output.text}}", [1]),
        ("{{ step_1.output.text }}", [1]),
        ("{{ step_1 }}", [1]),
        ("{{step_1}}", [1]),
        ("{{ step_1 .output }}", [1]),
        ("{{ step_1 }} och {{ step_2.output }}", [1, 2]),
        ("{{ step_10.output }}", [10]),
        ("{{ step_01 }}", []),
        ("{{ step_٢ }}", []),
        ("{{ step_1x }}", []),
        ("{{ form.step_1 }}", []),
        ("{{ föregående_steg }}", []),
        ("step_1 utan klamrar", []),
        ("{{ step_1 ", []),
    ],
)
def test_the_reader_finds_the_heads_the_runtime_resolves(
    text: str, orders: list[int]
) -> None:
    assert _reads(text) == orders


def test_the_reader_hands_the_resolver_the_expression_as_written() -> None:
    seen: list[tuple[int, str]] = []

    rewrite_step_alias_heads(
        "{{ step_2.output.text }} {{step_3}}",
        lambda order, expression: seen.append((order, expression)),
    )

    assert seen == [(2, "step_2.output.text"), (3, "step_3")]


def test_a_head_is_replaced_in_place_and_nothing_else_changes() -> None:
    text = "a {{step_1.output.text}} b {{ step_1 }} c {{ step_2 .x }} d {{ step_5 }}"

    assert (
        rewrite_step_alias_heads(
            text, lambda order, _: {1: "ref_a", 2: "step_9"}.get(order)
        )
        == "a {{ref_a.output.text}} b {{ ref_a }} c {{ step_9 .x }} d {{ step_5 }}"
    )


def _http(**fields: Any) -> dict[str, Any]:
    return {"url": "https://example.test/", "auth": {"mode": "none"}, **fields}


def _channel(
    column: ConfigColumn,
    config: dict[str, Any] | None,
    *,
    input_source: FlowInputSource = FlowInputSource.FLOW_INPUT,
    output_mode: FlowOutputMode = FlowOutputMode.PASS_THROUGH,
    step_order: int = 3,
):
    return config_channel(
        column=column,
        config=config,
        input_source=input_source,
        output_mode=output_mode,
        step_order=step_order,
    )


def _input(config: dict[str, Any]):
    return _channel("input_config", config, input_source=FlowInputSource.HTTP_GET)


def test_an_http_input_renumbers_its_url_its_plain_headers_and_its_active_body() -> (
    None
):
    config = _http(
        url="https://example.test/{{step_1.output.text}}",
        auth={"mode": "api_key", "header_name": "X-{{ step_1 }}", "key": "{{step_1}}"},
        custom_headers=[
            {"name": "A", "value": "{{ step_1 }}", "secret": False},
            {"name": "B", "value": "{{ step_1 }}", "secret": True},
        ],
        body={"mode": "json_template", "template": '{"t": "{{step_1.output.text}}"}'},
        timeout_seconds=12,
    )

    assert renumber_config_aliases(config, _input(config), {1: 2}) == _http(
        url="https://example.test/{{step_2.output.text}}",
        auth={"mode": "api_key", "header_name": "X-{{ step_2 }}", "key": "{{step_1}}"},
        custom_headers=[
            {"name": "A", "value": "{{ step_2 }}", "secret": False},
            {"name": "B", "value": "{{ step_1 }}", "secret": True},
        ],
        body={"mode": "json_template", "template": '{"t": "{{step_2.output.text}}"}'},
        timeout_seconds=12,
    )


def test_configuration_the_runtime_does_not_interpolate_keeps_what_was_saved() -> None:
    disabled = _http(body={"mode": "none", "template": "{{ step_1 }}"})
    literal = {"retrieval": {"note": "{{ step_1 }}"}, "note": "{{ step_1 }}"}

    assert renumber_config_aliases(disabled, _input(disabled), {1: 2}) == disabled
    # The same column of a step that does not read through HTTP is data.
    assert renumber_config_aliases(
        literal, _channel("input_config", literal), {1: 2}
    ) == (literal)
    assert (
        renumber_config_aliases(
            disabled,
            _channel(
                "output_config", disabled, output_mode=FlowOutputMode.COMPOSE_TEXT
            ),
            {1: 2},
        )
        == disabled
    )


def test_an_http_delivery_and_a_template_fill_are_read_in_their_own_column() -> None:
    delivery = _http(url="https://example.test/{{step_3.output.text}}")
    fill = {"bindings": {"a": "{{ step_1 }}"}, "note": "{{ step_1 }}"}

    renumbered_delivery = renumber_config_aliases(
        delivery,
        _channel("output_config", delivery, output_mode=FlowOutputMode.HTTP_POST),
        {3: 4},
    )
    renumbered_fill = renumber_config_aliases(
        fill,
        _channel("output_config", fill, output_mode=FlowOutputMode.TEMPLATE_FILL),
        {1: 2},
    )

    assert renumbered_delivery["url"] == "https://example.test/{{step_4.output.text}}"
    assert renumbered_fill == {
        "bindings": {"a": "{{ step_2 }}"},
        "note": "{{ step_1 }}",
    }


def test_a_configuration_the_runtime_cannot_read_is_left_as_saved() -> None:
    legacy = {"url": "https://example.test/{{step_1}}", "headers": {"A": "b"}}
    broken = _http(timeout_seconds="soon", url="{{step_1}}")

    assert renumber_config_aliases(legacy, _input(legacy), {1: 2}) == legacy
    assert renumber_config_aliases(broken, _input(broken), {1: 2}) == broken


def test_nothing_is_copied_when_no_site_changes() -> None:
    config = _http(url="https://example.test/{{ step_4 }}")

    assert renumber_config_aliases(config, _input(config), {1: 2}) is config


def test_the_column_reads_are_the_sites_the_channel_names_with_their_visibility() -> (
    None
):
    delivery = _http(
        url="{{ step_3 }}", custom_headers=[{"name": "A", "value": "{{step_1}}"}]
    )
    reads = config_alias_reads(
        _channel(
            "output_config",
            delivery,
            output_mode=FlowOutputMode.HTTP_POST,
            step_order=3,
        )
    )

    assert [(read.site, read.order, read.visible_below) for read in reads] == [
        ("output_config.url", 3, 4),
        ("output_config.custom_headers[0].value", 1, 4),
    ]
    assert config_alias_reads(_channel("output_config", delivery)) == []
    assert config_alias_reads(None) == []


def test_the_binding_reads_are_its_templates_and_its_source_refs() -> None:
    bindings = {
        "question": "Läs {{ step_2.output.text }} och {{ föregående_steg }}",
        "source_refs": [
            {"step_ref": "step_1", "output": "text"},
            {"step_ref": "step_01"},
            {"step_ref": "step_\u00b2"},
            {"step_ref": "existing_step_1"},
            "step_1",
        ],
    }

    reads = input_binding_alias_reads(bindings, step_order=4)

    assert [(read.site, read.order, read.visible_below) for read in reads] == [
        ("input_bindings.question", 2, 4),
        ("input_bindings.source_refs[0].step_ref", 1, 4),
        # The runtime reads a leading zero as the same number.
        ("input_bindings.source_refs[1].step_ref", 1, 4),
    ]
    assert input_binding_alias_reads(None, step_order=4) == []

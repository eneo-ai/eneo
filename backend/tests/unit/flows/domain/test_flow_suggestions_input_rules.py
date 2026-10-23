"""The suggestions about what reaches a step's model: a broad
``all_previous_steps``, a whole read of a wide JSON result, a whole result in
the prompt of a mapped step, and long material digested twice."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    SuggestionFlow,
    SuggestionStep,
    analyze_flow,
)

_IDS = [UUID(int=index) for index in range(1, 40)]
_WIDE = {
    "type": "object",
    "properties": {name: {"type": "string"} for name in ("a", "b", "c", "d")},
    "required": ["a", "b", "c", "d"],
}
_ITEMS = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
    "required": ["items"],
}


def _step(order: int, **columns: Any) -> SuggestionStep:
    values: dict[str, Any] = {
        "id": _IDS[order],
        "step_order": order,
        "user_description": f"Steg {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "text",
        "input_bindings": None,
        "input_config": None,
        "output_mode": "pass_through",
        "output_type": "text",
        "output_contract": None,
        "output_config": None,
        "prompt_text": "Gör så här.",
        "assistant_id": UUID(int=100 + order),
    }
    return SuggestionStep(**{**values, **columns})


def _of(
    code: FlowSuggestionCode,
    steps: list[SuggestionStep],
    metadata: Mapping[str, object] | None = None,
) -> list[FlowSuggestion]:
    return [
        suggestion
        for suggestion in analyze_flow(
            SuggestionFlow(steps=steps, metadata_json=metadata)
        )
        if suggestion.code is code
    ]


# --------------------------------------------------------------------------- #
# broad_all_previous_steps
# --------------------------------------------------------------------------- #

_BROAD = FlowSuggestionCode.BROAD_ALL_PREVIOUS_STEPS


def test_all_previous_steps_over_a_transcript_and_its_summary_is_medium() -> None:
    (suggestion,) = _of(
        _BROAD,
        [
            _step(1),
            _step(2, prompt_text="Sammanfatta."),
            _step(3, input_source="all_previous_steps", prompt_text="{{ step_1 }}"),
        ],
    )

    assert suggestion.steps == (_IDS[3],)
    assert suggestion.impact.level == "medium"
    assert suggestion.fix.kind == "assisted"
    assert suggestion.params == {
        "earlier_step_count": 2,
        "derived": [{"step_order": 2, "from_step_order": 1}],
        # Step 1 is in the prompt already.
        "suggested_source_refs": [{"step_order": 2, "step_id": str(_IDS[2])}],
    }
    assert "derived from step 1" in suggestion.message


def test_three_earlier_steps_without_a_derived_one_is_low() -> None:
    (suggestion,) = _of(
        _BROAD,
        [
            _step(1),
            _step(2, input_source="flow_input"),
            _step(3, input_source="flow_input"),
            _step(4, input_source="all_previous_steps"),
        ],
    )

    assert suggestion.impact.level == "low"
    assert suggestion.params["derived"] == []
    assert suggestion.params["earlier_step_count"] == 3


def test_no_broad_suggestion_for_two_independent_steps_underlag_or_no_model() -> None:
    independent = [
        _step(1),
        _step(2, input_source="flow_input"),
        _step(3, input_source="all_previous_steps"),
    ]
    with_underlag = [
        _step(1),
        _step(2),
        _step(3),
        _step(
            4,
            input_source="all_previous_steps",
            input_bindings={"source_refs": [{"step_ref": "step_3", "output": "text"}]},
        ),
    ]
    no_model = [
        _step(1),
        _step(2),
        _step(3),
        _step(4, input_source="all_previous_steps", output_mode="compose_text"),
    ]

    assert _of(_BROAD, independent) == []
    assert _of(_BROAD, with_underlag) == []
    assert _of(_BROAD, no_model) == []


def test_the_broad_fingerprint_follows_its_premise() -> None:
    def flow(prompt: str, name: str = "Steg 2") -> list[SuggestionStep]:
        return [
            _step(1),
            _step(2, user_description=name),
            _step(3, input_source="all_previous_steps", prompt_text=prompt),
        ]

    (before,) = _of(_BROAD, flow("Svara."))
    (reworded,) = _of(_BROAD, flow("Svara kort.", name="Sammanfattning"))
    independent = [
        _step(1),
        _step(2, input_source="flow_input"),
        _step(3, input_source="flow_input"),
        _step(4, input_source="all_previous_steps"),
    ]
    (other,) = _of(_BROAD, independent)

    assert reworded.fingerprint == before.fingerprint
    assert other.fingerprint != before.fingerprint


# --------------------------------------------------------------------------- #
# whole_structured_read
# --------------------------------------------------------------------------- #

_WHOLE = FlowSuggestionCode.WHOLE_STRUCTURED_READ


def _json(order: int, contract: Mapping[str, object] = _WIDE, **columns: Any):
    return _step(order, output_type="json", output_contract=contract, **columns)


def test_a_whole_read_of_a_wide_json_result_is_assisted() -> None:
    (suggestion,) = _of(_WHOLE, [_json(1), _step(2)])

    assert suggestion.steps == (_IDS[2], _IDS[1])
    assert suggestion.impact.level == "low"
    assert suggestion.fix.kind == "assisted"
    assert suggestion.params["fields"] == ["a", "b", "c", "d"]
    assert suggestion.params["reads"] == [
        {"channel": "input", "site": "input_source", "selector": []}
    ]


def test_a_whole_structured_value_in_the_prompt_is_a_whole_read() -> None:
    (suggestion,) = _of(
        _WHOLE,
        [
            _json(1),
            _step(
                2,
                input_source="flow_input",
                prompt_text="{{ step_1.output.structured }}",
            ),
        ],
    )

    assert suggestion.params["reads"][0]["selector"] == ["structured"]


def test_no_whole_read_suggestion_for_a_narrow_contract_a_field_or_a_text_step() -> (
    None
):
    narrow = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
    }

    assert _of(_WHOLE, [_json(1, narrow), _step(2)]) == []
    assert (
        _of(
            _WHOLE,
            [
                _json(1),
                _step(
                    2,
                    input_source="flow_input",
                    prompt_text="{{ step_1.output.structured.a }}",
                ),
            ],
        )
        == []
    )
    assert _of(_WHOLE, [_step(1, output_contract=_WIDE), _step(2)]) == []


def test_all_previous_steps_and_a_mapped_input_are_not_whole_reads() -> None:
    assert (
        _of(
            _WHOLE,
            [
                _json(1),
                _step(2, input_source="flow_input"),
                _step(3, input_source="all_previous_steps"),
            ],
        )
        == []
    )
    mapped = _json(
        2,
        _ITEMS,
        input_type="json",
        input_config={"item_map": {"enabled": True}},
    )
    assert _of(_WHOLE, [_json(1), mapped]) == []


def test_the_whole_read_fingerprint_follows_the_read() -> None:
    (before,) = _of(_WHOLE, [_json(1), _step(2)])
    (renamed,) = _of(_WHOLE, [_json(1, user_description="Fakta"), _step(2)])
    (other,) = _of(
        _WHOLE,
        [_json(1), _step(2, input_source="flow_input", prompt_text="{{ step_1 }}")],
    )

    assert renamed.fingerprint == before.fingerprint
    assert other.fingerprint != before.fingerprint


# --------------------------------------------------------------------------- #
# per_item_prompt_read
# --------------------------------------------------------------------------- #

_PER_ITEM = FlowSuggestionCode.PER_ITEM_PROMPT_READ


def _mapped(order: int, prompt: str) -> SuggestionStep:
    return _json(
        order,
        _ITEMS,
        input_type="json",
        input_config={"item_map": {"enabled": True}},
        prompt_text=prompt,
    )


def test_a_whole_result_in_the_prompt_of_a_mapped_step_is_sent_per_item() -> None:
    (suggestion,) = _of(
        _PER_ITEM,
        [
            _step(1),
            _json(2, _ITEMS),
            _mapped(3, "Bakgrund: {{ step_1.output.text }}"),
        ],
    )

    assert suggestion.steps == (_IDS[3], _IDS[1])
    assert suggestion.impact.level == "high"
    assert suggestion.fix.kind == "advice"
    assert suggestion.params["execution_mode"] == "per_item"
    assert suggestion.params["producer_step_order"] == 1


def test_a_per_source_step_with_a_whole_prompt_read_is_reported() -> None:
    per_source = _step(
        2,
        input_source="flow_input",
        input_type="document",
        output_type="json",
        output_contract=_ITEMS,
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "execution_mode": "per_source",
            }
        },
        prompt_text="{{ step_1.output.text }}",
    )

    (suggestion,) = _of(_PER_ITEM, [_step(1), per_source])

    assert suggestion.params["execution_mode"] == "per_source"


def test_no_per_item_suggestion_for_a_field_read_or_a_step_run_once() -> None:
    assert (
        _of(
            _PER_ITEM,
            [_json(1, _ITEMS), _mapped(2, "{{ step_1.output.structured.items.0 }}")],
        )
        == []
    )
    assert (
        _of(_PER_ITEM, [_step(1), _step(2), _step(3, prompt_text="{{ step_1 }}")]) == []
    )


# --------------------------------------------------------------------------- #
# repeated_long_material
# --------------------------------------------------------------------------- #

_LONG = FlowSuggestionCode.REPEATED_LONG_MATERIAL
_DIGEST = {"long_material": {"mode": "digest"}}


def test_two_steps_digesting_the_same_step_are_reported_on_the_later() -> None:
    (suggestion,) = _of(
        _LONG,
        [
            _step(1),
            _step(2, input_config=_DIGEST),
            _step(
                3,
                input_bindings={
                    "source_refs": [{"step_ref": "step_1", "output": "text"}]
                },
                input_config=_DIGEST,
            ),
        ],
    )

    assert suggestion.steps == (_IDS[3], _IDS[2])
    assert suggestion.impact.level == "medium"
    assert suggestion.fix.kind == "advice"
    assert suggestion.params == {
        "earlier_step_order": 2,
        "earlier_step_id": str(_IDS[2]),
        "shared_step_orders": [1],
        "shares_run_input": False,
    }


def test_two_steps_digesting_the_run_input_are_reported() -> None:
    (suggestion,) = _of(
        _LONG,
        [
            _step(1, input_config=_DIGEST),
            _step(2, input_source="flow_input", input_config=_DIGEST),
        ],
    )

    assert suggestion.params["shares_run_input"] is True
    assert suggestion.params["shared_step_orders"] == []


def test_digests_of_different_sources_or_a_single_digest_are_not_reported() -> None:
    assert (
        _of(
            _LONG,
            [
                _step(1),
                _step(2, input_config=_DIGEST),
                _step(3, input_config=_DIGEST),
            ],
        )
        == []
    )
    assert _of(_LONG, [_step(1), _step(2, input_config=_DIGEST)]) == []

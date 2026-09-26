"""The edit comparator: every way an edit can look fine and not be (eneo-e7h6).

Snapshots are hand-built from the frozen seeds A and G in the persisted shape
the public API returns, so each test changes exactly one fact about what the
Builder did and names the check and category that must catch it.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import eneo.database.tables  # noqa: E402,F401  (tables before the Builder modules)

edit = importlib.import_module("ai_builder_edit_expectation")
_FIXTURES = _SCRIPTS / "fixtures" / "ai_builder_battle"
A = json.loads((_FIXTURES / "edit_seed_a.json").read_text(encoding="utf-8"))
G = json.loads((_FIXTURES / "edit_seed_g.json").read_text(encoding="utf-8"))


def _snapshot(fixture: dict[str, Any], *, revision: int = 3) -> dict[str, Any]:
    steps = [
        {
            "assistant_id": f"a{order}",
            "step_order": order,
            "user_description": step["name"],
            **{key: copy.deepcopy(step.get(key)) for key in edit.PERSISTED_STEP_KEYS},
        }
        for order, step in enumerate(fixture["steps"], start=1)
    ]
    assistants = {
        f"a{order}": {
            "prompt": {"text": step["instructions"]},
            "completion_model": {"id": "m"},
        }
        for order, step in enumerate(fixture["steps"], start=1)
    }
    flow = {
        "name": fixture["name"],
        "description": fixture["description"],
        "draft_revision": revision,
        "metadata_json": copy.deepcopy(fixture.get("metadata_json")),
        "steps": steps,
    }
    return {"flow": flow, "assistants": assistants}


def _step(snapshot: dict[str, Any], aid: str) -> dict[str, Any]:
    return next(s for s in snapshot["flow"]["steps"] if s["assistant_id"] == aid)


def _renumber(snapshot: dict[str, Any], aids: list[str]) -> None:
    by_aid = {s["assistant_id"]: s for s in snapshot["flow"]["steps"]}
    snapshot["flow"]["steps"] = [
        dict(by_aid[aid], step_order=i) for i, aid in enumerate(aids, 1)
    ]


def _add(snapshot: dict[str, Any], aid: str, at: int) -> None:
    steps = snapshot["flow"]["steps"]
    steps.insert(
        at - 1,
        {
            "assistant_id": aid,
            "user_description": aid,
            "input_source": "previous_step",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "text",
        },
    )
    _renumber(snapshot, [s["assistant_id"] for s in steps])
    snapshot["assistants"][aid] = {
        "prompt": {"text": "Lista saknade datum."},
        "completion_model": {"id": "m"},
    }


def _plan(
    count: int,
    fields: dict[int, dict[str, Any]] | None = None,
    *,
    added: int = 0,
    removed: tuple[int, ...] = (),
    revision: int = 3,
) -> dict[str, Any]:
    fields = fields or {}
    changes = [
        {
            "kind": "removed"
            if order in removed
            else ("modified" if fields.get(order) else "unchanged"),
            "step_name": f"s{order}",
            "step_ref": f"existing_step_{order}",
            "field_changes": [
                {"field": field, "current": current}
                if not isinstance(current, dict)
                else {
                    "field": field,
                    "current": "…",
                    "current_detail": json.dumps(current),
                }
                for field, current in fields.get(order, {}).items()
            ],
        }
        for order in range(1, count + 1)
    ] + [
        {"kind": "added", "step_name": "new", "step_ref": None, "field_changes": []}
    ] * added
    return {
        "proposal": {
            "edit": {
                "base_flow_revision": revision,
                "removed_existing_step_refs": [
                    f"existing_step_{order}" for order in removed
                ],
                "diff": {"step_changes": changes},
            }
        }
    }


def _evidence(
    fixture: dict[str, Any],
    applied: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    **overrides: Any,
) -> dict[str, Any]:
    baseline = _snapshot(fixture)
    return {
        "identity": {
            f"a{order}": f"s{order}" for order in range(1, len(fixture["steps"]) + 1)
        },
        "captured_revision": 3,
        "baseline": baseline,
        "after_turn": copy.deepcopy(baseline),
        "outcome": {
            "plan": plan is not None,
            "questions": 0,
            "final_text": None,
            "ui_language": "sv",
        },
        "plan": plan,
        "apply": {"applied": {}} if applied is not None else None,
        "applied": applied,
        **overrides,
    }


def _judge(
    expect: dict[str, Any], fixture: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    gold = edit.parse_edit_expectation(expect, seed=fixture, owner="test")
    return edit.evaluate_edit(gold, seed=fixture, evidence=evidence)


def _failed(report: dict[str, Any]) -> dict[str, str]:
    return {
        check["name"]: check["category"]
        for check in report["checks"]
        if check["passed"] is False
    }


E02 = {
    "outcome": "plan",
    "changes": {"s3": {"required": ["instructions"], "permitted": ["instructions"]}},
}


E02_TEXT = A["steps"][2]["instructions"] + " Var vänlig."


def _e02_applied(text: str = E02_TEXT) -> dict[str, Any]:
    applied = _snapshot(A, revision=4)
    applied["assistants"]["a3"]["prompt"]["text"] = text
    return applied


def test_a_requested_instruction_change_and_nothing_else_passes() -> None:
    report = _judge(
        E02, A, _evidence(A, _e02_applied(), _plan(3, {3: {"instructions": E02_TEXT}}))
    )

    assert report["verdict"] == "pass", _failed(report)


def test_an_empty_or_unreadable_diff_fails_closed() -> None:
    empty = _plan(3, {3: {"instructions": E02_TEXT}})
    empty["proposal"]["edit"]["diff"]["step_changes"] = []
    duplicated = _plan(3, {3: {"instructions": E02_TEXT}})
    duplicated["proposal"]["edit"]["diff"]["step_changes"].append(
        duplicated["proposal"]["edit"]["diff"]["step_changes"][0]
    )
    moved = _plan(3, {3: {"instructions": E02_TEXT}})
    moved["proposal"]["edit"]["diff"]["step_changes"][0]["kind"] = "moved"

    for plan in (empty, duplicated, moved):
        assert (
            _failed(_judge(E02, A, _evidence(A, _e02_applied(), plan)))["diff_complete"]
            == "diff_integrity"
        )


def test_the_requested_change_missing_from_the_applied_flow_is_unfulfilled() -> None:
    report = _judge(E02, A, _evidence(A, _snapshot(A, revision=4), _plan(3)))

    assert _failed(report)["fulfilment"] == "fulfilment"


def test_an_unrequested_field_is_an_unauthorized_mutation() -> None:
    applied = _e02_applied()
    _step(applied, "a3")["output_type"] = "pdf"

    report = _judge(
        E02,
        A,
        _evidence(
            A, applied, _plan(3, {3: {"instructions": E02_TEXT, "output_type": "pdf"}})
        ),
    )

    assert _failed(report)["scope"] == "unauthorized_mutation"


def test_the_diff_must_show_exactly_what_the_apply_changed() -> None:
    # A change the diff hid, a change it claimed that never applied, and a
    # flow-level change it did not show.
    hidden = _e02_applied()
    hidden["assistants"]["a1"]["prompt"]["text"] = "Något annat."
    renamed_flow = _e02_applied()
    renamed_flow["flow"]["name"] = "Nytt namn"
    phantom = {
        "outcome": "plan",
        "changes": {
            "s3": {"required": ["instructions"], "permitted": ["instructions", "name"]}
        },
    }

    hidden_report = _judge(
        E02, A, _evidence(A, hidden, _plan(3, {3: {"instructions": E02_TEXT}}))
    )
    phantom_report = _judge(
        phantom,
        A,
        _evidence(
            A,
            _e02_applied(),
            _plan(3, {3: {"instructions": E02_TEXT, "name": "Nytt namn"}}),
        ),
    )
    flow_report = _judge(
        E02, A, _evidence(A, renamed_flow, _plan(3, {3: {"instructions": E02_TEXT}}))
    )

    assert _failed(hidden_report)["diff_matches_applied"] == "diff_integrity"
    assert _failed(hidden_report)["scope"] == "unauthorized_mutation"
    assert _failed(phantom_report) == {"diff_matches_applied": "diff_integrity"}
    assert _failed(flow_report)["diff_matches_applied"] == "diff_integrity"


def test_the_diff_must_show_the_values_the_apply_wrote() -> None:
    # Same fields on both sides; only the displayed instruction or name differs.
    other_text = _plan(3, {3: {"instructions": E02_TEXT + " Och kort."}})
    renamed = _e02_applied()
    _step(renamed, "a3")["user_description"] = "Besked till invånaren"
    rename_gold = {
        "outcome": "plan",
        "changes": {
            "s3": {
                "required": ["name", "instructions"],
                "permitted": ["name", "instructions"],
            }
        },
    }
    shown_other_name = _plan(3, {3: {"instructions": E02_TEXT, "name": "Något annat"}})
    shown_same_name = _plan(
        3, {3: {"instructions": E02_TEXT, "name": "Besked till invånaren"}}
    )

    assert _failed(_judge(E02, A, _evidence(A, _e02_applied(), other_text))) == {
        "diff_matches_applied": "diff_integrity"
    }
    assert _failed(_judge(rename_gold, A, _evidence(A, renamed, shown_other_name))) == {
        "diff_matches_applied": "diff_integrity"
    }
    assert (
        _judge(rename_gold, A, _evidence(A, renamed, shown_same_name))["verdict"]
        == "pass"
    )


def test_a_hidden_reorder_fails_the_sequence() -> None:
    applied = _snapshot(G, revision=4)
    _renumber(applied, ["a1", "a3", "a2", "a4"])

    report = _judge({"outcome": "plan"}, G, _evidence(G, applied, _plan(4)))

    assert _failed(report)["sequence"] == "order"


E16 = {
    "outcome": "plan",
    "sequence": ["s1", "s3", "s4"],
    "changes": {
        "s4": {
            "required": ["input_bindings"],
            "permitted": ["input_bindings", "input_contract"],
        }
    },
    "edges": {"add": ["s1.structured.belopp_kr -> s4"]},
}


def _e16_applied(
    amount: dict[str, Any] | None = None, *, keep_date: bool = True
) -> dict[str, Any]:
    applied = _snapshot(G, revision=4)
    applied["flow"]["steps"] = [
        s for s in applied["flow"]["steps"] if s["assistant_id"] != "a2"
    ]
    _renumber(applied, ["a1", "a3", "a4"])
    refs = [
        {
            "step_ref": "step_1",
            "output": "structured",
            "field_path": "diarienummer",
            "label": "Diarienummer",
        },
        amount
        or {"step_ref": "step_1", "output": "structured", "field_path": "belopp_kr"},
    ]
    if keep_date:
        refs.append(
            {
                "step_ref": "step_2",
                "output": "structured",
                "field_path": "sista_datum",
                "label": "Sista datum",
            }
        )
    _step(applied, "a4")["input_bindings"] = {"source_refs": refs}
    return applied


def _e16_plan(applied: dict[str, Any]) -> dict[str, Any]:
    """The diff an honest preview of `applied` shows (run refs are positions)."""

    return _plan(
        4, {4: {"input_bindings": _step(applied, "a4")["input_bindings"]}}, removed=(2,)
    )


def test_removing_a_step_takes_its_own_edges_but_nothing_else() -> None:
    correct, lost = _e16_applied(), _e16_applied(keep_date=False)

    assert (
        _judge(E16, G, _evidence(G, correct, _e16_plan(correct)))["verdict"] == "pass"
    )
    assert _failed(_judge(E16, G, _evidence(G, lost, _e16_plan(lost)))) == {
        "kept_dependencies": "dependency_loss"
    }


def test_the_preview_must_show_the_bindings_the_apply_wrote() -> None:
    # The preview names producers by plan ref (step_a is s1, step_b is s3 once
    # s2 is gone); only the producer of the amount differs.
    def shown(amount_from: str) -> dict[str, Any]:
        refs = [
            {
                "step_ref": "step_a",
                "output": "structured",
                "field_path": "diarienummer",
                "label": "Diarienummer",
            },
            {
                "step_ref": amount_from,
                "output": "structured",
                "field_path": "belopp_kr",
            },
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "sista_datum",
                "label": "Sista datum",
            },
        ]
        return _plan(4, {4: {"input_bindings": {"source_refs": refs}}}, removed=(2,))

    assert (
        _judge(E16, G, _evidence(G, _e16_applied(), shown("step_a")))["verdict"]
        == "pass"
    )
    assert _failed(_judge(E16, G, _evidence(G, _e16_applied(), shown("step_b")))) == {
        "diff_matches_applied": "diff_integrity"
    }


def test_the_preview_must_show_the_template_expressions_the_apply_wrote() -> None:
    # Step 3 reads both form fields already; only the one the text names differs.
    gold = {
        "outcome": "plan",
        "changes": {
            "s3": {"required": ["instructions"], "permitted": ["instructions"]}
        },
    }
    applied = _e02_applied(
        A["steps"][2]["instructions"] + " Nämn {{ flow_input.sokt_belopp }}."
    )
    shown = A["steps"][2]["instructions"] + " Nämn {{ flow_input.sokande }}."
    honest = applied["assistants"]["a3"]["prompt"]["text"]

    assert (
        _judge(gold, A, _evidence(A, applied, _plan(3, {3: {"instructions": honest}})))[
            "verdict"
        ]
        == "pass"
    )
    assert _failed(
        _judge(gold, A, _evidence(A, applied, _plan(3, {3: {"instructions": shown}})))
    ) == {"diff_matches_applied": "diff_integrity"}


def test_a_same_typed_or_whole_object_read_neither_satisfies_nor_is_permitted() -> None:
    wrong_producer = _e16_applied(
        {"step_ref": "step_2", "output": "structured", "field_path": "sista_datum"}
    )
    whole_object = _e16_applied({"step_ref": "step_1", "output": "structured"})

    assert (
        _failed(
            _judge(E16, G, _evidence(G, wrong_producer, _e16_plan(wrong_producer)))
        )["fulfilment"]
        == "fulfilment"
    )
    assert _failed(
        _judge(E16, G, _evidence(G, whole_object, _e16_plan(whole_object)))
    ) == {
        "scope": "unauthorized_mutation",
        "fulfilment": "fulfilment",
    }


E14 = {
    "outcome": "plan",
    "sequence": ["s1", "n1", "s2", "s3"],
    "changes": {
        "s2": {
            "permitted": [
                "input_source",
                "input_type",
                "input_bindings",
                "input_contract",
            ]
        }
    },
    "edges": {"add": ["s1.text -> n1"]},
    "step_outputs": {
        "n1": {
            "required_facts": ["startdatum", "slutbesiktning"],
            "forbidden": ["2026-10-05"],
        }
    },
}


def _e14_applied(*, keep_s2_explicit: bool) -> dict[str, Any]:
    applied = _snapshot(A, revision=4)
    _add(applied, "n-new", 2)
    # The compiler renumbers explicit refs past the insert; only an implicit
    # input can silently move to the new step.
    for ref in _step(applied, "a3")["input_bindings"]["source_refs"]:
        ref["step_ref"] = {"step_1": "step_1", "step_2": "step_3"}[ref["step_ref"]]
    if keep_s2_explicit:
        _step(applied, "a2")["input_bindings"] = copy.deepcopy(S2_EXPLICIT)
    return applied


S2_EXPLICIT = {"source_refs": [{"step_ref": "step_1", "output": "text"}]}


def test_an_insert_that_shifts_an_implicit_input_is_dependency_loss() -> None:
    shifted = _judge(
        E14, A, _evidence(A, _e14_applied(keep_s2_explicit=False), _plan(3, added=1))
    )
    rewritten = _judge(
        E14,
        A,
        _evidence(
            A,
            _e14_applied(keep_s2_explicit=True),
            _plan(3, {2: {"input_bindings": S2_EXPLICIT}}, added=1),
        ),
    )

    assert _failed(shifted) == {
        "kept_dependencies": "dependency_loss",
        "scope": "unauthorized_mutation",
    }
    assert rewritten["verdict"] == "pass", _failed(rewritten)


def test_an_inert_or_echoing_changed_step_fails_its_step_output() -> None:
    gold = edit.parse_edit_expectation(E14, seed=A, owner="test")
    evidence = _evidence(
        A,
        _e14_applied(keep_s2_explicit=True),
        _plan(3, {2: {"input_bindings": S2_EXPLICIT}}, added=1),
    )
    structural = edit.evaluate_edit(gold, seed=A, evidence=evidence)

    def run(payload: dict[str, Any]) -> dict[str, Any]:
        return edit.add_execution(
            structural,
            gold,
            evidence=evidence,
            output_success=True,
            step_results=[{"assistant_id": "n-new", "output_payload_json": payload}],
        )

    echo = run(
        {
            "text": "Datum för hembesök: 2026-10-05. Önskat startdatum: saknas. Slutbesiktning: saknas."
        }
    )
    listed = run({"text": "Saknade datum: startdatum för arbetet, slutbesiktning."})
    previewed = run(
        {"text": "Saknade datum: startdatum…", "text_overflow": {"file_ids": ["f"]}}
    )

    assert _failed(echo) == {"step_output_n1": "execution"}
    assert listed["verdict"] == "pass"
    assert previewed["verdict"] == "unmeasured"
    assert edit.add_execution(
        structural, gold, evidence=evidence, output_success=None, step_results=[]
    )["failed_checks"] == ["run_output"]


def test_e10_step_two_must_carry_the_case_and_one_verdict() -> None:
    cases = json.loads(
        (_SCRIPTS / "ai_builder_api_edit_cases.json").read_text(encoding="utf-8")
    )
    raw = next(
        c
        for c in cases["cases"]
        if c["id"] == "edit_e10_a_whole_flow_assessment_as_text"
    )
    gold = edit.parse_edit_expectation(raw["edit"]["expect"], seed=A, owner="E10")
    evidence = _evidence(A, _snapshot(A, revision=4), None)

    def step_two(text: str) -> dict[str, Any]:
        return edit.add_execution(
            {"checks": []},
            gold,
            evidence=evidence,
            output_success=True,
            step_results=[
                {"assistant_id": "a2", "output_payload_json": {"text": text}}
            ],
        )

    assert step_two("BAB-2026-0417: ansökan BEVILJAS.")["verdict"] == "pass"
    assert step_two("Ansökan BEVILJAS.")["failed_checks"] == ["step_output_s2"]
    assert step_two("BAB-2026-0417: BEVILJAS eller AVSLAS.")["failed_checks"] == [
        "step_output_s2"
    ]


def test_a_rebuild_with_new_steps_is_an_unauthorized_mutation() -> None:
    # The captured gemma answer: every step added again, the saved ones gone.
    rebuilt = _snapshot(A, revision=4)
    for step in rebuilt["flow"]["steps"]:
        step["assistant_id"] = "new-" + step["assistant_id"]
    rebuilt["assistants"] = {
        "new-" + key: value for key, value in rebuilt["assistants"].items()
    }

    report = _judge(E02, A, _evidence(A, rebuilt, _plan(3, added=3, removed=(1, 2, 3))))

    assert _failed(report)["scope"] == "unauthorized_mutation"


def test_a_write_before_approval_is_caught_for_every_outcome() -> None:
    evidence = _evidence(A, _e02_applied(), _plan(3, {3: {"instructions": E02_TEXT}}))
    evidence["after_turn"]["flow"]["draft_revision"] = 4

    assert (
        _failed(_judge(E02, A, evidence))["flow_unchanged_before_approval"]
        == "pre_approval_write"
    )


def test_a_reference_to_a_missing_step_is_dangling() -> None:
    applied = _e02_applied()
    applied["assistants"]["a3"]["prompt"]["text"] += " {{ step_7.output.text }}"

    report = _judge(
        E02, A, _evidence(A, applied, _plan(3, {3: {"instructions": E02_TEXT}}))
    )

    assert _failed(report)["references"] == "dangling_reference"


def test_a_decline_is_judged_without_a_plan_or_apply() -> None:
    from eneo.flows.ai_builder.ai_builder_non_plan_outcome import decline_message

    declined = {
        "outcome": "declined",
        "decline_reason": "model_choice_belongs_to_step_editor",
    }
    sentence = decline_message("model_choice_belongs_to_step_editor", ui_language="sv")

    def outcome(text: str) -> dict[str, Any]:
        return {"plan": False, "questions": 0, "final_text": text, "ui_language": "sv"}

    ok = _judge(declined, A, _evidence(A, None, None, outcome=outcome(sentence)))
    other = _judge(declined, A, _evidence(A, None, None, outcome=outcome("Nej.")))

    assert ok["verdict"] == "pass"
    assert next(c for c in ok["checks"] if c["name"] == "outcome")["detail"][
        "proxy_outcome"
    ]
    assert _failed(other) == {"outcome": "fulfilment"}


def test_a_selected_step_decline_is_judged_by_the_sentence_that_names_the_step() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_non_plan_outcome import decline_message

    gold = edit.parse_edit_expectation(
        {
            "outcome": "declined",
            "decline_reason": "model_choice_belongs_to_step_editor",
        },
        seed=A,
        owner="test",
    )

    def judge(text: str) -> dict[str, Any]:
        outcome = {
            "plan": False,
            "questions": 0,
            "final_text": text,
            "ui_language": "sv",
        }
        return edit.evaluate_edit(
            gold,
            seed=A,
            evidence=_evidence(A, None, None, outcome=outcome),
            selected_step_name="Bedöm ärendet",
        )

    named = decline_message(
        "model_choice_belongs_to_step_editor",
        ui_language="sv",
        step_name="Bedöm ärendet",
    )
    unnamed = decline_message("model_choice_belongs_to_step_editor", ui_language="sv")

    assert judge(named)["verdict"] == "pass"
    assert _failed(judge(unnamed)) == {"outcome": "fulfilment"}


def test_a_plan_that_silently_drops_a_step_and_is_refused_is_scored_as_it_happened() -> (
    None
):
    # Live E22 on gpt-5.6-luna, 2026-09-26: the diff listed three of four seed
    # steps and /apply refused with invalid_existing_step_ref. The code does not
    # say which rule fired, so no zero-tolerance category is guessed.
    plan = _plan(4, {4: {"output_config": None}})
    plan["proposal"]["edit"]["diff"]["step_changes"].pop(2)
    refused = {"status_code": 400, "error": '{"code": "invalid_existing_step_ref"}'}

    report = _judge(
        {"outcome": "plan"}, G, _evidence(G, None, plan, apply={"refused": refused})
    )

    assert set(report["categories"]) == {"diff_integrity", "apply_refused"}


def test_digit_groups_and_no_break_spaces_are_one_edit_fact() -> None:
    assert edit.normalized_text("Belopp: 48 500 kr") == "belopp: 48500 kr"
    assert edit.normalized_text("2026-11-30") == "2026-11-30"


@pytest.mark.parametrize(
    ("expect", "error"),
    [
        ({"outcome": "plan", "surprise": 1}, "Extra inputs"),
        ({"outcome": "clarification"}, "outcome"),
        (
            {"outcome": "plan", "changes": {"s3": {"required": ["name"]}}},
            "required field must also",
        ),
        (
            {"outcome": "plan", "changes": {"s3": {"permitted": ["colour"]}}},
            "permitted",
        ),
        ({"outcome": "plan", "edges": {"add": ["s1 -> s3"]}}, "pattern"),
        ({"outcome": "plan", "edges": {"drop": ["s1.text -> s2 @x"]}}, "drop"),
        ({"outcome": "plan", "edges": {"add": ["s1.text -> s3"]}}, "add"),
        (
            {
                "outcome": "plan",
                "sequence": ["s1", "s3"],
                "edges": {"add": ["s2.text -> s3"]},
            },
            "add",
        ),
        (
            {
                "outcome": "declined",
                "decline_reason": "model_choice_belongs_to_step_editor",
                "sequence": [],
            },
            "no plan gold",
        ),
        ({"outcome": "plan", "sequence": ["s1", "n2", "s2", "s3"]}, "sequence"),
    ],
)
def test_the_gold_loader_refuses_what_it_cannot_score(
    expect: dict[str, Any], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        edit.parse_edit_expectation(expect, seed=A, owner="test")

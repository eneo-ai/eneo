"""Mechanism diagnostics observe a run's wiring from the product's typed records.

`consumer_received` reads the typed lineage of the author's current attempt;
`review_checkpoint_on` reads where each checkpoint was created. Both abstain on
evidence they cannot read, and neither is a check any verdict reads.
"""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import fixture, mark

from tests.unittests.flows.ai_builder.test_ai_builder_api_battle_harness import (
    _battle_harness,  # pyright: ignore[reportPrivateUsage]
)

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

mechanisms = importlib.import_module("ai_builder_plan_mechanisms")
_DELETE = object()

READER, ASSESS, AUTHOR, FILL = (
    f"6b2e1d40-0000-4000-8000-00000000000{n}" for n in range(1, 5)
)
CHECKPOINT = "6b2e1d40-0000-4000-8000-0000000000c1"
SECOND_CHECKPOINT = "6b2e1d40-0000-4000-8000-0000000000c2"
STEPS = (
    (READER, "pass_through"),
    (ASSESS, "pass_through"),
    (AUTHOR, "pass_through"),
    (FILL, "template_fill"),
)


@fixture(scope="module")
def harness() -> ModuleType:
    return _battle_harness()


def flow_input_edge(*path: str | int, binding_ref: str) -> dict[str, Any]:
    return {
        "binding_ref": binding_ref,
        "selection": {"encoding": "utf8", "sha256": "a" * 64, "byte_size": 4},
        "source": {
            "kind": "flow_input",
            "selector": {"kind": "json_path", "path": list(path)},
        },
    }


def step_result_edge(
    *path: str, binding_ref: str, source: str = ASSESS
) -> dict[str, Any]:
    return {
        "binding_ref": binding_ref,
        "selection": {"encoding": "canonical_json", "sha256": "b" * 64, "byte_size": 9},
        "source": {
            "kind": "step_result",
            "selector": {"kind": "json_path", "path": ["output", "structured", *path]},
            "source_step_id": source,
            "source_attempt_no": 1,
        },
    }


def tracked(*edges: dict[str, Any]) -> dict[str, Any]:
    return {"status": "tracked", "schema_version": 1, "edges": list(edges)}


def attempt(
    step_id: str, attempt_no: int, lineage: dict[str, Any], status: str = "completed"
) -> dict[str, Any]:
    return {
        "id": f"6b2e1d40-0000-4000-a{attempt_no:03d}-{step_id[-12:]}",
        "step_id": step_id,
        "attempt_no": attempt_no,
        "status": status,
        "resolved_input_lineage": lineage,
    }


def evidence(
    *,
    author_lineage: dict[str, Any] | None = None,
    checkpoint_step: tuple[str, int] = (ASSESS, 2),
) -> dict[str, Any]:
    """A run whose author (step 3) consumed `hyra` from the run form; step 4,
    the delivery, renders step 3's result and selects the case number
    directly; the run paused once."""

    lineage = author_lineage or tracked(
        flow_input_edge("hyra", binding_ref="input_bindings.question:flow_input.hyra"),
        step_result_edge(
            binding_ref="input_bindings.question:step_2.output.structured"
        ),
    )
    step_id, order = checkpoint_step
    observed = {
        "id": CHECKPOINT,
        "step_id": step_id,
        "step_order": order,
        "review_mode": "edit",
        "output_type": "json",
    }
    return {
        "definition_snapshot": {
            "steps": [
                {
                    "step_id": sid,
                    "step_order": n,
                    "output_mode": mode,
                    "user_description": "x",
                }
                for n, (sid, mode) in enumerate(STEPS, start=1)
            ]
        },
        "run_contract": {
            "final_output": {"step_id": FILL, "output_mode": "template_fill"},
            "form_fields": [
                {"name": "diarienummer", "type": "text"},
                {"name": "hyra", "type": "number"},
            ],
        },
        "step_results": [
            {
                "step_id": sid,
                "status": "completed",
                "current_attempt_no": 1,
                "runtime_input_file_ids": [],
            }
            for sid, _ in STEPS
        ],
        "step_attempts": [
            attempt(READER, 1, tracked()),
            attempt(ASSESS, 1, tracked()),
            attempt(AUTHOR, 1, lineage),
            attempt(
                FILL,
                1,
                tracked(
                    step_result_edge("beslut", binding_ref="x", source=AUTHOR),
                    flow_input_edge(
                        "diarienummer",
                        binding_ref="output_config.bindings.dnr:flow_input.diarienummer",
                    ),
                ),
            ),
        ],
        "review_checkpoints": [
            {
                "id": CHECKPOINT,
                "step_id": step_id,
                "step_order": order,
                "attempt_no": 1,
                "created_at": "2026-10-01T16:45:08.053676Z",
                "original_payload_json": {"structured": {"bedomning": "Uppfyllt"}},
                "current_payload_json": {"structured": {"bedomning": "REVIEW-EDIT-1"}},
            }
        ],
        "execution": {
            "checkpoints": [{"action": "edit_target", "checkpoint": observed}],
            "failures": [],
        },
    }


def received(raw: object) -> dict[str, Any]:
    return mechanisms.plan_mechanisms(raw)["consumer_received"]


def checkpoint_on(raw: object) -> dict[str, Any]:
    return mechanisms.plan_mechanisms(raw)["review_checkpoint_on"]


# --- consumer_received --------------------------------------------------------


@mark.parametrize(
    "binding_ref",
    [
        "input_bindings.question:flow_input.hyra",
        "input_bindings.question:flow.input.hyra",
        "input_source",
    ],
)
def test_a_run_form_field_the_author_consumed_is_received_however_its_binding_is_spelled(
    binding_ref: str,
) -> None:
    raw = evidence(
        author_lineage=tracked(flow_input_edge("hyra", binding_ref=binding_ref))
    )

    assert received(raw) == {
        "consumer": "author",
        "step_order": 3,
        "fields": {"diarienummer": "not_received", "hyra": "received"},
    }


def runtime_input_edge(*path: str, binding_ref: str) -> dict[str, Any]:
    edge = flow_input_edge(*path, binding_ref=binding_ref)
    edge["source"]["kind"] = "runtime_input"
    return edge


@mark.parametrize("edge", [step_result_edge, runtime_input_edge])
def test_a_binding_that_names_a_field_but_selects_another_source_is_not_received(
    edge: Any,
) -> None:
    raw = evidence(
        author_lineage=tracked(
            edge("hyra", binding_ref="input_bindings.question:flow_input.hyra")
        )
    )

    assert received(raw)["fields"] == {
        "diarienummer": "not_received",
        "hyra": "not_received",
    }


def test_a_selection_of_the_whole_run_form_reaches_every_field_and_a_longer_name_none() -> (
    None
):
    whole = evidence(
        author_lineage=tracked(flow_input_edge(binding_ref="input_source"))
    )
    longer = evidence(
        author_lineage=tracked(
            flow_input_edge("hyra_per_manad", binding_ref="input_source")
        )
    )
    nested = evidence(
        author_lineage=tracked(flow_input_edge("hyra", 0, binding_ref="input_source"))
    )

    assert received(whole)["fields"] == {"diarienummer": "received", "hyra": "received"}
    assert received(longer)["fields"] == {
        "diarienummer": "not_received",
        "hyra": "not_received",
    }
    assert received(nested)["fields"]["hyra"] == "received"
    deeper = evidence(
        author_lineage=tracked(
            flow_input_edge("diarienummer", "hyra", binding_ref="input_source")
        )
    )
    assert received(deeper)["fields"] == {
        "diarienummer": "received",
        "hyra": "not_received",
    }


def test_the_author_is_followed_back_from_the_delivery_through_deterministic_steps() -> (
    None
):
    raw = evidence()
    # Deterministic steps after the reviewed one: the composer and the renderer.
    raw["definition_snapshot"]["steps"][2]["output_mode"] = "compose_text"
    raw["definition_snapshot"]["steps"][3]["output_mode"] = "render_verbatim"

    observed = received(raw)

    assert observed["step_order"] == 2
    # Step 4 selected the case number directly: that is no consumption by the author.
    assert observed["fields"] == {
        "diarienummer": "not_received",
        "hyra": "not_received",
    }


def _lineage_of(raw: dict[str, Any], step_id: str) -> dict[str, Any]:
    return next(a for a in raw["step_attempts"] if a["step_id"] == step_id)[
        "resolved_input_lineage"
    ]


def test_an_http_delivery_sends_the_authors_result_and_is_never_the_author() -> None:
    raw = evidence()
    raw["definition_snapshot"]["steps"][3]["output_mode"] = "http_post"
    raw["run_contract"]["final_output"]["output_mode"] = "http_post"

    assert received(raw) == {
        "consumer": "author",
        "step_order": 3,
        "fields": {"diarienummer": "not_received", "hyra": "received"},
    }


def test_a_delivering_model_step_is_not_its_own_author() -> None:
    raw = evidence()
    raw["definition_snapshot"]["steps"][3]["output_mode"] = "pass_through"

    assert received(raw)["step_order"] == 3


def test_the_last_completion_step_is_not_the_author_when_the_delivery_reads_another() -> (
    None
):
    raw = evidence()
    _lineage_of(raw, FILL)["edges"][0] = step_result_edge(
        binding_ref="x", source=ASSESS
    )

    observed = received(raw)

    assert observed["step_order"] == 2
    assert observed["fields"] == {
        "diarienummer": "not_received",
        "hyra": "not_received",
    }


def test_two_producers_reaching_the_delivery_leave_the_author_ambiguous() -> None:
    raw = evidence()
    _lineage_of(raw, FILL)["edges"].append(
        step_result_edge(binding_ref="y", source=ASSESS)
    )

    assert received(raw) == {"consumer": "author", "abstain": "consumer_ambiguous"}
    assert checkpoint_on(raw)["checkpoints"][0]["abstain"] == "consumer_ambiguous"


def test_a_delivery_that_reads_no_step_has_no_author() -> None:
    raw = evidence()
    del _lineage_of(raw, FILL)["edges"][0]

    assert received(raw) == {"consumer": "author", "abstain": "consumer_unresolved"}


@mark.parametrize(
    ("path", "value", "reason"),
    [
        (("step_results", 3, "status"), "cancelled", "delivery_not_completed"),
        (("step_results", 3), _DELETE, "delivery_not_completed"),
        (("run_contract", "final_output"), None, "delivery_invalid"),
        (("run_contract", "final_output", "step_id"), CHECKPOINT, "delivery_invalid"),
        (
            ("step_attempts", 3, "resolved_input_lineage"),
            {"status": "not_tracked"},
            "current_lineage_not_tracked",
        ),
    ],
)
def test_a_delivery_that_cannot_show_what_it_read_leaves_the_author_unresolved(
    path: tuple[Any, ...], value: object, reason: str
) -> None:
    raw = evidence()
    _set(raw, path, value)

    assert received(raw) == {"consumer": "author", "abstain": reason}
    (item,) = checkpoint_on(raw)["checkpoints"]
    assert (item["step_order"], item["abstain"]) == (2, reason)


def resolver_edge(source: str, *path: str | int) -> dict[str, Any]:
    """A `step_N.<path>` selection as the variable resolver records it."""
    edge = step_result_edge(binding_ref="input_bindings.question", source=source)
    edge["source"]["selector"]["path"] = list(path)
    return edge


def test_a_steps_input_or_status_is_no_consumption_of_its_result() -> None:
    raw = evidence()
    _lineage_of(raw, FILL)["edges"][0] = step_result_edge(
        binding_ref="x", source=ASSESS
    )
    _lineage_of(raw, FILL)["edges"] += [
        resolver_edge(AUTHOR, "input", "text"),
        resolver_edge(AUTHOR, "status"),
        resolver_edge(AUTHOR, "error_message"),
    ]

    observed = received(raw)

    # Step 3 consumed `hyra`, but the delivery read only its input and status.
    assert observed["step_order"] == 2
    assert observed["fields"] == {
        "diarienummer": "not_received",
        "hyra": "not_received",
    }


def test_a_metadata_selection_beside_the_authors_output_leaves_the_author() -> None:
    raw = evidence()
    _lineage_of(raw, FILL)["edges"].append(resolver_edge(ASSESS, "status"))

    assert received(raw)["step_order"] == 3


@mark.parametrize("path", [(), ("text",), (0,)])
def test_a_selection_that_is_neither_result_nor_metadata_abstains(
    path: tuple[str | int, ...],
) -> None:
    raw = evidence()
    _lineage_of(raw, FILL)["edges"].append(resolver_edge(ASSESS, *path))

    assert received(raw) == {"consumer": "author", "abstain": "selection_unsupported"}


@mark.parametrize(
    "unresolved",
    [
        lambda raw: _lineage_of(raw, FILL)["edges"].append(
            step_result_edge(binding_ref="y", source=ASSESS)
        ),
        lambda raw: raw["step_results"][3].update(status="cancelled"),
    ],
    ids=["ambiguous_author", "unfinished_delivery"],
)
def test_a_run_with_no_run_form_is_not_applicable_whatever_its_author(
    unresolved: Any,
) -> None:
    raw = evidence()
    raw["run_contract"]["form_fields"] = []
    unresolved(raw)

    assert received(raw) == {"consumer": "author", "not_applicable": "no_run_form"}
    # The checkpoint is placed on its own evidence.
    (item,) = checkpoint_on(raw)["checkpoints"]
    assert item["step_order"] == 2 and "abstain" in item


def test_a_lineage_source_the_definition_does_not_hold_abstains() -> None:
    raw = evidence()
    _lineage_of(raw, FILL)["edges"][0] = step_result_edge(
        binding_ref="x", source=CHECKPOINT
    )

    assert received(raw) == {"consumer": "author", "abstain": "definition_invalid"}


def test_only_the_current_attempt_counts() -> None:
    bound = tracked(flow_input_edge("hyra", binding_ref="input_source"))
    old_bound = evidence()
    old_bound["step_attempts"][2] = attempt(AUTHOR, 1, bound)
    old_bound["step_attempts"].append(attempt(AUTHOR, 2, tracked()))
    old_bound["step_results"][2]["current_attempt_no"] = 2
    new_bound = evidence()
    new_bound["step_attempts"][2] = attempt(AUTHOR, 1, tracked())
    new_bound["step_attempts"].append(attempt(AUTHOR, 2, bound))
    new_bound["step_results"][2]["current_attempt_no"] = 2

    assert received(old_bound)["fields"]["hyra"] == "not_received"
    assert received(new_bound)["fields"]["hyra"] == "received"


def _set(raw: dict[str, Any], path: tuple[Any, ...], value: object) -> dict[str, Any]:
    target: Any = raw
    for key in path[:-1]:
        target = target[key]
    if value is _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return raw


@mark.parametrize(
    ("path", "value", "reason"),
    [
        (
            ("step_attempts", 2, "resolved_input_lineage"),
            {"status": "not_tracked"},
            "current_lineage_not_tracked",
        ),
        (("step_attempts", 2, "status"), "failed", "current_attempt_invalid"),
        (("step_results", 2, "current_attempt_no"), None, "current_step_invalid"),
        (("step_results", 2, "current_attempt_no"), 2, "current_attempt_invalid"),
        (("step_results", 2, "status"), "cancelled", "step_not_completed"),
        (("step_results", 2), _DELETE, "not_reached"),
        (
            ("step_attempts", 2, "resolved_input_lineage"),
            {"status": "tracked"},
            "step_attempts_invalid",
        ),
        (("step_attempts",), {}, "step_attempts_invalid"),
        (("step_attempts",), [None], "step_attempts_invalid"),
        (("step_results",), _DELETE, "step_results_invalid"),
        (("step_results",), [{"status": "completed"}], "step_results_invalid"),
        (("run_contract",), _DELETE, "run_form_invalid"),
        (("run_contract", "form_fields"), None, "run_form_invalid"),
        (("run_contract", "form_fields"), [{"name": ""}], "run_form_invalid"),
        (
            ("run_contract", "form_fields"),
            [{"name": "hyra"}, {"name": "hyra"}],
            "run_form_invalid",
        ),
        (("definition_snapshot",), _DELETE, "definition_invalid"),
        (("definition_snapshot", "steps"), [], "definition_invalid"),
        (("definition_snapshot", "steps"), [None], "definition_invalid"),
        (
            ("definition_snapshot", "steps", 3, "output_mode"),
            "unknown_mode",
            "definition_invalid",
        ),
        (("definition_snapshot", "steps", 3, "step_order"), 3, "definition_invalid"),
        (("definition_snapshot", "steps", 1, "step_order"), True, "definition_invalid"),
    ],
)
def test_evidence_that_cannot_show_the_authors_inputs_abstains(
    path: tuple[Any, ...], value: object, reason: str
) -> None:
    assert received(_set(evidence(), path, value)) == {
        "consumer": "author",
        "abstain": reason,
    }


def test_a_flow_with_no_completion_step_has_no_author() -> None:
    raw = evidence()
    for step in raw["definition_snapshot"]["steps"]:
        step["output_mode"] = "template_fill"

    assert received(raw) == {"consumer": "author", "abstain": "consumer_unresolved"}


@mark.parametrize("raw", [None, [], "evidence"])
def test_no_run_evidence_abstains_both(raw: object) -> None:
    assert mechanisms.plan_mechanisms(raw) == {
        "consumer_received": {"consumer": "author", "abstain": "no_run"},
        "review_checkpoint_on": {"abstain": "no_run"},
    }


# --- review_checkpoint_on -----------------------------------------------------


@mark.parametrize(
    ("checkpoint_step", "relation"),
    [((ASSESS, 2), "upstream"), ((AUTHOR, 3), "is_author"), ((FILL, 4), "downstream")],
)
def test_a_checkpoint_is_placed_by_the_step_it_was_created_on(
    checkpoint_step: tuple[str, int], relation: str
) -> None:
    assert checkpoint_on(evidence(checkpoint_step=checkpoint_step)) == {
        "checkpoints": [
            {
                "checkpoint_id": CHECKPOINT,
                "attempt_no": 1,
                "step_order": checkpoint_step[1],
                "relation": relation,
            }
        ]
    }


def test_the_reviewed_payload_and_its_edit_are_never_read() -> None:
    raw = evidence()
    edited = copy.deepcopy(raw)
    edited["review_checkpoints"][0]["current_payload_json"] = None
    edited["review_checkpoints"][0]["original_payload_json"] = "not a payload"
    edited["step_results"][1]["output_payload_json"] = {"structured": {}}

    assert checkpoint_on(edited) == checkpoint_on(raw)


def test_a_harness_stop_before_the_edit_is_still_creation_evidence() -> None:
    raw = evidence(checkpoint_step=(AUTHOR, 3))
    stop = {
        "kind": "review_target_missing",
        "checkpoint": raw["execution"]["checkpoints"][0]["checkpoint"],
    }
    raw["execution"] = {
        "checkpoints": [],
        "failures": [{"kind": "deadline_reached"}, stop],
    }

    assert checkpoint_on(raw)["checkpoints"][0]["relation"] == "is_author"


def test_checkpoints_on_two_attempts_are_each_placed_in_creation_order() -> None:
    raw = evidence()
    later = {
        **raw["review_checkpoints"][0],
        "id": SECOND_CHECKPOINT,
        "attempt_no": 2,
        "step_id": AUTHOR,
        "step_order": 3,
        "created_at": "2026-10-01T16:50:00Z",
    }
    raw["review_checkpoints"] = [later, raw["review_checkpoints"][0]]

    assert [
        (c["checkpoint_id"], c["relation"]) for c in checkpoint_on(raw)["checkpoints"]
    ] == [
        (CHECKPOINT, "upstream"),
        (SECOND_CHECKPOINT, "is_author"),
    ]


def test_the_place_is_kept_when_the_author_cannot_be_resolved() -> None:
    raw = evidence()
    for step in raw["definition_snapshot"]["steps"]:
        step["output_mode"] = "render_verbatim"

    assert checkpoint_on(raw) == {
        "checkpoints": [
            {
                "checkpoint_id": CHECKPOINT,
                "attempt_no": 1,
                "step_order": 2,
                "abstain": "consumer_unresolved",
            }
        ]
    }


@mark.parametrize(
    ("path", "value", "expected"),
    [
        (("review_checkpoints",), [], {"abstain": "checkpoint_unrecorded"}),
        (("execution", "checkpoints", 0, "checkpoint", "step_order"), 3, None),
        (("review_checkpoints", 0, "step_order"), 3, None),
        (
            ("review_checkpoints", 0, "step_id"),
            "6b2e1d40-0000-4000-8000-0000000000ff",
            "checkpoint_step_unknown",
        ),
        (
            ("execution", "checkpoints", 0, "checkpoint", "id"),
            SECOND_CHECKPOINT,
            {"abstain": "checkpoint_unrecorded"},
        ),
        (("review_checkpoints",), _DELETE, {"abstain": "checkpoints_invalid"}),
        (("review_checkpoints",), {}, {"abstain": "checkpoints_invalid"}),
        (("review_checkpoints",), [None], {"abstain": "checkpoints_invalid"}),
        (("review_checkpoints", 0, "id"), _DELETE, {"abstain": "checkpoints_invalid"}),
        (
            ("review_checkpoints", 0, "created_at"),
            "yesterday",
            {"abstain": "checkpoints_invalid"},
        ),
        (
            ("review_checkpoints", 0, "created_at"),
            "2026-10-01T16:45:08",
            {"abstain": "checkpoints_invalid"},
        ),
        (("execution",), _DELETE, {"abstain": "checkpoints_invalid"}),
        (("execution", "failures"), None, {"abstain": "checkpoints_invalid"}),
        (("execution", "checkpoints"), ["edit"], {"abstain": "checkpoints_invalid"}),
        (
            ("execution", "checkpoints", 0, "checkpoint"),
            None,
            {"abstain": "checkpoints_invalid"},
        ),
        (("definition_snapshot",), _DELETE, {"abstain": "definition_invalid"}),
    ],
)
def test_checkpoint_evidence_that_disagrees_or_does_not_parse_abstains(
    path: tuple[Any, ...], value: object, expected: object
) -> None:
    observed = checkpoint_on(_set(evidence(), path, value))

    if isinstance(expected, dict):
        assert observed == expected
    else:
        (item,) = observed["checkpoints"]
        assert item["abstain"] == (expected or "checkpoint_evidence_conflict")
        assert "relation" not in item


def test_a_naive_and_an_aware_creation_time_never_crash_the_report() -> None:
    raw = evidence()
    later = {
        **raw["review_checkpoints"][0],
        "id": SECOND_CHECKPOINT,
        "created_at": "2026-10-01T16:50:00",
    }
    raw["review_checkpoints"].append(later)

    assert checkpoint_on(raw) == {"abstain": "checkpoints_invalid"}


def test_a_row_whose_order_disagrees_with_the_definition_abstains_without_any_observation() -> (
    None
):
    raw = evidence()
    raw["execution"]["checkpoints"] = []
    raw["review_checkpoints"][0]["step_order"] = 3

    (item,) = checkpoint_on(raw)["checkpoints"]
    assert item["abstain"] == "checkpoint_evidence_conflict"


def test_a_run_that_never_paused_created_no_checkpoint() -> None:
    raw = evidence()
    raw["review_checkpoints"] = []
    raw["execution"]["checkpoints"] = []

    assert checkpoint_on(raw) == {"abstain": "no_checkpoint_created"}


# --- no verdict reads them ------------------------------------------------------


def _reported(harness: ModuleType, raw: dict[str, Any]) -> dict[str, Any]:
    plan = {"proposal": {"spec": {"flow_name": "Wired", "steps": []}}}
    return harness._quality_report(  # pyright: ignore[reportPrivateUsage]
        plan=plan,
        summary=harness._summarize_plan(plan),  # pyright: ignore[reportPrivateUsage]
        expected={},
        runtime_evidence=raw,
    )


def test_the_report_carries_the_mechanisms_and_no_check_depends_on_them(
    harness: ModuleType,
) -> None:
    wired = evidence()
    unwired = evidence(author_lineage=tracked(), checkpoint_step=(AUTHOR, 3))

    wired_report, unwired_report = (
        _reported(harness, wired),
        _reported(harness, unwired),
    )

    assert wired_report["mechanisms"] == mechanisms.plan_mechanisms(wired)
    assert unwired_report["mechanisms"] == mechanisms.plan_mechanisms(unwired)
    assert wired_report["mechanisms"] != unwired_report["mechanisms"]
    assert wired_report["checks"] == unwired_report["checks"]
    assert (
        wired_report["delivery_check_names"] == unwired_report["delivery_check_names"]
    )


def test_the_observation_row_carries_the_reports_mechanisms(
    harness: ModuleType,
) -> None:
    report = _reported(harness, evidence())
    bundle = {"quality_report": report, "artifact_mode": "live_execution"}

    projected = harness._observation_projection(bundle)  # pyright: ignore[reportPrivateUsage]

    unrecorded = {
        **bundle,
        "quality_report": {k: v for k, v in report.items() if k != "mechanisms"},
    }

    assert projected["mechanisms"] == report["mechanisms"]
    assert harness._observation_projection(unrecorded)["mechanisms"] is None  # pyright: ignore[reportPrivateUsage]

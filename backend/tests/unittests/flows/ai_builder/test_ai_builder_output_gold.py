"""Output gold: one closed representation, one comparator, grounded in its sources (eneo-jk6t.51).

A fact is a typed value with the spellings its case accepts and, optionally,
where it must stand (a field after its labels, a line, a JSON pointer). The
required-fact check and the binding grader decide through the same comparison,
so they never disagree on a spelling. Gold lives in its own corpus, keyed by
the digest of the sources it was authored from; the scorer applies it only to
a run of exactly those sources, and the corpus digest is part of the scorer
identity, so receipts scored under different gold are INCOMPARABLE.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import MonkeyPatch, fixture, mark, raises

from tests.unittests.flows.ai_builder.test_ai_builder_api_battle_harness import (
    _battle_harness,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_battle_compare import (
    _compare_module,  # pyright: ignore[reportPrivateUsage]
)
from tests.unittests.flows.ai_builder.test_ai_builder_verdict_states import (
    _scored_by,  # pyright: ignore[reportPrivateUsage]
)

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

edit = importlib.import_module("ai_builder_edit_expectation")


@fixture(scope="module")
def harness() -> ModuleType:
    return _battle_harness()


@fixture(scope="module")
def gold_module(harness: ModuleType) -> ModuleType:
    return importlib.import_module("ai_builder_output_gold")


def _fact(
    fact_id: str,
    value: str,
    forms: list[str],
    *,
    kind: str = "text",
    labels: list[str] | None = None,
    pointer: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "id": fact_id,
        "type": kind,
        "value": value,
        "forms": forms,
        **extra,
    }
    if labels is not None:
        fact["location"] = {"kind": "field", "labels": labels}
    if pointer is not None:
        fact["location"] = {"kind": "pointer", "pointer": pointer}
    return fact


def _gold(*facts: dict[str, Any], output_kind: str = "text", **extra: Any) -> Any:
    return edit.OutputGold.model_validate(
        {"output_kind": output_kind, "facts": list(facts), **extra}
    )


def _distance_gold(meter: list[str]) -> Any:
    """Two distances that must state their unit (metres); the first accepts
    the unit spellings `meter`."""

    return _gold(
        _fact(
            "avstand",
            "30",
            ["30"],
            kind="number",
            unit="m",
            unit_required=True,
            unit_forms=meter,
            labels=["avstånd"],
        ),
        _fact(
            "hojd",
            "22",
            ["22"],
            kind="number",
            unit="m",
            unit_required=True,
            unit_forms=["meter"],
            labels=["höjd"],
        ),
    )


def _report(
    harness: ModuleType,
    gold: Any,
    *,
    text: str | None = None,
    structured: object = None,
    document: str | None = None,
) -> dict[str, Any]:
    if document is not None:
        result: dict[str, Any] = {
            "kind": "artifact",
            "files": [{"mimetype": _DOCX, "file_id": "f1"}],
        }
        kind = "docx"
    elif structured is not None:
        result, kind = {"kind": "structured", "value": structured}, "json"
    else:
        result, kind = {"kind": "inline_text", "text": text}, "text"
    expect = harness.OutputExpectation(
        output_kind=kind,
        required_facts=tuple(fact.spellings[0] for fact in gold.facts),
        gold=gold,
    )
    return harness._output_report(  # pyright: ignore[reportPrivateUsage]
        expect,
        {
            "execution": {"outcome": "completed", "failures": []},
            "run": {"status": "completed", "result": result},
            "run_contract": {"final_output": {"output_type": kind}},
            "final_artifact": {} if document is None else {"text": document},
        },
        runtime_checks=[],
    )


_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _states(report: dict[str, Any], name: str) -> list[object]:
    return [c["passed"] for c in report["output_checks"] if c["name"] == name]


def _binding(harness: ModuleType, report: dict[str, Any]) -> object:
    [passed] = _states(report, harness.OUTPUT_BINDING_GRADER)
    return passed


# --- one comparator for facts and their places ---------------------------------


@mark.parametrize(
    ("forms", "holds"),
    [(["meter"], True), ([], False)],
    ids=["gold_lists_the_form", "gold_does_not"],
)
def test_a_required_fact_and_its_location_decide_a_spelling_alike(
    harness: ModuleType, forms: list[str], holds: bool
) -> None:
    """'30 meter' holds for a fact '30 m' exactly when the case's gold lists
    that unit spelling; the literal check and the binding grader never
    disagree."""

    report = _report(
        harness,
        _distance_gold(forms),
        text="Avstånd till väg: 30 meter.\nHöjd: 22 meter.",
    )

    assert _states(report, "required_fact") == [holds, True]
    assert _states(report, "output_fact_location") == [holds, True]
    assert report["output_success"] is holds


def test_two_located_values_that_exchanged_places_fail_with_every_fact_present(
    harness: ModuleType,
) -> None:
    gold = _distance_gold(["meter"])
    right = _report(harness, gold, text="Avstånd: 30 meter, höjd: 22 meter.")
    swapped = _report(harness, gold, text="Avstånd: 22 meter, höjd: 30 meter.")

    assert _binding(harness, right) is True
    assert _states(swapped, "required_fact") == [True, True]
    assert _binding(harness, swapped) is False
    assert swapped["output_success"] is False


def test_a_value_also_under_another_field_does_not_stand_only_at_its_own(
    harness: ModuleType,
) -> None:
    report = _report(
        harness,
        _distance_gold(["meter"]),
        text="Avstånd: 30 m. Höjd: 22 m, varav 30 m tak.",
    )

    # 30 also stands under Höjd, which then holds two values.
    assert _states(report, "output_fact_location") == [False, False]


def test_a_pointer_reads_the_structured_leaf_by_value_and_fails_a_swap(
    harness: ModuleType,
) -> None:
    gold = _gold(
        _fact("belopp", "48500", ["48500"], kind="number", pointer="/belopp"),
        _fact(
            "datum", "2026-11-30", ["2026-11-30"], kind="date", pointer="/beslut/senast"
        ),
        output_kind="json",
    )
    right = _report(
        harness,
        gold,
        structured={"belopp": 48500.0, "beslut": {"senast": "2026-11-30"}},
    )
    swapped = _report(
        harness, gold, structured={"belopp": "2026-11-30", "beslut": {"senast": 48500}}
    )

    assert _binding(harness, right) is True
    # A structured fact is its typed leaf: neither leaf is delivered.
    assert _states(swapped, "required_fact") == [False, False]
    assert _binding(harness, swapped) is False


def test_a_document_is_read_as_its_text_and_a_field_spans_table_cells(
    harness: ModuleType,
) -> None:
    """The DOCX text is the product's own reader's (`extract_docx_text`: a
    cell per paragraph); a field runs to the next label, across cells."""

    gold = _gold(
        _fact("belopp", "48500", ["48500"], kind="number", labels=["belopp"]),
        _fact(
            "datum", "2026-11-30", ["2026-11-30"], kind="date", labels=["sista datum"]
        ),
        output_kind="docx",
    )
    right = _report(
        harness, gold, document="Belopp\n\n48500 kr\n\nSista datum\n\n2026-11-30"
    )
    swapped = _report(
        harness, gold, document="Belopp\n\n2026-11-30\n\nSista datum\n\n48500 kr"
    )

    assert _binding(harness, right) is True
    assert _binding(harness, swapped) is False


def test_a_location_the_output_cannot_show_is_unmeasured_never_a_pass(
    harness: ModuleType,
) -> None:
    gold = _gold(
        _fact("belopp", "48500", ["48500"], kind="number", pointer="/belopp"),
        _fact("datum", "2026-11-30", ["2026-11-30"], kind="date", pointer="/datum"),
        output_kind="json",
    )

    report = _report(harness, gold, text="belopp 48500, datum 2026-11-30")

    assert _states(report, "output_fact_location") == [None, None]
    assert _binding(harness, report) is None


def test_two_facts_without_any_location_leave_the_binding_unmeasured(
    harness: ModuleType,
) -> None:
    gold = _gold(
        _fact("belopp", "48500", ["48500"], kind="number"),
        _fact("datum", "2026-11-30", ["2026-11-30"], kind="date"),
    )

    report = _report(harness, gold, text="48500 kr senast 2026-11-30")

    assert _binding(harness, report) is None
    assert report["output_success"] is None


def test_an_association_is_the_case_literal_read_as_a_line_location(
    harness: ModuleType,
) -> None:
    expect = harness.OutputExpectation(
        output_kind="text",
        required_facts=("10,6", "8,6"),
        associations=(
            harness.OutputAssociation(fact="10,6", with_="Kyldisk", not_with="Kylrum"),
        ),
    )

    gold = harness._scoring_gold(expect)  # pyright: ignore[reportPrivateUsage]

    assert [(f.id, f.forms, f.location and f.location.kind) for f in gold.facts] == [
        ("10,6", ["10,6"], "line"),
        ("8,6", ["8,6"], None),
    ]


@mark.parametrize(
    ("text", "required", "state"),
    [
        ("Belopp 48500 kr", False, "stated"),
        ("Belopp 48 500 kronor", False, "stated"),
        ("Belopp 48500kr", False, "stated"),
        ("Belopp 48500euro", False, None),
        ("Belopp 48500öre", False, None),
        ("Belopp 48500", False, "unmeasured"),
        # A spaced word is never read as a unit (no word list): undetected.
        ("Belopp 48500 euro", False, "unmeasured"),
        ("Belopp 48500 kr", True, "stated"),
        ("Belopp 48500kronor", True, "stated"),
        ("Belopp 48500", True, None),
        ("Belopp 48500 euro", True, None),
        ("Belopp 48500euro", True, None),
        # Every occurrence counts: a wrong glued unit is never outvoted.
        ("Belopp 48500euro, alltså 48500 kr", False, None),
        ("Belopp 48500 kr, alltså 48500euro", True, None),
        ("Belopp 48500kr och 48500", False, "stated"),
    ],
)
def test_a_glued_unit_must_be_the_cases_and_a_bare_number_leaves_it_unmeasured(
    text: str, required: bool, state: str | None
) -> None:
    fact = edit.GoldFact.model_validate(
        _fact(
            "belopp",
            "48500",
            ["48500"],
            kind="number",
            unit="kr",
            unit_forms=["kronor"],
            unit_required=required,
        )
    )
    normalized = edit.normalized_text(text)

    assert edit.unit_state(fact, normalized) == state
    assert edit.fact_in_text(fact, normalized) is (state is not None)


@mark.parametrize("unit", ["", "   "])
def test_a_blank_unit_is_refused_like_any_unit_spelling(unit: str) -> None:
    with raises(ValueError, match="non-empty literals"):
        edit.GoldFact.model_validate(
            _fact(
                "belopp",
                "48500",
                ["48500"],
                kind="number",
                unit=unit,
                unit_required=True,
            )
        )


class _CountingTokens(tuple[object, ...]):
    """A token tuple that records every slice taken of it."""

    slices: list[int] = []

    def __getitem__(self, key: Any) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]
        if isinstance(key, slice):
            _CountingTokens.slices.append(len(range(*key.indices(len(self)))))
        return super().__getitem__(key)


def test_every_occurrence_is_read_in_place_with_no_copy_of_the_rest(
    monkeypatch: MonkeyPatch,
) -> None:
    """All occurrences are inspected, each with at most a unit's length of
    lookahead: no slice of the remaining tokens is built (a copy per
    occurrence made a 200k-character output quadratic)."""

    tokens = edit._tokens  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(edit, "_tokens", lambda text: _CountingTokens(tokens(text)))
    _CountingTokens.slices = []
    fact = edit.GoldFact.model_validate(
        _fact("belopp", "48500", ["48500"], kind="number", unit="kr")
    )
    text = edit.normalized_text("Belopp 48500 kr. " * 2000 + "Slut 48500euro.")

    assert edit.unit_state(fact, text) is None  # the last occurrence is read
    assert max(_CountingTokens.slices, default=0) <= 1


def test_a_field_holding_its_amount_with_a_wrong_glued_unit_fails_and_states_nothing(
    harness: ModuleType,
) -> None:
    gold = _gold(
        _fact(
            "belopp", "57300", ["57300"], kind="number", unit="kr", labels=["belopp"]
        ),
        _fact("datum", "2027-01-15", ["2027-01-15"], kind="date", labels=["datum"]),
    )

    report = _report(
        harness, gold, text="Belopp: 57300euro och 57300 kr. Datum: 2027-01-15"
    )

    [fact] = [
        c
        for c in report["output_checks"]
        if c["name"] == "required_fact" and c["fact"] == "belopp"
    ]
    assert fact["passed"] is False and "unit" not in fact
    assert _states(report, "output_fact_location") == [False, True]
    assert _binding(harness, report) is False


@mark.parametrize(("required", "passed"), [(False, True), (True, False)])
def test_a_json_number_states_no_unit_so_never_holds_a_required_one(
    harness: ModuleType, required: bool, passed: bool
) -> None:
    gold = _gold(
        _fact(
            "belopp",
            "48500",
            ["48500"],
            kind="number",
            unit="kr",
            unit_required=required,
            pointer="/amount",
        ),
        output_kind="json",
    )

    report = _report(harness, gold, structured={"amount": 48500})

    assert _states(report, "required_fact") == [passed]
    assert _states(report, "output_fact_location") == [passed]
    # A string leaf that states the unit still holds it.
    stated = _report(harness, gold, structured={"amount": "48500 kr"})
    assert _states(stated, "required_fact") == [True]


def test_a_required_fact_reports_whether_its_unit_was_stated(
    harness: ModuleType,
) -> None:
    gold = _gold(
        _fact(
            "belopp", "48500", ["48500"], kind="number", unit="kr", labels=["belopp"]
        ),
    )

    def unit(text: str) -> object:
        [check] = [
            c
            for c in _report(harness, gold, text=text)["output_checks"]
            if c["name"] == "required_fact"
        ]
        return check.get("unit")

    assert unit("Belopp 48500 kr.") == "stated"
    assert unit("Belopp 48500.") == "unmeasured"
    assert unit("Belopp 48500euro.") is None


@mark.parametrize("pointer", ["/items/01", "/items/²", "/items/-1", "/items/9", "/x/y"])
def test_a_pointer_that_names_no_element_fails_closed(pointer: str) -> None:
    gold = _gold(
        _fact("a", "5", ["5"], kind="number", pointer=pointer), output_kind="json"
    )

    located = edit.fact_located(
        gold.facts[0], gold, text="{}", structured={"items": [5, 5], "x": 5}
    )

    assert located is False
    assert edit.json_at({"items": [5, 5]}, ["items", "1"]) == (True, 5)


def test_a_complete_pointer_reaches_the_root_and_the_empty_key_and_never_raises() -> (
    None
):
    root = _gold(_fact("a", "5", ["5"], kind="number", pointer=""), output_kind="json")
    empty = _gold(
        _fact("a", "5", ["5"], kind="number", pointer="/"), output_kind="json"
    )

    assert edit.fact_located(root.facts[0], root, text=None, structured=5) is True
    assert (
        edit.fact_located(empty.facts[0], empty, text=None, structured={"": 5}) is True
    )
    assert edit.json_at([5], ["9" * 5000]) == (False, None)
    assert edit.json_at([5], ["9" * 16]) == (False, None)


def test_a_structured_required_fact_is_its_typed_leaf_not_serialized_json(
    harness: ModuleType,
) -> None:
    gold = _gold(
        _fact(
            "belopp", "48500", ["48500"], kind="number", unit="kr", pointer="/amount_kr"
        ),
        output_kind="json",
    )

    right = _report(harness, gold, structured={"amount_kr": 48500})
    wrong = _report(harness, gold, structured={"amount_kr": 48501, "note": "48500 kr"})

    assert _states(right, "required_fact") == [True]
    assert _states(right, "output_fact_location") == [True]
    assert _states(wrong, "required_fact") == [False]


def test_a_unit_spelling_not_in_the_sources_is_refused(gold_module: ModuleType) -> None:
    gold = _gold(
        _fact(
            "belopp",
            "48500",
            ["48500"],
            kind="number",
            unit="kr",
            unit_forms=["bananas"],
        )
    )

    assert gold_module.grounding_problems(gold, "Amount 48500 kr") == [
        "belopp: unit 'bananas' is not in the sources"
    ]


def test_gold_written_into_a_case_is_refused_not_dropped(harness: ModuleType) -> None:
    with raises(ValueError, match="unknown keys: gold"):
        harness._output_expectation(  # pyright: ignore[reportPrivateUsage]
            {"output_kind": "text", "required_facts": ["a1"], "gold": {"facts": []}},
            owner="case",
        )


# --- the gold is validated on load ---------------------------------------------


_GOOD_FACT = _fact("belopp", "48500", ["48500"], kind="number", labels=["belopp"])


@mark.parametrize(
    ("facts", "output_kind"),
    [
        ([{**_GOOD_FACT, "colour": "red"}], "text"),
        ([{**_GOOD_FACT, "value": "48 500"}], "text"),
        ([_fact("avstand", "30", ["38 m"], kind="number")], "text"),
        ([_fact("namn", "Ingrid", ["Ingrid"], unit="kr")], "text"),
        ([_fact("datum", "30 november", ["30 november"], kind="date")], "text"),
        ([_fact("belopp", "1", ["1"], kind="number", labels=["rad 2"])], "text"),
        ([_fact("belopp", "1", ["1"], kind="number", pointer="/belopp")], "text"),
        ([_fact("belopp", "1", ["1"], kind="number", labels=["belopp"])], "json"),
        (
            [
                _fact(
                    "datum", "2026-11-30", ["2026-11-30"], kind="date", labels=["datum"]
                ),
                _fact(
                    "sista",
                    "2026-12-01",
                    ["2026-12-01"],
                    kind="date",
                    labels=["sista datum"],
                ),
            ],
            "text",
        ),
        ([_fact("namn", "Ingrid Belopp", ["Ingrid Belopp"]), _GOOD_FACT], "text"),
        ([_GOOD_FACT, _GOOD_FACT], "text"),
        (
            [_fact("datum", "2026-11-30", ["2026-11-30", "2026-10-05"], kind="date")],
            "text",
        ),
        ([_fact("datum", "2026-11-30", ["30 november 2026"], kind="date")], "text"),
        ([_fact("belopp", "1", ["1"], kind="number", pointer="junk/a")], "json"),
        ([_fact("belopp", "1", ["1"], kind="number", pointer="/a~2")], "json"),
    ],
    ids=[
        "unknown_key",
        "number_not_plain",
        "number_form_without_its_value",
        "unit_on_text",
        "date_not_iso",
        "label_with_digit",
        "pointer_in_text",
        "field_in_json",
        "labels_overlap",
        "label_inside_a_form",
        "fact_twice",
        "date_form_of_another_date",
        "date_form_not_readable",
        "pointer_not_anchored",
        "pointer_bad_escape",
    ],
)
def test_malformed_gold_is_refused_on_load(
    gold_module: ModuleType,
    tmp_path: Path,
    facts: list[dict[str, Any]],
    output_kind: str,
) -> None:
    path = _corpus(tmp_path, [_entry("a" * 64, facts, output_kind=output_kind)])

    with raises(ValueError):
        gold_module.load_gold(path)


@mark.parametrize(
    "corpus",
    [
        {"version": 2, "entries": []},
        {"version": 1, "entries": [{"subject": "case:x", "sources_sha256": "a" * 64}]},
        {
            "version": 1,
            "entries": [
                {**{"subject": "seed:a.json"}, "sources_sha256": "a" * 64, "gold": {}}
            ]
            * 2,
        },
    ],
    ids=["version", "subject_and_gold", "duplicate_entry"],
)
def test_a_malformed_corpus_is_refused_on_load(
    gold_module: ModuleType, tmp_path: Path, corpus: dict[str, Any]
) -> None:
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(corpus), encoding="utf-8")

    with raises(ValueError):
        gold_module.load_gold(path)


def test_one_form_names_one_fact(gold_module: ModuleType, tmp_path: Path) -> None:
    facts = [
        _fact("a", "48500", ["48500"], kind="number"),
        _fact("b", "48 500", ["48 500"]),
    ]

    with raises(ValueError):
        gold_module.load_gold(_corpus(tmp_path, [_entry("a" * 64, facts)]))


def _entry(sha: str, facts: list[dict[str, Any]], **gold: Any) -> dict[str, Any]:
    return {
        "subject": "case:cases.json:c1",
        "sources_sha256": sha,
        "gold": {"output_kind": "text", "facts": facts, **gold},
    }


def _corpus(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "gold.json"
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    return path


# --- grounding: the authoring check ---------------------------------------------


def test_the_checked_in_corpus_is_grounded_in_its_subjects_sources(
    gold_module: ModuleType,
) -> None:
    assert gold_module.check() == []
    assert gold_module.unit_notes() == [
        "seed:edit_seed_a.json: sokt_belopp unit: unmeasured ('kr' not required; a bare number holds)",
        "seed:edit_seed_g.json: belopp_kr unit: unmeasured ('kr' not required; a bare number holds)",
    ]


_SOURCES = "Sökt belopp: 48 500 kr. Sökande: Ingrid Wästberg. Offert 51200 kr. BAB-2026-0417, senast 2026-11-30."


def test_gold_grounded_in_its_sources_passes_the_check(gold_module: ModuleType) -> None:
    gold = _gold(
        _fact("belopp", "48500", ["48500"], kind="number", labels=["belopp"]),
        _fact("namn", "Ingrid Wästberg", ["Ingrid Wästberg"]),
        forbidden=["51200"],
    )

    assert gold_module.grounding_problems(gold, _SOURCES) == []
    assert gold_module.grounding_problems(
        gold, _SOURCES.replace("belopp", "summa")
    ) == ["belopp: label 'belopp' is not in the sources"]
    assert gold_module.grounding_problems(gold, _SOURCES.replace("51200", "")) == [
        "forbidden '51200' is not in the sources"
    ]


@mark.parametrize(
    ("fact", "problems"),
    [
        (
            _fact(
                "datum", "2026-11-30", ["2026-11-30", "2026-11-30T10:00"], kind="date"
            ),
            ["datum: form '2026-11-30T10:00' is not in the sources"],
        ),
        (
            _fact("id", "ZZZ-NOT-THERE", ["BAB-2026-0417"]),
            ["id: 'ZZZ-NOT-THERE' is not in the sources"],
        ),
        (
            _fact("namn", "Ingrid Wästberg", ["Ingrid Wästberg", "Greta Svensson"]),
            ["namn: form 'Greta Svensson' is not in the sources"],
        ),
    ],
    ids=["second_spelling", "value_not_a_form", "second_name"],
)
def test_one_grounded_form_never_grounds_another_or_the_value(
    gold_module: ModuleType, fact: dict[str, Any], problems: list[str]
) -> None:
    assert gold_module.grounding_problems(_gold(fact), _SOURCES) == problems


def test_a_date_form_naming_a_competing_date_is_refused_at_authoring(
    gold_module: ModuleType, tmp_path: Path
) -> None:
    """Seed A's sources hold both dates (hembesök 2026-10-05, beslut senast
    2026-11-30): a form of 2026-11-30 must still be that date."""

    facts = [_fact("datum", "2026-11-30", ["2026-11-30", "2026-10-05"], kind="date")]

    with raises(ValueError, match="not the date 2026-11-30"):
        gold_module.load_gold(_corpus(tmp_path, [_entry("a" * 64, facts)]))


def test_gold_that_drops_or_alters_a_case_literal_is_refused(
    gold_module: ModuleType,
) -> None:
    gold = _gold(
        _fact("avstand", "30", ["30"], kind="number", unit="meter"), forbidden=["x"]
    )

    problems = gold_module.coverage_problems(
        gold, output_kind="docx", required=["30 m"], forbidden=["y"]
    )

    assert problems == [
        "required '30 m' is no form of a gold fact",
        "forbidden 'y' is not forbidden by the gold",
        "output_kind 'text' is not the case's 'docx'",
    ]
    # A unit spelling the gold carries covers the case's literal exactly.
    wider = _gold(
        _fact("avstand", "30", ["30"], kind="number", unit="m", unit_forms=["meter"])
    )
    assert (
        gold_module.coverage_problems(
            wider, output_kind="text", required=["30 m"], forbidden=[]
        )
        == []
    )


def test_gold_that_drops_a_case_association_is_refused(
    gold_module: ModuleType,
) -> None:
    associations = [("30 m", "avstånd", "höjd"), ("22 m", "höjd", "avstånd")]
    unplaced = _gold(_fact("a", "30 m", ["30 m"]), _fact("b", "22 m", ["22 m"]))
    placed = _gold(
        {
            **_fact("a", "30 m", ["30 m"]),
            "location": {"kind": "line", "with": ["avstånd"], "not_with": ["höjd"]},
        },
        {
            **_fact("b", "22 m", ["22 m"]),
            "location": {"kind": "line", "with": ["höjd"], "not_with": ["avstånd"]},
        },
    )

    def problems(gold: Any) -> list[str]:
        return gold_module.coverage_problems(
            gold,
            output_kind="text",
            required=["30 m", "22 m"],
            forbidden=[],
            associations=associations,
        )

    assert problems(unplaced) == [
        "association of '30 m' is no line location of its fact",
        "association of '22 m' is no line location of its fact",
    ]
    assert problems(placed) == []


def test_a_stale_entry_is_refused_by_the_check(
    gold_module: ModuleType, tmp_path: Path
) -> None:
    entries = json.loads(gold_module.GOLD_FILE.read_text(encoding="utf-8"))["entries"]
    entries[0]["sources_sha256"] = "f" * 64

    problems = gold_module.check(_corpus(tmp_path, entries))

    assert len(problems) == 1 and "stale" in problems[0]


# --- edit-seed calibration is decided by the gold authored from each seed --------


def _calibration_run(text: str) -> dict[str, Any]:
    return {
        "execution": {"outcome": "completed", "failures": []},
        "run": {"result": {"kind": "inline_text", "text": text}},
        "run_contract": {"final_output": {"output_type": "text"}},
        "final_artifact": {},
    }


_SEED_A = (
    "Hej Ingrid Wästberg,\n\nDitt ärende har diarienummer BAB-2026-0417. "
    "Det sökta beloppet är {amount} kr och sista datum är {date}."
)


@mark.parametrize(
    ("seed", "text", "passed"),
    [
        ("edit_seed_a.json", _SEED_A.format(amount="48500", date="2026-11-30"), True),
        ("edit_seed_a.json", _SEED_A.format(amount="2026-11-30", date="48500"), False),
        (
            "edit_seed_g.json",
            "Diarienummer: BAB-2026-0588\nBelopp: 57300 kr\nSista datum: 2027-01-15",
            True,
        ),
        (
            "edit_seed_g.json",
            "Diarienummer: BAB-2026-0588\nBelopp: 2027-01-15\nSista datum: 57300",
            False,
        ),
        (
            "edit_seed_g.json",
            "Diarienummer: BAB-2026-0588\nBelopp: 57300 kr\nSista datum: 2027-01-15\n"
            "Tidigare bidrag: 12400 kr",
            False,
        ),
        (
            "edit_seed_a.json",
            "Hej Ingrid Wästberg,\nDiarienummer BAB-2026-0417. Belopp 48500 kr. "
            "Sista datum: 2026-10-05. Beslut önskas senast 2026-11-30.",
            False,
        ),
        (
            "edit_seed_a.json",
            "Hej Ingrid Wästberg,\nDiarienummer BAB-2026-0417. Belopp 99999 kr. "
            "Belopp 48500 kr. Sista datum 2026-11-30.",
            False,
        ),
        (
            "edit_seed_a.json",
            "Hej Ingrid Wästberg,\nDiarienummer: BAB-2026-0000. Ärendet BAB-2026-0417 "
            "Belopp 48500 kr. Sista datum 2026-11-30.",
            False,
        ),
        # The seeds state their currency (kr) but never require it: a glued
        # other unit fails; a bare amount holds, its currency unmeasured.
        (
            "edit_seed_a.json",
            _SEED_A.format(amount="48500", date="2026-11-30").replace(" kr ", "euro "),
            False,
        ),
        (
            "edit_seed_a.json",
            _SEED_A.format(amount="48500", date="2026-11-30").replace(" kr ", "öre "),
            False,
        ),
        (
            "edit_seed_g.json",
            "Diarienummer: BAB-2026-0588\nBelopp: 57300\nSista datum: 2027-01-15",
            True,
        ),
        (
            "edit_seed_g.json",
            "Diarienummer: BAB-2026-0588\nBelopp: 57300euro\nSista datum: 2027-01-15",
            False,
        ),
    ],
    ids=[
        "a_right",
        "a_swapped",
        "g_right",
        "g_swapped",
        "g_forbidden",
        "a_other_date_under_its_label",
        "a_label_twice_two_amounts",
        "a_other_id_under_its_label",
        "a_glued_euro",
        "a_glued_ore",
        "g_bare_amount_currency_unmeasured",
        "g_glued_euro",
    ],
)
def test_a_seed_calibration_run_is_decided_by_its_own_gold(
    harness: ModuleType, seed: str, text: str, passed: bool
) -> None:
    fixture = harness._load_seed_flow_fixture(seed)  # pyright: ignore[reportPrivateUsage]

    assert harness.calibration_run_passed(fixture, _calibration_run(text)) is passed


def test_gold_applies_only_to_the_sources_it_was_authored_from(
    harness: ModuleType,
) -> None:
    """A seed whose bytes changed is not the seed the gold was authored from:
    its calibration keeps its own literals, and two of them unbound cannot
    decide a swap."""

    fixture = copy.deepcopy(
        harness._load_seed_flow_fixture("edit_seed_g.json")  # pyright: ignore[reportPrivateUsage]
    )
    fixture["description"] = "changed"
    text = "Diarienummer: BAB-2026-0588\nBelopp: 57300\nSista datum: 2027-01-15"

    assert harness.calibration_run_passed(fixture, _calibration_run(text)) is None


def test_case_gold_is_read_by_the_case_contract_at_load_and_refused_if_it_drops_a_fact(
    harness: ModuleType,
    gold_module: ModuleType,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases_file = _SCRIPTS / "ai_builder_api_municipal_cases.json"
    case = next(c for c in harness._read_cases_file(cases_file) if c.executes)  # pyright: ignore[reportPrivateUsage]
    sha = harness._case_contract_sha256(case)  # pyright: ignore[reportPrivateUsage]
    expect = case.execution.expect
    facts = [
        _fact(f"f{i}", literal, [literal])
        for i, literal in enumerate(expect.required_facts)
    ]
    entry = _entry(
        sha, facts, output_kind=expect.output_kind, forbidden=list(expect.forbidden)
    )
    entry["subject"] = f"case:{cases_file.name}:{case.case_id}"
    monkeypatch.setattr(gold_module, "GOLD_FILE", _corpus(tmp_path, [entry]))

    loaded = next(
        c
        for c in harness._read_cases_file(cases_file)
        if c.case_id == case.case_id  # pyright: ignore[reportPrivateUsage]
    )
    assert loaded.execution.expect.gold is not None
    assert harness._case_contract_sha256(loaded) == sha  # pyright: ignore[reportPrivateUsage]

    entry["gold"]["facts"] = facts[1:]
    _corpus(tmp_path, [entry])
    with raises(ValueError, match="no form of a gold fact"):
        harness._read_cases_file(cases_file)  # pyright: ignore[reportPrivateUsage]


# --- identity: a receipt names the gold it was scored under ---------------------


def test_the_scorer_names_its_output_gold_and_digests_the_corpus(
    harness: ModuleType, gold_module: ModuleType
) -> None:
    identity = harness._suite_evaluator_identity(  # pyright: ignore[reportPrivateUsage]
        release_identity={"build": {"harness_sha256": "a" * 64}},
        run_context={},
        expected_observations=[],
    )

    assert harness.SCORER_SEMANTICS_VERSION == 4
    assert identity["output_gold_sha256"] == gold_module.gold_sha256()
    assert {"ai_builder_output_gold.json", "ai_builder_output_gold.py"} <= set(
        harness._SCORER_MODULES  # pyright: ignore[reportPrivateUsage]
    )


@mark.parametrize("waived", [False, True], ids=["plain", "harness_change_waived"])
def test_a_scorer_3_receipt_without_its_output_gold_is_refused(
    tmp_path: Path, waived: bool
) -> None:
    module = _compare_module()
    baseline = _scored_by(tmp_path, "base.json", scorer=(3, "a" * 64))
    current = _scored_by(tmp_path, "cur.json", scorer=(3, "a" * 64))

    with raises((SystemExit, ValueError), match="output_gold_sha256"):
        module.compare(baseline, current, allow_harness_change=waived)


@mark.parametrize("waived", [False, True], ids=["plain", "harness_change_waived"])
def test_receipts_scored_under_different_gold_are_incomparable(
    tmp_path: Path, waived: bool
) -> None:
    module = _compare_module()
    baseline = _scored_by(
        tmp_path, "base.json", scorer=(3, "a" * 64), output_gold_sha256="b" * 64
    )
    current = _scored_by(
        tmp_path, "cur.json", scorer=(3, "a" * 64), output_gold_sha256="c" * 64
    )

    with raises(SystemExit) as refused:
        module.compare(baseline, current, allow_harness_change=waived)

    assert str(refused.value).startswith("INCOMPARABLE")
    assert "output_gold_sha256" in str(refused.value)
    # Both arms rescored under the same gold compare.
    module.compare(
        baseline,
        _scored_by(
            tmp_path, "again.json", scorer=(3, "a" * 64), output_gold_sha256="b" * 64
        ),
    )

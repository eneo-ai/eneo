from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import mark, raises

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
PDF = "01_protokoll_bun_2026_02_25.pdf"
DOCX = "02_tjansteskrivelse_underlag.docx"
SOURCE = {"catalogue_id": "BYG-01", "url": "https://e-tjanster.sundsvall.se/bygglov"}
SOURCE_ENTRY = {
    "name": "Bygglov - tillbyggnad",
    "municipalities": ["Sundsvall"],
    "urls": ["https://e-tjanster.sundsvall.se/bygglov"],
    "legal_basis": ["PBL 9 kap. 2 §"],
}
SOURCES = {
    "version": 1,
    "research_date": "2026-09-26",
    "description": "test sources",
    "sources": {"BYG-01": SOURCE_ENTRY},
}


def _coverage() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ai_builder_corpus_coverage", SCRIPTS / "ai_builder_corpus_coverage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create(
    case_id: str,
    *,
    attachments: tuple[str, ...] = (),
    runtime: tuple[str, ...] = (),
    form: bool = False,
    output_kind: str | None = "text",
    expected: dict[str, Any] | None = None,
    forbidden: tuple[str, ...] = (),
) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": case_id,
        "prompt": f"Bygg ett flöde för {case_id}.",
        "attachments": list(attachments),
        "expected": expected or {"min_steps": 1},
        "source": SOURCE,
    }
    if output_kind is not None:
        inputs: dict[str, Any] = (
            {"files": list(runtime)} if runtime else {"text": "Ansökan."}
        )
        if form:
            inputs["form_fields"] = {"diarienummer": "BAB-2026-0417"}
        case["apply_plan"] = True
        case["execution"] = {
            "inputs": inputs,
            "expect": {
                "output_kind": output_kind,
                "required_facts": ["BAB-2026-0417"],
                "forbidden": list(forbidden),
            },
        }
    return case


def _edit(
    case_id: str, *, gold: bool = True, cohorts: tuple[str, ...] = ()
) -> dict[str, Any]:
    edit: dict[str, Any] = {
        "seed_flow_fixture": "edit_seed_a.json",
        "scope": "selected_step",
        "target_step_order": 2,
    }
    if gold:
        edit["expect"] = {
            "outcome": "declined",
            "decline_reason": "model_choice_belongs_to_step_editor",
        }
    return {
        "id": case_id,
        "prompt": "Byt språkmodell i det här steget.",
        "cohorts": list(cohorts),
        "edit": edit,
        "source": SOURCE,
    }


def _dialogue(case_id: str, expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case_id,
        "prompt": f"Hjälp mig med {case_id}.",
        "cohorts": ["dialogue"],
        "expected": expected,
        "source": SOURCE,
    }


def _policy(**overrides: Any) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "version": 2,
        "description": "test tier",
        "require_source": True,
        "builder_inputs": {"pdf": 1},
        "runtime_inputs": {"text": 1},
        "output_kinds": {"text": 1},
        "smoke": {"ids": [], "create": 0, "edit": 0, "dialogue": 0},
    }
    policy.update(overrides)
    return policy


def _check(
    tmp_path: Path, cases: list[dict[str, Any]], policy: dict[str, Any]
) -> list[str]:
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps({"version": 9, "cases": cases}), encoding="utf-8")
    coverage = _coverage()
    loaded = coverage.load_cases(cases_file)
    return coverage.check(
        loaded, coverage.parse_policy(policy), coverage.parse_sources(SOURCES)
    )


def test_a_tier_that_meets_its_policy_has_no_problems(tmp_path: Path) -> None:
    assert _check(tmp_path, [_create("a", attachments=(PDF,))], _policy()) == []


def test_a_required_input_class_that_is_absent_fails_not_only_a_small_one(
    tmp_path: Path,
) -> None:
    problems = _check(tmp_path, [_create("a", attachments=(DOCX,))], _policy())

    assert "builder input 'pdf': 0 cases, policy requires 1" in problems


def test_builder_and_runtime_inputs_are_separate_axes(tmp_path: Path) -> None:
    # The PDF reaches the run, not the Builder: it does not cover the Builder axis.
    cases = [_create("a", runtime=(PDF,), form=True)]

    problems = _check(
        tmp_path, cases, _policy(runtime_inputs={"pdf": 1, "form": 1, "text": 1})
    )

    assert problems == [
        "builder input 'pdf': 0 cases, policy requires 1",
        "runtime input 'text': 0 cases, policy requires 1",
    ]


def test_typed_runtime_text_does_not_count_as_a_text_file(tmp_path: Path) -> None:
    problems = _check(
        tmp_path, [_create("a", attachments=(PDF,))], _policy(runtime_inputs={"txt": 1})
    )

    assert problems == ["runtime input 'txt': 0 cases, policy requires 1"]


def test_an_output_kind_counts_only_for_a_case_that_runs_a_flow(tmp_path: Path) -> None:
    # The plan-level expectation names a text output, but nothing runs.
    cases = [
        _create(
            "a",
            attachments=(PDF,),
            output_kind=None,
            expected={"terminal_output_type": "text"},
        )
    ]

    problems = _check(tmp_path, cases, _policy())

    assert "output 'text': 0 executed cases, policy requires 1" in problems


def test_smoke_composition_and_execution_are_enforced(tmp_path: Path) -> None:
    cases = [
        _create("a", attachments=(PDF,)),
        _create("b", attachments=(PDF,), output_kind=None),
        _create("c", attachments=(PDF,)),
        _edit("e"),
    ]
    smoke = {"ids": ["a", "b", "c", "missing"], "create": 2, "edit": 1, "dialogue": 1}

    problems = _check(tmp_path, cases, _policy(smoke=smoke))

    assert problems == [
        "case 'b' has no scored oracle (a create case needs a run)",
        "smoke id 'missing' is not a case in this tier",
        "smoke has 3 create cases, policy requires 2",
        "smoke has 0 edit cases, policy requires 1",
        "smoke has 0 dialogue cases, policy requires 1",
        "smoke create 'b' has no executed output kind",
    ]


def test_smoke_output_coverage_counts_only_its_create_cases(tmp_path: Path) -> None:
    edit_with_run = _edit("e")
    edit_with_run.update(
        apply_plan=True, execution=_create("x", output_kind="json")["execution"]
    )
    cases = [
        _create("a", attachments=(PDF,)),
        _create("b", output_kind="json"),
        edit_with_run,
    ]
    smoke = {"ids": ["a", "e"], "create": 1, "edit": 1, "dialogue": 0}

    problems = _check(
        tmp_path, cases, _policy(output_kinds={"text": 1, "json": 1}, smoke=smoke)
    )

    assert problems == ["smoke covers no executed 'json' output"]


def test_every_case_needs_a_pinned_source_with_a_matching_url(tmp_path: Path) -> None:
    unknown = _create("a", attachments=(PDF,))
    unknown["source"] = {"catalogue_id": "OMS-01", "url": "https://x.se/a"}
    wrong_url = _create("b", attachments=(PDF,))
    wrong_url["source"] = {"catalogue_id": "BYG-01", "url": "https://x.se/b"}
    missing = _create("c", attachments=(PDF,))
    del missing["source"]
    cases = [unknown, wrong_url, missing]

    assert _check(tmp_path, cases, _policy()) == [
        "case 'a': source 'OMS-01' is not in the pinned sources",
        "case 'b': url https://x.se/b is not a pinned url of 'BYG-01'",
        "case 'c' has no source",
    ]
    assert _check(tmp_path, cases, _policy(require_source=False)) == []


_DIALOGUE = "dialogue needs a question expectation that can fail"


@mark.parametrize(
    ("case", "hint"),
    [
        (
            _dialogue(
                "d",
                {
                    "preferred_question_event_ids": ["terminal_output"],
                    "allow_question_instead_of_plan": True,
                },
            ),
            _DIALOGUE,
        ),
        (_dialogue("d", {"min_steps": 1}), _DIALOGUE),
        (_dialogue("d", {"expected_question_event_ids": []}), _DIALOGUE),
        (_dialogue("d", {"min_question_event_count": 0}), _DIALOGUE),
        (
            _create("d", output_kind=None, expected={"min_steps": 1}),
            "a create case needs a run",
        ),
        (_edit("d", gold=False), "an edit case needs edit gold"),
    ],
)
def test_a_case_without_a_scoring_oracle_is_reported(
    tmp_path: Path, case: dict[str, Any], hint: str
) -> None:
    problems = _check(tmp_path, [_create("a", attachments=(PDF,)), case], _policy())

    assert problems == [f"case 'd' has no scored oracle ({hint})"]


def test_scored_dialogue_and_edit_cases_pass_and_an_edit_stays_an_edit(
    tmp_path: Path,
) -> None:
    cases = [
        _create("a", attachments=(PDF,)),
        _dialogue("d", {"forbidden_question_event_ids": ["terminal_output"]}),
        _edit("e", cohorts=("dialogue",)),
    ]
    smoke = {"ids": ["a", "d", "e"], "create": 1, "edit": 1, "dialogue": 1}

    assert _check(tmp_path, cases, _policy(smoke=smoke)) == []


@mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p.pop("require_source"), "exactly the keys"),
        (lambda p: p.update(require_sources=True), "exactly the keys"),
        (lambda p: p.update(version=1), "version must be 2"),
        (
            lambda p: p.update(require_source="yes"),
            "require_source must be true or false",
        ),
        (lambda p: p["builder_inputs"].update(pdf=0), "at least 1"),
        (lambda p: p["builder_inputs"].update(pdf=1.5), "at least 1"),
        (lambda p: p["builder_inputs"].update(pdf=True), "at least 1"),
        (lambda p: p["output_kinds"].update(html=1), "unknown class 'html'"),
        (lambda p: p.update(features={}), "exactly the keys"),
        (
            lambda p: p.update(
                smoke={"ids": ["a", "a"], "create": 2, "edit": 0, "dialogue": 0}
            ),
            "smoke ids must be unique",
        ),
        (
            lambda p: p.update(
                smoke={"ids": ["a"], "create": 2, "edit": 0, "dialogue": 0}
            ),
            "must add up",
        ),
    ],
)
def test_a_malformed_policy_is_an_error_never_a_pass(change: Any, message: str) -> None:
    policy = copy.deepcopy(_policy())
    change(policy)

    with raises(ValueError, match=message):
        _coverage().parse_policy(policy)


@mark.parametrize(
    ("change", "message"),
    [
        (lambda s: s.pop("version"), "exactly version, research_date"),
        (lambda s: s.update(version=2), "version 1"),
        (lambda s: s.update(version=True), "version 1"),
        (lambda s: s.update(research_date=None), "ISO research_date"),
        (lambda s: s.update(research_date="hösten 2026"), "ISO research_date"),
        (lambda s: s.update(description=[]), "a description"),
        (lambda s: s["sources"]["BYG-01"].pop("legal_basis"), "exactly name"),
        (lambda s: s["sources"]["BYG-01"].update(municipalities=[]), "municipalities"),
        (lambda s: s["sources"]["BYG-01"].update(name=" "), "a name"),
        (
            lambda s: s["sources"]["BYG-01"].update(urls=SOURCE_ENTRY["urls"][0]),
            "https urls",
        ),
        (lambda s: s["sources"]["BYG-01"].update(urls=["http://x.se/a"]), "https urls"),
        (lambda s: s["sources"]["BYG-01"].update(urls=["https://"]), "https urls"),
        (
            lambda s: s["sources"]["BYG-01"].update(
                urls=["https://example.org:bad/path"]
            ),
            "https urls",
        ),
        (
            lambda s: s["sources"].update({"byg-1": SOURCE_ENTRY}),
            "must look like BYG-01",
        ),
    ],
)
def test_a_malformed_sources_file_is_an_error(change: Any, message: str) -> None:
    sources = copy.deepcopy(SOURCES)
    change(sources)

    with raises(ValueError, match=message):
        _coverage().parse_sources(sources)


@mark.parametrize(
    ("expected", "message"),
    [
        ({"min_steps": None}, "must not be null"),
        ({"min_steps": "3"}, "non-negative integer"),
        ({"max_question_event_count": -1}, "non-negative integer"),
        ({"min_json_steps": True}, "non-negative integer"),
        ({"expected_question_event_ids": "terminal_output"}, "list of unique"),
    ],
)
def test_the_harness_refuses_an_expectation_that_would_check_nothing(
    tmp_path: Path, expected: dict[str, Any], message: str
) -> None:
    cases_file = tmp_path / "cases.json"
    case = _create("a", attachments=(PDF,), expected=expected)
    cases_file.write_text(json.dumps({"version": 9, "cases": [case]}), encoding="utf-8")

    with raises(ValueError, match=message):
        _coverage().load_cases(cases_file)


@mark.parametrize(
    ("source", "message"),
    [
        ({"catalogue_id": "BYG-01", "url": "http://insecure"}, "must be an https URL"),
        ({"catalogue_id": "BYG-01", "url": "https://"}, "must be an https URL"),
        (
            {"catalogue_id": "BYG-01", "url": "https://example.org:bad/path"},
            "must be an https URL",
        ),
        ({"catalogue_id": "BYG-٠١", "url": SOURCE["url"]}, "must look like BYG-01"),
        ({**SOURCE, "name": "Bygglov"}, "exactly catalogue_id and url"),
    ],
)
def test_the_harness_rejects_a_malformed_source(
    tmp_path: Path, source: dict[str, str], message: str
) -> None:
    case = _create("a", attachments=(PDF,))
    case["source"] = source
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps({"version": 9, "cases": [case]}), encoding="utf-8")

    with raises(ValueError, match=message):
        _coverage().load_cases(cases_file)


def test_a_source_is_part_of_the_case_and_its_contract_only_when_present(
    tmp_path: Path,
) -> None:
    cases_file = tmp_path / "cases.json"
    plain = _create("b", attachments=(PDF,))
    del plain["source"]
    cases_file.write_text(
        json.dumps({"version": 9, "cases": [_create("a", attachments=(PDF,)), plain]}),
        encoding="utf-8",
    )
    with_source, without = _coverage().load_cases(cases_file)
    harness = sys.modules["ai_builder_api_battle_test"]

    assert (with_source.source.catalogue_id, with_source.source.url) == (
        SOURCE["catalogue_id"],
        SOURCE["url"],
    )
    assert harness._case_contract_payload(with_source)["source"] == SOURCE
    # Cases without provenance keep their exact contract, so no existing hash moves.
    assert "source" not in harness._case_contract_payload(without)


def test_the_tracked_policy_and_sources_are_well_formed() -> None:
    coverage = _coverage()
    policy = coverage.parse_policy(
        json.loads(
            (SCRIPTS / "ai_builder_municipal_policy.json").read_text(encoding="utf-8")
        )
    )
    coverage.parse_sources(
        json.loads(
            (SCRIPTS / "ai_builder_municipal_sources.json").read_text(encoding="utf-8")
        )
    )

    assert policy.require_source is True
    # The corpus plan's smoke composition.
    assert dict(policy.smoke_kinds) == {"create": 12, "edit": 5, "dialogue": 3}

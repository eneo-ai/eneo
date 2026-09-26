"""What one tier's case file measures, derived from the cases the sealed runner reads, checked against its policy.

Every count comes from the parsed cases (the harness's own parser), never from prose. The Builder-visible inputs
(attachments) and the runtime inputs (what a run is given) are separate axes; typed runtime text is `text`, a text
FILE is `txt`. An output kind counts only for a case that runs a flow, and smoke output coverage only for its create
cases. A case's kind is structural (edit when it has an edit block), except dialogue, which the case declares with
the `dialogue` cohort. A case is scored only by an oracle that can fail: a create case must run a flow (the harness
refuses a run without an output kind or facts), an edit needs edit gold, a dialogue case a question expectation the
harness judges effective. Features (review, templates, secrecy, ...) are counted once their gold lands (corpus H2).

The policy file is the target of the next batch until that batch lands, then what the tier guarantees; it is raised
batch by batch (minimums per class, smoke membership, whether every case needs a pinned source). A malformed policy
or sources file is an error, never a pass.

usage: python scripts/ai_builder_corpus_coverage.py <cases-file> <policy-file> <sources-file>
"""

from __future__ import annotations

import argparse
import collections
import datetime
import importlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

POLICY_VERSION = 2
_FILE_KINDS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".json": "json",
    ".txt": "txt",
    ".md": "txt",
    ".wav": "audio",
    ".mp3": "audio",
    ".m4a": "audio",
    ".pptx": "pptx",
}
_BUILDER_INPUTS = frozenset(_FILE_KINDS.values())
_RUNTIME_INPUTS = _BUILDER_INPUTS | {"text", "form"}
_KINDS = ("create", "edit", "dialogue")
_ORACLE_HINT = {
    "create": "a create case needs a run",
    "edit": "an edit case needs edit gold",
    "dialogue": "dialogue needs a question expectation that can fail",
}


@dataclass(frozen=True, slots=True)
class Policy:
    require_source: bool
    builder_inputs: Mapping[str, int]
    runtime_inputs: Mapping[str, int]
    output_kinds: Mapping[str, int]
    smoke_ids: tuple[str, ...]
    smoke_kinds: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CaseCoverage:
    case_id: str
    kind: str
    executed: bool
    builder_inputs: frozenset[str]
    runtime_inputs: frozenset[str]
    output_kind: str | None
    scored: bool


def _harness() -> ModuleType:
    return importlib.import_module("ai_builder_api_battle_test")


def _minimums(raw: object, *, key: str, allowed: frozenset[str]) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"policy {key} must be an object of class -> minimum.")
    minimums: dict[str, int] = {}
    for name, minimum in cast(Mapping[str, object], raw).items():
        if name not in allowed:
            raise ValueError(f"policy {key} names unknown class {name!r}.")
        if type(minimum) is not int or minimum < 1:
            raise ValueError(f"policy {key}.{name} must be an integer of at least 1.")
        minimums[name] = minimum
    return minimums


def parse_policy(raw: object) -> Policy:
    keys = {
        "version",
        "description",
        "require_source",
        "builder_inputs",
        "runtime_inputs",
        "output_kinds",
        "smoke",
    }
    if not isinstance(raw, Mapping) or set(cast(Mapping[str, object], raw)) != keys:
        raise ValueError(f"policy must have exactly the keys {sorted(keys)}.")
    policy = cast(Mapping[str, object], raw)
    if policy["version"] != POLICY_VERSION:
        raise ValueError(f"policy version must be {POLICY_VERSION}.")
    require_source = policy["require_source"]
    if not isinstance(require_source, bool):
        raise ValueError("policy require_source must be true or false.")
    smoke = policy["smoke"]
    if not isinstance(smoke, Mapping) or set(cast(Mapping[str, object], smoke)) != {
        "ids",
        *_KINDS,
    }:
        raise ValueError(
            "policy smoke must have exactly ids, create, edit and dialogue."
        )
    smoke = cast(Mapping[str, object], smoke)
    ids = smoke["ids"]
    if not isinstance(ids, list) or not all(
        isinstance(i, str) for i in cast(list[object], ids)
    ):
        raise ValueError("policy smoke ids must be a list of case ids.")
    ids = cast(list[str], ids)
    if len(set(ids)) != len(ids):
        raise ValueError("policy smoke ids must be unique.")
    kinds: dict[str, int] = {}
    for kind in _KINDS:
        count = smoke[kind]
        if type(count) is not int or count < 0:
            raise ValueError("policy smoke counts must be integers of at least 0.")
        kinds[kind] = count
    if sum(kinds.values()) != len(ids):
        raise ValueError("policy smoke counts must add up to the number of smoke ids.")
    return Policy(
        require_source=require_source,
        builder_inputs=_minimums(
            policy["builder_inputs"], key="builder_inputs", allowed=_BUILDER_INPUTS
        ),
        runtime_inputs=_minimums(
            policy["runtime_inputs"], key="runtime_inputs", allowed=_RUNTIME_INPUTS
        ),
        output_kinds=_minimums(
            policy["output_kinds"],
            key="output_kinds",
            allowed=frozenset(_harness()._OUTPUT_KINDS),
        ),
        smoke_ids=tuple(ids),
        smoke_kinds=kinds,
    )


def _strings(value: object) -> list[str] | None:
    """A non-empty list of non-empty strings, else None."""

    if not isinstance(value, list) or not value:
        return None
    items = cast(list[object], value)
    if not all(isinstance(item, str) and item.strip() for item in items):
        return None
    return cast(list[str], items)


def _is_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_sources(raw: object) -> dict[str, frozenset[str]]:
    """Pinned catalogue id -> its source urls, after checking the whole pinned-evidence schema."""

    if not isinstance(raw, Mapping) or set(cast(Mapping[str, object], raw)) != {
        "version",
        "research_date",
        "description",
        "sources",
    }:
        raise ValueError(
            "sources file must have exactly version, research_date, description and sources."
        )
    root = cast(Mapping[str, object], raw)
    sources = root["sources"]
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("sources file must be version 1.")
    if _strings([root["description"]]) is None or not _is_date(root["research_date"]):
        raise ValueError("sources file needs a description and an ISO research_date.")
    if not isinstance(sources, Mapping) or not sources:
        raise ValueError("sources file needs a non-empty sources object.")
    harness = _harness()
    pinned: dict[str, frozenset[str]] = {}
    for catalogue_id, entry in cast(Mapping[str, object], sources).items():
        if not harness._CATALOGUE_ID.fullmatch(catalogue_id):
            raise ValueError(f"source id {catalogue_id!r} must look like BYG-01.")
        if not isinstance(entry, Mapping) or set(cast(Mapping[str, object], entry)) != {
            "name",
            "municipalities",
            "urls",
            "legal_basis",
        }:
            raise ValueError(
                f"source {catalogue_id} must have exactly name, municipalities, urls and legal_basis."
            )
        fields = cast(Mapping[str, object], entry)
        urls = _strings(fields["urls"])
        if (
            _strings([fields["name"]]) is None
            or _strings(fields["municipalities"]) is None
            or _strings(fields["legal_basis"]) is None
        ):
            raise ValueError(
                f"source {catalogue_id} needs a name, municipalities and a legal basis."
            )
        if urls is None or not all(harness._is_https_url(url) for url in urls):
            raise ValueError(f"source {catalogue_id} needs a list of https urls.")
        pinned[catalogue_id] = frozenset(urls)
    return pinned


def _file_kind(name: str) -> str:
    return _FILE_KINDS.get(Path(name).suffix.lower(), "other")


def case_coverage(case: Any) -> CaseCoverage:
    kind = (
        "edit"
        if case.edit is not None
        else "dialogue"
        if "dialogue" in case.cohorts
        else "create"
    )
    runtime: set[str] = set()
    output_kind: str | None = None
    if case.execution is not None:
        inputs = case.execution.inputs
        runtime |= {_file_kind(name) for name in inputs.files}
        if inputs.text:
            runtime.add("text")
        if inputs.form_fields:
            runtime.add("form")
        output_kind = case.execution.expect.output_kind
    if case.edit is not None:
        scored = case.edit.gold is not None
    elif kind == "dialogue":
        scored = _harness()._has_question_oracle(case.expected or {})
    else:
        scored = case.execution is not None
    return CaseCoverage(
        case_id=case.case_id,
        kind=kind,
        executed=case.execution is not None,
        builder_inputs=frozenset(_file_kind(name) for name in case.attachments),
        runtime_inputs=frozenset(runtime),
        output_kind=output_kind,
        scored=scored,
    )


def load_cases(path: Path) -> list[Any]:
    """The tier's cases through the harness's own parser, so coverage sees what a sealed run sees."""

    return _harness()._read_cases_file(path)


def check(
    cases: Sequence[Any], policy: Policy, sources: Mapping[str, frozenset[str]]
) -> list[str]:
    rows = [case_coverage(case) for case in cases]
    problems: list[str] = []
    for axis, minimums, attribute in (
        ("builder input", policy.builder_inputs, "builder_inputs"),
        ("runtime input", policy.runtime_inputs, "runtime_inputs"),
    ):
        for kind, minimum in minimums.items():
            count = sum(kind in getattr(row, attribute) for row in rows)
            if count < minimum:
                problems.append(
                    f"{axis} '{kind}': {count} cases, policy requires {minimum}"
                )
    for kind, minimum in policy.output_kinds.items():
        count = sum(row.output_kind == kind for row in rows)
        if count < minimum:
            problems.append(
                f"output '{kind}': {count} executed cases, policy requires {minimum}"
            )
    problems += [
        f"case '{row.case_id}' has no scored oracle ({_ORACLE_HINT[row.kind]})"
        for row in rows
        if not row.scored
    ]
    problems += _smoke_problems({row.case_id: row for row in rows}, policy)
    if policy.require_source:
        problems += _source_problems(cases, sources)
    return problems


def _smoke_problems(rows: Mapping[str, CaseCoverage], policy: Policy) -> list[str]:
    problems = [
        f"smoke id '{case_id}' is not a case in this tier"
        for case_id in policy.smoke_ids
        if case_id not in rows
    ]
    members = [rows[case_id] for case_id in policy.smoke_ids if case_id in rows]
    counts = collections.Counter(row.kind for row in members)
    problems += [
        f"smoke has {counts[kind]} {kind} cases, policy requires {required}"
        for kind, required in policy.smoke_kinds.items()
        if counts[kind] != required
    ]
    creates = [row for row in members if row.kind == "create"]
    problems += [
        f"smoke create '{row.case_id}' has no executed output kind"
        for row in creates
        if row.output_kind is None
    ]
    if members:
        covered = {row.output_kind for row in creates}
        problems += [
            f"smoke covers no executed '{kind}' output"
            for kind in policy.output_kinds
            if kind not in covered
        ]
    return problems


def pinned_source_problem(
    owner: str, catalogue_id: str, url: str, pinned: Mapping[str, frozenset[str]]
) -> str | None:
    """Why a claimed source is not pinned evidence, or None. Cases and fixture specs share this rule."""

    urls = pinned.get(catalogue_id)
    if urls is None:
        return f"{owner}: source '{catalogue_id}' is not in the pinned sources"
    if url not in urls:
        return f"{owner}: url {url} is not a pinned url of '{catalogue_id}'"
    return None


def _source_problems(
    cases: Sequence[Any], pinned: Mapping[str, frozenset[str]]
) -> list[str]:
    problems: list[str] = []
    for case in cases:
        if case.source is None:
            problems.append(f"case '{case.case_id}' has no source")
            continue
        problem = pinned_source_problem(
            f"case '{case.case_id}'", case.source.catalogue_id, case.source.url, pinned
        )
        if problem is not None:
            problems.append(problem)
    return problems


def _report(rows: Sequence[CaseCoverage]) -> str:
    def tally(values: Sequence[str]) -> str:
        return ", ".join(
            f"{name} {count}"
            for name, count in sorted(collections.Counter(values).items())
        )

    def kinds(kind: str) -> str:
        of_kind = [row for row in rows if row.kind == kind]
        executed = sum(row.executed for row in of_kind)
        return f"{kind} {len(of_kind)} (executed {executed}, not executed {len(of_kind) - executed})"

    return "\n".join(
        (
            f"cases: {'; '.join(kinds(kind) for kind in _KINDS)}",
            f"builder inputs: {tally([kind for row in rows for kind in row.builder_inputs])}",
            f"runtime inputs: {tally([kind for row in rows for kind in row.runtime_inputs])}",
            "executed outputs: "
            + tally([row.output_kind or "facts only" for row in rows if row.executed]),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a tier's case file against its coverage policy."
    )
    parser.add_argument("cases_file", type=Path)
    parser.add_argument("policy_file", type=Path)
    parser.add_argument("sources_file", type=Path)
    args = parser.parse_args(argv)
    # The table registry first: the flows packages import each other through it, so an entry point loads it
    # before them (demo scripts do the same).
    importlib.import_module("eneo.database.tables")
    cases = load_cases(args.cases_file)
    try:
        policy = parse_policy(json.loads(args.policy_file.read_text(encoding="utf-8")))
        sources = parse_sources(
            json.loads(args.sources_file.read_text(encoding="utf-8"))
        )
    except ValueError as error:
        print(f"INVALID: {error}")
        return 2
    problems = check(cases, policy, sources)
    print(_report([case_coverage(case) for case in cases]))
    for problem in problems:
        print(f"PROBLEM: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

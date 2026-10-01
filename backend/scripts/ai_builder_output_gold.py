"""The output gold corpus: typed facts per subject, grounded in its own sources.

A subject is an executable seed's calibration block (`seed:<fixture>`) or an
executing create case (`case:<cases file>:<case id>`). Its entry holds the
subject's `OutputGold` (`ai_builder_edit_expectation`: each fact's typed value,
its accepted surface forms and its location) and the digest of the sources it
was authored from: the seed fixture as parsed, or the case contract. The
scorer applies an entry only to a run of exactly those sources
(`authored_gold`); any other run keeps the case's own literals, so a changed
case is never scored by stale gold. The entry is no part of the case contract:
a historical bundle of the same contract is rescored under it, and the
corpus digest (`gold_sha256`) is part of every receipt's scorer identity, so
two receipts compare only when both were scored under the same gold.

Authoring: `python ai_builder_output_gold.py sources SUBJECT` prints a
subject's sources and their digest; `check` refuses every entry that is stale,
drops or alters one of the case's own required facts or forbidden literals,
or holds a value, label or placeholder its sources do not (`grounding_problems`).
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

# The table modules first: the Builder modules the scorer imports reach them.
importlib.import_module("eneo.database.tables")

from ai_builder_edit_expectation import (  # noqa: E402
    FieldLocation,
    GoldFact,
    LineLocation,
    OutputGold,
    literal_appears,
    normalized_text,
)
from ai_builder_receipt import canonical_sha256  # noqa: E402
from pydantic import (  # noqa: E402
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    model_validator,
)

GOLD_FILE = Path(__file__).with_name("ai_builder_output_gold.json")
GOLD_VERSION = 1
_SUBJECT = r"^(seed:[\w.-]+\.json|case:[\w.-]+\.json:[\w.-]+)$"
# Input fixtures the authoring check reads as text, by the harness's own
# readers of a run's final output (a DOCX through the product's document text
# owner); any other fixture is listed unread, never parsed a second way.
_FIXTURE_READERS: Mapping[str, str] = {
    ".txt": "text",
    ".csv": "text",
    ".md": "text",
    ".json": "text",
    ".eml": "text",
    ".pdf": "pdf",
    ".docx": "docx",
}


class GoldEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: Annotated[str, StringConstraints(pattern=_SUBJECT)]
    sources_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    gold: OutputGold

    @model_validator(mode="after")
    def _one_fact_per_form(self) -> Self:
        forms = [
            normalized_text(form) for fact in self.gold.facts for form in fact.forms
        ]
        if len(set(forms)) != len(forms):
            raise ValueError(f"{self.subject}: a form names one fact")
        return self


class GoldCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    entries: list[GoldEntry]

    @model_validator(mode="after")
    def _one_entry_each(self) -> Self:
        for key in ("subject", "sources_sha256"):
            values = [getattr(entry, key) for entry in self.entries]
            if len(set(values)) != len(values):
                raise ValueError(f"each entry has its own {key}")
        return self


@functools.lru_cache(maxsize=8)
def _corpus(path: Path, digest: str) -> dict[str, GoldEntry]:
    try:
        corpus = GoldCorpus.model_validate_json(path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"{path}: {error}") from error
    return {entry.sources_sha256: entry for entry in corpus.entries}


def load_gold(path: Path | None = None) -> dict[str, GoldEntry]:
    """Every entry by its sources digest, validated on load."""

    path = path or GOLD_FILE
    return _corpus(path, gold_sha256(path))


def gold_sha256(path: Path | None = None) -> str:
    return hashlib.sha256((path or GOLD_FILE).read_bytes()).hexdigest()


def seed_sources_sha256(fixture: Mapping[str, Any]) -> str:
    """A seed subject's sources digest: the seed fixture as parsed."""

    return canonical_sha256(fixture)


def authored_gold(sources_sha256: str, path: Path | None = None) -> OutputGold | None:
    """The gold authored from exactly these sources, or None."""

    entry = load_gold(path).get(sources_sha256)
    return entry.gold if entry is not None else None


def coverage_problems(
    gold: OutputGold,
    *,
    output_kind: str | None,
    required: Sequence[str],
    forbidden: Sequence[str],
    associations: Sequence[tuple[str, str, str]] = (),
) -> list[str]:
    """What authored gold would change of the case's own expectation.

    Gold refines a case's literals, it never drops one: every required literal
    is exactly one accepted spelling of a fact (`GoldFact.spellings`: "22 m"
    is 22 with the unit spelled "m") or one of its forms (the gold adds the
    unit the sources state), every association (fact, with, not_with)
    stays a line location of that fact holding both literals, every forbidden
    literal stays forbidden and the output kind is the case's."""

    def spelled(fact: GoldFact, literal: str) -> bool:
        wanted = normalized_text(literal)
        return any(
            literal_appears(wanted, other) and literal_appears(other, wanted)
            for other in map(normalized_text, [*fact.spellings, *fact.forms])
        )

    kept = {normalized_text(literal) for literal in gold.forbidden}
    problems = [
        f"required {literal!r} is no form of a gold fact"
        for literal in required
        if not any(spelled(fact, literal) for fact in gold.facts)
    ]
    for fact_literal, with_, not_with in associations:
        placed = [
            fact.location
            for fact in gold.facts
            if spelled(fact, fact_literal) and isinstance(fact.location, LineLocation)
        ]
        if not any(
            normalized_text(with_) in map(normalized_text, location.with_)
            and normalized_text(not_with) in map(normalized_text, location.not_with)
            for location in placed
        ):
            problems.append(
                f"association of {fact_literal!r} is no line location of its fact"
            )
    problems += [
        f"forbidden {literal!r} is not forbidden by the gold"
        for literal in forbidden
        if normalized_text(literal) not in kept
    ]
    if gold.output_kind != output_kind:
        problems.append(
            f"output_kind {gold.output_kind!r} is not the case's {output_kind!r}"
        )
    return problems


def expectation_problems(gold: OutputGold, expect: Any) -> list[str]:
    """`coverage_problems` of gold against a case's OutputExpectation."""

    return coverage_problems(
        gold,
        output_kind=expect.output_kind,
        required=expect.required_facts,
        forbidden=expect.forbidden,
        associations=[
            (item.fact, item.with_, item.not_with) for item in expect.associations
        ],
    )


def grounding_problems(gold: OutputGold, sources: str) -> list[str]:
    """Every form, value, label, placeholder and forbidden literal the
    subject's sources do not hold, each on its own (`literal_appears`).

    Each form and each unit spelling must be in the sources, and the value
    too: as written, or as a form that holds it, so one grounded form never
    grounds another."""

    text = normalized_text(sources)

    def grounded(literal: str) -> bool:
        return literal_appears(normalized_text(literal), text)

    problems: list[str] = []
    for fact in gold.facts:
        problems += [
            f"{fact.id}: form {form!r} is not in the sources"
            for form in fact.forms
            if not grounded(form)
        ]
        problems += [
            f"{fact.id}: unit {unit!r} is not in the sources"
            for unit in fact.units
            if not grounded(unit)
        ]
        holding = [
            form
            for form in fact.forms
            if literal_appears(normalized_text(fact.value), normalized_text(form))
        ]
        if not any(grounded(spelling) for spelling in (fact.value, *holding)):
            problems.append(f"{fact.id}: {fact.value!r} is not in the sources")
        if isinstance(fact.location, FieldLocation):
            problems += [
                f"{fact.id}: label {label!r} is not in the sources"
                for label in fact.location.labels
                if not grounded(label)
            ]
            placeholder = fact.location.placeholder
            if placeholder and normalized_text(placeholder) not in text:
                problems.append(
                    f"{fact.id}: placeholder {placeholder!r} is not in the sources"
                )
    problems += [
        f"forbidden {literal!r} is not in the sources"
        for literal in gold.forbidden
        if not grounded(literal)
    ]
    return problems


# --- Subjects (authoring and the check; the harness is imported on use) ------


@dataclass(frozen=True)
class Subject:
    name: str
    sources_sha256: str
    sources: str
    unread: tuple[str, ...]
    # The subject's own output expectation (the harness's OutputExpectation).
    expect: Any


def _harness() -> Any:
    importlib.import_module("eneo.database.tables")
    return importlib.import_module("ai_builder_api_battle_test")


def subject(name: str) -> Subject:
    """A subject's sources, their digest and its own expectation."""

    harness = _harness()
    kind, _, rest = name.partition(":")
    if kind == "seed":
        fixture = harness._load_seed_flow_fixture(rest)
        calibration = cast(Mapping[str, Any], fixture.get("calibration") or {})
        if "expect" not in calibration:
            raise ValueError(f"{name} has no calibration block")
        expect = harness._output_expectation(calibration["expect"], owner=name)
        # The run's inputs and the flow it runs; the block's expectation is
        # the gold's to refine, never a source of it.
        sources = {**fixture, "calibration": {"inputs": calibration.get("inputs")}}
        return Subject(
            name,
            seed_sources_sha256(fixture),
            "\n".join(_strings(sources)),
            (),
            expect,
        )
    cases_file, _, case_id = rest.partition(":")
    cases = harness._read_cases_file(Path(harness.__file__).with_name(cases_file))
    case = next((case for case in cases if case.case_id == case_id), None)
    if case is None or case.execution is None:
        raise ValueError(f"{name} names no executing case")
    texts = [case.prompt, *_strings(case.configured_question_answers or {})]
    inputs = case.execution.inputs
    texts += _strings({"text": inputs.text, "form_fields": dict(inputs.form_fields)})
    unread: list[str] = []
    for fixture_name in (*case.attachments, *case.runtime_files):
        reader = _FIXTURE_READERS.get(Path(fixture_name).suffix.lower())
        if reader is None:
            unread.append(fixture_name)
            continue
        path = harness._verified_fixture_path(fixture_name, harness._fixture_manifest())
        texts.append(harness._FINAL_FILE_READERS[reader](path.read_bytes()))
    expect = case.execution.expect
    return Subject(
        name,
        harness._case_contract_sha256(case),
        "\n".join(texts),
        tuple(unread),
        expect,
    )


def _strings(value: object) -> list[str]:
    if isinstance(value, Mapping):
        return [
            text
            for item in cast(Mapping[str, object], value).values()
            for text in _strings(item)
        ]
    if isinstance(value, list):
        return [text for item in cast(list[object], value) for text in _strings(item)]
    if isinstance(value, bool) or value is None:
        return []
    return [str(value)] if isinstance(value, (str, int, float)) else []


def check(path: Path | None = None) -> list[str]:
    """Every problem of the corpus at `path`; empty when it may be used."""

    problems: list[str] = []
    for entry in load_gold(path).values():
        try:
            found = subject(entry.subject)
        except ValueError as error:
            problems.append(f"{entry.subject}: {error}")
            continue
        if found.sources_sha256 != entry.sources_sha256:
            problems.append(
                f"{entry.subject}: stale, its sources are now {found.sources_sha256}"
            )
            continue
        own = expectation_problems(entry.gold, found.expect) + grounding_problems(
            entry.gold, found.sources
        )
        if own and found.unread:
            own.append(f"unread sources (no text reader): {', '.join(found.unread)}")
        problems += [f"{entry.subject}: {problem}" for problem in own]
    return problems


def unit_notes(path: Path | None = None) -> list[str]:
    """Each amount whose unit the gold does not require: its currency or
    unit is unmeasured wherever it is delivered bare, never counted correct."""

    return [
        f"{entry.subject}: {fact.id} unit: unmeasured "
        f"({fact.unit!r} not required; a bare number holds)"
        for entry in load_gold(path).values()
        for fact in entry.gold.facts
        if fact.unit is not None and not fact.unit_required
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    checked = commands.add_parser("check", help="validate every entry of the corpus")
    checked.add_argument("--gold", type=Path, default=None)
    shown = commands.add_parser("sources", help="print a subject's sources and digest")
    shown.add_argument("subject")
    args = parser.parse_args(argv)
    if args.command == "sources":
        found = subject(args.subject)
        print(
            json.dumps(
                {
                    "subject": found.name,
                    "sources_sha256": found.sources_sha256,
                    "unread": list(found.unread),
                    "sources": found.sources,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    try:
        problems = check(args.gold)
    except ValueError as error:
        problems = [str(error)]
    for problem in problems:
        print(problem, file=sys.stderr)
    for note in [] if problems else unit_notes(args.gold):
        print(note)
    print(f"output gold {'REFUSED' if problems else 'ok'}: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

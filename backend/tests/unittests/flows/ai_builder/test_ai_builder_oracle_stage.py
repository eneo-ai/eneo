"""What an expert gold-spec author may see: the request the Builder gets, never the oracle."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
SENTINEL = "ORACLE-SENTINEL-2b9c"


def _load(name: str, filename: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def harness() -> ModuleType:
    return _load("ai_builder_api_battle_test", "ai_builder_api_battle_test.py")


@pytest.fixture()
def stage(harness: ModuleType) -> ModuleType:
    del harness  # the stage script finds the harness by name
    return _load("ai_builder_oracle_stage", "ai_builder_oracle_stage.py")


ANSWERS = {
    "terminal_output": {"selected_option_id": "docx_document"},
    "runtime_metadata_field_details": {
        "input_fields": [
            {
                "value": {
                    "name": "diarienummer",
                    "label": "Diarienummer",
                    "type": "text",
                    "required": True,
                    "options": [],
                },
                "purpose": "shape_result",
            }
        ]
    },
}


def _case(harness: ModuleType, attachment: str) -> Any:
    """A parsed case whose every oracle-side field carries the sentinel."""
    return harness.BattleCase(
        case_id="case-1",
        prompt="Jag vill ha ett flöde som skriver ett beslut.",
        attachments=(attachment,),
        configured_question_answers=ANSWERS,
        expected={"expected_review_policy": {"target_field_groups": [[SENTINEL]]}},
        note=SENTINEL,
        cohorts=(SENTINEL,),
        synthetic_user_profile=SENTINEL,
        source=harness.CaseSource(catalogue_id=SENTINEL, url=f"https://x/{SENTINEL}"),
        execution=harness.CaseExecution(
            inputs=harness.ExecutionInputs(
                files=(f"{SENTINEL}.pdf",), form_fields={"dnr": SENTINEL}
            ),
            checkpoints=(
                harness.ExpectedCheckpoint(
                    review_mode="edit", output_type=None, action=SENTINEL
                ),
            ),
            expect=harness.OutputExpectation(
                output_kind="docx", required_facts=(SENTINEL,), forbidden=(SENTINEL,)
            ),
        ),
    )


def _docx(stage: ModuleType) -> str:
    return next(p.name for p in stage.FIXTURES.iterdir() if p.suffix == ".docx")


def test_only_four_fields_of_a_parsed_case_are_ever_projected(
    harness: ModuleType, stage: ModuleType
) -> None:
    material = stage.request_material(_case(harness, "x.docx"))
    assert tuple(material) == stage.PROJECTED_FIELDS
    assert SENTINEL not in json.dumps(material)


def test_a_staged_tree_holds_no_oracle_and_lists_every_file_it_holds(
    harness: ModuleType, stage: ModuleType, tmp_path: Path
) -> None:
    attachment = _docx(stage)
    material = stage.request_material(_case(harness, attachment))
    manifest = stage.stage_case(material, tmp_path)

    staged = {
        str(p.relative_to(tmp_path / "case-1")): p.read_bytes()
        for p in (tmp_path / "case-1").rglob("*")
        if p.is_file()
    }
    assert not any(SENTINEL.encode() in payload for payload in staged.values())
    assert set(staged) - {"MATERIAL.json"} == set(manifest["files"])
    assert manifest["projected_fields"] == list(stage.PROJECTED_FIELDS)
    assert staged["request.md"].decode() == material["prompt"]
    answers = staged["answers.md"].decode()
    assert "Diarienummer" in answers and "obligatoriskt" in answers
    assert staged[f"attachments/{attachment}.txt"].strip()  # the text an author reads


def test_staging_is_deterministic(
    harness: ModuleType, stage: ModuleType, tmp_path: Path
) -> None:
    material = stage.request_material(_case(harness, _docx(stage)))
    assert stage.stage_case(material, tmp_path / "a") == stage.stage_case(
        material, tmp_path / "b"
    )


def test_the_author_docs_leave_the_builders_sections_out(
    stage: ModuleType, tmp_path: Path
) -> None:
    digests = stage.stage_docs(tmp_path)
    text = "\n".join((tmp_path / "docs" / name).read_text() for name in digests)
    assert "## Flow AI Builder" not in text
    assert "What does Flow AI Builder do" not in text
    assert "StepSpec" in text and "input_bindings" in text  # the schema is there
    assert "DOCX" in text  # and the template rules


# ---------------------------------------- the same brief the Builder receives


def _selected_ids() -> list[str]:
    selection = json.loads((_SCRIPTS / "ai_builder_oracle_cases.json").read_text())
    return [c["id"] for c in selection["cases"]]


def test_every_selected_cases_staged_brief_is_the_builders_first_message_byte_for_byte(
    harness: ModuleType, stage: ModuleType, tmp_path: Path
) -> None:
    """The resolved answers: profile answers with the case's own on top.

    `mc_oms03_lss` and `mc_oms16_stiftelse` inherit five and three answers from
    their synthetic profile; a brief staged from the raw overrides would miss
    them, and the freeze would then refuse the leg. Both sides are built from the
    harness's own parse, so this holds for every selected case.
    """

    cases = stage.load_cases(_SCRIPTS / "ai_builder_api_municipal_cases.json")
    raw = {
        c["id"]: c
        for c in json.loads(
            (_SCRIPTS / "ai_builder_api_municipal_cases.json").read_text()
        )["cases"]
    }
    upfront = argparse.Namespace(arm="builder", intake_answers="upfront", edit=None)
    for case_id in _selected_ids():
        case = cases[case_id]
        stage.stage_case(stage.request_material(case), tmp_path)
        request = (tmp_path / case_id / "request.md").read_text()
        answers = (tmp_path / case_id / "answers.md").read_text()
        staged = request + ("\n\n" + answers if answers else "")
        assert staged == harness._first_message(case, upfront), case_id
        assert (
            stage.verify_staged_case(tmp_path / case_id)
            == hashlib.sha256(staged.encode()).hexdigest()
        )

    # The two profile cases really do carry more than their own overrides.
    for case_id, extra in (("mc_oms03_lss", 5), ("mc_oms16_stiftelse", 3)):
        merged = cases[case_id].configured_question_answers
        own = raw[case_id].get("question_answer_overrides") or {}
        assert len(merged) - len(own) == extra
        answers = (tmp_path / case_id / "answers.md").read_text()
        assert answers.count("\n- ") == len(merged)  # one bullet per answer


# ------------------------------------ the freeze trusts bytes, not a manifest


def test_the_intake_digest_comes_from_the_staged_bytes_and_drift_is_refused(
    harness: ModuleType, stage: ModuleType, tmp_path: Path
) -> None:
    stage.stage_case(stage.request_material(_case(harness, _docx(stage))), tmp_path)
    case_dir = tmp_path / "case-1"
    honest = stage.verify_staged_case(case_dir)

    # An altered brief with an unchanged MATERIAL.json.
    answers = case_dir / "answers.md"
    original = answers.read_text()
    answers.write_text(original.replace("DOCX-dokument", "PDF-dokument"))
    with pytest.raises(stage.MaterialError, match="differ from MATERIAL.json"):
        stage.verify_staged_case(case_dir)
    answers.write_text(original)
    assert stage.verify_staged_case(case_dir) == honest

    # A manifest that claims a digest the bytes do not give (files still match).
    manifest_path = case_dir / "MATERIAL.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["intake_message_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(stage.MaterialError, match="claims an intake digest"):
        stage.verify_staged_case(case_dir)

    # A file the manifest does not list.
    manifest["intake_message_sha256"] = honest
    manifest_path.write_text(json.dumps(manifest))
    (case_dir / "extra.md").write_text("hint")
    with pytest.raises(stage.MaterialError, match="extra.md"):
        stage.verify_staged_case(case_dir)


def test_a_manifest_without_a_claimed_digest_still_yields_the_recomputed_one(
    harness: ModuleType, stage: ModuleType, tmp_path: Path
) -> None:
    stage.stage_case(stage.request_material(_case(harness, _docx(stage))), tmp_path)
    manifest_path = tmp_path / "case-1" / "MATERIAL.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["intake_message_sha256"]
    manifest_path.write_text(json.dumps(manifest))
    expected = harness.intake_message(
        "Jag vill ha ett flöde som skriver ett beslut.", ANSWERS
    )
    assert (
        stage.verify_staged_case(tmp_path / "case-1")
        == hashlib.sha256(expected.encode()).hexdigest()
    )


def test_the_docs_and_the_material_tree_have_digests_that_move_with_their_bytes(
    harness: ModuleType, stage: ModuleType, tmp_path: Path
) -> None:
    stage.stage_case(stage.request_material(_case(harness, _docx(stage))), tmp_path)
    stage.stage_docs(tmp_path)
    before_docs = stage.verify_docs(tmp_path)
    before_material = stage.material_digest(tmp_path, ["case-1"])

    doc = next(p for p in (tmp_path / "docs").iterdir() if p.name != "DOCS.json")
    doc.write_text(doc.read_text() + "\nA changed line.")
    with pytest.raises(stage.MaterialError, match="differ from DOCS.json"):
        stage.verify_docs(tmp_path)

    manifest = tmp_path / "case-1" / "MATERIAL.json"
    manifest.write_text(manifest.read_text() + " ")
    assert stage.material_digest(tmp_path, ["case-1"]) != before_material
    assert before_docs


# ------------------------------- the staged bytes come from the frozen sources


def _staged_from_sources(
    harness: ModuleType,
    stage: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str]:
    attachment = _docx(stage)
    monkeypatch.setattr(
        stage, "load_cases", lambda _path: {"case-1": _case(harness, attachment)}
    )
    material = tmp_path / "material"
    stage.stage_case(stage.request_material(_case(harness, attachment)), material)
    stage.stage_docs(material)
    return material, attachment


def _verify_against_sources(
    stage: ModuleType, material: Path, *, fixtures: Path | None = None
) -> None:
    stage.verify_against_source(
        material,
        ["case-1"],
        cases_file=Path("corpus.json"),
        fixtures=fixtures or stage.FIXTURES,
        repo=stage._REPO,
    )


def test_material_staged_from_the_sources_verifies_against_them(
    harness: ModuleType,
    stage: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material, _ = _staged_from_sources(harness, stage, tmp_path, monkeypatch)
    _verify_against_sources(stage, material)


def test_a_staged_file_that_its_own_manifest_vouches_for_but_the_sources_do_not_is_refused(
    harness: ModuleType,
    stage: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sol round 4, F2: `verify_staged_case` and `verify_docs` pass on every one
    of these; only regenerating from the sources refuses them."""

    material, attachment = _staged_from_sources(harness, stage, tmp_path, monkeypatch)
    case_dir = material / "case-1"
    manifest_path = case_dir / "MATERIAL.json"

    def rewrite(relative: str, payload: bytes | None) -> None:
        manifest = json.loads(manifest_path.read_text())
        if payload is None:
            del manifest["files"][relative]
            (case_dir / relative).unlink()
        else:
            (case_dir / relative).write_bytes(payload)
            manifest["files"][relative] = hashlib.sha256(payload).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True)
        )

    original = (case_dir / f"attachments/{attachment}.txt").read_bytes()
    rewrite(f"attachments/{attachment}.txt", original + b"\nA hint.")
    stage.verify_staged_case(case_dir)  # self-consistent
    with pytest.raises(stage.MaterialError, match=f"{attachment}.txt"):
        _verify_against_sources(stage, material)
    rewrite(f"attachments/{attachment}.txt", original)
    _verify_against_sources(stage, material)

    rewrite("hint.md", b"the answer is 42")  # an extra file, declared
    stage.verify_staged_case(case_dir)
    with pytest.raises(stage.MaterialError, match="hint.md"):
        _verify_against_sources(stage, material)
    rewrite("hint.md", None)

    rewrite(f"attachments/{attachment}.txt", None)  # a rendering left out, undeclared
    stage.verify_staged_case(case_dir)
    with pytest.raises(stage.MaterialError, match=f"{attachment}.txt"):
        _verify_against_sources(stage, material)


def test_a_replaced_fixture_or_case_outside_the_corpus_is_refused(
    harness: ModuleType,
    stage: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material, attachment = _staged_from_sources(harness, stage, tmp_path, monkeypatch)
    other = tmp_path / "fixtures"
    other.mkdir()
    (other / attachment).write_bytes((stage.FIXTURES / attachment).read_bytes() + b"x")

    with pytest.raises(stage.MaterialError):
        _verify_against_sources(stage, material, fixtures=other)
    with pytest.raises(stage.MaterialError, match="does not hold"):
        stage.verify_against_source(
            material,
            ["case-1", "case-2"],
            cases_file=Path("corpus.json"),
            fixtures=stage.FIXTURES,
            repo=stage._REPO,
        )

    docs = material / "docs"
    doc = next(p for p in sorted(docs.iterdir()) if p.name != "DOCS.json")
    doc.write_text(doc.read_text() + "\nEn rad till.\n")
    listed = json.loads((docs / "DOCS.json").read_text())
    listed[doc.name] = hashlib.sha256(doc.read_bytes()).hexdigest()
    (docs / "DOCS.json").write_text(json.dumps(listed, indent=1, sort_keys=True))
    stage.verify_docs(material)  # the docs' own manifest agrees
    with pytest.raises(stage.MaterialError, match=doc.name):
        _verify_against_sources(stage, material)
